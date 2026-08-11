# Odpowiedź na kontrakt sesji — backend CRM

**Data:** 2026-08-11
**Dotyczy:** dokumentu „Profile pracowników — dwie zmiany po stronie apki"
**Gałąź:** worktree-worker-profiles

Wszystkie liczby i ciała odpowiedzi pochodzą z realnych żądań — na testach
oraz na kopii bazy produkcyjnej, nie z dokumentacji.

---

Odpowiadamy po kolei, po Waszych punktach. Wszystkie liczby i ciała odpowiedzi niżej pochodzą z realnych żądań — na testach oraz na kopii bazy produkcyjnej, nie z dokumentacji.

## 1. Jeden tablet = jeden pracownik

Przyjęte, bez zmian formatu przewodowego. `worker_ids` zostaje tablicą, `X-Worker-Ids` zostaje CSV.

Wprost, o co pytaliście: **kod nadal obsługuje N > 1** i nie zamierzamy tego wycinać. Gdyby przyszło więcej niż jedno id, stanie się to: powstanie N wierszy sesji z jednym wspólnym `session_group`, a atrybucja akcji dostanie `share = 1/N` (`attach_worker_attribution()`). Nic nie wybuchnie, ale raport wydajności rozdzieli sztuki na ułamki. Skoro decyzja jest „zawsze jeden", ta ścieżka po prostu się nie uruchomi — zostaje jako martwy kod, nie jako pułapka.

Warto, żebyście wiedzieli o skutku ubocznym decyzji: **jeden pracownik = maksymalnie jedna otwarta sesja globalnie**, nie tylko jedna na tablet. To jest mechanizm wariantu A.

## 2. Wariant A — jak dokładnie działa teraz

`POST /sessions/start` domyka jako `replaced` sesje z **sumy dwóch zakresów**:
1. sesje **tego urządzenia** — zmiana obsady na tablecie kończy poprzednią, kimkolwiek była;
2. sesje **wskazanych pracowników na dowolnym urządzeniu** — to jest przejęcie profilu.

Przebieg z kopii produkcyjnej (dwa różne tablety, ten sam pracownik):
```
strefa     : dev=prod-test-tablet-ping 17:18:16 -> 21:18:16 (replaced) 240 min
przejecie  : dev=test-cp13-check       21:18:16 -> OTWARTA            0 min
stary tablet /active : {'session_group': None, 'worker_ids': [], 'started_at': None}
nowy  tablet /active : {'session_group': 'WERYF-przejecie', 'worker_ids': [1], 'started_at': '2026-08-11T21:18:16'}
```
Kod: **200**, `superseded: false`. Nigdy 409.

Jedna rzecz do wiedzy: start z panelu CRM (brygadzista) też domyka sesję tego pracownika na tablecie. Jeden człowiek nie może wisieć w dwóch miejscach niezależnie od tego, skąd przyszedł start.

## 3. `GET /sessions/active` — dokładne odpowiedzi

Zakres: sesja otwarta **dla urządzenia z JWT**. Nie per pracownik, nie globalnie.

**Z sesją** — `200`:
```json
{
  "session_group": "6f1c...",
  "worker_ids": [3],
  "started_at": "2026-08-11T21:18:16",
  "station_code": "gluing",
  "idle_timeout_minutes": 120,
  "sessions": [
    {"id": 4412, "worker_id": 3, "worker_name": "Adam Kowalski", "initials": "AK",
     "color_hex": "#3E7C59", "station_code": "gluing",
     "started_at": "2026-08-11T21:18:16", "last_activity_at": "2026-08-11T21:41:02"}
  ]
}
```

**Bez sesji** — też `200`, komplet kluczy, nie brak pól:
```json
{
  "session_group": null,
  "worker_ids": [],
  "started_at": null,
  "station_code": "gluing",
  "idle_timeout_minutes": 120,
  "sessions": []
}
```

Ustalamy ten wariant — nie `{}` i nie 404.

Nagłówki, zmierzone: `Cache-Control: no-store`, `Vary: Authorization`, **`ETag: None`** (endpoint świadomie nie używa `cached_json`, żadnego `max-age`).

Uwaga praktyczna: `worker_ids` i `started_at` opisują **najnowszą** grupę urządzenia. Gdyby na urządzeniu wisiały dwie otwarte grupy (dane zastane sprzed wdrożenia), oddajemy tę, przy której ktoś faktycznie stoi — nie najstarszą. Wiemy, że dziś czytacie tylko `sessionGroup` (`reconcileSessionWithServer`); mówimy o tym na wypadek, gdybyście chcieli odtwarzać obsadę po restarcie.

## 4. Polling co 60 s — konkretna liczba

**Zostawcie 60 s.** Zmierzone na kopii bazy produkcyjnej (6 tabletów × 20 przebiegów):

| | |
|---|---|
| zapytań SQL na żądanie | **4** |
| średni czas żądania | **2,97 ms** |
| 6 tabletów raz na minutę | **17,8 ms** |
| obciążenie | **0,03 % czasu jednego procesu** |

Nie prosimy o 5 minut. Przy tym koszcie szybsze wykrycie przejęcia profilu jest warte więcej niż te 18 ms.

## 5. Punkt (a) — akcje na samym `X-Worker-Ids`, bez otwartej sesji

Potwierdzone. Nigdzie nie ma warunku „musi być otwarta sesja". `resolve_worker_ids()` sprawdza wyłącznie istnienie i aktywność pracownika, `touch_sessions()` przy braku sesji zwraca pustą mapę zamiast błędu.

Dowód (bramka **włączona**, zero otwartych sesji, akcja z kolejki starego tabletu): `HTTP 200`, event powstaje, atrybucja `worker_id=1`, `share=1.000000`, `session_id=None`. Sesja domknięta jako `replaced` **nie ożywa** — `touch_sessions` nie ma czego reanimować, bo wariant A ją zamknął.

Test pilnujący: `test_akcje_z_kolejki_starego_tabletu_przechodza_po_przejeciu`.

## 6. Punkt (b) — kolizja to 200, nie 409

Potwierdzone. `409` występuje w `/sessions/start` **wyłącznie** dla `worker_inactive` (pracownik dezaktywowany w katalogu) — i to jest zamierzone, bo u Was ląduje jako `Blocked`, czyli faktycznie wymaga interwencji biura. Za kolizję nigdy.

Do tego `409 worker_inactive` jest u nas w `retryable_statuses`, więc **nie zostaje zapamiętane** przez idempotencję: po przywróceniu pracownika ponowienie z tym samym `X-Operation-Id` przechodzi i praca się księguje.

## 7. Punkt (c) — `end` już zamkniętej sesji to no-op z 200

Potwierdzone, z jednym dopowiedzeniem na plus.

```json
// grupa domknieta przez serwer jako 'replaced'
{"session_group": "6f1c...", "closed": 0, "no_op": true}      // HTTP 200
// grupa w ogole nieznana
{"session_group": "nigdy-nie-istniala", "closed": 0, "no_op": true}   // HTTP 200
```
`end_reason` **nie jest nadpisywany** — `close()` jest idempotentne.

**Dopowiedzenie: czas końca korygujemy w dół.** `replaced` to nasze zgadnięcie („koniec = start następczyni"). Gdy dosyłacie prawdziwy `ended_at`, skracamy do niego, o ile mieści się w `[started_at, obecny ended_at)`. Powód zostaje `replaced`. Bez tego raport dopisywał człowiekowi cały czas między realnym wyjściem a przejęciem profilu — przy tablecie offline od poprzedniej doby liczyło się to do nocnego cutoffu.

Zmierzone na kopii produkcyjnej: sesja pokazywana jako 240 min, po dosłanym `end` → **60 min**, `end_reason` dalej `replaced`, odpowiedź `200 {closed: 0, no_op: true}`.

Wydłużania nie robimy nigdy — oznaczałoby cofnięcie przejęcia profilu.

## 8. Uwaga o kolejności (spóźniony start) — i sprostowanie

**Tu mieliście rację, a my mieliśmy błąd — i nie ten, o którym myśleliście.**

Wasza uwaga była trafna, ale zabezpieczenie, które na nią zrobiliśmy, **nie działało w formacie, który faktycznie wysyłacie**. `started_at` bez offsetu czytaliśmy jako **UTC**. Skutek: każdy zaległy start młodszy niż offset strefy (czyli 2 h latem) był przycinany do „teraz" i **zawsze wygrywał** — profil wracał na odłożony tablet, a człowiek stojący przy drugim wracał na bramkę. Dokładnie to, przed czym ostrzegaliście. Zabezpieczenie działało tylko dla opóźnień powyżej 2 godzin.

Naprawione. **`started_at` i `ended_at` bez offsetu to CZAS LOKALNY** (Europe/Warsaw) — czyli dokładnie to, co produkuje `toLocalIso()`, i ta sama konwencja co `measured_at` trakowni. **Nic po Waszej stronie nie musi się zmienić.** Offset, gdybyście kiedyś przeszli na `ISO_OFFSET_DATE_TIME`, też przyjmiemy i przeliczymy — obie formy są poprawne. Przyszłość powyżej minuty przycinamy do „teraz", nie odrzucamy: 4xx zablokowałoby Wam kolejkę przez dryf zegara.

Sprawdzone wprost na bajtach klienta: wysłane `2026-08-11T17:18:16` → zapisane `17:18:16`, różnica **0 min**. Przed poprawką: **+120 min**.

Jak działa sam mechanizm kolejności: start jest **spóźniony**, gdy istnieje sesja nowsza niż jego `started_at` — patrzymy na otwarte sesje tego urządzenia i wskazanych pracowników **oraz na sesje zamknięte tych pracowników** (bo domknięcie przez brygadzistę albo cron też dowodzi, że człowiek poszedł dalej). Wtedy:
- obsady **nie ruszamy**, nie domykamy niczego;
- żądanie księgujemy jako sesję **historyczną**, od razu domkniętą w momencie startu następczyni — czas pracy sprzed przejęcia nie znika z raportu;
- odpowiadamy **200** ze stanem **bieżącym tego urządzenia** i `superseded: true`:

```json
{"session_group": null, "worker_ids": [], "started_at": null,
 "sessions": [], "expires_at": null, "superseded": false}
```
(przykład dla tabletu bez otwartej sesji; `superseded: true` gdy start był spóźniony)

Start z **poprzedniej doby**, którego nikt nie zastąpił, domykamy na nocnym cutoffie jego doby z powodem `night_cutoff` — inaczej pracownik wracałby dziś na panel „kto na hali" z kilkunastoma godzinami na liczniku.

Uczciwie o granicy: **rozjazd zegara tabletu do tyłu wygląda dla nas identycznie jak wpis z kolejki.** Jeśli tablet, na który przenosicie profil, ma zegar spóźniony o 2 minuty względem poprzedniego, przejęcie nie nastąpi i tablet wróci na bramkę. Nie dokładamy tolerancji, bo każda wartość byłaby zgadywana — prosimy o pewność, że czas sieciowy jest na tabletach włączony.

## 9. Pytanie osobne: `If-None-Match` i `catalog_version` — **było NIE, teraz TAK**

Sprostowanie: poprzednia odpowiedź („naprawione i potwierdzone") dotyczyła echa nagłówka `ETag`, którego **nie wysyłacie**. Wysyłacie `configStore.catalogVersion()`, zapisywane z `body.catalogVersion` — czyli z pola JSON. To były dwa różne stringi:

```
ETag serwera    : W/"workers:gluing:2026-08-11T20:36:04.393165:0"
catalog_version : 2026-08-11T20:36:04.393165          <- to wysyłaliście
```
Porównanie string-equal nie trafiało **nigdy**. Efekt: pełny katalog przy każdym starcie i każdym odświeżeniu, a gałąź `CatalogRefresh.NOT_MODIFIED` była u Was martwym kodem.

Naprawione tak, że **`catalog_version` to dokładnie ten sam string co nagłówek `ETag`**:
```
ETag naglowkowy : W/"workers:packaging:2026-08-11T18:55:22:faabdc81b3b5"
catalog_version : W/"workers:packaging:2026-08-11T18:55:22:faabdc81b3b5"
tozsame?        : True
powtorny GET z catalog_version -> HTTP 304
```
Po Waszej stronie **nic się nie zmienia** — nadal odsyłacie `catalog_version` jako `If-None-Match`. Zmienia się tylko to, że wartość jest teraz nieprzezroczystym tokenem, nie znacznikiem czasu. Jeśli macie test kontraktowy asertujący format (`WorkersResponseDtoTest` sprawdza `"2026-08-11T18:55:22"`), trzeba go poluzować do „dowolny niepusty string".

**Co dokładnie wchodzi w skład ETagu — trzy rzeczy:**
1. `station_code` z JWT (bo `recent_on_station` jest per stanowisko);
2. `MAX(prod_workers.updated_at)` — zmiany katalogu;
3. **odcisk WARTOŚCI konfiguracji**: `selection_required`, `idle_timeout_minutes`, `night_cutoff`, `quick_pick_count`.

Punkt 3 to nie jest znacznik czasu, tylko hash tego, co realnie leci w ciele. Poprzednio był to `MAX(prod_config.updated_at)` i miał trzy dziury naraz: rozdzielczość sekundy (dwuklik „Zapisz" = druga zmiana nieosiągalna dla tabletu na zawsze), kolumnę bez `ON UPDATE` (zmiana surowym SQL-em nie ruszała ETagu) i — najgorsze — **ciało brało wartości z 60-minutowego cache procesu, a ETag z bazy**. Passenger trzyma kilka procesów, więc przestawiony kill-switch przyjeżdżał do Was jako *stara wartość pod nowym ETagiem*, którą zapisywaliście i od następnego żądania dostawaliście 304. Teraz przed złożeniem odpowiedzi sprawdzamy, czy baza jest świeższa od cache, i jeśli tak — przeładowujemy.

Sprawdzone na kopii produkcyjnej, zmiana wprowadzona surowym UPDATE-em **z pominięciem invalidacji cache**: `HTTP 200`, nowa wartość w ciele, nowy `catalog_version`. Wszystkie cztery klucze osobno pokryte testem (`test_kazdy_klucz_konfiguracji_uniewaznia_catalog_version`).

Odpowiedź na Wasze pytanie brzmi więc: **tak, zmiana kill-switcha dojedzie na tablety.**

## 10. Czego jeszcze nie zamknęliśmy

Żeby nie było niespodzianek:

- **Dwa równoległe `/sessions/start` w tej samej sekundzie** dla tego samego pracownika potrafią dać dwie otwarte sesje (zmierzone: 4 na 8 prób). Sekwencyjnie problem nie występuje. Fix wymaga unikatu w bazie — osobny task, migracja schematu.
- **`SESSION_END`, który dotrze przed swoim `SESSION_START`**, zostawia po starcie otwartą sesję-widmo — Wy po `end` robicie `closeAllOpen` i drugiego `end` już nie wyślecie. Domknie ją cron `close_stale_sessions`, ale **ten cron nie jest jeszcze wpisany w crontab hostingu**; to nasza pozycja przed roll-outem.
- **Praca z kolejki offline wpada do doby synchronizacji, nie do doby wykonania.** Format przewodowy akcji (`/complete`, `/quantity`, `/reject`) nie ma dziś pola na moment wykonania, więc raport dzienny pokaże wczoraj godziny bez sztuk, a dziś sztuki bez godzin. Praca nie ginie, ale rozjeżdża się w czasie. Jeśli uznacie to za warte naprawy, potrzebujemy opcjonalnego `performed_at` w tych trzech endpointach — w tym samym formacie co znaczniki sesji. Powiedzcie, czy chcecie to dołożyć.

---

## Pytanie od nas: stan absolutny czy przyrost przy wielu tabletach na stanowisku?

Wasza decyzja 1 zmienia jedną rzecz, której wcześniej nie było widać. Skoro na
jednym stanowisku stoi kilku ludzi z osobnymi tabletami — a w bazie widzimy
**7 tabletów na składaniu, 7 na sklejaniu, 6 na pakowaniu** — to wszyscy oni
widzą **tę samą kolejkę produktów**.

`PATCH /orders/{id}/quantity` przyjmuje dziś **stan absolutny** (`quantity_done`),
nie przyrost. Przy dwóch osobach pracujących nad tym samym produktem wygrywa
ostatnie żądanie:

```
produkt 240, sklejanie, quantity_done = 0
Adam   (tablet A) robi 5 → wysyła quantity_done: 5   → w bazie 5
Bartek (tablet B) robi 3 → wysyła quantity_done: 3   → w bazie 3  (praca Adama znika)
```

Bartek dostaje przy tym event z `delta = -2`, czyli **ujemny wkład w raporcie
imiennym**.

**Skala dzisiaj (dane produkcyjne, 18 385 eventów):** 16 przypadków, w których
ten sam produkt na tym samym stanowisku ruszały różne tablety tego samego dnia.
Po obejrzeniu przebiegów wyglądają na pracę sekwencyjną (jeden odbił rano, drugi
korygował po południu), nie na równoczesny wyścig. Czyli mechanizm jest realny,
ale jeszcze nie gryzie.

Zmienia się natomiast jego cena. Dziś nadpisanie to zła liczba na stanowisku —
po wdrożeniu profili to **minus u konkretnego człowieka** w raporcie, który
trafia na rozmowę o wynikach.

**Pytanie:** czy apka wysyła stan całego produktu, jaki widzi u siebie, czy
własny przyrost?

Jeśli stan całego produktu, do rozważenia jedno z dwóch:
- przejście na **deltę** (`quantity_delta: +3` zamiast `quantity_done: 3`), albo
- **optimistic locking**: apka odsyła `quantity_done_after`, które ostatnio
  widziała, a backend odrzuca żądanie z 409, gdy stan w międzyczasie się zmienił.

Nie prosimy o zmianę teraz — bramka jest wyłączona, profile jeszcze nie działają
na hali. Chcemy tylko wiedzieć, po której stronie leży ta decyzja, zanim
włączymy `WORKER_SELECTION_REQUIRED`.

---

## Dopisek: konfiguracja zmieniana z pominięciem panelu

Po Waszym pytaniu o kill-switcha domknęliśmy jeszcze jedną drogę. `prod_config.updated_at`
nie miało `ON UPDATE` w schemacie, więc wypełniał je wyłącznie zapis z panelu.
Zmiana wykonana zapytaniem w phpMyAdmin — a po kill-switcha sięga się dokładnie
wtedy, gdy hala stoi i ktoś idzie na skróty — nie ruszała znacznika, a przez to
nie unieważniała `catalog_version`.

Migracja `2026-08-11-07-prod-config-updated-at.sql` to naprawia. Sprawdzone na
kopii produkcyjnej: po niej **obie** drogi (panel i surowy UPDATE) dają na tablecie
HTTP 200 z nową wartością.
