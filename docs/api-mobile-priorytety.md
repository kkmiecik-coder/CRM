# API mobilne po priorytetach produkcji — stół stanowiska, Odłóż, sygnały

## 0. Do kogo i na czym stoi ten dokument

Referencja różnicowa dla aplikacji Android (`woodpower_prod_app`; starsze dokumenty, np.
`docs/api-mobile-krawedzie-lakiernia.md`, nazywają ją `crm_prod_app` — to ta sama appka). Opisuje **stan przed**
(lista całej kolejki, na której stoi appka 1.7.3), **stan po** (stół stanowiska) i **jak wołać nowe końcówki**.
Sesja appki pracuje wyłącznie z tego dokumentu.

Każde twierdzenie o serwerze ma odnośnik `ścieżka:linia` — sprawdzaj w kodzie, nie ufaj temu dokumentowi na słowo.
Odnośniki wskazują stan na gałęzi `claude/priorytety-produkcji` @ `07710d4c3b6c4ba313fbf234c003d8878d8db86d`
(kod po karcie K3-poprawka-2: pole `tryb` w `desk`, 409 `pozycja_poza_stanowiskiem`).
**Ten hash nie jest jeszcze na `main`**: kod wchodzi na produkcję jednym wdrożeniem razem z logistyką etapów 1–4
i nową appką (decyzja Konrada 5.10). Do tego czasu sprawdzaj na podglądzie wskazanym przez Konrada, nigdy na
produkcji.

Punkt wejścia API mobilnego: blueprint pod `/api/mobile` (`app.py:876`), trasy w
`modules/production/routers/mobile_api.py:201` (`register`) i dalej. Trakownia (`app.py:878`), Weryfikacja
(`app.py:882`) i Dostawa (`app.py:885`) mają własne blueprinty — priorytety ich nie zmieniają.

Oznaczenia: „S” = kod stanowiska (`cutting`, `assembly`, `gluing`, `formatting`, `edges`, `painting`, `packaging`),
„K” = liczba miejsc na stole (`miejsca`), „kafel” = to, co tablet pokazuje do zrobienia (pozycja albo całe
zamówienie). Przykłady JSON mają dane fikcyjne; kształt, kody i komunikaty są z żywych odpowiedzi podglądu
(sekcje 4–8 mówią, co było sprawdzone na żywo, a co złożone z kodu).

---

## 1. Najważniejsze w pięciu zdaniach

1. **Tablet pokazuje stół, nie kolejkę — gdy `tryb == "stol"`.** Nowa końcówka `GET /stations/<S>/desk` w trybie
   `stol` dopełnia stół z kolejki do K kafli i oddaje stół, odłożone i (Formatowanie, Pakowanie) niekompletne
   zamówienia; appka pokazuje to w kolejności z odpowiedzi i niczego nie sortuje; w trybie `stary` `desk` tylko czyta,
   a appka zostaje na liście (`modules/production/routers/mobile_api.py:559-622` (`station_desk`)).
2. **Odłóż z powodem** (`POST /orders/<id>/postpone`) przenosi kafel do „Odłożonych” — kafel zostaje widoczny i da się
   go zakończyć; na stanowisko jest limit otwartych odłożeń (`modules/production/routers/mobile_api.py:625-689`
   (`order_postpone`)).
3. **Sygnał zamiast odpytywania co 30 s:** serwer po commicie publikuje sygnał na kanał `station:<S>` (ładunek bez znaczenia dla appki), tablet po
   sygnale woła `GET desk`; siatką jest odpytywanie 30 s przy pustym stole i 5 min przy pełnym
   (`modules/production/priorytety/services/sygnaly.py:1-16`, `modules/production/routers/mobile_api.py:692-731`
   (`realtime_token`)).
4. **ZAKOŃCZ i licznik dostają bramkę tylko w trybie `stol` i tylko dla nowej appki:** pozycja spoza statusu
   stanowiska → 409 `pozycja_poza_stanowiskiem`, kafel spoza stołu i odłożonych → 409 `nie_na_stole`
   (`modules/production/priorytety/services/stol.py:261-302` (`bramka_zakoncz`)).
5. **Stara appka działa bez zmian:** lista `/stations/<S>/orders` zostaje, dochodzą tylko pola `priorytet`
   i `grupa_wykonczenia`; tablet poniżej progu wersji omija bramkę stołu
   (`modules/production/priorytety/services/stol.py:145-155` (`stara_appka`)).

---

## 2. Stan przed / stan po

| | przed (appka 1.7.3, tryb `stary`) | po (nowa appka, tryb `stol`) |
|---|---|---|
| co pokazuje ekran stanowiska | całą kolejkę: `GET /stations/<S>/orders` oddaje wszystkie pozycje zamówień, które mają pozycję w statusie S, posortowane `COALESCE(priority_rank, 999999), internal_order_number, id` (`modules/production/routers/mobile_api.py:258-349` (`station_orders`), sort `modules/production/routers/mobile_api.py:319-323`) | stół: 1–K kafli + „Odłożone” + „Niekompletne” z `GET /stations/<S>/desk` (`modules/production/routers/mobile_api.py:417-511` (`_odpowiedz_stolu`)); listy kolejki brak, tylko licznik `kolejka_dalej` |
| kto wybiera, co robić | pracownik (dowolna pozycja z listy) | serwer kładzie kafle na stół (`modules/production/priorytety/services/stol.py:606-639` (`dopelnij`)); pracownik kończy albo odkłada |
| odświeżanie | co `refresh_interval_seconds` z `/summary` (domyślnie 30 s) z ETagiem (`modules/production/services/mobile_api_service.py:1701-1714`, `modules/production/services/mobile_api_service.py:1727`) | sygnał `station:<S>` + siatka 30 s (pusty stół) / 5 min (pełny) (sekcja 9) |
| ZAKOŃCZ | dowolnej pozycji; serwer nie sprawdza kolejności (`complete_task` deleguje tranzycję bez bramki kolejki, `modules/production/models.py:639` (`complete_task`)); w trybie `stary` bramka stołu wychodzi od razu (`modules/production/priorytety/services/stol.py:284-285`) | tylko pozycja w statusie stanowiska (inaczej 409 `pozycja_poza_stanowiskiem`), i to z kafla na stole, odłożonego albo z niekompletnego zamówienia (inaczej 409 `nie_na_stole`) (`modules/production/priorytety/services/stol.py:282-302`) |
| pilność na kaflu | `is_priority` (bool, pomarańczowa ramka) i `priority_rank` (`modules/production/services/mobile_api_service.py:1290-1291`) | obiekt `priorytet`: gwiazdki 0–5, szczebel drabiny, trasa, „poz. i/n” (`modules/production/services/mobile_api_service.py:1292`; sekcja 7) |
| Odłóż | nie ma | `POST /orders/<id>/postpone` z powodem (sekcja 5) |
| realtime | tylko agent druku (`modules/production/routers/api/print_agent_api.py:265-301` (`realtime_token`)) | tablety: `GET /api/mobile/realtime-token`, kanały `station:<S>` (`modules/production/routers/mobile_api.py:692-731` (`realtime_token`)) |
| Lakiernia | lista po randze, appka sortuje sama („Partia”) | lista ułożona przez serwer po grupach wykończenia, z polem `grupa_wykonczenia`; **bez stołu na stałe** (`modules/production/routers/mobile_api.py:327`, `modules/production/priorytety/services/lista.py:84-112` (`porzadek_listy`)) |

---

## 3. Tabela końcówek

`/api/mobile` ma **26 tras**: 23 dotychczasowe i 3 nowe (`grep -c "@mobile_api_bp.route"` w
`modules/production/routers/mobile_api.py`). Wszystkie poza `register` i `app/version` wymagają
`Authorization: Bearer <JWT>` (`modules/production/services/mobile_api_service.py:413-463` (`require_device_token`)).

### Nowe

| Trasa | Sekcja | Odnośnik |
|---|---|---|
| `GET /stations/<S>/desk` | 4 | `modules/production/routers/mobile_api.py:559` (`station_desk`) |
| `POST /orders/<id>/postpone` | 5 | `modules/production/routers/mobile_api.py:625` (`order_postpone`) |
| `GET /realtime-token` | 8 | `modules/production/routers/mobile_api.py:692` (`realtime_token`) |

### Zmienione

| Trasa | Co się zmieniło | Odnośnik |
|---|---|---|
| `GET /stations/<S>/orders` | pola `priorytet` i `grupa_wykonczenia` w każdej pozycji; ETag zmienia się raz przez `KSZTALT_ODPOWIEDZI_KOLEJKI = 6`; dla `painting` kolejność po grupach wykończenia (sekcja 13) | `modules/production/routers/mobile_api.py:309-310`, `modules/production/routers/mobile_api.py:146` (`KSZTALT_ODPOWIEDZI_KOLEJKI`), `modules/production/routers/mobile_api.py:339-347` |
| `GET /stations/<S>/orders/since` | `priorytet` i `grupa_wykonczenia` w `changed`; dla `painting` `all_ids` i `changed` w kolejności listy; **bez ETagu** (jak dotąd) | `modules/production/services/mobile_api_service.py:1813` (`get_station_queue_delta`), `modules/production/services/mobile_api_service.py:1834-1841`, `modules/production/routers/mobile_api.py:1136-1180` (`station_orders_since`) |
| `GET /orders/search` | `priorytet` w każdej pozycji | `modules/production/routers/mobile_api.py:780-783` |
| `GET /orders/<id>` | `priorytet` (liczony dla pojedynczej pozycji przez serializer) | `modules/production/routers/mobile_api.py:828`, `modules/production/services/mobile_api_service.py:1236-1239` |
| `POST /orders/<id>/complete` | w trybie `stol` bramki 409 `pozycja_poza_stanowiskiem` i `nie_na_stole` (sekcja 6); zdjęcie kafla ze stołu i sygnały po commicie; odpowiedź 200 bez zmian w kształcie (dochodzi `priorytet`) | `modules/production/routers/mobile_api.py:875-886`, `modules/production/routers/mobile_api.py:901-912`, `modules/production/routers/mobile_api.py:920` |
| `PATCH /orders/<id>/quantity` | te same bramki (sekcja 6); sygnał na stanowisko po commicie | `modules/production/routers/mobile_api.py:953-959`, `modules/production/routers/mobile_api.py:974-975` |
| `POST /orders/<id>/reject` | bez bramki; doróbka zdejmuje kafle i wysyła sygnały; `original` i `rework` mają `priorytet` | `modules/production/routers/mobile_api.py:1059-1064`, `modules/production/services/rework_service.py:376` |

### Bez zmian (16)

`POST /register` (`modules/production/routers/mobile_api.py:201`), `GET /stations/<S>/summary` — bez zmian, a
`refresh_interval_seconds` zostaje dla starej appki (`modules/production/routers/mobile_api.py:1071` (`station_summary`)),
`GET /app/version` (`modules/production/routers/mobile_api.py:1187`), `GET /app/apk` (`modules/production/routers/mobile_api.py:1199`),
`POST /products/<short_id>/print-label` (`modules/production/routers/mobile_api.py:1256`),
`POST /products/by-id/<id>/print-label` (`modules/production/routers/mobile_api.py:1286`),
`POST /orders/<bl_id>/print-labels` (`modules/production/routers/mobile_api.py:1423`),
`GET` i `PUT /orders/<numer>/packages` (`modules/production/routers/mobile_api.py:1556`, `modules/production/routers/mobile_api.py:1571`),
`POST /packages/<id>/print` (`modules/production/routers/mobile_api.py:1627`),
`POST /orders/<numer>/packages/print` (`modules/production/routers/mobile_api.py:1659`),
`POST /devices/heartbeat` — kształt bez zmian, ale nabiera znaczenia dla bramki wersji (sekcja 11;
`modules/production/routers/mobile_api.py:1693` (`device_heartbeat`)), `GET /workers`
(`modules/production/routers/mobile_api.py:1757`), `POST /sessions/start`, `POST /sessions/end`, `GET /sessions/active`
(`modules/production/routers/mobile_api.py:1888`, `modules/production/routers/mobile_api.py:1981`,
`modules/production/routers/mobile_api.py:2049`).

Trakownia (`/api/mobile/sawmill`), Weryfikacja (`/api/mobile/verification`) i Dostawa (`/api/mobile/delivery`) —
bez zmian w kontrakcie (`app.py:877-885`); „Cofnij do pakowania” w Weryfikacji wysyła tylko dodatkowy sygnał
`station:packaging` (`modules/production/logistics/routers/weryfikacja_api.py:322`).

---

## 4. GET /api/mobile/stations/<S>/desk

### Żądanie

```
GET /api/mobile/stations/gluing/desk
Authorization: Bearer <JWT>
If-None-Match: W/"desk:gluing:…"        (opcjonalnie — ETag z poprzedniej odpowiedzi)
```

Bez `X-Worker-Ids` i bez `X-Operation-Id`: końcówka nie ma dekoratora idempotencji
(`modules/production/routers/mobile_api.py:559-561`). `<S>` to kod stanowiska; stary kod `finishing` serwer rozwija
na `edges` (`modules/production/routers/mobile_api.py:587`).

### Co robi serwer (w tej kolejności)

1. 404 `unknown_station`, gdy kod nie jest stanowiskiem z kolejką produktów (np. `sawmill`, `verification`,
   `delivery`) (`modules/production/routers/mobile_api.py:589-590`).
2. 403 `station_mismatch`, gdy urządzenie nie ma dostępu do stanowiska; tablet Krawędzi ma dostęp do `edges`
   i `painting`, tablet Lakierni do obu tak samo (`modules/production/routers/mobile_api.py:592-597`,
   `modules/production/services/mobile_api_service.py:118-148` (`STATION_GROUPS`)).
3. 409 `stanowisko_bez_stolu` dla Lakierni, bez żadnego zapisu (`modules/production/routers/mobile_api.py:600-601`,
   `modules/production/routers/mobile_api.py:364-371` (`_stanowisko_bez_stolu`)).
4. Czyta tryb stanowiska z Konfiguracji (zwykły odczyt, `modules/production/routers/mobile_api.py:605`). **W trybie `stary` kroki 5–6 nie zachodzą**:
   bez commita, blokady stanowiska, limitu czekania i zapisów — od razu krok 7 na migawce żądania
   (`modules/production/routers/mobile_api.py:606-609`; test `tests/test_priorytety_mobile.py:1023` (`test_desk_stary_nie_dopelnia_i_nie_blokuje`)).
5. **Tylko w trybie `stol`: dopełnia stół i commituje** (`modules/production/routers/mobile_api.py:514-550` (`_dopelnij_stol`)):
   - do K liczą się wszystkie kafle leżące na stole (bez odłożonych), niezależnie od źródła; serwer dobiera z kolejki
     tylko wtedy, gdy leży ich mniej niż K (`modules/production/priorytety/services/stol.py:632-635`);
   - doróbki stoją na początku kolejki i wchodzą pierwsze, **w ramach K**, ze źródłem `dorobka`
     (`modules/production/priorytety/services/stol.py:630-637`);
   - kafel leżący na stole albo odłożony nie jest pobierany drugi raz (`modules/production/priorytety/services/widok.py:391`);
   - Formatowanie i Pakowanie biorą na stół tylko zamówienia **kompletne** na stanowisku; niekompletne idą do sekcji
     „Niekompletne” (do K sztuk) (`modules/production/priorytety/services/kolejka.py:392-394`,
     `modules/production/priorytety/services/stol.py:516-522` (`_lista_niekompletnych`));
   - Pakowanie: zamówienie bez sposobu dostawy jest zwykłym kandydatem — wchodzi na stół, do „Niekompletnych”
     i do `kolejka_dalej` jak każde inne (logistyka 4.6, od `2f3e6ce7`; sekcja 6)
     (`modules/production/priorytety/services/stol.py:465-474` (`_kandydaci`)).
6. Jeśli coś dołożył — sygnał `station:<S>` po commicie (budzi drugi tablet); `desk`, który niczego nie dołożył, nie
   wysyła nic (`modules/production/routers/mobile_api.py:552-555`).
7. Liczy ETag (w `stol` po commicie dopełnienia); zgodny z `If-None-Match` → 304 bez ciała, inaczej 200 z ciałem
   (`modules/production/routers/mobile_api.py:611-617`).

### Pole `tryb` (K3-poprawka-2)

**[K3-poprawka-2]** Decyzja centrali 5.10 (przed wdrożeniem 8.10), w kodzie od `9a72d056`:

- odpowiedź `desk` (i `postpone`, ten sam kształt) ma pole **`tryb`**: `"stary"` | `"stol"` — tryb stanowiska
  z Konfiguracji (`modules/production/routers/mobile_api.py:503`, `modules/production/routers/mobile_api.py:605`); znacznik kształtu odpowiedzi stołu podbity do 2, a tryb wchodzi do ETagu,
  więc tablet z zapamiętanym ETagiem dostaje 200, nie 304 — także po samym przełączeniu trybu
  (`modules/production/routers/mobile_api.py:148-153`, `modules/production/routers/mobile_api.py:410-414`; test `tests/test_priorytety_mobile.py:1085`
  (`test_desk_przelaczenie_trybu_miedzy_wywolaniami`));
- **w trybie `stary` `desk` niczego nie dopełnia** — bez zapisów i bez blokady stanowiska; oddaje `tryb: "stary"`
  i bieżące wiersze stołu tylko do odczytu (np. kafle startowe po „Przygotuj stoły”); kroki 5–6 z listy wyżej
  działają wyłącznie w `stol` (`modules/production/routers/mobile_api.py:605-609`; sprawdzone też na MySQL z kopią produkcji: zero zapisów, zero odczytów
  blokujących, zero blokad InnoDB);
- **appka pokazuje ekran stołu tylko przy `tryb == "stol"`**; przy `"stary"` pokazuje dzisiejszą listę
  `/stations/<S>/orders` i woła `desk` najwyżej co 30 s, żeby wykryć przełączenie (sekcje 9, 12);
- Lakiernia bez zmian: 409 `stanowisko_bez_stolu` w obu trybach (`modules/production/routers/mobile_api.py:600-601`).

Backend bez pola `tryb` (kod sprzed `9a72d056`, np. stary podgląd) oddaje 200 **bez** `tryb` i dopełnia stół w obu
trybach. **Build debug** appki traktuje 200 bez pola `tryb` jak `"stol"` (żeby dało się testować stół na takim
podglądzie); **build release — jak `"stary"`** (lista). Wdrożenie 8.10 zawiera kod z polem `tryb`.

**Stół bywa dłuższy niż `miejsca`.** Ponad K wchodzą tylko kafle położone przez biuro: „Wyślij na stanowisko”
(`zrodlo: "biuro"`, `modules/production/priorytety/services/stol.py:900` (`wyslij`)) i start stołów
(`zrodlo: "start"`, `modules/production/priorytety/services/stol.py:1054` (`przygotuj_start`)). Lista „Teraz” musi
się przewijać.

**`GET desk` w trybie `stol` jest zapisem.** To jedyny GET API mobilnego, który zapisuje i commituje sam
(`modules/production/routers/mobile_api.py:520-526`); w trybie `stary` tylko czyta (`modules/production/routers/mobile_api.py:606-609`). Appka woła go tylko z ekranu stanowiska: przy wejściu na
ekran, po własnym ZAKOŃCZ/Odłóż, po sygnale i wg siatki z sekcji 9 — nigdy z wyszukiwarki ani w tle częściej niż
siatka.

**Dwa tablety naraz.** Dopełnianie bierze blokadę stanowiska (wiersz `prod_config` `priorytety_blokada_<S>`); drugi
tablet czeka na nią i widzi już pełny stół — nie dubluje kafli (`modules/production/priorytety/services/stol.py:366-389`
(`zablokuj_stanowisko`), test `tests/test_priorytety_stol.py:1029` (`test_dopelnij_po_blokadzie_widzi_cudzy_kafel`)).
Oba dostają ten sam stół w tej samej kolejności.

**Odpowiedź bywa wolniejsza i bez dopełnienia.** Dopełnianie czeka na cudzą blokadę najwyżej 5 s
(`modules/production/priorytety/services/kolejka.py:456` (`LIMIT_CZEKANIA_NA_BLOKADE_S`)); po przekroczeniu serwer
oddaje **200 z bieżącym stołem bez dopełnienia** (wolne miejsce mimo `kolejka_dalej > 0`) — to nie jest błąd
(`modules/production/routers/mobile_api.py:537-541`). Limit czasu żądania `desk` w appce: co najmniej 15 s (5 s na
blokadzie stanowiska + 5 s na zamówieniu + odczyt).

### Błędy

| Status | Ciało | Kiedy | Co robi appka |
|---|---|---|---|
| 401 | `{"error": "missing_token"}` / `{"error": "invalid_token", "detail": …}` | brak albo zły JWT (`modules/production/services/mobile_api_service.py:430-443`) | przerejestrowanie, jak dotąd |
| 403 | `{"error": "station_mismatch", "device_station": "gluing", "requested_station": "cutting"}` | cudze stanowisko | błąd konfiguracji tabletu, bez ponawiania w pętli |
| 404 | `{"error": "unknown_station"}` (JSON) | kod spoza stanowisk z kolejką | błąd konfiguracji tabletu; to **nie** jest „backend bez stołu” (sekcja 12) |
| 404 | strona HTML Flaska, nie JSON | trasy nie ma (backend sprzed priorytetów) | fallback do listy (sekcja 12) |
| 409 | `{"error": "stanowisko_bez_stolu", "message": "Lakiernia pracuje z listy, bez stołu."}` | `<S>` = `painting` | appka nie woła `desk` dla Lakierni (sekcja 13) |
| 426 | `{"error": "app_version_too_old", …}` | `X-App-Version` poniżej progu konfiguracji (sekcja 11) | jak dotąd |
| 500 | `{"error": "desk_failed"}` | drugie zakleszczenie MySQL 1213 z rzędu albo błąd odczytu (`modules/production/routers/mobile_api.py:542-550`, `modules/production/routers/mobile_api.py:618-622`; test `tests/test_priorytety_mobile.py:378` (`test_desk_dwa_1213_to_500_bez_zapisow`)) | następna próba wg siatki (sekcja 9), nie od razu w pętli; pokazuje ostatni znany stół |

Pierwsze 1213 serwer ponawia sam, raz (`modules/production/routers/mobile_api.py:530-545`; test
`tests/test_priorytety_mobile.py:355` (`test_desk_ponawia_raz_po_1213`)).

### ETag, 304 i pamięć podręczna

- Odpowiedź ma słaby `ETag` i `Cache-Control: private, max-age=0` — także 304
  (`modules/production/routers/mobile_api.py:616-617`, `modules/production/utils/cache.py:47-63`). Klient HTTP appki
  (OkHttp Cache) **nie może** podać `desk` z pamięci bez pytania serwera: każde pobranie idzie do serwera
  z `If-None-Match`. 304 oszczędza tylko ciało — dopełnienie i tak się wykonało (ETag liczony po commicie).
- ETag zmienia się przy każdej zmianie: pozycji zamówień stanowiska (czas, liczba, liczba w statusie S, suma
  liczników sztuk), gwiazdek, wierszy stołu, ustawień K/limitu/jednostki, **trybu** i wersji kształtu
  (`modules/production/routers/mobile_api.py:380-414` (`_etag_stolu`), `modules/production/routers/mobile_api.py:153`
  (`KSZTALT_ODPOWIEDZI_STOLU`)). Appka nie parsuje ETagu, tylko go odsyła.
- Lista `/stations/<S>/orders` ma dla porównania `max-age=15` (`modules/production/utils/cache.py:54`) — reguła
  „zawsze pytaj serwer” dotyczy `desk`.

### Ciało 200

| Pole | Typ | Znaczenie |
|---|---|---|
| `station_code` | string | kod kanoniczny stanowiska |
| `tryb` | `"stary"` \| `"stol"` | **[K3-poprawka-2]** tryb stanowiska z Konfiguracji; ekran stołu tylko przy `"stol"` (wyżej) |
| `jednostka` | `"pozycja"` \| `"zamowienie"` | co jest kaflem; Formatowanie i Pakowanie domyślnie `zamowienie` (`modules/production/priorytety/services/ustawienia.py:84-85`) |
| `miejsca` | int | K — ile kafli serwer trzyma na stole z kolejki (domyślnie 2) |
| `stol` | lista `{kafel, pobrano, zrodlo}` | sekcja „Teraz”; może mieć więcej niż `miejsca` elementów |
| `odlozone` | lista `{kafel, odlozono, powod, notatka, pracownik}` | sekcja „Odłożone” |
| `niekompletne` | lista `{kafel, na_stanowisku, pozycji, brakuje}` | tylko jednostka `zamowienie`; dla `pozycja` zawsze `[]`; najwyżej `miejsca` elementów |
| `limit_odlozen` | int | limit otwartych odłożeń stanowiska — informacyjnie (sekcja 5) |
| `kolejka_dalej` | int | ile kafli czeka w kolejce poza stołem (z doróbkami, które nie weszły) — nagłówek „w kolejce: N” |

Pola z `modules/production/routers/mobile_api.py:501-511`; `kolejka_dalej` z
`modules/production/priorytety/services/stol.py:652-654`.

- `pobrano`, `odlozono` — czas lokalny serwera w ISO 8601 bez strefy; na MySQL z dokładnością do sekundy
  (`"2026-10-05T09:12:40"`), na innych bazach bywa z mikrosekundami — appka parsuje obie postaci
  (`modules/production/routers/mobile_api.py:488-492`).
- `zrodlo` — `kolejka` | `dorobka` | `biuro` | `start` (`modules/production/priorytety/stale.py:82-86`). Plakietki:
  `biuro` → „wysłane przez biuro”, `start` → „rozpoczęte przed startem”; `dorobka` ma już plakietkę z `priorytet`
  (sekcja 7); `kolejka` — bez plakietki.
- `powod` — kod powodu (sekcja 5); `notatka` — tekst albo `null`; `pracownik` — „Imię I.” (imię i inicjał nazwiska)
  albo `null`, gdy odłożono bez obsady (`modules/production/routers/mobile_api.py:474-480`,
  `modules/production/priorytety/services/stol.py:122-131` (`imie_z_inicjalem`)).
- `niekompletne[].na_stanowisku` — ile pozycji czeka na tym stanowisku; `pozycji` — ile pozycji liczy się do
  kompletności (bez anulowanych, wstrzymanych i omijających stanowisko); `brakuje` — pozycje jeszcze przed
  stanowiskiem: `{short_id, stanowisko}`, gdzie `stanowisko` to kod stanowiska, na którym pozycja czeka, albo `null`,
  gdy jej status nie odpowiada żadnemu stanowisku (`modules/production/routers/mobile_api.py:493-500`,
  `modules/production/priorytety/services/kolejka.py:128-139` (`liczone_na_stanowisku`),
  `modules/production/priorytety/services/stol.py:516-522`). Postęp „3/5 na stanowisku, 2 na Sklejaniu” appka
  składa z tych pól i nazw stanowisk z buildu (API nazw nie wystawia).

### Kolejność — appka nie sortuje

Kolejność `stol`, `odlozone` i `niekompletne` ustala serwer i jest taka sama dla każdego tabletu stanowiska; appka
pokazuje ją bez przesortowania i bez grupowania
(`modules/production/routers/mobile_api.py:417-426`):

- `stol`: doróbki, wysłane przez biuro, startowe, pobrane z kolejki — w każdej grupie po czasie wejścia, potem po id;
  `odlozone`: najdłużej leżące pierwsze (`modules/production/priorytety/services/stol.py:442-449` (`uporzadkuj`),
  `modules/production/priorytety/stale.py:88` (`KOLEJNOSC_ZRODEL_NA_STOLE`));
- `niekompletne`: w kolejności rangi zamówień (`modules/production/priorytety/services/kolejka.py:376-394`).

Kolejność kafli w kolejce (co wejdzie następne) liczy wyłącznie serwer; appka jej nie odtwarza.

### Kafel jednostki `pozycja`

`kafel` = obiekt pozycji z serializera — **te same pola co w `/stations/<S>/orders`**, w tym `priorytet`
i `grupa_wykonczenia` (`modules/production/routers/mobile_api.py:453-455`,
`modules/production/services/mobile_api_service.py:1130` (`serialize_order`), pola `modules/production/services/mobile_api_service.py:1245-1314`). Klucze poniżej w kolejności
z kodu; na podglądzie przychodziły posortowane alfabetycznie — appka nie może zależeć od kolejności kluczy.

### Przykład 1 — Sklejanie (`jednostka: "pozycja"`): dwa kafle na stole, jeden odłożony

Kształt i wartości pól sterujących sprawdzone na żywo na podglądzie (`gluing`, tryb `stol`, 2026-10-05); dane
klienta, numery i wymiary fikcyjne. Drugi kafel i kafel odłożony skrócone do `…` — mają te same pola co pierwszy.
Pole `tryb` (we wszystkich przykładach stołu) doszło po tym sprawdzeniu — z kodu i testu
`tests/test_priorytety_mobile.py:1005` (`test_desk_oddaje_tryb`).

```json
{
  "station_code": "gluing",
  "tryb": "stol",
  "jednostka": "pozycja",
  "miejsca": 2,
  "stol": [
    {
      "kafel": {
        "id": 9101,
        "short_id": "9001_3",
        "internal_order_number": "9001",
        "baselinker_order_id": 90000001,
        "product_name": "Blat dębowy 140x40x2 cm",
        "client_name": "Klient testowy",
        "client_order_number": "KT-1",
        "label_printed": [],
        "label_print_count": 0,
        "label_offset": 2,
        "label_total": 5,
        "order_source": "shop",
        "order_source_id": 1,
        "order_source_name": "Sklep",
        "order_source_display": "Sklep",
        "delivery_type": "transport_woodpower",
        "transport": {"mode": "wlasny", "trip_name": "Trasa testowa", "trip_date": "2026-10-08",
                      "vehicle_name": "Auto testowe", "repack_required": false, "repack_reason": null},
        "packing_hint": {"kind": "paczka", "count": 1, "pallet_type": null, "weight_kg": 18},
        "wood_species": "dąb",
        "wood_class": "A/B",
        "technology": "mikrowczep",
        "dimensions": {"length_mm": 1400, "width_mm": 400, "thickness_mm": 20},
        "volume_m3": 0.0112,
        "quantity_ordered": 1,
        "quantity_done": 0,
        "priority_rank": 1203,
        "is_priority": false,
        "priorytet": {"gwiazdki": 0, "szczebel": "trasa",
                      "trasa": {"id": 7, "nazwa": "Trasa testowa", "data": "2026-10-08"},
                      "pozycja_w_zamowieniu": "3/5"},
        "grupa_wykonczenia": null,
        "status": "czeka_na_sklejanie",
        "status_display": "Czeka na sklejanie",
        "finish": null,
        "edge": null,
        "delivery_city": "Testowo",
        "delivery_postcode": "00-000",
        "deadline": "2026-10-08",
        "order_notes": null,
        "production_notes": null,
        "attachments": [],
        "shape_svg": null,
        "shape": "rectangular",
        "edge_svg": null,
        "has_edge": false,
        "cut_to_size": true,
        "shape_rotation": 0,
        "updated_at": "2026-10-05T09:10:31",
        "is_rework": false,
        "original_product_id": null,
        "rework_open_count": 0
      },
      "pobrano": "2026-10-05T09:12:40",
      "zrodlo": "kolejka"
    },
    {"kafel": {"id": 9102, "short_id": "9001_4", "…": "…"}, "pobrano": "2026-10-05T09:15:02", "zrodlo": "kolejka"}
  ],
  "odlozone": [
    {"kafel": {"id": 9100, "short_id": "9001_2", "…": "…"}, "odlozono": "2026-10-05T09:14:55",
     "powod": "brak_materialu", "notatka": "czekamy na dąb 4 cm", "pracownik": "Adam K."}
  ],
  "niekompletne": [],
  "limit_odlozen": 10,
  "kolejka_dalej": 75
}
```

Pola `transport`, `packing_hint`, `attachments`, `finish`, `edge` i rysunki mają kształt sprzed priorytetów
(logistyka etapy 1–4) — bez zmian (`modules/production/services/mobile_api_service.py:1211-1232`).

### Kafel jednostki `zamowienie`

`kafel` = `{"zamowienie": {…}, "pozycje": [kafel-pozycja, …]}` (`modules/production/routers/mobile_api.py:457-466`):

- `zamowienie` — 14 pól wziętych z pierwszej pozycji (`modules/production/routers/mobile_api.py:357-361`
  (`POLA_ZAMOWIENIA_KAFLA`)) plus `order_id`, `deadline` (termin zamówienia = najbliższy termin jego aktywnych
  pozycji, `modules/production/priorytety/services/kolejka.py:83-91` (`termin_zamowienia`)) i `priorytet` **bez**
  `pozycja_w_zamowieniu` (`modules/production/priorytety/services/stol.py:843-852` (`priorytet_zamowienia`));
- `pozycje` — **wszystkie** pozycje zamówienia, także w innych statusach i anulowane, po kolejności w zamówieniu
  (`product_sequence_in_order`, potem id) (`modules/production/routers/mobile_api.py:436-443`). Appka pokazuje
  postęp i plakietki sąsiednich stanowisk z pola `status` każdej pozycji.

**Pozycja, która nie przyjdzie na Formatowanie.** Pozycja bez docięcia (`cut_to_size: false`) omija Formatowanie
i idzie prosto do pakowania (`modules/production/services/order_timeline_service.py:105-106`,
`modules/production/priorytety/services/widok.py:341-348` (`sciezka_omija`)). Nie liczy się do kompletności
zamówienia na Formatowaniu: zamówienie jest kompletne i wchodzi na stół, choć ta pozycja stoi jeszcze np. na
Sklejaniu, a `brakuje` i `pozycji` jej nie pokazują (`modules/production/priorytety/services/kolejka.py:128-139`).
Kafel zamówienia na Formatowaniu dalej ją niesie w `pozycje`. **Appka ją wyróżnia** na ekranie Formatowania: pozycja
z `cut_to_size == false` i `status` innym niż `czeka_na_formatowanie` → plakietka „idzie prosto do pakowania”, bez
przycisków ZAKOŃCZ i licznika. Pozycja z `cut_to_size == false`, która **stoi** w `czeka_na_formatowanie` (ręczna
zmiana statusu w panelu), liczy się normalnie (`modules/production/priorytety/services/kolejka.py:135-139`). Na
Pakowaniu nic nie omija stanowiska (`modules/production/services/order_timeline_service.py:103-104`).

### Przykład 2 — Formatowanie (`jednostka: "zamowienie"`): jeden kafel, jedno niekompletne

Kształt sprawdzony na żywo (`formatting`, 2026-10-05); dane fikcyjne, pozycje skrócone do pól istotnych dla ekranu
(pełny kafel-pozycja jak w przykładzie 1).

```json
{
  "station_code": "formatting",
  "tryb": "stol",
  "jednostka": "zamowienie",
  "miejsca": 2,
  "stol": [
    {
      "kafel": {
        "zamowienie": {
          "internal_order_number": "9002",
          "baselinker_order_id": 90000002,
          "client_name": "Klient testowy",
          "client_order_number": null,
          "delivery_type": "courier",
          "transport": {"mode": "kurier", "trip_name": null, "trip_date": null, "vehicle_name": null,
                        "repack_required": false, "repack_reason": null},
          "packing_hint": {"kind": "paczka", "count": 1, "pallet_type": null, "weight_kg": 25},
          "delivery_city": "Testowo",
          "delivery_postcode": "00-000",
          "order_notes": null,
          "order_source": "allegro",
          "order_source_id": 2,
          "order_source_name": "Allegro",
          "order_source_display": "Allegro",
          "order_id": 9502,
          "deadline": "2026-10-07",
          "priorytet": {"gwiazdki": 3, "szczebel": "gwiazdki", "trasa": null}
        },
        "pozycje": [
          {"id": 9201, "short_id": "9002_1", "status": "czeka_na_formatowanie", "cut_to_size": true,
           "quantity_ordered": 2, "quantity_done": 0,
           "priorytet": {"gwiazdki": 3, "szczebel": "gwiazdki", "trasa": null, "pozycja_w_zamowieniu": "1/2"},
           "…": "…"},
          {"id": 9202, "short_id": "9002_2", "status": "czeka_na_sklejanie", "cut_to_size": false,
           "quantity_ordered": 1, "quantity_done": null,
           "priorytet": {"gwiazdki": 3, "szczebel": "gwiazdki", "trasa": null, "pozycja_w_zamowieniu": "2/2"},
           "…": "…"}
        ]
      },
      "pobrano": "2026-10-05T09:20:00",
      "zrodlo": "kolejka"
    }
  ],
  "odlozone": [],
  "niekompletne": [
    {
      "kafel": {"zamowienie": {"order_id": 9503, "internal_order_number": "9003", "…": "…"},
                "pozycje": [{"id": 9301, "short_id": "9003_1", "status": "czeka_na_formatowanie", "…": "…"},
                            {"id": 9302, "short_id": "9003_2", "status": "czeka_na_sklejanie", "…": "…"},
                            {"id": 9303, "short_id": "9003_3", "status": "czeka_na_formatowanie", "…": "…"}]},
      "na_stanowisku": 2,
      "pozycji": 3,
      "brakuje": [{"short_id": "9003_2", "stanowisko": "gluing"}]
    }
  ],
  "limit_odlozen": 10,
  "kolejka_dalej": 17
}
```

W przykładzie pozycja `9002_2` jest bez docięcia: zamówienie 9002 leży na stole, a appka pokazuje przy `9002_2`
„idzie prosto do pakowania”. `quantity_done` to licznik **tego** stanowiska (`station_code` z URL) albo `null`
(`modules/production/services/mobile_api_service.py:1197-1199`).

---

## 5. POST /api/mobile/orders/<id>/postpone

„Odłóż” kafel z powodem (`modules/production/routers/mobile_api.py:625-689` (`order_postpone`)).

### Żądanie

```
POST /api/mobile/orders/9101/postpone
Authorization: Bearer <JWT>
X-Operation-Id: 3f6c…            (nowy na akcję, ten sam przy każdym ponowieniu — sekcja 10)
X-Worker-Ids: 12                  (jak w ZAKOŃCZ)
Content-Type: application/json

{"station_code": "gluing", "zakres": "pozycja", "powod": "brak_materialu", "notatka": "czekamy na dąb 4 cm"}
```

| Pole | Typ | Wymagane | Walidacja |
|---|---|---|---|
| `station_code` | string | nie (domyślnie stanowisko urządzenia) | jak w ZAKOŃCZ: 400 `missing_station_code`, 404 `unknown_station`, 403 `station_mismatch` (`modules/production/routers/mobile_api.py:99-111`, `modules/production/routers/mobile_api.py:644-646`) |
| `zakres` | `"pozycja"` \| `"zamowienie"` | tak | musi być równy `jednostka` stanowiska z `desk`; inaczej 400 `dane_niepoprawne` (`modules/production/routers/mobile_api.py:652-665`) |
| `powod` | string z listy niżej | tak | spoza listy → 400 `powod_niepoprawny` (`modules/production/priorytety/services/stol.py:703-704`) |
| `notatka` | string \| null | przy `powod = "inne"` tak | najwyżej 255 znaków, inaczej 400 `dane_niepoprawne`; serwer obcina spacje, pusta = brak; `inne` bez notatki → 400 `powod_niepoprawny` (`modules/production/routers/mobile_api.py:653-658`, `modules/production/priorytety/services/stol.py:702-706`) |

`<id>` w ścieżce to **zawsze id pozycji** (pole `id` kafla-pozycji). Dla `zakres: "zamowienie"` — id dowolnej pozycji
zamówienia (np. `kafel.pozycje[0].id`); odkładany jest kafel całego zamówienia
(`modules/production/routers/mobile_api.py:632-634`, `modules/production/routers/mobile_api.py:678-679`).

### Powody

Serwer zna tylko kody (`modules/production/priorytety/stale.py:64` (`POWODY_ODLOZENIA`)). Etykiety to propozycja
dla appki (te same słowa panel biura pokazuje małą literą, `modules/production/priorytety/stale.py:66-72`):

| Kod | Etykieta na tablecie |
|---|---|
| `brak_materialu` | Brak materiału |
| `awaria_maszyny` | Awaria maszyny |
| `brak_miejsca` | Brak miejsca |
| `czeka_na_biuro` | Czeka na biuro |
| `inne` | Inne (notatka wymagana) |

### Kolejność sprawdzeń

stanowisko (`modules/production/routers/mobile_api.py:644-646`) → Lakiernia 409 (`modules/production/routers/mobile_api.py:649-650`)
→ dane i zakres 400 (`modules/production/routers/mobile_api.py:652-665`) → pracownicy z `X-Worker-Ids`
(`modules/production/routers/mobile_api.py:667-669`) → blokada zamówienia, 404 `order_not_found`
(`modules/production/routers/mobile_api.py:673-675`) → powód 400 → kafel na stole 409 → limit 409
(`modules/production/priorytety/services/stol.py:690-721` (`odloz`)) → zapis i log, sygnał po commicie
(`modules/production/routers/mobile_api.py:687`).

### 200 — stół bez dopełnienia

Ciało jak w `GET desk` (sekcja 4), ale **bez dopełnienia**: odłożony kafel jest już w `odlozone`, a jego miejsce
w `stol` jest wolne (`modules/production/routers/mobile_api.py:636-638`, `modules/production/routers/mobile_api.py:689`).
**Appka po 200 woła `GET desk`** — dopiero on dołoży następny kafel. Na podglądzie: po Odłóż `stol` miał 1 kafel przy
`miejsca: 2`, następny `GET desk` dołożył drugi (sprawdzone na żywo 2026-10-05). Test:
`tests/test_priorytety_mobile.py:643` (`test_postpone_200_zwraca_stol_z_odlozonym`).

```json
{
  "station_code": "gluing", "tryb": "stol", "jednostka": "pozycja", "miejsca": 2,
  "stol": [{"kafel": {"id": 9102, "…": "…"}, "pobrano": "2026-10-05T09:15:02", "zrodlo": "kolejka"}],
  "odlozone": [{"kafel": {"id": 9101, "…": "…"}, "odlozono": "2026-10-05T09:31:32", "powod": "brak_materialu",
                "notatka": "czekamy na dąb 4 cm", "pracownik": "Adam K."}],
  "niekompletne": [], "limit_odlozen": 10, "kolejka_dalej": 76
}
```

### Błędy (dosłowne komunikaty z kodu, sprawdzone na żywo)

| Status | Ciało | Zapamiętane pod `X-Operation-Id`? |
|---|---|---|
| 400 | `{"error": "powod_niepoprawny", "message": "Wybierz powód odłożenia z listy."}` | nie |
| 400 | `{"error": "powod_niepoprawny", "message": "Przy powodzie „inne” wpisz, dlaczego odkładasz."}` | nie |
| 400 | `{"error": "dane_niepoprawne", "message": "Podaj zakres (pozycja albo zamowienie), powód i opcjonalną notatkę do 255 znaków."}` | nie |
| 400 | `{"error": "dane_niepoprawne", "message": "Na tym stanowisku odkłada się pojedyncze pozycje."}` (albo „…całe zamówienia.”) | nie |
| 404 | `{"error": "order_not_found"}` | nie |
| 409 | `{"error": "nie_na_stole", "message": "Zamówienie 9001 nie leży na stole Sklejania."}` — kafla nie ma na stole **albo jest już odłożony** (np. drugi tablet go zamknął albo odłożył) | nie |
| 409 | `{"error": "limit_odlozen", "message": "Na Sklejaniu leży 10 odłożonych pozycji. Zamknij którąś, zanim odłożysz kolejną."}` (odmiana wg liczby i jednostki: „…leży 1 odłożona pozycja…”, „…leżą 3 odłożone zamówienia. Zamknij któreś…”) | nie |
| 409 | `{"error": "stanowisko_bez_stolu", "message": "Lakiernia pracuje z listy, bez stołu."}` | nie |
| 400 / 404 / 409 | `worker_ids_required` / `worker_not_found` / `worker_inactive` — obsada z `X-Worker-Ids` jak w ZAKOŃCZ (sekcja 10) | nie |
| 422 | `{"error": "invalid_worker_ids", "detail": …}` — pusty albo zły `X-Worker-Ids` | **tak** (422 nie jest „do ponowienia”) |

Komunikaty: `modules/production/priorytety/services/stol.py:703-721`, `modules/production/priorytety/services/stol.py:677-687`
(`komunikat_limitu`), `modules/production/routers/mobile_api.py:652-665`. „Nie zapamiętane” = kody 400, 403, 404,
409 są w `BLEDY_DO_PONOWIENIA` i dekorator cofa transakcję bez zapisu wpisu
(`modules/production/routers/mobile_api.py:130` (`BLEDY_DO_PONOWIENIA`),
`modules/production/services/mobile_api_service.py:590-595`); testy `tests/test_priorytety_mobile.py:672`
(`test_postpone_limit_409_bez_wpisu_idempotencji`), `tests/test_priorytety_mobile.py:690`
(`test_postpone_nie_na_stole_409_bez_wpisu_idempotencji`). 200 jest zapamiętane: powtórka z tym samym
`X-Operation-Id` oddaje **zapisaną** odpowiedź (stół z chwili pierwszego wykonania) bez ponownego odkładania
(`modules/production/services/mobile_api_service.py:551-566`; test `tests/test_priorytety_mobile.py:746`
(`test_postpone_powtorka_idempotentna_zwraca_zapisana_odpowiedz`)) — dlatego po każdym 200 appka i tak woła `GET desk`.

### Zasady dla appki

- **Limit jest miękki i liczy go serwer.** Liczba odłożonych jest czytana zwykłym odczytem, więc dwa Odłóż w tej
  samej chwili mogą oba dostać 200 i przekroczyć limit o 1 (`modules/production/priorytety/services/stol.py:665-668`).
  Appka nie liczy limitu sama i nie blokuje przycisku na podstawie `limit_odlozen` — decyduje odpowiedź serwera;
  przy 409 `limit_odlozen` pokazuje `message`, kafel zostaje na stole.
- **Odłóż tylko online.** Odłożenie zmienia stół, a następny kafel przychodzi z serwera. Przycisk Odłóż jest
  nieaktywny bez połączenia. Gdyby wpis `postpone` mimo to trafił do kolejki offline: 409 `limit_odlozen`
  i `nie_na_stole` porzucają go z komunikatem (sekcja 10).
- **Odłożony kafel zamyka się zwykłym ZAKOŃCZ** (i działa na nim licznik sztuk): bramka przepuszcza wiersz odłożony
  tak samo jak leżący (`modules/production/priorytety/services/stol.py:293-298`; test
  `tests/test_priorytety_mobile.py:768` (`test_zakoncz_odlozonego_200`)). Tablet nie ma „przywróć” — odłożony kafel
  wraca na stół tylko przez „Wyślij” w panelu biura (`modules/production/priorytety/services/stol.py:900` (`wyslij`)).

---

## 6. ZAKOŃCZ i licznik w trybie `stol`

`POST /orders/<id>/complete` i `PATCH /orders/<id>/quantity` — ciało, nagłówki i odpowiedź 200 bez zmian.
Dochodzi bramka statusu i stołu, zdjęcie kafla i sygnały.

### Kolejność sprawdzeń ZAKOŃCZ

1. stanowisko: 400 `missing_station_code`, 404 `unknown_station`, 403 `station_mismatch`
   (`modules/production/routers/mobile_api.py:852-855`);
2. pracownicy z `X-Worker-Ids` (`modules/production/routers/mobile_api.py:857-859`);
3. blokada zamówienia i pozycji, 404 `order_not_found` (`modules/production/routers/mobile_api.py:866-868`);
4. **bramka statusu** → 409 `pozycja_poza_stanowiskiem` **[K3-poprawka-2]**, potem **bramka stołu** → 409
   `nie_na_stole` — obie w `stol.bramka_zakoncz`, na pozycji z blokady, przed zapisem
   (`modules/production/routers/mobile_api.py:875-886`, `modules/production/priorytety/services/stol.py:288-302`). Dawnej odmowy Pakowania
   bez sposobu dostawy (409 `delivery_method_not_set`) w kodzie już nie ma — logistyka 4.6
   (`modules/production/routers/mobile_api.py:870-873`; sekcja „Pakowanie i sposób dostawy” niżej);
5. zapis: 400 `invalid_station`, 500 `complete_failed` (`modules/production/routers/mobile_api.py:888-899`);
6. zdjęcie kafla ze stołu w tej samej transakcji — **także w trybie `stary` i dla starej appki**; plan sygnałów
   (`modules/production/routers/mobile_api.py:901-912`);
7. 200 z obiektem pozycji (`modules/production/routers/mobile_api.py:920`). Stół trzeba pobrać osobno (`GET desk`).

**ZAKOŃCZ i licznik tylko dla pozycji, która czeka na tym stanowisku** (`status` = status stanowiska z sekcji 10).
**[K3-poprawka-2]** W trybie `stol` (nowa appka) serwer to pilnuje: pozycja w innym statusie dostaje 409
`pozycja_poza_stanowiskiem`, zanim bramka spojrzy na stół (`modules/production/priorytety/services/stol.py:288-291`). Bez tej bramki tranzycja ustawiłaby
status następnego stanowiska bez sprawdzania bieżącego (`modules/production/models.py:668-701`) — pozycja ze
Sklejania „zrobiona” na Formatowaniu przeskoczyłaby na Krawędzie. W trybie `stary` i dla starej appki tej bramki nie
ma (jak dziś). **Appka i tak pokazuje pozostałe pozycje kafla bez przycisków ZAKOŃCZ i licznika** — 409 to bramka
na błędy i na zaległe wpisy kolejki offline. ZAKOŃCZ kafla-zamówienia to osobne ZAKOŃCZ każdej pozycji w statusie
stanowiska, każde z własnym `X-Operation-Id`; przycisk po kliknięciu jest nieaktywny do odpowiedzi serwera.

Licznik: walidacja `quantity_done` (400 `missing_or_invalid_quantity_done`), stanowisko, pracownicy, 404, **ta sama
bramka** (statusu i stołu), zapis (400 `invalid_quantity`, 500 `update_failed`), sygnał na stanowisko po commicie
(`modules/production/routers/mobile_api.py:936-977`). Bramka licznika czyta status pozycji i stół zwykłym odczytem, bez blokady
zamówienia (`modules/production/routers/mobile_api.py:953-959`); licznik nie zdejmuje kafla.

### Bramka — co przechodzi

`stol.bramka_zakoncz` (`%s:261-302` (`bramka_zakoncz`)) przepuszcza bez żadnej kontroli:

| Przypadek | Odnośnik |
|---|---|
| Lakiernia — zawsze, niezależnie od ustawień | `modules/production/priorytety/services/stol.py:282-283` |
| tryb stanowiska `stary` | `modules/production/priorytety/services/stol.py:284-285` |
| stara appka (sekcja 11) | `modules/production/priorytety/services/stol.py:286-287` |

Poza tymi trzema przypadkami pozycja musi czekać na stanowisku (inaczej 409 `pozycja_poza_stanowiskiem`, niżej),
a do tego przechodzi tylko:

| Przypadek | Odnośnik |
|---|---|
| kafel leżący na stole **albo odłożony** | `modules/production/priorytety/services/stol.py:292-298` |
| na stanowisku zamówieniowym: pozycja zamówienia **niekompletnego** — każdego, nie tylko pokazanego w „Niekompletne” (sekcja nie ma wiersza stołu) | `modules/production/priorytety/services/stol.py:299-300`; test `tests/test_priorytety_stol.py:512` (`test_bramka_przepuszcza_pozycje_niekompletnego_zamowienia`) |

**[K3-poprawka-2] Pozycja spoza statusu stanowiska → 409 `pozycja_poza_stanowiskiem`** (z kodu i testów, nie
z żywego podglądu):

```json
{"error": "pozycja_poza_stanowiskiem", "message": "Pozycja 1203_4 nie czeka na Pakowaniu."}
```

Szablon: „Pozycja {short_id pozycji} nie czeka na {stanowisko w miejscowniku}.” (`modules/production/priorytety/services/stol.py:288-291`). Typowe
przyczyny: pozycja kafla-zamówienia już spakowana albo czekająca na innym stanowisku, pozycja omijająca stanowisko
(np. bez docięcia na Formatowaniu), pozycja zamówienia z „Niekompletnych”, która jeszcze nie doszła, zaległy wpis
kolejki offline dla pozycji, która poszła dalej. Odmowa niczego nie zapisuje i nie jest zapamiętywana (status 409
jest w `BLEDY_DO_PONOWIENIA`, `modules/production/routers/mobile_api.py:130`); appka **porzuca** wpis kolejki — decyduje po polu `error` (sekcja 10).
Testy: `tests/test_priorytety_stol.py:1874` (`test_poza_stanowiskiem_pakowanie_kafel_zamowienia_z_pozycjami_w_roznych_statusach`),
`tests/test_priorytety_stol.py:1897` (`test_poza_stanowiskiem_formatowanie_niekompletne_zamowienie`),
`tests/test_priorytety_stol.py:1914` (`test_poza_stanowiskiem_pozycja_omijajaca_stanowisko`),
`tests/test_priorytety_stol.py:1928` (`test_poza_stanowiskiem_stanowisko_pozycyjne_przed_nie_na_stole`),
`tests/test_priorytety_stol.py:1938` (`test_poza_stanowiskiem_bez_bramki_w_stary_dla_starej_appki_i_lakierni`).

Pozycja w statusie stanowiska, ale bez kafla na stole i bez furtki „Niekompletne” → 409 `nie_na_stole` (sprawdzone na
żywo dla ZAKOŃCZ i licznika na Sklejaniu):

```json
{"error": "nie_na_stole", "message": "Zamówienie 9001 nie leży na stole Sklejania."}
```

Szablon: „Zamówienie {numer zamówienia} nie leży na stole {stanowisko w dopełniaczu}.”
(`modules/production/priorytety/services/stol.py:301-302`) — także na stanowisku pozycyjnym podaje numer
zamówienia. Typowe przyczyny: kafel zdjęło biuro albo zaległy wpis kolejki offline dotyczy kafla, którego już nie
ma, choć pozycja dalej czeka na stanowisku; **zamówienie kompletne, które jeszcze nie weszło na stół** (np. ostatnia pozycja
właśnie doszła) też dostaje 409 — wejdzie przy następnym `GET desk` (test jw., druga część). 409 `nie_na_stole` nie
jest zapamiętywane (`tests/test_priorytety_stol.py:666` (`test_nie_na_stole_nie_zapisuje_wpisu_idempotencji`)).
Reakcja appki: komunikat z `message` i `GET desk`; z kolejki offline — reguła z sekcji 10.

**„Niekompletne” — ZAKOŃCZ pozycji działa.** Pracownik Formatowania/Pakowania może zakończyć i liczyć każdą pozycję
z sekcji „Niekompletne”, która już czeka na stanowisku; brakujące pozycje dostają 409 `pozycja_poza_stanowiskiem`. Ostatnia brakująca pozycja czyni zamówienie kompletnym —
wejdzie na stół przy następnym `GET desk` (sygnał z ZAKOŃCZ na poprzednim stanowisku go wywoła, sekcja 8).

### Dwa tablety, ten sam kafel — potwierdzone w K5

ZAKOŃCZ bierze blokadę zamówienia i jego pozycji przed bramką i zapisem, a własny wiersz stołu czyta odczytem
bieżącym (`modules/production/routers/mobile_api.py:861-886`; test `tests/test_priorytety_stol.py:455`
(`test_zdjecie_kafla_po_blokadzie_zamowienia_i_pozycji`)). Dwa ZAKOŃCZ tego samego kafla z dwóch tabletów idą więc po
kolei: drugi czeka na blokadzie, a potem widzi pozycję już w statusie następnego stanowiska i dostaje 409
`pozycja_poza_stanowiskiem` **[K3-poprawka-2]** (kafel zszedł w pierwszej transakcji razem z pozycją,
`modules/production/routers/mobile_api.py:901-908`, `modules/production/priorytety/services/stol.py:288-291`). Dotyczy to też stanowiska zamówieniowego, na którym kafel zamówienia zostaje, dopóki
na stanowisku jest inna pozycja zamówienia (`modules/production/priorytety/services/stol.py:217-223`) — dawniej drugie ZAKOŃCZ tej samej pozycji przeszło tam
bramkę.
**Potwierdzone na MySQL w kroku K5** (tryb `zakoncz-zakoncz-ten-sam-kafel` na Sklejaniu oraz jego warianty dla
kafla-zamówienia na Formatowaniu i Pakowaniu, razem 102 przebiegi): zawsze jedno 200 i jedno 409
`pozycja_poza_stanowiskiem`, status pozycji przesunięty raz, przy 409 bez wpisu idempotencji. Dla appki:
409 `pozycja_poza_stanowiskiem` w tej sytuacji to normalny wynik (komunikat i `GET desk`), a przycisk ZAKOŃCZ po kliknięciu jest
nieaktywny do odpowiedzi serwera (bez podwójnego wysłania z jednego tabletu).

Dwa Odłóż naraz przy limicie mogą oba dostać 200 (limit miękki, sekcja 5); dwa `GET desk` naraz dają ten sam stół
(sekcja 4).

### Kiedy bramki nie ma

- tryb `stary` (domyślny po wdrożeniu, zanim biuro włączy stoły) — ZAKOŃCZ jak dziś;
- stara appka (sekcja 11);
- `POST /orders/<id>/reject` (doróbka) i druk etykiet — bez bramki
  (`modules/production/routers/mobile_api.py:980-1064`, `modules/production/routers/mobile_api.py:1256-1289`).

### Pakowanie i sposób dostawy (logistyka 4.6 w kodzie)

Logistyka 4.6 („pakowanie bez sposobu dostawy”, decyzja Konrada 5.10) jest scalona do gałęzi (`8f60b221`) i jest
w kodzie pod hashem z nagłówka: `POST /orders/<id>/complete` na Pakowaniu **nie zwraca już** 409
`delivery_method_not_set` — zamówienie bez sposobu dostawy pakuje się normalnie (etykieta paczki z pasem „NIE
USTAWIONO” robi serwer, Base. nie dostaje statusu po spakowaniu, dopóki logistyk nie ustawi sposobu)
(`modules/production/routers/mobile_api.py:870-873`). Kształt odpowiedzi bez zmian; `transport.mode` dalej bywa `null`
(`modules/production/logistics/sposoby.py:107-113`, `modules/production/logistics/sposoby.py:124`).

**Stół Pakowania przyjmuje zamówienia bez sposobu dostawy** (od `2f3e6ce7`): takie zamówienie jest zwykłym
kandydatem Pakowania — wchodzi na stół, do „Niekompletnych” i do `kolejka_dalej`, biuro może je „Wysłać” na
stanowisko, a start stołów bierze je jak każde inne (`modules/production/priorytety/services/stol.py:465-474` (`_kandydaci`), `modules/production/priorytety/services/stol.py:1007`; testy
`tests/test_priorytety_stol.py:836` (`test_dopelnij_pakowanie_bez_sposobu_dostawy_wchodzi_jak_kazde`),
`tests/test_priorytety_mobile.py:246` (`test_desk_pakowanie_bez_sposobu_dostawy_na_stole`),
`tests/test_priorytety_stol.py:1480` (`test_wyslij_pakowanie_bez_sposobu_dostawy_kladzie_kafel`),
`tests/test_priorytety_stol.py:1730` (`test_rozpoczete_pakowanie_bez_sposobu_dostawy_wchodzi`)). ZAKOŃCZ takiego kafla przechodzi bramkę
jak każdy inny (`tests/test_priorytety_stol.py:566` (`test_bramka_pakowanie_bez_sposobu_dostawy_tylko_bramka_stolu`)). Appka niczego tu nie
obchodzi.

**Appka zostawia obsługę 409 `delivery_method_not_set`** (komunikat z `message`, wpis zostaje w kolejce): nowa appka
na backendzie sprzed 4.6 (produkcja przed deployem 8.10) dostaje go jak dotąd. Nie zakłada jednak, że wystąpi,
i nie potrzebuje osobnej sekcji „czeka na sposób dostawy”.

**Blokada po stronie appki** (zgłoszenie centrali logistyki 5.10, dotyczy kodu appki, nie serwera): appka 1.7.3 sama
blokuje ZAKOŃCZ na Pakowaniu, gdy sposób dostawy jest pusty (`transport.mode == null`; komponent appki
`DeliveryGate`). Po 4.6 serwer takiego zamówienia nie odrzuca, więc **nowa appka tę blokadę usuwa**: zamówienie bez sposobu dostawy da się
zakończyć, a lista/stół nie spycha go na koniec (kolejność daje serwer). Na kaflu najwyżej informacyjna plakietka
**„Sposób dostawy do ustalenia – pakuj normalnie”** (tekst zatwierdzony przez Konrada 5.10), bez blokady
przycisku. Okno paczek przy ZAKOŃCZ działa dla zamówienia z i bez sposobu dostawy (w appce 1.7.3
jest warunkowane tą samą flagą co blokada — do rozdzielenia). O odmowie decyduje serwer, nie appka.

---

## 7. Pole `priorytet` i `KSZTALT_ODPOWIEDZI_KOLEJKI = 6`

Każda pozycja serializowana przez API mobilne ma pole `priorytet` (`modules/production/services/mobile_api_service.py:1292`),
liczone przez `stol.kontekst_priorytetu` (`modules/production/priorytety/services/stol.py:775-840` (`kontekst_priorytetu`)):

```json
{
  "priorytet": {
    "gwiazdki": 4,
    "szczebel": "trasa",
    "trasa": {"id": 7, "nazwa": "Trasa testowa", "data": "2026-10-08"},
    "pozycja_w_zamowieniu": "2/5"
  }
}
```

| Pole | Typ | Znaczenie |
|---|---|---|
| `gwiazdki` | int 0–5 | gwiazdki zamówienia ustawione przez biuro (`modules/production/priorytety/services/stol.py:830`) |
| `szczebel` | string \| null | rodzaj szczebla drabiny, z którego zamówienie bierze kolejność (tabela niżej) (`modules/production/priorytety/services/stol.py:815-837`) |
| `trasa` | `{id, nazwa, data}` \| null | tylko gdy `szczebel = "trasa"`; `data` = data trasy (ISO) albo `null` (`modules/production/priorytety/services/stol.py:826-829`) |
| `pozycja_w_zamowieniu` | `"i/n"` \| null | miejsce pozycji wśród niezanulowanych pozycji zamówienia; doróbka ma miejsce oryginału; pozycja anulowana bez żywej doróbki → `null` (`modules/production/priorytety/services/stol.py:737-772`) |

| `szczebel` | Plakietka na kaflu (propozycja) |
|---|---|
| `"trasa"` | „Trasa: {nazwa}, {data}” |
| `"gwiazdki"` | gwiazdki z pola `gwiazdki` („★★★★★” … brak przy 0) — także szczebel „bez gwiazdek” |
| `"po_terminie"` | „Po terminie” |
| `"blisko_terminu"` | „Blisko terminu” |
| `"rozpoczete"` | „Rozpoczęte” |
| `"dorobka"` | „Doróbka” (pozycja jest doróbką; `trasa` wtedy `null`) (`modules/production/priorytety/services/stol.py:836-837`) |
| `null` | bez plakietki (zamówienie jeszcze bez rangi) |

Gwiazdki pokazuje się przy każdym szczeblu (także przy trasie i tagu), plakietkę szczebla — obok nich.
`szczebel` i `trasa` pochodzą z rangi zapisanej przy ostatnim przeliczeniu, więc plakietka tagu może być chwilę
nieaktualna — jak ranga na liście (`modules/production/priorytety/services/stol.py:792-793`). Appka nie liczy z tych
pól kolejności (sekcja 4).

Testy: `tests/test_priorytety_mobile.py:829` (`test_serialize_order_ma_priorytet_i_ksztalt_6`),
`tests/test_priorytety_mobile.py:849` (`test_priorytet_szczebel_z_rangi_i_drabiny`).

### Gdzie pole jest

Wszędzie, gdzie serializer pozycji: listy `/stations/<S>/orders` (`modules/production/routers/mobile_api.py:339-347`),
`/orders/since` w `changed` (`modules/production/services/mobile_api_service.py:1865-1873`), `desk` i `postpone`
(`modules/production/routers/mobile_api.py:447-455`), `/orders/search` (`modules/production/routers/mobile_api.py:780-783`),
`/orders/<id>`, odpowiedzi ZAKOŃCZ i licznika (pojedyncza pozycja liczy `priorytet` sama,
`modules/production/services/mobile_api_service.py:1236-1239`) oraz `reject` (`original`, `rework`,
`modules/production/routers/mobile_api.py:1059-1064`). Kafel-zamówienie ma dodatkowo `zamowienie.priorytet` bez
`pozycja_w_zamowieniu` (sekcja 4).

`grupa_wykonczenia` — w tym samym serializerze; obiekt tylko dla listy Lakierni (`station_code = painting`), dla
pozostałych stanowisk `null` (`modules/production/services/mobile_api_service.py:1240-1243`; sekcja 13).

### Pola starej appki zostają

`priority_rank` i `is_priority` bez zmian (`modules/production/services/mobile_api_service.py:1290-1291`), licznik
`priority_count` w `/summary` też (`modules/production/services/mobile_api_service.py:1721`). Nowa appka rysuje
plakietki z `priorytet`, nie z `is_priority`.

### KSZTALT 6

`KSZTALT_ODPOWIEDZI_KOLEJKI` podbity z 5 na 6 razem z polami `priorytet` i `grupa_wykonczenia`
(`modules/production/routers/mobile_api.py:140-146`). Wchodzi do ETagu listy `/orders` (`modules/production/routers/mobile_api.py:309-310`)
i `desk` (`modules/production/routers/mobile_api.py:413`): stara appka po wdrożeniu raz pobierze pełną listę (ETag się
zmienia), a dodatkowe pola zignoruje. `/orders/since` ETagu nie ma.

---

## 8. Realtime: token, połączenie SSE, sygnał

Wzór: agent druku. Serwer zapisuje do bazy, **po commicie** wysyła krótki sygnał bez danych na kanał brokera
(Centrifugo), odbiorca po sygnale woła REST (`modules/production/services/realtime_service.py:1-17`). Dla tabletu
REST-em po sygnale jest `GET desk` (Lakiernia: lista).

### GET /api/mobile/realtime-token

`Authorization: Bearer <JWT>`, bez ciała (`modules/production/routers/mobile_api.py:692-731` (`realtime_token`)).

200 — przykład złożony z kodu (na podglądzie realtime był wyłączony; kształt potwierdza test
`tests/test_priorytety_sygnaly.py:403` (`test_realtime_token_kanaly_stanowiska`)), tablet Krawędzi:

```json
{
  "enabled": true,
  "token": "eyJ…(skrócony)",
  "ttl_seconds": 3600,
  "sse_url": "https://<adres CRM>/realtime/connection/uni_sse",
  "channels": ["station:edges", "station:painting"]
}
```

- `channels` — kanały są już w tokenie (klient SSE nie subskrybuje sam): najpierw stanowisko urządzenia, potem
  reszta jego grupy w kolejności procesu (`modules/production/routers/mobile_api.py:715-718`,
  `modules/production/services/realtime_service.py:209-233` (`issue_connection_token`)). Tablet Sklejania:
  `["station:gluing"]`; tablet Krawędzi: `["station:edges", "station:painting"]`; tablet zarejestrowany na Lakierni
  (ta sama grupa): `["station:painting", "station:edges"]` (`modules/production/services/mobile_api_service.py:118-120`,
  `modules/production/services/station_catalog.py:24-34` (`STATION_ORDER`)).
- `ttl_seconds` — czas życia tokena (domyślnie 3600, z konfiguracji `REALTIME.token_ttl_seconds`)
  (`modules/production/services/realtime_service.py:35`, `modules/production/services/realtime_service.py:225`).
  Pole nazywa się inaczej niż u agenta druku (`expires_in`, `modules/production/routers/api/print_agent_api.py:280-282`).
- `sse_url` — adres publiczny połączenia; **może być pustym napisem** — wtedy appka składa go z adresu CRM:
  `<adres CRM>/realtime/connection/uni_sse` (`modules/production/services/realtime_service.py:81-84`, wzór
  `tools/print_agent/print_agent.py:417-422`).
- Token jest wystawiany dla `device:<device_id>` (`modules/production/routers/mobile_api.py:720`).

| Status | Ciało | Co robi appka |
|---|---|---|
| 503 | `{"enabled": false, "reason": "realtime disabled"}` | realtime wyłączony: samo odpytywanie (sekcja 9), nowa próba tokena co 5 min, bez komunikatu dla pracownika (sprawdzone na żywo) (`modules/production/routers/mobile_api.py:712-713`; test `tests/test_priorytety_sygnaly.py:428` (`test_realtime_token_503_gdy_wylaczony`)) |
| 503 | `{"enabled": false, "reason": "misconfigured"}` | jak wyżej (`modules/production/routers/mobile_api.py:721-723`) |
| 404 | `{"error": "unknown_station"}` | urządzenie spoza stanowisk z kolejką (trakownia, Weryfikacja, Dostawa) — te ekrany nie łączą się z realtime (`modules/production/routers/mobile_api.py:708-710`; test `tests/test_priorytety_sygnaly.py:448` (`test_realtime_token_404_trakownia`)) |
| 404 | HTML, nie JSON | backend bez tej trasy — jak 503 (sekcja 12) |
| 401 | `{"error": "missing_token"}` / `invalid_token` | jak w każdej końcówce z tokenem |

### Połączenie SSE krok po kroku (wzorzec: `tools/print_agent/print_agent.py`)

1. **Świeży token przy każdym połączeniu** — appka nie odnawia tokena w tle; po zerwaniu woła `realtime-token`
   jeszcze raz (`tools/print_agent/print_agent.py:1003-1028` (`connect_push`)).
2. **`POST` na `sse_url`** z ciałem JSON `{"token": "<JWT>"}`, nagłówki `Content-Type: application/json`,
   `Accept: text/event-stream`; odpowiedź inna niż 200 = nieudane połączenie
   (`tools/print_agent/print_agent.py:487-515` (`open_sse`)). Limit nawiązania połączenia krótki (agent: 5 s,
   `tools/print_agent/print_agent.py:372-376`).
3. **Ramki** (`tools/print_agent/print_agent.py:518-548` (`classify_sse_line`)): linia pusta albo zaczynająca się od
   `:` oraz pola `event:`, `id:`, `retry:` — szum; `data:` puste albo `{}` — ping; `data:` z jedynym kluczem
   `connect` — powitanie (kanał aktywny); **każda inna ramka `data:`** (także niesparsowalna) — sygnał. Appka nie czyta
   treści sygnału; serwer i tak wysyła tylko `{"kind": "station", "station": "<S>"}`
   (`modules/production/services/realtime_service.py:199-206` (`publish_station_signal`)), a format ramki brokera nie
   jest częścią kontraktu.
4. **Po każdym udanym (ponownym) połączeniu** — ramka powitalna `connect` — jedno `GET desk` (na tablecie Krawędzi
   także lista Lakierni): sygnały z przerwy (np. wymiana tokena co godzinę) przepadły, a siatka przy pełnym stole
   nadrobiłaby je dopiero po 5 min.
5. **Ping co ~25 s; 40 s ciszy = połączenie martwe** — zamknąć i połączyć od nowa
   (`tools/print_agent/print_agent.py:366-371` (`SSE_PING_TIMEOUT_SECONDS`)).
6. **Zerwanie raz na TTL to rutyna**: broker rozłącza po wygaśnięciu tokena; jeśli połączenie żyło co najmniej
   `ttl_seconds − 60 s`, nie zgłaszać awarii, tylko połączyć się od razu z nowym tokenem
   (`tools/print_agent/print_agent.py:978-1000` (`czy_token_wygasl_planowo`)).
7. **Ponowienia wg drabinki** 1, 2, 5, 10, 15, 30, 60 s (potem co 60 s bez końca), każda wartość z losowym
   rozrzutem ±10 % — po restarcie brokera tablety hali nie mogą ruszyć w tej samej milisekundzie
   (`tools/print_agent/print_agent.py:379` (`SSE_RECONNECT_LADDER`), `tools/print_agent/print_agent.py:961-975`
   (`_reconnect_delay`)). Udane połączenie zeruje drabinkę.
8. Broker po stronie serwera ma namespace `station` i włączone `uni_sse` w przykładowej konfiguracji
   (`ops/centrifugo/config.example.json:14-25`); czy jest włączony na produkcji — sprawdza wdrożenie (K7), nie appka.

**Tablet z dwoma kanałami** (Krawędzie/Lakiernia): ramka nie mówi appce (w kontrakcie), z którego kanału przyszła,
więc po każdym sygnale tablet odświeża oba widoki — `GET /stations/edges/desk` i listę
`GET /stations/painting/orders` z `If-None-Match` (zwykle 304). Lista ma `max-age=15`
(`modules/production/utils/cache.py:54-57`), więc odświeżenie listy **po sygnale** musi wymusić pytanie serwera
(nagłówek żądania `Cache-Control: no-cache`) — inaczej OkHttp poda ją z pamięci do 15 s. Lakierni nie woła się przez `desk` nigdy (sekcja 13).

### Kiedy przychodzi sygnał `station:<S>`

Zawsze **po commicie**; publikacja nigdy nie rzuca i przy awarii brokera po prostu się nie odbywa
(`modules/production/services/realtime_service.py:112-182` (`publish`); test
`tests/test_priorytety_sygnaly.py:107` (`test_publish_station_signal_nie_rzuca_gdy_broker_padl`)).

| Zdarzenie | Kanał(y) | Odnośnik |
|---|---|---|
| ZAKOŃCZ (także stara appka, tryb `stary`) | to stanowisko, następne stanowisko pozycji, stanowiska, z których zdjęto zaległy kafel | `modules/production/routers/mobile_api.py:909-912`, `modules/production/priorytety/services/sygnaly.py:82-92` (`zaplanuj_po_zakonczeniu`); test `tests/test_priorytety_sygnaly.py:193` (`test_zakoncz_sygnal_na_to_i_nastepne_stanowisko`) |
| licznik sztuk | to stanowisko | `modules/production/routers/mobile_api.py:974-975` |
| Odłóż | to stanowisko | `modules/production/routers/mobile_api.py:686-687` |
| `GET desk`, który coś dołożył (także Twój własny) | to stanowisko | `modules/production/routers/mobile_api.py:552-555`; test `tests/test_priorytety_sygnaly.py:331` (`test_desk_sygnal_tylko_gdy_dopelnil`) |
| doróbka (`reject`) | stanowisko odrzutu, stanowisko powrotu, stanowiska ze zdjętym kaflem | `modules/production/services/rework_service.py:376` |
| zmiany z Base. w panelu | stanowiska ze zdjętym kaflem; Wycinanie, gdy doszła pozycja | `modules/production/routers/api/products_api.py:1317-1321` |
| hurtowa zmiana statusu w panelu | stanowiska ze zdjętym kaflem i stanowisko nowego statusu | `modules/production/routers/api/products_api.py:1688-1692` |
| „Wyślij”, „Zdejmij”, „Przygotuj stoły” (biuro) | to stanowisko | `modules/production/priorytety/routers/panel_api.py:428`, `modules/production/priorytety/routers/panel_api.py:453`, `modules/production/priorytety/routers/panel_api.py:508` |
| import nowych zamówień z Base. | `cutting` i `assembly` | `modules/production/services/sync_service.py:946-953` |
| „Cofnij do pakowania” (Weryfikacja), przepakowanie w Logistyce | `packaging` | `modules/production/logistics/routers/weryfikacja_api.py:322`, `modules/production/logistics/routers/panel_api.py:240-244` |
| cron logistyki (przeniesienie osieroconych pozycji do pakowania) | `packaging` / stanowiska ze zdjętym kaflem | `modules/production/logistics/services/delivery.py:596`, `modules/production/logistics/routers/cron_api.py:55-63` |

**Sygnał nie idzie**, gdy akcja się nie zapisała: 4xx „do ponowienia”, 5xx, wyjątek — plan sygnałów przepada razem
z transakcją (`modules/production/services/mobile_api_service.py:590-595`,
`modules/production/services/mobile_api_service.py:526-534`; test `tests/test_priorytety_sygnaly.py:221`
(`test_sygnal_nie_idzie_przy_rollbacku_409`)), ani przy powtórce idempotentnej (handler się nie wykonuje,
`modules/production/services/mobile_api_service.py:551-566`). Nie każda zmiana ma sygnał — np. zwykła zmiana
sposobu dostawy w Logistyce (bez cofnięcia do pakowania) nie wysyła nic. **Sygnał może nie przyjść nigdy: siatką
jest odpytywanie z sekcji 9**, nie zakładanie, że każda zmiana da sygnał.

---

## 9. Pobieranie stołu i odpytywanie awaryjne

Tablet woła `GET /stations/<S>/desk` (z `If-None-Match`):

1. przy wejściu na ekran stanowiska i po powrocie appki na pierwszy plan;
2. **po własnym ZAKOŃCZ i Odłóż** — także po zsynchronizowaniu kolejki offline (odpowiedź tych akcji nie niesie
   dopełnionego stołu, sekcje 5–6);
3. po sygnale `station:<S>` (sekcja 8);
4. **zawsze, także przy działającym SSE**, wg siatki: **co 30 s, gdy na stole leży mniej kafli niż `miejsca`**
   (w szczególności pusty stół), **co 5 min, gdy leży ich co najmniej `miejsca`**. Siatka łapie zgubiony sygnał,
   wyłączony realtime, odpowiedź `desk` bez dopełnienia (sekcja 4) i zmiany bez sygnału (sekcja 8).

Siatka 30 s / 5 min wynika z kodu i komentarzy serwera (`modules/production/priorytety/services/sygnaly.py:3-6`,
`modules/production/routers/mobile_api.py:703-705`); `refresh_interval_seconds` z `/summary` dotyczy starej listy
i nowa appka go do stołu nie używa (`modules/production/services/mobile_api_service.py:1701-1714`).

**Łączenie sygnałów.** ZAKOŃCZ publikuje na dwa kanały, tablet Krawędzi słucha dwóch, a własny `GET desk` po ZAKOŃCZ
sam wywołuje sygnał „pobranie na stół” (`modules/production/routers/mobile_api.py:552-555`), który wraca do tego
samego tabletu. Zasada: **na stanowisko najwyżej jedno `GET desk` w locie i jedno oczekujące**; sygnał, który
przyjdzie w trakcie pobierania, daje jedno dodatkowe pobranie po nim, kolejne sygnały w tym czasie nic nie dokładają.
Pętli nie ma: `desk`, który niczego nie dołożył, sygnału nie wysyła.

**Bez realtime** (503 albo 404 HTML z `realtime-token`): sama siatka; nowa próba tokena co 5 min.

**500 `desk_failed`** → następna próba przy najbliższym takcie siatki (30 s), nie od razu w pętli; ekran pokazuje
ostatni znany stół (`modules/production/routers/mobile_api.py:546-550`).

**Appka w tle / wygaszony ekran:** nie częściej niż siatka; `GET desk` jest zapisem (sekcja 4).

**Lakiernia** (lista, nie stół): odświeżanie jak dziś — `GET /stations/painting/orders` z ETagiem co
`refresh_interval_seconds` — plus odświeżenie po sygnale `station:painting`
(`modules/production/routers/mobile_api.py:304-312`).

**[K3-poprawka-2] Stanowisko w trybie `stary`** (appka na liście): lista odświeża się jak dziś (ETag,
`refresh_interval_seconds`, delta), a dodatkowo appka woła `GET desk` **najwyżej co 30 s** (i po sygnale), wyłącznie
po to, żeby wykryć przełączenie na `stol`. W `stary` `desk` niczego nie zapisuje (sekcja 4, „Pole `tryb`”,
`modules/production/routers/mobile_api.py:605-609`). Na
backendzie bez `desk` (404 HTML) próba co 30 s jest tania i bezpieczna — też niczego nie zapisuje.

---

## 10. Kolejka offline i idempotencja

**`X-Operation-Id`**: nowy identyfikator (UUID) na każdą akcję, **ten sam** przy każdym ponowieniu tej akcji. Serwer
zapamiętuje odpowiedź 2xx i 4xx spoza kodów „do ponowienia” razem z zapisem i przy powtórce oddaje ją bez
wykonywania akcji (`modules/production/services/mobile_api_service.py:551-566`,
`modules/production/services/mobile_api_service.py:597-624`). Kody 400, 403, 404 i 409 są „do ponowienia”: serwer cofa
transakcję i **niczego nie zapamiętuje**, każde ponowienie trafia do handlera
(`modules/production/routers/mobile_api.py:113-130` (`BLEDY_DO_PONOWIENIA`),
`modules/production/services/mobile_api_service.py:590-595`). Appka **nigdy** nie wysyła tej samej akcji ponownie
z nowym `X-Operation-Id`.

Statusy stanowisk (potrzebne do reguły `nie_na_stole` i do ukrywania przycisków pozycji spoza statusu): `cutting` → `czeka_na_wyciecie`, `assembly` →
`czeka_na_skladanie`, `gluing` → `czeka_na_sklejanie`, `formatting` → `czeka_na_formatowanie`, `edges` →
`czeka_na_krawedzie`, `painting` → `czeka_na_lakiernie`, `packaging` → `czeka_na_pakowanie`
(`modules/production/services/station_catalog.py:68-76` (`STATION_PENDING_STATUS`)).

| Kod | Akcja | Zapamiętany? | Co robić z wpisem kolejki |
|---|---|---|---|
| 409 `pozycja_poza_stanowiskiem` | ZAKOŃCZ, licznik | nie | **[K3-poprawka-2]** **porzucić** (ponowienie nic nie zmieni — pozycja nie czeka już na tym stanowisku), pokazać `message`, potem `GET desk` (`modules/production/priorytety/services/stol.py:288-291`) |
| 409 `nie_na_stole` | ZAKOŃCZ, licznik | nie | **reguła niżej** |
| 409 `nie_na_stole` | Odłóż | nie | porzucić z komunikatem „Zamknięte na innym tablecie albo zdjęte przez biuro”, potem `GET desk` |
| 409 `limit_odlozen` | Odłóż | nie | porzucić, pokazać `message` (ponawianie nic nie da bez człowieka) |
| 409 `stanowisko_bez_stolu` | Odłóż | nie | porzucić i zalogować (błąd appki — Lakiernia nie ma Odłóż) |
| 409 `delivery_method_not_set` | ZAKOŃCZ Pakowania | nie | tylko backend sprzed logistyki 4.6 (produkcja przed deployem 8.10): **zostawić w kolejce**, komunikat z `message`; w kodzie pod hashem z nagłówka tej odmowy już nie ma (`modules/production/routers/mobile_api.py:870-873`) |
| 400 `powod_niepoprawny`, `dane_niepoprawne` | Odłóż | nie | błąd appki: porzucić i zalogować (walidacja w UI ma do tego nie dopuścić) |
| 400 `worker_ids_required` | wszystkie | nie | zachować, wrócić na wybór profilu (bez zmian) |
| 404 `worker_not_found`, 409 `worker_inactive` | wszystkie | nie | **zostawić** w kolejce i pokazać (katalog pracowników się odświeży, admin przywróci pracownika — `modules/production/routers/mobile_api.py:113-130`) |
| 400 `missing_or_invalid_quantity_done` | licznik | nie | błąd appki: porzucić i zalogować |
| 403 `ip_not_allowed` | wszystkie | nie | zostawić i pokazać (konfiguracja sieci serwera, `modules/production/services/mobile_api_service.py:425-428`) |
| 422 `invalid_worker_ids` | wszystkie | **tak** | błąd trwały, nie ponawiać (sprawdzone na żywo: zapamiętany) (`modules/production/services/worker_service.py:452-470`) |
| 403 `station_mismatch` | wszystkie | nie | zachować, nie ponawiać w pętli, pokazać błąd rejestracji (bez zmian) |
| 404 `order_not_found` | ZAKOŃCZ, licznik, Odłóż | nie | pozycji nie ma w systemie (np. usunięta po zmianie w Base.): porzucić z komunikatem |
| 400 `invalid_station`, 500 `complete_failed` | ZAKOŃCZ | nie | bez zmian: 5xx ponawiać, 400 to błąd appki (`modules/production/routers/mobile_api.py:888-899`) |
| 400 `invalid_quantity`, 500 `update_failed` | licznik | nie | bez zmian (`modules/production/routers/mobile_api.py:961-972`) |
| 401 | wszystkie | nie | przerejestrować i ponowić z **tym samym** `X-Operation-Id` (bez zmian) |
| 426 `app_version_too_old` | wszystkie | nie | zostaje w kolejce; pokazać, że tablet wymaga aktualizacji (sekcja 11) |
| 500 `desk_failed`, 503 realtime | `GET` | — | nie są akcjami kolejki (sekcje 8–9) |

**Decyduj po polu `error`, nie po samym statusie HTTP** — ten sam status (404, 409) bywa raz „porzucić”, raz
„zostawić”. Nieznany `error` przy 4xx → zostawić wpis i pokazać. Wpis zostawiony w kolejce nie blokuje akcji innych
pozycji, ale akcje **tej samej** pozycji idą w kolejności (licznik przed ZAKOŃCZ).

**Reguła dla 409 `nie_na_stole` z kolejki (ZAKOŃCZ, licznik).** Kod jest „do ponowienia”: akcja przejdzie z tym samym
`X-Operation-Id`, gdy kafel wejdzie na stół (`modules/production/routers/mobile_api.py:880`; test
`tests/test_priorytety_stol.py:666` (`test_nie_na_stole_nie_zapisuje_wpisu_idempotencji`)). Po 409 appka woła
`GET desk` stanowiska i `GET /orders/<id>` (`<id>` = id pozycji z wpisu, `modules/production/routers/mobile_api.py:802-828`
(`order_details`)):

- pozycja nie leży na stole ani w „Odłożonych” (dla jednostki `zamowienie` — jej zamówienie), **i** jej `status` nie
  jest już statusem tego stanowiska → **porzucić** wpis z komunikatem „Zamknięte na innym tablecie albo zdjęte
  przez biuro” (na backendzie z K3-poprawką-2 taka pozycja dostaje od razu 409 `pozycja_poza_stanowiskiem`; ta
  gałąź reguły zostaje dla pozycji, która zmieniła status między odpowiedzią a `GET /orders/<id>`);
- `GET /orders/<id>` → 404 `order_not_found` → porzucić (pozycja usunięta);
- w przeciwnym razie (pozycja dalej w statusie stanowiska, a kafla nie ma na stole — np. zamówienie kompletne, które
  jeszcze nie weszło na stół) — **zostawić**, ponowić najwyżej raz na takt siatki (≥ 30 s) albo po sygnale, **nie**
  po `GET desk` wywołanym przez samą tę regułę (inaczej 409 → desk → ponowienie → 409 kręciłoby się w tempie sieci),
  i pokazać
  ostrzeżenie z możliwością ręcznego porzucenia przez pracownika.

**Retencja wpisów idempotencji nie jest gwarancją kodu.** Serwer usuwa zapamiętane odpowiedzi starsze niż 7 dni
(domyślnie) tylko komendą `flask cleanup-mobile-operations` (`modules/production/services/mobile_api_service.py:735-793`
(`cleanup_old_operations`), `app.py:394-402`); repo nie mówi, czy jest w crontabie produkcji. Wpis żyje **co
najmniej** do sprzątania; akcja dosłana po ponad 7 dniach może wykonać się drugi raz. **Appka nie dosyła wpisów
starszych niż 7 dni bez potwierdzenia człowieka.**

---

## 11. Dwa progi wersji appki i tryb stanowiska

Dwa różne mechanizmy — nie zlewać ich w jeden:

| | Próg konfiguracji API (`X-App-Version`) | Próg stołu (`priorytety_min_app_version_code`) |
|---|---|---|
| co porównuje | nagłówek `X-App-Version` (semver, np. `1.8.0`) z `API_MOBILE.min_supported_app_version` | `last_app_version_code` urządzenia (liczba z ostatniego heartbeatu) z kluczem `prod_config` (liczba; 0 = brak progu) |
| gdzie | każda końcówka z tokenem, przed handlerem (`modules/production/services/mobile_api_service.py:444-451`) | bramka ZAKOŃCZ/licznika (`modules/production/priorytety/services/stol.py:145-155` (`stara_appka`)) |
| skutek | 426 `app_version_too_old` — także dla `GET /app/apk`, więc tablet poniżej tego progu nie pobierze aktualizacji przez API | tablet „stary” omija bramkę stołu (zachowanie `stary`), ale jego ZAKOŃCZ zdejmuje kafel (test `tests/test_priorytety_stol.py:583` (`test_bramka_stara_appka_bez_bramki_ale_zdejmuje_kafel`)) |
| kto ustawia | konfiguracja serwera (`config/core.json`) | biuro w Konfiguracji przy „Włącz stoły” (K7) |

Nagłówek `X-App-Version` zapisuje tylko napis wersji urządzenia, nie `version_code`
(`modules/production/models.py:1196-1202` (`touch`)). **`last_app_version_code` ustawia wyłącznie heartbeat**
(`modules/production/routers/mobile_api.py:1715`).

**Próg stołu w szczegółach** (`modules/production/priorytety/services/stol.py:151-155`):
- próg 0 → nikt nie jest „stary”: w trybie `stol` bramka obowiązuje każdego, także starą appkę (test
  `tests/test_priorytety_stol.py:614` (`test_bramka_prog_zero_to_brak_bramki_wersji`)). Panel nie pozwala jednak
  takiego stanu wprowadzić: zapis ustawień odrzuca włączenie `stol` (i obniżenie progu do 0 przy włączonym stole)
  błędem 400 `prog_wersji_wymagany` (`modules/production/priorytety/services/ustawienia.py:261` (`sprawdz_prog_wersji`),
  `modules/production/priorytety/routers/panel_api.py:539-547`) — w praktyce przy stołach próg jest > 0;
- próg > 0 i `last_app_version_code` nieznany (brak heartbeatu) albo mniejszy → „stary” (test
  `tests/test_priorytety_stol.py:598` (`test_bramka_tablet_bez_heartbeatu_to_stara_appka`)).

**Heartbeat zaraz po starcie appki i po każdej aktualizacji APK** (nie dopiero po 15 min, jak w docstringu
`modules/production/routers/mobile_api.py:1697`):

```
POST /api/mobile/devices/heartbeat
{"app_version_code": 180, "app_version_name": "1.8.0", "battery_pct": 80, "battery_charging": true,
 "temperature_c": 31.5, "ip_address": "<adres tabletu w sieci hali>"}
```

`app_version_code` (int) i `app_version_name` (string) wymagane, reszta opcjonalna; 204 bez ciała, zły ładunek →
422 `{"error": "validation", "detail": "app_version_code required"}` (sprawdzone na żywo)
(`modules/production/routers/mobile_api.py:1693-1745` (`device_heartbeat`),
`modules/production/services/mobile_api_service.py:380-404` (`validate_heartbeat_payload`)). Nowej appce brak
heartbeatu nie szkodzi (bez bramki dla „starej” zachowa się tylko łagodniej), ale panel pokaże ją jako starą do
pierwszego heartbeatu.

**Tryb stanowiska** (`priorytety_tryb_<S>`: `stary` | `stol`) jest ustawieniem serwera, zmienianym w Konfiguracji;
w `stary` ZAKOŃCZ i licznik nie mają bramki (`modules/production/priorytety/services/stol.py:284-285`). Lakiernia jest
zawsze bez stołu niezależnie od wpisu (`modules/production/priorytety/services/ustawienia.py:31-34`
(`STANOWISKA_BEZ_STOLU`)). **[K3-poprawka-2]** `desk` oddaje `tryb` i w `stary` niczego nie dopełnia
(`modules/production/routers/mobile_api.py:503`, `modules/production/routers/mobile_api.py:605-609`), a appka wybiera ekran po `tryb` — stół tylko przy `"stol"` (sekcje 4, 12). Bramka statusu
(409 `pozycja_poza_stanowiskiem`) obowiązuje tylko w `stol` i tylko nową appkę — jak bramka stołu (sekcja 6).

---

## 12. Kompatybilność i kolejność wdrożenia

**Jedno wdrożenie** (decyzje Konrada 5.10): CRM (logistyka etapy 1–4 + priorytety) i nowa appka — **czwartek 8.10,
w przerwie o 10:30**. **Nowe APK trafia na tablety wcześniej** (w środę albo rano), czyli **nowa appka przez kilka
godzin pracuje na starym backendzie produkcji** i musi tam działać jak 1.7.3. Po deployu wszystkie stanowiska są
w `stary`; po zakończeniu zmiany biuro robi „Przygotuj stoły”, a przed następną zmianą jednym zapisem ustawia
`priorytety_min_app_version_code` = `version_code` nowej appki i przełącza **naraz** wszystkie stanowiska poza
Lakiernią na `stol` („Włącz stoły”). Stara appka to tylko zabezpieczenie dla tabletu, którego nie zaktualizowano.
Ustawienia priorytetów serwer czyta wprost z `prod_config`, bez pamięci podręcznej procesu — zmiana trybu i progu
działa od razu na wszystkich workerach (`modules/production/priorytety/services/ustawienia.py:9-12`,
`modules/production/priorytety/services/ustawienia.py:43-56` (`_surowa`)).

### Nowa appka na starym backendzie (przed deployem 8.10, cofnięte wdrożenie, stary podgląd)

Wszystko, co nowe, ma bezpieczne zachowanie zastępcze — appka działa jak 1.7.3, bez komunikatów błędu:

| Co appka widzi | Co znaczy | Zachowanie |
|---|---|---|
| `GET desk` → 404 **bez ciała JSON** (strona HTML Flaska) | backend bez stołu: nieznana trasa pod `/api/mobile` oddaje domyślne 404 HTML — w `app.py` nie ma obsługi 404, są tylko 401 i błędy bazy (`app.py:1138-1150`, `app.py:1803-1880`; sprawdzone na żywo: `GET /stations/gluing/deskx` → 404 `text/html`) | dzisiejsza lista `/stations/<S>/orders`; ponowna próba `desk` najwyżej co 30 s (sekcja 9) |
| `GET desk` → 404 JSON `{"error": "unknown_station"}` | błąd konfiguracji tabletu, nie stary backend | komunikat o rejestracji |
| `GET /realtime-token` → 404 HTML | brak realtime dla tabletów | samo odpytywanie, jak przy 503 (sekcja 8) |
| brak pól `priorytet`, `grupa_wykonczenia`, `zrodlo` | stary kształt | bez plakietek; Lakiernia bez separatorów serwera (appka może użyć swojego dzisiejszego sortowania) |
| brak obiektu `transport` w pozycji | backend sprzed logistyki etapu 1 — `transport` jest w nowym backendzie **zawsze** obecny (`modules/production/services/mobile_api_service.py:1211-1214`) | zachowanie appki sprzed logistyki (jak dziś w 1.7.3) |
| `PUT /orders/<numer>/packages` → 404 | backend bez deklaracji paczek (`modules/production/routers/mobile_api.py:1584-1585`) | pominąć deklarację (jak dziś) |
| rejestracja telefonu Weryfikacji/Dostawy → 400 `invalid_station_code` | stary backend nie zna tych stanowisk (`modules/production/routers/mobile_api.py:231-235`) | przed wdrożeniem oczekiwane; czytelny komunikat |
| 409 `delivery_method_not_set` na Pakowaniu | backend sprzed logistyki 4.6 | komunikat z `message`, wpis zostaje w kolejce (sekcje 6, 10) |

### Przełączanie bez restartu appki

**[K3-poprawka-2]** Appka wybiera ekran stanowiska przy **każdej** odpowiedzi `desk`, nie raz przy starcie:
404 HTML albo `tryb: "stary"` → lista; `tryb: "stol"` → stół; 200 bez pola `tryb` — wg buildu (sekcja 4). Serwer
oddaje tryb przy każdym `desk`, a przełączenie zmienia ETag, więc tablet nie dostanie 304 ze starym trybem
(`modules/production/routers/mobile_api.py:605`, `modules/production/routers/mobile_api.py:410-414`). Ekranu
**nie** przełączają: 304 (zostaje bieżący), 5xx, przekroczony czas, brak sieci, 401, 426. Dzięki temu deploy pod działającą appką, „Włącz stoły” i wycofanie stanowiska na `stary`
przełączają tablet przy najbliższym `desk` — deploy i „Włącz stoły” w ciągu najwyżej 30 s (na liście appka pyta
`desk` co 30 s), wycofanie na `stary` do 30 s przy niepełnym stole i do 5 min przy pełnym (siatka z sekcji 9;
zmiana trybu nie wysyła sygnału — doprecyzowane w K5) — **bez restartu, bez ponownego logowania i bez utraty kolejki offline**
(wpisy kolejki nie zależą od ekranu — ZAKOŃCZ, licznik i paczki mają ten sam kształt na liście i na stole; Odłóż
istnieje tylko online). Po przejściu na stół appka od razu woła `desk` i przechodzi na siatkę z sekcji 9.

**Stara appka (1.7.3) na nowym backendzie:** lista `/stations/<S>/orders` i delta działają; ETag listy zmienia się
raz (KSZTALT 6), pola `priorytet` i `grupa_wykonczenia` ignoruje (sekcja 7). Do progu wersji nie ma bramki; jej ZAKOŃCZ
zdejmuje kafel ze stołu i wysyła sygnały, więc nowe tablety tego samego stanowiska widzą zmianę
(`modules/production/routers/mobile_api.py:901-912`). Listę Lakierni stara appka sortuje sama — porządek po wykończeniu
widać dopiero w nowej appce.

**Mieszana flota na jednym stanowisku** (stara i nowa appka): stara pracuje z listy, nowa ze stołu; ZAKOŃCZ starej
zdejmuje kafel, nowa dowiaduje się sygnałem albo z siatki. Przy progu > wersji starej appki stara nie ma bramki.

**Wycofanie stołów** — `priorytety_tryb_<S>` → `stary` w Konfiguracji, bez wdrożenia: ZAKOŃCZ bez bramki
(`modules/production/priorytety/services/stol.py:284-285`), `desk` przestaje dopełniać, a wiersze stołu zostają tylko
do odczytu (`modules/production/routers/mobile_api.py:605-609`); **[K3-poprawka-2]** nowa appka wraca na listę (wyżej).
**Wycofanie kodu** idzie razem z logistyką: nowa appka dostanie 404 HTML z `desk` i wróci do listy.

**Co zostaje dla starej appki**, dopóki jakikolwiek tablet jej używa: lista `/stations/<S>/orders`, `/orders/since`
i `refresh_interval_seconds` w `/summary` (`modules/production/services/mobile_api_service.py:1727`). Nowa appka
korzysta z listy dla Lakierni (sekcja 13), na stanowiskach w trybie `stary` i na starym backendzie.

**Tablet Krawędzi** na stałe w trybie mieszanym: ekran Krawędzi to stół (po przełączeniu Krawędzi na `stol`), ekran
Lakierni to lista; token ma oba kanały (sekcja 8). Dostęp do obu stanowisk daje grupa
(`modules/production/services/mobile_api_service.py:118-148` (`device_can_access_station`)).

---

## 13. Ekrany do zmiany

Kodu appki w tym repo nie ma — sekcja opisuje zmiany od strony kontraktu, nie klasy Kotlina. Nazwy stanowisk
(„Sklejanie”, „Formatowanie”…) zostają w buildzie appki: API ich nie wystawia.

**Który ekran.** Lakiernia — zawsze lista (niżej). Pozostałe stanowiska: **[K3-poprawka-2]** ekran stołu tylko przy
`tryb == "stol"` w odpowiedzi `desk`; przy `tryb == "stary"` albo 404 HTML — dzisiejsza lista (sekcja 12).

**Ekran stanowiska ze stołem** (Wycinanie, Składanie, Sklejanie, Formatowanie, Krawędzie, Pakowanie) — z `GET desk`
(sekcja 4):

1. **Nagłówek:** nazwa stanowiska i „w kolejce: N” z `kolejka_dalej` (`modules/production/routers/mobile_api.py:510`).
   Bez listy kolejki.
2. **„Teraz”** (nazwa robocza sekcji stołu — ostateczny tekst akceptuje Konrad przy odbiorze): kafle z `stol`
   w kolejności odpowiedzi; lista przewijana, bo stół bywa dłuższy niż `miejsca`; plakietki źródła `biuro` → „wysłane
   przez biuro”, `start` → „rozpoczęte przed startem” (sekcja 4).
3. **„Odłożone”**: kafle z `odlozone` z powodem (etykieta wg sekcji 5), godziną z `odlozono` i pracownikiem („Imię
   I.”); ZAKOŃCZ i licznik dostępne, Odłóż nie (kafel już odłożony).
4. **„Niekompletne”** (tylko gdy `jednostka = "zamowienie"`: Formatowanie, Pakowanie): zamówienia z `niekompletne`
   z postępem „{na_stanowisku}/{pozycji} na stanowisku, {liczba brakujących} na {nazwa stanowiska z `brakuje[]`}”
   i listą brakujących `short_id`; ZAKOŃCZ i licznik **pozycji**, które już czekają na stanowisku, działają
   (sekcja 6); bez Odłóż.
5. **Kafel:** dotychczasowa karta pozycji albo zamówienia + gwiazdki z `priorytet.gwiazdki` + plakietka szczebla +
   „poz. i/n” z `pozycja_w_zamowieniu` (sekcja 7); przyciski **Odłóż** (lewy) i **ZAKOŃCZ** (prawy); licznik sztuk jak
   dotąd. Na kaflu zamówienia Formatowania pozycja z `cut_to_size == false` w innym statusie niż
   `czeka_na_formatowanie` dostaje plakietkę „idzie prosto do pakowania” i nie ma przycisków (sekcja 4). **ZAKOŃCZ
   i licznik tylko przy pozycjach w statusie tego stanowiska**; pozostałe pozycje kafla — bez przycisków (sekcja 6).
6. **Modal Odłóż:** pięć powodów (sekcja 5), pole notatki — wymagane i niepuste przy „Inne” (zatwierdzenie nieaktywne
   bez notatki), najwyżej 255 znaków; `zakres` = `jednostka` z `desk`; tylko online; 409 → `message` jako komunikat,
   kafel zostaje na stole (`modules/production/routers/mobile_api.py:625-689`).
7. **Po własnym ZAKOŃCZ/Odłóż:** `GET desk` (sekcja 9). Po 409 `nie_na_stole` albo **[K3-poprawka-2]**
   `pozycja_poza_stanowiskiem`: komunikat z `message` i `GET desk`.
8. **Pakowanie** (zmiany wspólne z logistyką 4.6, sekcja 6): appka nie blokuje ZAKOŃCZ przy pustym sposobie dostawy
   (`transport.mode == null`), nie spycha takich zamówień na koniec, pokazuje informacyjną plakietkę **„Sposób dostawy
   do ustalenia – pakuj normalnie”** (tekst zatwierdzony przez Konrada 5.10); okno paczek działa niezależnie od
   sposobu dostawy; obsługa 409 `delivery_method_not_set` zostaje. Pas „NIE USTAWIONO” na etykiecie paczki generuje
   serwer — appka niczego nie rysuje.

**Lakiernia — bez stołu** (Konrad 5.10): ekran wybiera się **po kodzie stanowiska** (`painting`), nie po trybie.
Ekran = pełna lista `GET /stations/painting/orders` (pracownik wybiera sam), ZAKOŃCZ i licznik jak dziś, bez Odłóż,
bez „Teraz” i bez „w kolejce”; appka **nie woła** `desk` ani `postpone` dla `painting` (oba → 409
`stanowisko_bez_stolu`, `modules/production/routers/mobile_api.py:600-601`,
`modules/production/routers/mobile_api.py:649-650`). Kolejność listy liczy serwer — grupy wykończenia w jednym ciągu,
grupy po najpilniejszej pozycji, w grupie po pilności, doróbki pierwsze, pozycje w innych statusach na końcu
(`modules/production/priorytety/services/lista.py:84-112` (`porzadek_listy`)); delta `/orders/since` oddaje `all_ids`
i `changed` w tej samej kolejności (`modules/production/services/mobile_api_service.py:1834-1856`). **Domyślny widok =
kolejność odpowiedzi**, bez wynoszenia pilnych nad grupy; separator grupy rysuje się przy zmianie **dowolnego**
z czterech pól `grupa_wykonczenia` między sąsiednimi pozycjami w statusie `czeka_na_lakiernie`:

```json
{"grupa_wykonczenia": {"rodzaj": "lakierowane", "typ_koloru": "bezbarwnie", "kolor": null, "polysk": "półmatowy"}}
```

Wartości znormalizowane (małe litery, bez spacji na brzegach, pusty = `null`); `polysk` tylko dla lakierowanych,
dla pozostałych `null`; dla stanowisk innych niż Lakiernia całe pole jest `null`
(`modules/production/priorytety/services/lista.py:27-49` (`klucz_grupy_wykonczenia`); test
`tests/test_priorytety_lista_lakierni.py:277` (`test_serialize_order_grupa_wykonczenia`); kształt sprawdzony na
żywo). Etykieta separatora — pola w tej kolejności, z pominięciem `null` (tak robi panel,
`modules/production/priorytety/services/lista.py:52-56`). Ręczne sortowanie przez pracownika może zostać jako opcja,
ale domyślnie zawsze kolejność serwera. Odświeżanie listy jak dziś (sekcja 9) plus sygnał `station:painting`.

**Tablet Krawędzi:** ekran Krawędzi = stół, ekran Lakierni = lista; jeden token z dwoma kanałami (sekcja 8); każdy
sygnał odświeża oba widoki. Tablet zarejestrowany na Lakierni ma ten sam dostęp
(`modules/production/services/mobile_api_service.py:118-120`).

**Heartbeat** zaraz po starcie i po aktualizacji (sekcja 11). **Praca na starym backendzie i przejście na stół bez
restartu** — sekcja 12.

---

## 14. Kryteria odbioru z tabletem

Na podglądzie wskazanym przez Konrada (nigdy produkcja), nowa appka na tablecie po USB. Każdy punkt: wynik i dowód
(zrzut ekranu albo wpis z logu serwera/appki).

1. Dwa tablety Sklejania (tryb `stol`) pokazują ten sam stół, w tej samej kolejności co odpowiedź `desk` (§4).
2. ZAKOŃCZ na tablecie A → tablet B pokazuje zmianę w ≤ 5 s przy włączonym realtime (§8).
3. To samo przy `REALTIME.enabled = false` (`realtime-token` → 503): B pokazuje zmianę w ≤ 5 min przy pełnym stole
   i ≤ 30 s, gdy stół ma mniej kafli niż `miejsca`; brak komunikatu błędu dla pracownika (§9).
4. ZAKOŃCZ ostatniej brakującej pozycji na Sklejaniu → zamówienie przechodzi z „Niekompletne” na stół Formatowania
   po sygnale (≤ 5 s z realtime) (§4, §8).
5. Odłóż z każdym z pięciu powodów; przy „Inne” bez notatki zatwierdzenie nieaktywne; notatka > 255 znaków
   niemożliwa (§5, §13).
6. Przy limicie odłożeń (na podglądzie limit 1): komunikat = `message` z 409, kafel zostaje na stole (§5).
7. Kafel odłożony widoczny w „Odłożone” z powodem, godziną i „Imię I.”; ZAKOŃCZ na nim → 200 i znika (§5).
8. Formatowanie: zamówienie niekompletne w „Niekompletne” z postępem i listą brakujących; ZAKOŃCZ jego pozycji
   przechodzi (200); po dojściu ostatniej pozycji zamówienie wchodzi na stół (§6).
9. Formatowanie: kafel zamówienia z pozycją bez docięcia, która stoi jeszcze na Sklejaniu — plakietka „idzie prosto
   do pakowania”, zamówienie da się zakończyć (§4).
10. ZAKOŃCZ w trybie samolotowym → po powrocie sieci zsynchronizowane z **tym samym** `X-Operation-Id` (log serwera),
    potem `GET desk` (§10).
11. 409 `nie_na_stole` z kolejki (kafel zamknął w tym czasie drugi tablet) → wpis porzucony z komunikatem „Zamknięte
    na innym tablecie albo zdjęte przez biuro”, bez pętli ponowień (log serwera: najwyżej kilka żądań, nie seria) (§10).
12. Odłóż bez sieci niedostępny (przycisk nieaktywny) (§5).
13. Zerwanie SSE (restart brokera albo wygaśnięcie tokena przy skróconym TTL) → ponowne połączenie wg drabinki
    z nowym tokenem; w tym czasie zmiany docierają najpóźniej z siatką (§8, §9).
14. Tablet Krawędzi: ekran Krawędzi = stół, ekran Lakierni = lista; `realtime-token` z dwoma kanałami; sygnał
    po ZAKOŃCZ na Lakierni odświeża listę (§8, §13).
15. Heartbeat zaraz po starcie appki → panel urządzeń pokazuje nowy `version_code` przed upływem 1 min (§11).
16. Stara appka (1.7.3) na tym samym stanowisku: w trybie `stary` i w `stol` z progiem > jej `version_code` działa
    jak dziś (lista, ZAKOŃCZ bez 409) (§11, §12).
17. **Nowa appka na starym backendzie** (podgląd z kodem sprzed priorytetów): `GET desk` → 404 HTML → dzisiejsza
    lista; `realtime-token` → 404 → samo odpytywanie; brak pól `priorytet`/`grupa_wykonczenia`/`zrodlo` → bez plakietek;
    ZAKOŃCZ, licznik, paczki i kolejka offline działają jak w 1.7.3; bez awarii i bez komunikatów błędu (§12).
18. **Przełączenie backendu bez restartu appki:** appka działa na liście (stary backend), backend zostaje
    zaktualizowany pod spodem → **[K3-poprawka-2]** appka dostaje `desk` z `tryb: "stary"` i **zostaje na liście**
    (log serwera: `desk` najwyżej co 30 s, zero nowych wierszy stołu); bez ponownego logowania i bez utraty kolejki
    offline (wpis z czasu starego backendu synchronizuje się z tym samym `X-Operation-Id`) (§12).
18a. **[K3-poprawka-2] Przełączenie `stary → stol` w trakcie pracy** („Włącz stoły” w Konfiguracji podglądu): w ciągu
    ≤ 30 s appka przechodzi na ekran stołu, bez restartu, ponownego logowania i utraty kolejki offline (§12).
18b. **[K3-poprawka-2] Wycofanie `stol → stary`** (stanowisko przełączone z powrotem w Konfiguracji): w ciągu ≤ 30 s
    appka wraca na listę, tak samo bez restartu i bez utraty kolejki (§12).
19. Doróbka na stanowisku pojawia się na stole jako pierwsza w ramach `miejsca` (plakietka „Doróbka”) (§4, §7).
20. Po sygnale `GET desk` idzie do serwera mimo pamięci podręcznej OkHttp (log serwera: żądanie z `If-None-Match`,
    odpowiedź 200 albo 304) (§4).
21. Lakiernia: lista w kolejności odpowiedzi `/stations/painting/orders`, separatory z `grupa_wykonczenia`, ZAKOŃCZ
    bez bramki nawet przy `priorytety_tryb_painting = stol` wpisanym ręcznie w bazie podglądu, brak przycisku Odłóż
    i **zero** wywołań `/stations/painting/desk` w logu serwera (§13).
22. Kafle „wysłane przez biuro” (panel: „Wyślij na stanowisko”) i „rozpoczęte przed startem” (panel: „Przygotuj
    stoły”) mają plakietki; stół dłuższy niż `miejsca` przewija się (§4, §13).
23. Pakowanie: pozycję zamówienia bez sposobu dostawy da się zakończyć (backend z 4.6; na backendzie sprzed 4.6 —
    komunikat 409 `delivery_method_not_set`, wpis zostaje w kolejce), plakietka „Sposób dostawy do ustalenia – pakuj normalnie” bez blokady; **okno paczek
    działa dla zamówienia z i bez sposobu dostawy** (§6, §13).
23a. Kafel-zamówienie (Formatowanie, Pakowanie, także wysłany przez biuro): ZAKOŃCZ i licznik tylko przy pozycjach
    w statusie stanowiska; pozycje w innych statusach i anulowane bez przycisków (§6, §13).
23b. **[K3-poprawka-2]** 409 `pozycja_poza_stanowiskiem` (np. wpis kolejki offline z ZAKOŃCZ pozycji, którą w tym
    czasie zakończył drugi tablet albo cofnęło biuro) → wpis **porzucony** z komunikatem z `message`, potem `GET desk`;
    zero ponowień tego wpisu w logu serwera (§6, §10).
24. Wpisu kolejki offline starszego niż 7 dni appka nie dosyła bez potwierdzenia człowieka (test jednostkowy appki
    wystarczy) (§10).
25. Telefony Weryfikacji i Dostawy na starym backendzie: rejestracja sekcjami Biuro/Dostawa → 400
    `invalid_station_code` — **przed wdrożeniem oczekiwane**, appka pokazuje czytelny komunikat (§12).

---

## 15. Czego ten dokument nie rozstrzyga

- Układ graficzny, kolory i animacje kafli, ostateczna nazwa sekcji „Teraz” (decyzja przy odbiorze; dla tabletów
  hali obowiązuje: tylko ciemny motyw, zero animacji, cele dotykowe ≥ 48 px).
- Budowa kolejki offline wewnątrz appki (Room, migracje — bez `fallbackToDestructiveMigration`), poza regułami
  z sekcji 10.
- Nazwy stanowisk w buildzie appki.
- Kolejność czynności w dniu wdrożenia i przełączania stołów — runbook K7.
- Raport odłożeń dla biura i monitory hali — nie są częścią kontraktu appki.
- Format ramki brokera SSE poza regułą „każda ramka danych inna niż ping i powitanie = sygnał”.
- Czy `flask cleanup-mobile-operations` jest w crontabie produkcji (sekcja 10 zakłada „co najmniej 7 dni”).
