# Priorytety produkcji, krok K6 — kontrakt API mobilnego dla appki i karta sesji appki — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sesja appki (repo `woodpower_prod_app`) dostaje jeden dokument `docs/api-mobile-priorytety.md`, z którego da się
zbudować ekran stołu, Odłóż, SSE z odpytywaniem awaryjnym i obsługę 409 **bez czytania kodu CRM**. Każde twierdzenie
w dokumencie ma odnośnik `ścieżka:linia` na gałęzi `claude/priorytety-produkcji` pod hashem z nagłówka i jest sprawdzone
na kodzie. Do tego gotowa karta (prompt startowy) dla tej sesji, z listą zmian ekranów, kryteriami odbioru z tabletem
i raportem końcowym.

**Architecture:** Krok wyłącznie dokumentacyjny, **zero zmian w kodzie**. Dwa nowe pliki: kontrakt
`docs/api-mobile-priorytety.md` (styl `docs/api-mobile-krawedzie-lakiernia.md`: „stan przed / stan po”, odnośniki,
tabela błędów, „czego dokument nie rozstrzyga”) i karta `docs/superpowers/plans/2026-10-05-priorytety-karta-appki.md`.
Źródłem prawdy jest kod gałęzi roboczej po K3 (i K5); spec 6 i Doprecyzowania K3 są tylko mapą, co sprawdzić. Odnośniki
weryfikuje mechanicznie sprawdzacz w scratchpadzie (poza repo, `git show <hash>:<ścieżka>`), a treść twierdzeń —
czytanie kodu i nazwy testów K3. Przykłady JSON: z `curl` na podglądzie, gdy sesja jest lokalna; w sesji cloud —
złożone z serializera i asercji testów, z dopiskiem „zbudowane z kodu”.

**Tech Stack:** Markdown; git (`git show`, `git grep`, `git log`); Python 3 stdlib (sprawdzacz odnośników, uruchamiany
z scratchpadu); opcjonalnie `curl` na podglądzie (tylko sesja lokalna, nigdy produkcja).

**Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md`: 2 (ustalenia 5–8, 11, 13), 5.1–5.6 (stół,
pobieranie, Odłóż, sygnały, bramki, kompletność), **6.1–6.4** (kontrakt i zakres dla appki), 8.4, 8.6 (klucze
`priorytety_tryb_<S>`, `priorytety_min_app_version_code`), 9.4 (współbieżność — tylko do opisu skutków dla appki), 10
(błędy), 11 (P2, P3, kompatybilność, wycofanie), **12** (kontrakt), 13 (P-2, P-3, P-6, P-7, P-9). Symulacja
`docs/superpowers/specs/2026-10-04-priorytety-produkcji-symulacja.md`: „Analiza wyniku” D p. 5–6 (K=2 i „Niekompletne”
do K wystarczają; ~380 zdarzeń liczników dziennie), „E. Decyzje”. Podręcznik centrali
`docs/superpowers/plans/2026-10-05-priorytety-produkcji-centrala.md`: 2, 3, 4, 4a, **8.7**. Plan K3
`docs/superpowers/plans/2026-10-05-priorytety-krok-K3-stol-odloz-sygnaly.md`: Doprecyzowania 1–16 (dla appki zwłaszcza
3, 4–7, 12 — bramka przepuszcza pozycje niekompletnych, 13 — limit odłożeń miękki, 14 — `Cache-Control: max-age=0`,
16 — `pozycje` kafla-zamówienia), Interfaces Task 1–5, Task 3 (postpone bez dopełnienia), Task 6 Step 6 („K6 (kontrakt
appki)”), „Pytania do Konrada” K3 p. 2–5. Raport K5, „Co następny krok musi wiedzieć” → K6 (curl-e z podglądu
z K5 Task 5 i hash). Plan K4b, „Co następny krok musi wiedzieć” → K6: monitory nie są częścią kontraktu.
Wzór stylu: `docs/api-mobile-krawedzie-lakiernia.md`.

**Sesja:** **cloud dopuszczalna**, **Opus 5.5, effort high** (podręcznik 4a: jasny zakres, brak współbieżności w kodzie;
tryb szybki dozwolony). Krok tylko czyta kod i pisze dokumenty, testów nie uruchamia (środowisko cloud nie ma
zależności aplikacji — podręcznik 4). Sesja **lokalna** tylko wtedy, gdy centrala chce żywych odpowiedzi z podglądu
(Task 4 Step 5) — wtedy podgląd wskazany przez centralę (S-3), nigdy produkcja.

**Zależności:** **K3 zakończony i zaliczony** (twarda: `stol.py`, `sygnaly.py`, końcówki `desk`/`postpone`/`realtime-token`,
`priorytet` w serializerze, `KSZTALT_ODPOWIEDZI_KOLEJKI = 6`). **K5 zaliczony — zalecany** (sekcja „Priorytety produkcji”
w CLAUDE.md, doprecyzowania K1–K4b w specu, wynik wyścigu `zakoncz-zakoncz-ten-sam-kafel` z listy K3 Task 6, czasy `GET desk`).
Kolejność centrali (podręcznik 3): K6 po K7 część 1, czyli kod P1 jest już na produkcji — dokument opisuje kod, który
appka zobaczy. Bez K5 krok da się zrobić, ale sekcje z wynikiem wyścigu i odnośnikiem do CLAUDE.md dostają dopisek
„do potwierdzenia przez K5” i pozycję w „Pytaniach do Konrada”.

**Gałąź:** `claude/priorytety-produkcji`. Start: `git fetch origin && git checkout claude/priorytety-produkcji && git pull
--ff-only origin claude/priorytety-produkcji`. Nigdy `main`. Numery linii w sekcjach „Stan obecny” dotyczą
`claude/logistyka-etap-4` @ `b4b4a54d` (sprzed K1–K5); kod K3 jeszcze nie istnieje (`modules/production/priorytety/` —
brak katalogu na `b4b4a54d`). Po K3 linie się przesuną — szukaj po nazwie (`git grep -n`), nazwy podane są w każdym miejscu.

## Global Constraints

- **Żadnych zmian w kodzie, testach, migracjach, CLAUDE.md ani specu.** Krok tworzy dokładnie dwa pliki (kontrakt
  i kartę) plus raport kroku. Rozbieżność spec ↔ kod opisuje się w raporcie i w kontrakcie („stan faktyczny: …”), nie
  naprawia. Sprawdzacz odnośników i surowe odpowiedzi z `curl` leżą w scratchpadzie sesji, **nie w repo**.
- **Źródłem prawdy jest kod pod hashem z nagłówka dokumentu**, nie spec i nie plan K3. Każde twierdzenie
  o zachowaniu serwera ma odnośnik `ścieżka:linia` albo `ścieżka:od-do`, pełną ścieżką od korzenia repo (bez skrótu
  `:241` stosowanego w `api-mobile-krawedzie-lakiernia.md` — sprawdzacz musi umieć go rozwiązać). Odnośnik do funkcji
  albo stałej dostaje kotwicę: `` `modules/production/routers/mobile_api.py:425` (`order_complete`) ``.
- **Hash w nagłówku = HEAD gałęzi przed pierwszym commitem K6** (commit dokumentu nie zmienia kodu, więc odnośniki
  zostają prawdziwe). Jeśli HEAD jest już na `origin/main` (`git merge-base --is-ancestor <hash> origin/main`), nagłówek
  mówi to wprost — sesja appki wie, że to kod produkcji.
- **Repo publiczne:** w przykładach JSON żadnych danych klientów (nazwiska, adresy, telefony, numery zamówień z Base.
  z produkcji), żadnych tokenów, sekretów, adresów IP, kluczy `REALTIME`. Token w przykładach: `"eyJ…(skrócony)"`.
  `sse_url` w przykładzie jak w docstringu agenta druku (`print_agent_api.py:280`) — to adres publiczny, już w repo.
- **Nazwy pól, kodów błędów, kluczy `prod_config` i końcówek dokładnie jak w kodzie** (po K3 równe specowi 6 i 8.6
  albo opisane w „Odstępstwach” raportu K3). Inna nazwa w kodzie niż w specu → dokument podaje nazwę z kodu, raport K6
  wymienia różnicę.
- Polszczyzna, w tekstach dla ludzi „Base.”, bez emoji. Komunikaty serwera cytowane dosłownie z kodu.
- Commity Conventional Commits po polsku, temat bez polskich znaków, **jeden na Task**, stopka atrybucji własnej sesji.
  `docs/api-mobile-priorytety.md` zwykłym `git add` (katalog `docs/` nie jest ignorowany — `.gitignore:241` ignoruje
  tylko `docs/superpowers/`); karta i raport przez `git add -f`. Push wg karty centrali (S-2). Nigdy `main`.
- `tools/print_agent` bez zmian (krok go tylko cytuje jako wzorzec klienta SSE). Kod appki — poza zakresem.
- **Nigdy nie uruchamiaj niczego na produkcji** (także `POST /api/mobile/register` — założyłby urządzenie w bazie
  produkcyjnej). `curl` wyłącznie na podglądzie wskazanym przez centralę.

## Review Focus

1. **ZAKOŃCZ i licznik pozycji zamówienia z sekcji „Niekompletne” w trybie `stol`.** Spec 5.6 p. 2 i P-9: „ZAKOŃCZ
   pozycji działa”. Kafel-zamówienie niekompletny **nie leży na stole** (nie ma wiersza `o:<order_id>`). Plan K3
   (Doprecyzowania p. 12, Interfaces Task 1: `bramka_zakoncz` — „jednostka `zamowienie` i `not kompletne_na(item.order,
   S)` → przepuść”) to przewiduje, i to dla **każdego** niekompletnego zamówienia, nie tylko K pokazanych. Sprawdź
   w kodzie, że ta gałąź bramki istnieje (ZAKOŃCZ **i** licznik), i wskaż test `test_bramka_przepuszcza_pozycje_niekompletnego_zamowienia`
   (K3 Review Focus 4; jeśli K3 nazwał inaczej — nazwa z kodu, „Odstępstwa”). **Brak takiej ścieżki w kodzie = STOP**
   (Ryzyka R1): kontrakt nie może obiecać appce czegoś, czego serwer odmawia 409.
2. **JSON w dokumencie = to, co serwer naprawdę oddaje.** Każde pole przykładu `desk` (obie jednostki), `postpone`,
   `realtime-token` i `priorytet` ma pokrycie w serializerze albo w asercji testu K3: `test_desk_ksztalt_odpowiedzi_pozycja`,
   `test_desk_ksztalt_odpowiedzi_zamowienie`, `test_postpone_200_zwraca_stol_z_odlozonym`,
   `test_realtime_token_kanaly_stanowiska`, `test_serialize_order_ma_priorytet_i_ksztalt_6`,
   `test_priorytet_szczebel_z_rangi_i_drabiny`, `test_serialize_order_grupa_wykonczenia` (Lakiernia, K3 Task 5a). Pole bez pokrycia → usunąć z przykładu albo opisać jako „nieobecne w kodzie”.
3. **Kolejka offline nie traci pracy i nie kręci się w kółko.** Które nowe kody są „do ponowienia” (nie zapamiętane pod
   `X-Operation-Id`), a które ostateczne: `BLEDY_DO_PONOWIENIA` (`mobile_api.py:122` na `b4b4a54d`) +
   `test_nie_na_stole_nie_zapisuje_wpisu_idempotencji`, `test_postpone_limit_409_bez_wpisu_idempotencji`,
   `test_postpone_nie_na_stole_409_bez_wpisu_idempotencji`, `test_postpone_powtorka_idempotentna_zwraca_zapisana_odpowiedz`.
   Dokument podaje dla każdego kodu regułę porzucenia wpisu (Doprecyzowania p. 1–2).
4. **Sygnały: po commicie, bez ładunku, na właściwe kanały; brak realtime = odpytywanie.** `test_zakoncz_sygnal_na_to_i_nastepne_stanowisko`,
   `test_sygnal_nie_idzie_przy_rollbacku_409`, `test_desk_sygnal_tylko_gdy_dopelnil`, `test_realtime_token_503_gdy_wylaczony`,
   `test_realtime_token_404_trakownia`, `test_publish_station_signal_nie_rzuca_gdy_broker_padl`. Dokument mówi wprost:
   sygnał może nie przyjść nigdy, siatką jest odpytywanie 30 s / 5 min (P-7).
5. **Dwa różne progi wersji appki nie zlewają się w jeden.** `X-App-Version` (semver, 426 `app_version_too_old`,
   `mobile_api_service.py:444-451`) kontra `priorytety_min_app_version_code` (liczba, porównywana z
   `ProductionDevice.last_app_version_code` z heartbeatu, `mobile_api.py:1278`). Testy: `test_bramka_stara_appka_bez_bramki_ale_zdejmuje_kafel`,
   `test_bramka_prog_zero_to_brak_bramki_wersji`. Dokument każe appce wysłać heartbeat zaraz po starcie (Doprecyzowania p. 4).
6. **Każdy odnośnik sprawdzony mechanicznie:** sprawdzacz (Task 4 Step 2) kończy się `bledow 0` na hashu z nagłówka;
   każda sekcja `##` kontraktu (poza 14 „Kryteria odbioru” i 15 „Czego ten dokument nie rozstrzyga”) ma co najmniej jeden odnośnik.
7. **Karta appki jest samowystarczalna:** sesja appki nie potrzebuje dostępu do kodu CRM ani do specu; lista zmian
   ekranów, kody błędów i kryteria odbioru odsyłają do numerów sekcji kontraktu; raport końcowy appki podaje
   `version_code`, którego K7 potrzebuje do `priorytety_min_app_version_code`.

## Decyzje przyjęte (ze specu, symulacji i podręcznika)

1. **Stół zamiast listy** (Konrad 4.10, spec 2 p. 5, 5.1): tablet pokazuje 1–2 kafle (`priorytety_stol_<S>`, K=2, P-2),
   bez kroku „rozpocznij”; kafel raz pokazany zostaje do ZAKOŃCZ albo Odłóż, niezależnie od zmian w biurze.
2. **Odłóż z powodem, kafel zostaje widoczny, limit 10 na stanowisko** (Konrad 4.10, spec 2 p. 6, 5.3, P-3, P-6);
   powody `brak_materialu`, `awaria_maszyny`, `brak_miejsca`, `czeka_na_biuro`, `inne` (z notatką).
3. **Sygnał zamiast odpytywania; siatka 30 s przy pustym stole, 5 min przy pełnym** (Konrad 4.10, spec 2 p. 7, 5.4,
   P-7; symulacja D p. 6 — ~380 zdarzeń dziennie, brak ryzyka po stronie brokera). Wyłączony realtime = odpytywanie.
4. **Kafel = pozycja** na Wycinaniu, Składaniu, Sklejaniu, Krawędziach; **= zamówienie** na Formatowaniu
   i Pakowaniu (Lakiernia bez stołu — p. 10) (Konrad 4.10, spec 2 p. 8, P-1); sekcja „Niekompletne” do K zamówień z postępem i listą brakujących,
   ZAKOŃCZ pozycji dozwolony (spec 5.6, P-9; symulacja B/D p. 5).
5. **Stara appka działa bez zmian** do przełączenia stanowiska na `stol` i podniesienia progu wersji (spec 1.3, 5.5, 11 P3).
6. **Kontrakt w stylu `api-mobile-krawedzie-lakiernia.md`, każde twierdzenie z odnośnikiem, hash w nagłówku; sesja appki
   pracuje wyłącznie z kontraktu** (Konrad 4.10, spec 2 p. 11, 12; podręcznik 8.7).
7. **Sesja appki: lokalna z tabletem po USB, Fable 5.1, extra** (podręcznik 4a i 8.7; decyzja Konrada 5.10: trudniejsze
   kroki na Fable 5.1 — kolejka offline, idempotencja i SSE to logika, której testy appki nie złapią).
8. **Kolejność wdrożenia** (podręcznik 3): P1 na produkcji (K7 część 1) → K6 → sesja appki → wydanie APK → K7 część 2
   (próg wersji, przełączanie stanowisk od Sklejania, S-6).
9. **Kolejność kafli liczy wyłącznie serwer** (spec 3.2 z decyzjami Konrada 5.10: próg „Blisko terminu” 3 dni robocze,
   grupa materiału = (gatunek, klasa, grubość) po najbliższym terminie w grupie, w grupie termin przed długością,
   „Blisko terminu” nad „Rozpoczęte”, bloki po N zamówień odrzucone). Kontrakt tego algorytmu nie opisuje appce do
   odtworzenia — mówi tylko, że appka pokazuje `stol`, `odlozone` i `niekompletne` w kolejności z odpowiedzi i niczego
   nie sortuje ani nie grupuje sama (inaczej dwa tablety stanowiska pokazałyby różne kolejności).
10. **Lakiernia bez stołu** (Konrad 5.10, S-6 wariant C; spec ustalenie 15, 3.2 „Lista Lakierni”, 5.5, 6.3, 6.4 p. 7):
    `painting` na stałe w trybie `stary` — ekran Lakierni to pełna lista `/stations/painting/orders` (pracownik wybiera
    sam), bez stołu, Odłóż i licznika „w kolejce”; ZAKOŃCZ bez bramki stołu. Kolejność listy liczy serwer (grupy
    wykończenia: rodzaj, kolor, połysk; grupy po najpilniejszej pozycji, w grupie ranga, doróbki pierwsze); appka pokazuje
    ją bez przesortowania jako domyślny widok, separatory grup z pola `grupa_wykonczenia`. `desk`/`postpone` dla
    `painting` → 409 `stanowisko_bez_stolu` (K3 Task 5a) — appka ich nie woła; ekran wybiera po kodzie stanowiska.
    Dzisiejsza appka 1.7.3 sortuje listę Lakierni sama (`buildOrderComparator`, „Partia (kolor i połysk)”) — kontrakt
    opisuje zmianę jako „stan przed / stan po” (raport karty D-Lakiernia, pytanie do Konrada o domyślne sortowanie).

## Doprecyzowania (do specu — K5 jest już za nami; centrala zleca naniesienie kartą dokumentacyjną)

Kontrakt rozstrzyga sprawy, których spec 6 nie opisuje. Każde doprecyzowanie trafia do kontraktu jako zasada dla appki
i do raportu K6 jako pozycja „Rozstrzygnięcia”.

1. **409 `nie_na_stole` z kolejki offline.** Kod jest w `BLEDY_DO_PONOWIENIA`, więc serwer go nie zapamiętuje i każde
   ponowienie trafia do handlera (spec 10). Reguła dla appki: po 409 `nie_na_stole` appka woła `GET desk` stanowiska
   i `GET /api/mobile/orders/<id>`; jeśli pozycja nie leży na stole ani w „Odłożonych” **i** jej `status` (pole
   `serialize_order`, `mobile_api_service.py:1233` na `b4b4a54d`) nie jest już statusem tego stanowiska — wpis
   **porzuca** z komunikatem „Zamknięte na innym tablecie albo zdjęte przez biuro”; 404 `order_not_found` z `GET
   /orders/<id>` (pozycja usunięta, np. zmiana z Base.) — też porzuca. `<id>` w `/orders/<id>` to id **pozycji**
   (`order_details`, `mobile_api.py:396-422`). W przeciwnym razie (pozycja dalej w statusie stanowiska, a kafla nie ma
   na stole — np. zamówienie kompletne, które jeszcze nie weszło na stół) zostawia wpis w kolejce, ponawia go najwyżej
   raz na pobranie stołu (nie w pętli) i pokazuje ostrzeżenie z możliwością ręcznego porzucenia. Nigdy nie wysyła akcji
   ponownie z nowym `X-Operation-Id`.
2. **Odłóż tylko online.** Odłożenie zmienia stół, a następny kafel przychodzi z serwera — offline nie da się go
   pokazać. Przycisk Odłóż nieaktywny bez połączenia; gdyby wpis `postpone` trafił do kolejki offline, 409
   `limit_odlozen` i `nie_na_stole` porzucają go z komunikatem (oba w `BLEDY_DO_PONOWIENIA`, ponawianie nic nie da bez
   człowieka). ZAKOŃCZ i licznik w kolejce offline — jak dotąd.
3. **Nowa appka na backendzie bez `/desk`.** Nieznana trasa pod `/api/mobile` oddaje domyślne 404 Flaska (HTML, nie
   JSON — w `app.py` nie ma `errorhandler(404)`; są tylko `:1135` 401 i obsługa błędów bazy `:1800-1870` na `b4b4a54d`).
   Appka traktuje 404 bez ciała JSON z `GET desk` jako „backend bez stołu” i wraca do dzisiejszej listy
   `/stations/<kod>/orders` (wzór z etapu 4 logistyki: nowa appka na starym backendzie ukrywa Dostawę). 404 z JSON
   `{"error": "unknown_station"}` to co innego (stanowisko bez stołu, np. trakownia) — nie fallback, tylko błąd
   konfiguracji tabletu. Tak samo `GET /realtime-token`: 404 bez JSON = backend bez realtime dla tabletów → samo
   odpytywanie, jak przy 503.
4. **Heartbeat zaraz po starcie appki** (i po aktualizacji APK). Bramka wersji czyta `last_app_version_code`, który
   ustawia wyłącznie heartbeat (`mobile_api.py:1278`), wysyłany dziś co 15 min (docstring `mobile_api.py:1260`). Tablet
   bez heartbeatu po progu > 0 liczy się jako stara appka (K3 Doprecyzowania p. 3) — dla nowej appki to bezpieczne (brak
   bramki), ale panel pokaże ją jako starą do pierwszego heartbeatu.
5. **Sygnały łączone po stronie appki.** ZAKOŃCZ publikuje na dwa kanały, tablet Krawędzi słucha dwóch (`station:edges`,
   `station:painting`), a własny `GET desk` po ZAKOŃCZ wywołuje sygnał „pobranie na stół”. Appka trzyma najwyżej jedno
   `GET desk` w locie i jedno oczekujące na stanowisko (sygnał w trakcie pobierania = jedno dodatkowe pobranie po nim),
   z ETagiem (`If-None-Match`). Każda ramka danych SSE inna niż ping i `connect` znaczy „pobierz stół” (wzór
   `classify_sse_line`, `tools/print_agent/print_agent.py:518-550` na `b4b4a54d`).
6. **Krawędzie i Lakiernia.** Tablet Krawędzi ma stół Krawędzi (`/stations/edges/desk`) i **listę** Lakierni
   (`/stations/painting/orders`, Decyzje p. 10), dostęp przez `STATION_GROUPS` (`mobile_api_service.py:118-120`); tryb
   mieszany jest stały (Krawędzie `stol` po przełączeniu, Lakiernia zawsze `stary`). Sygnał na `station:painting`
   odświeża tylko listę Lakierni (`GET /orders` z ETagiem), nie woła `desk`.
   Grupa jest symetryczna (`device_can_access_station`, `mobile_api_service.py:123-148`) — tablet zarejestrowany na
   `painting` też ma dostęp do stołu Krawędzi; kanały takiego tabletu opisać z kodu `realtime-token` (K3), nie zakładać.
7. **`GET desk` jest zapisem.** Dopełnia stół i commituje (spec 5.2), więc appka woła go tylko z ekranu stanowiska:
   po własnym ZAKOŃCZ/Odłóż, po sygnale, przy wejściu na ekran i wg siatki 30 s / 5 min — nie z wyszukiwarki, nie
   w tle przy wygaszonym ekranie częściej niż siatka.
8. **Format odnośników w kontrakcie:** pełna ścieżka i kotwica (Global Constraints) — odstępstwo od stylu
   `api-mobile-krawedzie-lakiernia.md`, które pozwala sprawdzać odnośniki skryptem.
9. **Kolejność i pamięć podręczna `desk` po stronie appki.** Elementy `stol`, `odlozone`, `niekompletne` appka pokazuje
   w kolejności z odpowiedzi (Decyzje p. 9; kontrakt podaje `ORDER BY` z kodu `stol.kafle`/odpowiedzi `desk`). `desk`
   ma `Cache-Control: private, max-age=0` + ETag (K3 Doprecyzowania p. 14): klient HTTP appki (OkHttp Cache) nie może
   serwować `desk` z pamięci bez zapytania serwera — każde pobranie idzie do serwera z `If-None-Match`; 304 oszczędza
   tylko ciało, nie dopełnienie (ETag liczony po dopełnieniu i commicie, K3 p. 6).
10. **Retencja wpisów idempotencji nie jest gwarancją kodu.** `cleanup_old_operations` (domyślnie 7 dni,
    `mobile_api_service.py:693`) woła wyłącznie komenda `flask cleanup-mobile-operations` (`app.py:394-402`); repo nie
    pokazuje, czy jest w crontabie produkcji (CLAUDE.md „Zadania cykliczne” jej nie wymienia). Kontrakt mówi: wpis
    zapamiętany żyje **co najmniej** do sprzątania; akcja dosłana po > 7 dniach może wykonać się drugi raz — appka
    takich wpisów nie dosyła bez potwierdzenia człowieka. Pytanie do Konrada p. 4.
11. **Pole `priorytet` jest wszędzie, gdzie `serialize_order`:** listy `orders`, `orders/since` (`changed`), `desk`,
    a także `orders/search` (`mobile_api.py:377`), `orders/<id>` (`:422`), odpowiedzi `complete` (`:495`), `quantity`
    (`:541`) i `reject` (`original`, `rework`, `:624-625`). Tabela końcówek (sekcja 3) wymienia je jako „zmienione:
    dodatkowe pole”. `orders/since` nie ma ETagu (`station_orders_since` `:699-747`) — KSZTALT 6 zmienia ETag tylko listy
    `orders`.

## Współbieżność (krok jej nie zmienia — kontrakt opisuje skutki dla appki)

K6 nie dotyka blokad. Kontrakt streszcza kolejność z CLAUDE.md (sekcja „Priorytety produkcji” dopisana przez K5;
„Trasy logistyki — jeden piszący naraz”, „zamówienie najpierw”) i spec 9.4 **tylko tam, gdzie appka widzi skutek**,
z odnośnikiem do kodu i testu K3, bez własnej interpretacji:

```
ZAKOŃCZ (order_complete):  touch_sessions → X zamówienie → X pozycje → delivery_method_not_set → bramka_zakoncz
                           → mark_order_complete → zdejmij_nieaktualne (DELETE stołu) → commit dekoratora → sygnały
                           testy: test_zdjecie_kafla_po_blokadzie_zamowienia_i_pozycji, test_zakoncz_nie_dotyka_blokady_stanowiska
GET desk (dopelnij):       COMMIT → prod_config priorytety_blokada_<S> FOR UPDATE → zamówienia LOCK IN SHARE MODE
                           → pozycje LOCK IN SHARE MODE → zwykły SELECT stołu → INSERT → COMMIT → sygnał (gdy dopełnił)
                           testy: test_dopelnij_commit_blokada_stanowiska_zamowienia_pozycje_potem_insert,
                                  test_dopelnij_po_blokadzie_widzi_cudzy_kafel, test_desk_ponawia_raz_po_1213
POST postpone (odloz):     touch_sessions → X zamówienie → X pozycje → własny wiersz stołu (station_code, unit_key)
                           FOR UPDATE → zwykły COUNT odłożonych stanowiska → UPDATE → log → commit dekoratora → sygnał
                           testy: test_odloz_zablokuj_zamowienie_potem_stol, test_odloz_nie_blokuje_cudzych_wierszy_stolu
```

Skutki do opisania w kontrakcie: dwa tablety wołające `desk` naraz dostają ten sam stół (drugi czeka na blokadzie,
nie dubluje); `desk` po drugim MySQL 1213 → 500 `desk_failed` (appka ponawia wg siatki, nie od razu w pętli);
`postpone` oddaje stół **bez** dopełnienia (K3 Task 3 Interfaces i „Pytania do Konrada” K3 p. 2 — appka woła `GET desk`
po Odłóż); limit odłożeń jest **miękki** (K3 Doprecyzowania p. 13, limit liczony zwykłym odczytem): dwa Odłóż naraz
przy limicie mogą oba dostać 200 (odłożonych = limit + 1) — appka nie liczy limitu sama i nie zakłada, że po 200 jest
miejsce na kolejne; rozkład z raportu K5 (tryb `odloz-odloz`); ZAKOŃCZ tego samego kafla z dwóch tabletów — wynik
z raportu K5 (tryb `zakoncz-zakoncz-ten-sam-kafel`), bez K5 „do potwierdzenia”.

## Mapa plików

| Plik | Task | Rola |
|---|---|---|
| `docs/api-mobile-priorytety.md` (nowy) | 1–4 | kontrakt dla appki, sekcje 0–15 (układ w Task 1) |
| `docs/superpowers/plans/2026-10-05-priorytety-karta-appki.md` (nowy, `git add -f`) | 5 | prompt startowy sesji appki |
| `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K6-raport.md` (nowy, `git add -f`) | 6 | raport kroku |
| `<scratchpad>/sprawdz_odnosniki.py`, `<scratchpad>/odpowiedzi/*.json` | 1–4 | narzędzia i surowe odpowiedzi — **poza repo, nie commitować** |

Zmienione: nic. Usunięte: nic. Czytane (do odnośników): `modules/production/routers/mobile_api.py`,
`modules/production/services/mobile_api_service.py`, `modules/production/services/realtime_service.py`,
`modules/production/routers/api/print_agent_api.py`, `modules/production/models.py` (`ProductionDevice`),
`modules/production/priorytety/**` (K1–K3), `modules/production/services/station_catalog.py`, `app.py`,
`tools/print_agent/print_agent.py`, `ops/centrifugo/config.example.json`, testy `tests/test_priorytety_*.py` (K3),
CLAUDE.md, raporty K3 i K5.

---

### Task 1: Punkt wyjścia, inwentarz faktów, szkielet kontraktu (sekcje 0–3)

**Files:**
- Create: `docs/api-mobile-priorytety.md`
- Scratchpad (poza repo): `sprawdz_odnosniki.py`, `inwentarz.txt`

**Stan obecny (ugruntowanie, `b4b4a54d` — przed K1–K5):**
- Blueprint mobilny: `app.py:876` (`/api/mobile`), osobne `:878` trakownia, `:882` Weryfikacja, `:885` Dostawa —
  trzy ostatnie poza zakresem kontraktu (priorytety ich nie zmieniają; kontrakt to mówi jednym zdaniem).
- `modules/production/routers/mobile_api.py` — **23 trasy** (`grep -c "@mobile_api_bp.route"`). Istotne dla kontraktu:
  `_resolve_station_code` `:52-103` (alias `finishing`, 404 `unknown_station`, 403 `station_mismatch`);
  `BLEDY_DO_PONOWIENIA = {400, 403, 404, 409}` `:122` (uzasadnienie `:107-121`); `KSZTALT_ODPOWIEDZI_KOLEJKI = 5` `:137`
  (historia podbić `:124-136`); `_resolve_workers` `:147-180` (`X-Worker-Ids`); `register` `:185-235` (bez tokena —
  tylko podgląd!); `station_orders` `:242-326` (cała kolejka, sort `COALESCE(priority_rank, 999999)` `:303-306`, ETag
  `:292-296`); `order_details` `:396-422` (zwykły odczyt, pole `status`); `order_complete` `:425-495`
  (`zablokuj_zamowienie_pozycji` `:460`, 409 `delivery_method_not_set` `:467-474`, 400 `invalid_station` i 500
  `complete_failed` `:476-486`); `order_quantity` `:498-541`
  (`ProductionItem.query.get` `:524`, bez blokady zamówienia); `order_reject` `:544-631`; `station_summary` `:634-696`;
  `station_orders_since` `:699-747`; `app_version` `:750-759`; `app_apk` `:762-787`; `device_heartbeat` `:1256-1311`
  (`last_app_version_code` `:1278`).
- `modules/production/services/mobile_api_service.py`: `STATION_STATUS_MAP` `:69`, `STATUS_TO_STATION` `:106`,
  `STATION_GROUPS` `:118-120`, `device_can_access_station` `:123-148`, `_version_too_old` `:244-252`,
  `validate_heartbeat_payload` `:380-404` (`app_version_code` wymagane), `require_device_token` `:413-463` (426
  `app_version_too_old` z `X-App-Version` `:444-451`), `with_idempotency` `:470-664` (powtórka `:536-552`, rollback dla
  `retryable` `:573-577`, zapis wpisu `:579-624`, sygnał druku `:638-645`, dopychacz `:647-655`),
  `cleanup_old_operations` `:693` (retencja wpisów idempotencji 7 dni — granica kolejki offline), `serialize_order`
  `:1088-1253` (`priority_rank`/`is_priority` `:1231-1232`, `status` `:1233`, `updated_at` `:1249`),
  `mark_order_complete` `:1260-1316`, `update_order_quantity` `:1319-1340`, `compute_station_summary` `:1604-1668`
  (`refresh_interval_seconds` z `REFRESH_INTERVAL_SECONDS` `:1646-1653`), `get_station_queue_delta` `:1752-1799`.
- `modules/production/models.py`: `ProductionDevice.app_version` `:1155`, `last_app_version_code` `:1161`,
  `VALID_STATION_CODES` `:1168`, `touch` `:1194-1200` (zapisuje tylko `app_version` z nagłówka, nie `version_code`).
- `modules/production/services/realtime_service.py`: docstring kanałów `:10-12` (`station:<code>` zapowiedziany),
  `is_enabled` `:53-56`, `sse_url` `:79-82`, `publish` `:110-180` (nigdy nie rzuca), `publish_print_signal` `:183-189`,
  `issue_connection_token` `:192-216` (TTL domyślny 3600 s `:33`).
- `modules/production/routers/api/print_agent_api.py:265-301` (`realtime_token`) — wzór 200/503 dla agenta druku.
- `tools/print_agent/print_agent.py` — wzorcowy klient SSE: `fetch_realtime_config` `:390-431`, `open_sse` `:487-515`
  (**POST** z JSON `{"token": …}` na `uni_sse`), `classify_sse_line` `:518-550`, `wait_for_signal` `:551-600` (ping co 25 s,
  martwe po 40 s `:367-371`), drabinka ponowień `SSE_RECONNECT_LADDER = (1, 2, 5, 10, 15, 30, 60)` `:379`,
  `_reconnect_delay` z jitterem `:961-975`, `czy_token_wygasl_planowo` `:986-1000` (zerwanie raz na TTL to rutyna).
- `ops/centrifugo/config.example.json:14-26` — `uni_sse` włączone, namespace `station` w konfiguracji brokera.
- **Nie istnieje na `b4b4a54d`** (powstaje w K1/K3, nazwy ze specu 9.1 i planu K3): `modules/production/priorytety/`
  (`stale.POWODY_ODLOZENIA`, `ustawienia.tryb/miejsca/jednostka/limit/min_app_version`, `services/stol.py`:
  `BladStolu`, `bramka_zakoncz`, `stara_appka`, `dopelnij`, `odloz`, `kontekst_priorytetu`; `services/sygnaly.py`:
  `zaplanuj`, `wyslij`, `nastepne_stanowisko`), końcówki `desk`, `postpone`, `realtime-token`, stała
  `KSZTALT_ODPOWIEDZI_STOLU`, `realtime_service.publish_station_signal`, `channel_station`.

**Interfaces (Produces — układ kontraktu, na który powołuje się karta appki z Task 5; numery sekcji stałe):**
```
0  Nagłówek: gałąź, hash, czy na main, „sprawdzaj w kodzie”
1  Najważniejsze w pięciu zdaniach
2  Stan przed / stan po (tabela)
3  Tabela końcówek: bez zmian / nowe / zmienione (23 + 3 trasy /api/mobile; trakownia, Weryfikacja, Dostawa bez zmian)
4  GET /api/mobile/stations/<kod>/desk
5  POST /api/mobile/orders/<id>/postpone
6  ZAKOŃCZ i licznik w trybie `stol` (bramka 409 nie_na_stole, kolejność bramek, Niekompletne)
7  Pole `priorytet` i KSZTALT 6 (listy, delta, desk)
8  Realtime: GET /api/mobile/realtime-token, połączenie SSE, sygnał
9  Odpytywanie awaryjne i pobieranie stołu (30 s / 5 min, po własnej akcji, łączenie sygnałów)
10 Kolejka offline i idempotencja (tabela kodów: ponawiać / porzucić / pokazać)
11 Bramka wersji appki i tryb `stary` (dwa progi, heartbeat)
12 Kompatybilność i kolejność wdrożenia (nowa appka ↔ stary backend, stara appka ↔ nowy backend, wycofanie P3)
13 Ekrany do zmiany (spec 6.4)
14 Kryteria odbioru z tabletem (checklista)
15 Czego ten dokument nie rozstrzyga
```

- [x] **Step 0: Punkt wyjścia**
  1. Start z karty; `git log -1 --format='%H %s'` zgodny z kartą centrali, inaczej STOP. Zapisz pełny hash jako `HASH`.
  2. `git merge-base --is-ancestor $HASH origin/main && echo NA_MAIN` — wynik do nagłówka kontraktu.
  3. Przeczytaj raporty K3 i K5 (`docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K3-raport.md`, `…-K5-raport.md`):
     „Odstępstwa od planu”, „Rozstrzygnięcia”, „Co następny krok musi wiedzieć” → K6. Brak raportu K3 z werdyktem
     „zaliczony” w dzienniku centrali → STOP.
- [x] **Step 1: Inwentarz** (`<scratchpad>/inwentarz.txt`): `git grep -n` po nazwach z listy „Nie istnieje na
  `b4b4a54d`” oraz:
  `git grep -n "@mobile_api_bp.route\|BLEDY_DO_PONOWIENIA\|KSZTALT_ODPOWIEDZI_\|def bramka_zakoncz\|def stara_appka\|def dopelnij\|def odloz\|class BladStolu\|POWODY_ODLOZENIA\|def publish_station_signal\|CHANNEL_STATION\|def channel_station\|def kontekst_priorytetu\|def zaplanuj\|def wyslij\|def realtime_token\|def station_desk\|def order_postpone\|STATION_GROUPS\|last_app_version_code" -- modules app.py`
  oraz `git grep -n "def test_" -- tests/test_priorytety_stol.py tests/test_priorytety_mobile.py tests/test_priorytety_sygnaly.py`.
  Każda nazwa z Review Focus musi mieć trafienie; brakujące → lista do raportu („Odstępstwa”: nazwa z kodu) albo STOP
  (R1, R2).
- [x] **Step 2: Sprawdzacz odnośników** — `<scratchpad>/sprawdz_odnosniki.py` (stdlib, poza repo). Szkic:
  ```python
  # Użycie: python3 sprawdz_odnosniki.py <HASH> docs/api-mobile-priorytety.md
  import re, subprocess, sys
  HASH, DOC = sys.argv[1], sys.argv[2]
  REF = re.compile(r'`((?:modules|tests|tools|ops|migrations|scripts)/[\w/.\-]+|app\.py|CLAUDE\.md)'
                   r':(\d+)(?:-(\d+))?`(?:\s*\(`([^`]+)`\))?')
  tekst = open(DOC, encoding='utf-8').read()
  bledy, ile, cache = 0, 0, {}
  for m in REF.finditer(tekst):
      sciezka, od, do, kotwica = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2)), m.group(4)
      ile += 1
      if sciezka not in cache:
          r = subprocess.run(['git', 'show', '%s:%s' % (HASH, sciezka)], capture_output=True, text=True)
          cache[sciezka] = r.stdout.splitlines() if r.returncode == 0 else None
      linie = cache[sciezka]
      if linie is None: print('BRAK PLIKU', m.group(0)); bledy += 1; continue
      if not (1 <= od <= do <= len(linie)): print('POZA PLIKIEM', m.group(0)); bledy += 1; continue
      if kotwica and not any(kotwica in l for l in linie[max(0, od - 4):do + 3]):
          print('KOTWICA NIE PASUJE', m.group(0)); bledy += 1
  # każda sekcja '## ' (poza „Kryteria odbioru” i „Czego ten dokument nie rozstrzyga”) ma >= 1 odnośnik
  for naglowek, tresc in re.findall(r'^## (.+)\n((?:(?!^## ).*\n?)*)', tekst, re.M):
      # „Kryteria odbioru” odsyłają do sekcji kontraktu, nie do kodu
      if 'nie rozstrzyga' not in naglowek and 'Kryteria odbioru' not in naglowek and not REF.search(tresc):
          print('SEKCJA BEZ ODNOSNIKA', naglowek); bledy += 1
  if ile == 0: print('BRAK ODNOSNIKOW'); bledy += 1
  print('odnosnikow', ile, 'bledow', bledy); sys.exit(1 if bledy else 0)
  ```
  Uruchom na pustym pliku → oczekiwany wynik: kod wyjścia 1 (`BRAK ODNOSNIKOW`) — to jest „test, który pada”.
- [x] **Step 3: Sekcje 0–3.** Nagłówek jak w `api-mobile-krawedzie-lakiernia.md` („Referencja różnicowa dla aplikacji
  Android (`woodpower_prod_app`)… Każde twierdzenie ma odnośnik… Odnośniki wskazują stan na gałęzi
  `claude/priorytety-produkcji` @ `<HASH>`” + zdanie o `main`). Uwaga o nazwie repo: starsze dokumenty mówią
  `crm_prod_app` (np. `docs/api-mobile-krawedzie-lakiernia.md`), to ta sama appka. Sekcja 1: pięć zdań (stół zamiast
  listy; Odłóż; sygnał + siatka; bramka tylko w trybie `stol` i tylko dla nowej appki; stara appka bez zmian).
  Sekcja 2: tabela przed/po — kolejka cała vs stół (`station_orders` `:242-326` vs `desk`), odświeżanie co
  `refresh_interval_seconds` vs sygnał + 30 s/5 min, ZAKOŃCZ dowolnej pozycji (spec 1.1; brak sprawdzenia
  `current_status` — odnośnik do `complete_task`) vs bramka w `stol`, gwiazdka bool `is_priority` vs `priorytet`,
  realtime tylko dla agenta druku vs kanały `station:<kod>`. Sekcja 3: tabela 26 tras (23 dotychczasowe z kolumną
  „bez zmian / zmienione: co” — zmienione `orders` (`priorytet`, ETag przez KSZTALT 6), `orders/since` (`priorytet` w `changed`; bez ETagu),
  `orders/search` i `orders/<id>` (`priorytet` — Doprecyzowania p. 11), `complete`,
  `quantity` (bramka + sygnał), `reject` (sygnał; zdjęcie kafla), `summary` (bez zmian, `refresh_interval_seconds`
  zostaje dla starej appki) — plus 3 nowe).
- [x] **Step 4:** `python3 <scratchpad>/sprawdz_odnosniki.py $HASH docs/api-mobile-priorytety.md` → `bledow 0` dla
  sekcji 0–3 (sekcje 4–15 jeszcze nie istnieją — sprawdzacz liczy tylko obecne).
- [x] **Step 5: Commit** `docs(priorytety): kontrakt appki - szkielet, stan przed i po, tabela koncowek`

---

### Task 2: Stół, Odłóż, bramka ZAKOŃCZ, pole `priorytet` (sekcje 4–7) z pełnymi przykładami JSON

**Files:**
- Modify: `docs/api-mobile-priorytety.md`
- Scratchpad: `odpowiedzi/*.json` (tylko sesja lokalna, Task 4 Step 5 — tu przykłady z kodu)

**Stan obecny:** końcówki powstają w K3 (Task 2, 3, 5). Kształt wg spec 6.1–6.2 i planu K3: `desk` →
`{station_code, jednostka, miejsca, stol[{kafel, pobrano}], odlozone[{kafel, odlozono, powod, notatka, pracownik}],
niekompletne[{kafel, na_stanowisku, pozycji, brakuje[{short_id, stanowisko}]}], limit_odlozen, kolejka_dalej}`; `kafel`
jednostki `pozycja` = obiekt `serialize_order` + `priorytet`; jednostki `zamowienie` = `{zamowienie: {…}, pozycje: […]}`
(pola zamówienia wg K3 Task 2 Interfaces); ETag `desk` wg K3 Doprecyzowania p. 6 (`KSZTALT_ODPOWIEDZI_STOLU = 1`);
`postpone` body `{station_code, zakres, powod, notatka?}`, `<id>` = id pozycji także dla `zakres: "zamowienie"`
(K3 Doprecyzowania p. 7); 200 = stół bez dopełnienia; błędy 409 `limit_odlozen`, 409 `nie_na_stole`, 400
`powod_niepoprawny`, 400 `dane_niepoprawne`, 404 `order_not_found`; `priorytet` =
`{gwiazdki, szczebel: "trasa"|"gwiazdki"|"po_terminie"|"blisko_terminu"|"rozpoczete"|"dorobka"|null, trasa: {id, nazwa, data}|null, pozycja_w_zamowieniu: "i/n"}`
(spec 6.1 + K3 Doprecyzowania p. 4–5); `desk` z `Cache-Control: private, max-age=0` (K3 p. 14); limit odłożeń miękki
(K3 p. 13); `kafel.pozycje` = wszystkie pozycje zamówienia (K3 p. 16). Źródło przykładów JSON, w tej kolejności: curl-e
z podglądu z raportu K5 (Task 5 K5, „Co następny krok musi wiedzieć” → K6), potem — gdy ich brak — serializer i asercje
testów K3. **Wszystko to sprawdzasz w kodzie pod `HASH`; plan K3 i raport K5 to tylko lista kontrolna.**

**Interfaces (Consumes — HTTP, nazwy dokładnie jak w specu 6 i kodzie K3):**
- `GET /api/mobile/stations/<station_code>/desk` (`require_device_token`, bez `with_idempotency`; 200/304; 403
  `station_mismatch`; 404 `unknown_station`; 500 `desk_failed`).
- `POST /api/mobile/orders/<int:order_id>/postpone` (`require_device_token`, `with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)`,
  `X-Worker-Ids`, `X-Operation-Id`).
- `POST /api/mobile/orders/<int:order_id>/complete`, `PATCH /api/mobile/orders/<int:order_id>/quantity` — ciało bez
  zmian; w trybie `stol` 409 `{"error": "nie_na_stole", "message": "Zamówienie {numer} nie leży na stole {nazwa}."}`.
- `serialize_order(..., priorytety=None)` → pole `priorytet` za `is_priority`; `KSZTALT_ODPOWIEDZI_KOLEJKI = 6`.

- [x] **Step 1: „Test, który pada”** — dopisz do kontraktu nagłówki `## 4`–`## 7` bez treści; sprawdzacz → `SEKCJA BEZ
  ODNOSNIKA` ×4.
- [x] **Step 2: Sekcja 4 `desk`.** Żądanie (nagłówki: `Authorization`, `If-None-Match`; bez `X-Worker-Ids`), co robi
  serwer (dopełnia do K, doróbki ponad K, pakowanie bez sposobu dostawy nie wchodzi, odłożony nie wraca — odnośniki do
  `stol.dopelnij`), **dwa pełne przykłady 200**: Sklejanie (`jednostka: "pozycja"`, 2 kafle na stole, 1 odłożony,
  `niekompletne: []`) i Formatowanie (`jednostka: "zamowienie"`, 1 kafel-zamówienie z 2 pozycjami, 1 niekompletne
  z `brakuje`). Kafel-pozycję pokaż **w całości** (wszystkie pola `serialize_order` z kodu pod `HASH`, w kolejności
  kluczy), dane fikcyjne (`"client_name": "Klient testowy"`, numer `9001`, miasto „Testowo”). Opisz, które pozycje są
  w `kafel.pozycje` kafla-zamówienia (wszystkie niezanulowane czy tylko w statusie stanowiska — z kodu). Tabela pól
  z typami i znaczeniem (`kolejka_dalej` = licznik „w kolejce: 37”; `limit_odlozen`; `miejsca`). Kolejność elementów
  `stol`/`odlozone`/`niekompletne` z kodu (ORDER BY) i zasada „appka nie sortuje” (Doprecyzowania p. 9). ETag/304, co go
  zmienia, i `Cache-Control: private, max-age=0` (OkHttp zawsze pyta serwer). Błędy z kodami. Akapit „`GET desk` jest zapisem” (Doprecyzowania p. 7) i „dwa tablety naraz” (Współbieżność).
- [x] **Step 3: Sekcja 5 `postpone`.** Body z typami i walidacją (`zakres` musi zgadzać się z `jednostka`; `inne`
  wymaga notatki ≤ 255 znaków), tabela powodów z proponowanymi etykietami UI („Brak materiału”, „Awaria maszyny”,
  „Brak miejsca”, „Czeka na biuro”, „Inne”) — etykiety to propozycja dla appki, serwer zna tylko kody
  (`stale.POWODY_ODLOZENIA`). Pełne przykłady: 200 (stół z odłożonym, **bez dopełnienia** — appka woła potem `GET desk`),
  409 `limit_odlozen` z dosłownym `message` z kodu, 409 `nie_na_stole`, 400 `powod_niepoprawny`, 400 `dane_niepoprawne`,
  409 `stanowisko_bez_stolu` (Lakiernia, `desk` i `postpone`; K3 Task 5a). Dla każdego: czy zapamiętane pod `X-Operation-Id` (odnośnik do `BLEDY_DO_PONOWIENIA` i testów z Review Focus 3).
  Odłożenie już odłożonego kafla → 409 `nie_na_stole` (z kodu `stol.odloz`). Limit miękki (Współbieżność): appka nie
  liczy limitu i nie blokuje przycisku na podstawie `limit_odlozen` — decyduje odpowiedź serwera.
  Zasada „Odłóż tylko online” (Doprecyzowania p. 2). Odłożony kafel zamyka się zwykłym ZAKOŃCZ (`test_zakoncz_odlozonego_200`).
- [x] **Step 4: Sekcja 6 ZAKOŃCZ i licznik w trybie `stol`.** Kolejność bramek z kodu: `station_mismatch`/`unknown_station`
  → pracownicy → 404 → `delivery_method_not_set` (pakowanie) → `nie_na_stole` → zapis. Pełny przykład 409 `nie_na_stole`
  z dosłownym `message`. Kiedy bramki nie ma: tryb `stary`, stara appka (sekcja 11), `reject` i druk etykiet (spec 5.5).
  **Pozycje zamówienia z „Niekompletne”** — opis tego, co robi kod (Review Focus 1). Licznik (`PATCH quantity`) — ta sama
  bramka, odczyt stołu bez blokady zamówienia (K3). Odpowiedź 200 ZAKOŃCZ bez zmian (`serialize_order`), stół trzeba
  pobrać osobno.
- [x] **Step 5: Sekcja 7 `priorytet` i KSZTALT 6.** Tabela wartości `szczebel` z polskimi etykietami do plakietki
  („Trasa: <nazwa>, <data>”, „★★★★★”, „Po terminie”, „Blisko terminu”, „Rozpoczęte”, „Doróbka”, `null` = brak
  plakietki), `gwiazdki` 0–5, `pozycja_w_zamowieniu` (pomija anulowane, doróbka ma `i` oryginału). Gdzie pole jest
  (Doprecyzowania p. 11: listy `orders`, `orders/since`, `desk`, `orders/search`, `orders/<id>`, odpowiedzi ZAKOŃCZ,
  licznika i `reject` — sprawdź w kodzie, że pojedyncza pozycja liczy je sama).
  `priority_rank`/`is_priority` dalej są (stara appka, licznik `priority_count` w `/summary`). Podbicie
  `KSZTALT_ODPOWIEDZI_KOLEJKI` 5 → 6: stara appka raz pobierze pełną listę (ETag się zmienia), dodatkowe pole ignoruje.
- [x] **Step 6:** sprawdzacz → `bledow 0`. Każde pole każdego przykładu skreśl na liście kontrolnej z serializerem/testem
  (Review Focus 2); lista do raportu.
- [x] **Step 7: Commit** `docs(priorytety): kontrakt appki - desk, postpone, bramka ZAKONCZ, pole priorytet`

---

### Task 3: Realtime, odpytywanie awaryjne, kolejka offline, wersje, kompatybilność (sekcje 8–12)

**Files:**
- Modify: `docs/api-mobile-priorytety.md`

**Stan obecny:** `realtime_service` i wzór agenta druku jak w Task 1; `realtime-token` dla tabletu i
`publish_station_signal` z K3 Task 4 (spec 6.3: `{enabled, token, ttl_seconds, sse_url, channels}`, 503 gdy wyłączony;
K3: 404 `unknown_station` dla trakowni/Weryfikacji/Dostawy, `sub = 'device:<device_id>'`, kanały = stanowisko + grupa).
Miejsca publikacji: tabela K3 Task 4 (ZAKOŃCZ → to stanowisko i następne pozycji; licznik; Odłóż; pobranie na stół;
doróbka → to, powrotu, zdjęte; hurt; Base.; cron). Tryb i próg: `ustawienia.tryb(S)`, `ustawienia.min_app_version()`,
`stol.stara_appka(device)` (K3 Doprecyzowania p. 3: `prog > 0 and (kod is None or kod < prog)`).

**Interfaces (Consumes):**
- `GET /api/mobile/realtime-token` → 200 `{"enabled": true, "token", "ttl_seconds", "sse_url", "channels": ["station:<kod>", …]}`;
  503 `{"enabled": false, "reason": "realtime disabled" | "misconfigured"}`; 404 `unknown_station`; 401 bez tokena.
- Kanał `station:<kod>`, ładunek `{"kind": "station", "station": "<kod>"}` (appka **nie** czyta ładunku — sygnał to budzik).
- Klucze `prod_config`: `priorytety_tryb_<S>` (`stary`|`stol`), `priorytety_min_app_version_code` (int, 0 = brak bramki),
  `priorytety_stol_<S>`, `priorytety_jednostka_<S>`, `priorytety_limit_odlozen_<S>` (spec 8.6) — appka ich nie czyta,
  kontrakt mówi, co od nich zależy.

- [x] **Step 1: „Test, który pada”** — nagłówki `## 8`–`## 12`; sprawdzacz → `SEKCJA BEZ ODNOSNIKA` ×5.
- [x] **Step 2: Sekcja 8 Realtime.** Pełne przykłady 200 (tablet Krawędzi: dwa kanały) i 503. Połączenie SSE krok po
  kroku wg klienta agenta druku (odnośniki do `print_agent.py`): POST JSON `{"token": …}` na `sse_url`, `Accept:
  text/event-stream`; ramki: ping (pusty albo `{}`), `connect`, sygnał (każda inna ramka danych); ping co 25 s, połączenie
  martwe po 40 s ciszy; token przy **każdym** połączeniu świeży (TTL z `ttl_seconds`, zerwanie raz na TTL to rutyna);
  ponowienia wg drabinki 1–60 s z jitterem ±10 % (wiele tabletów po restarcie brokera). Tabela „zdarzenie → kanał →
  co robi tablet” (spec 5.4 + tabela K3 Task 4, każde z odnośnikiem do miejsca publikacji). Sygnał idzie po commicie,
  nie idzie przy 409/rollbacku/powtórce idempotentnej (testy z Review Focus 4) — appka nie może zakładać, że każda
  zmiana da sygnał.
- [x] **Step 3: Sekcja 9 Odpytywanie i pobieranie stołu.** Reguły: `GET desk` przy wejściu na ekran, po własnym
  ZAKOŃCZ/Odłóż (także po synchronizacji kolejki offline), po sygnale (łączenie: Doprecyzowania p. 5), co 30 s przy
  pustym stole, co 5 min przy pełnym — **zawsze, także przy działającym SSE** (siatka na zgubiony sygnał, spec 5.4);
  przy 503 z `realtime-token` tylko odpytywanie i ponowna próba tokena co 5 min. `refresh_interval_seconds` z `/summary`
  dotyczy starej listy — nowa appka go nie używa do stołu (spec 6.3). 500 `desk_failed` → następna próba wg siatki.
- [x] **Step 4: Sekcja 10 Kolejka offline.** Wzór tabeli z `api-mobile-krawedzie-lakiernia.md` §8 („kod | znaczenie |
  co robić”), wiersze: 409 `nie_na_stole` (ZAKOŃCZ, licznik, Odłóż — reguła Doprecyzowań p. 1–2), 409 `limit_odlozen`,
  409 `delivery_method_not_set` (bez zmian: zostaje w kolejce), 400 `powod_niepoprawny`/`dane_niepoprawne` (błąd appki:
  porzucić i zalogować — sprawdź w kodzie, czy 400 jest w `BLEDY_DO_PONOWIENIA`; jest → serwer nie zapamięta, appka
  i tak nie ponawia), 500 `desk_failed`, 503 realtime, 426, 401. `X-Operation-Id`: nowy na akcję, **ten sam** przy każdym
  ponowieniu (`with_idempotency`, odnośniki); retencja wpisów idempotencji wg Doprecyzowań p. 10 (`cleanup_old_operations`
  domyślnie 7 dni, ale tylko przez komendę `flask cleanup-mobile-operations`, `app.py:394-402`) — akcja dosłana po
  ponad 7 dniach może wykonać się drugi raz. Wiersze istniejących kodów ZAKOŃCZ, które appka może spotkać z kolejki:
  400 `invalid_station`, 500 `complete_failed` (`mobile_api.py:476-486`) — bez zmian, z odnośnikiem.
- [x] **Step 5: Sekcja 11 Bramka wersji i tryb `stary`.** Dwa progi w tabeli: `X-App-Version` + `API_MOBILE.min_supported_app_version`
  → 426 dla każdej końcówki z tokenem, także `GET /app/apk` (odnośniki; ostrzeżenie z `api-mobile-krawedzie-lakiernia.md`
  §9 p. 2); `priorytety_min_app_version_code` vs `last_app_version_code` z heartbeatu → tylko wyłączenie bramki stołu
  dla starej appki (`stara_appka`). Tryb `stary`: `desk`/`postpone` działają (spec 6.3), ZAKOŃCZ bez bramki; tryb
  `stol`: bramka dla nowej appki. Heartbeat zaraz po starcie (Doprecyzowania p. 4). Appka **nie zna trybu** stanowiska
  i nie musi — zachowuje się tak samo w obu (sprawdź, czy `desk` w kodzie oddaje `tryb`; jeśli tak, opisz pole).
- [x] **Step 6: Sekcja 12 Kompatybilność.** Nowa appka na backendzie bez `/desk` (Doprecyzowania p. 3), stara appka na
  nowym backendzie (lista, `priorytet` ignorowany, bramka nie dotyczy jej do progu), mieszana flota na jednym stanowisku
  w P3 (ZAKOŃCZ starej appki zdejmuje kafel ze stołu, spec 5.5), wycofanie P3 (`priorytety_tryb_<S>` → `stary` w
  Konfiguracji, nowa appka dalej działa — spec 11), zmiana trybu w Konfiguracji może dojść z opóźnieniem pamięci
  podręcznej ustawień — **sprawdź w kodzie**: jeśli `ustawienia.tryb/min_app_version` czytają przez
  `config_service.get_config` (pamięć podręczna procesu, 60 min — `config_service.py:47-54`, singleton
  `get_config_service` `:1063-1078`) bez unieważnienia na innych workerach gunicorna, kontrakt mówi to z odnośnikiem
  i opisuje skutek dla appki (do 60 min część żądań z bramką, część bez); naprawa poza zakresem (raport K2/K5).
- [x] **Step 7:** sprawdzacz → `bledow 0`. **Step 8: Commit** `docs(priorytety): kontrakt appki - realtime, odpytywanie, kolejka offline, wersje`

---

### Task 4: Ekrany, kryteria odbioru, „czego nie rozstrzyga” (sekcje 13–15) i weryfikacja całości

**Files:**
- Modify: `docs/api-mobile-priorytety.md`
- Scratchpad: `odpowiedzi/*.json` (tylko sesja lokalna)

**Stan obecny:** spec 6.4 p. 1–6 (zakres ekranów), 5.6 (Niekompletne), 2 p. 5–8. Appka dziś: pojedyncze pozycje na
większości stanowisk, całe zamówienia na Formatowaniu i Pakowaniu (spec 1.1), lista całej kolejki odświeżana co 30 s.
Kodu appki w tym repo nie ma — sekcja 13 opisuje zmiany od strony kontraktu, nie klasy Kotlina.

- [x] **Step 1: Sekcja 13 Ekrany** (spec 6.4, każdy punkt z odesłaniem do sekcji 4–12): ekran stanowiska = sekcje
  **„Teraz”** (stół; nazwa robocza z karty centrali, ostateczny tekst do akceptacji Konrada przy odbiorze), **„Odłożone”**
  (powód, godzina, pracownik; ZAKOŃCZ dostępny), **„Niekompletne”** (tylko Formatowanie i Pakowanie; postęp
  „3/5 na stanowisku, 2 na Sklejaniu” z `na_stanowisku`, `pozycji`, `brakuje[].stanowisko` — nazwy stanowisk z buildu,
  bo API ich nie wystawia, `api-mobile-krawedzie-lakiernia.md` §7); nagłówek „w kolejce: N” (`kolejka_dalej`); bez listy
  kolejki. Kafel: dotychczasowa karta + gwiazdki + plakietka szczebla + „poz. i/n”; przyciski **Odłóż** (lewy) i
  **ZAKOŃCZ** (prawy); licznik sztuk jak dotąd. Modal Odłóż (5 powodów, notatka przy „Inne”, `message` z 409 jako
  komunikat). Tablet Krawędzi: stół Krawędzi i lista Lakierni. **Lakiernia** (Decyzje p. 10): ekran = lista pozycji
  w kolejności serwera z separatorami grup z `grupa_wykonczenia`, ZAKOŃCZ i licznik jak dziś, bez Odłóż, bez stołu,
  bez „w kolejce”; ewentualne ręczne sortowanie pracownika tylko jako opcja, domyślnie kolejność serwera. Pakowanie: kafel bez sposobu dostawy na stół nie wchodzi; 409
  `delivery_method_not_set` zostaje (bez zmian).
- [x] **Step 2: Sekcja 14 Kryteria odbioru z tabletem** — numerowana checklista (≥ 14 punktów), każdy z warunkiem
  mierzalnym i sekcją kontraktu. Co najmniej: (1) dwa tablety Sklejania na podglądzie pokazują ten sam stół;
  (2) ZAKOŃCZ na A → B widzi zmianę ≤ 5 s przy realtime; (3) to samo przy `REALTIME.enabled=false` → ≤ 5 min przy
  pełnym stole, ≤ 30 s przy pustym; (4) ZAKOŃCZ na Sklejaniu → stół Formatowania dopełnia się po sygnale; (5) Odłóż
  z każdym powodem, „Inne” bez notatki zablokowane w UI; (6) przy limicie komunikat z `message`, kafel zostaje na stole;
  (7) odłożony widoczny i zamykany ZAKOŃCZ; (8) Formatowanie: zamówienie niekompletne w „Niekompletne” z postępem,
  ZAKOŃCZ jego pozycji przechodzi (Review Focus 1), po dojściu ostatniej pozycji wchodzi na stół; (9) ZAKOŃCZ offline
  → po powrocie sieci zsynchronizowany z tym samym `X-Operation-Id`, stół odświeżony; (10) 409 `nie_na_stole` z kolejki
  (kafel zamknął drugi tablet) → wpis porzucony z komunikatem, bez pętli; (11) Odłóż offline niedostępny;
  (12) zerwanie SSE (restart brokera / wygaśnięcie tokena) → ponowne połączenie wg drabinki, bez utraty sygnałów dłużej
  niż siatka; (13) tablet Krawędzi: stół Krawędzi, lista Lakierni i oba kanały; (14) heartbeat po starcie → panel pokazuje nowy
  `version_code`; (15) stara appka na tym samym stanowisku w trybie `stary` i w `stol` z progiem > jej wersji działa
  jak dziś; (16) nowa appka z backendem bez `/desk` (np. podgląd ze starym kodem) wraca do listy; (17) doróbka pojawia
  się na stole ponad K; (18) dwa tablety pokazują kafle w tej samej kolejności co odpowiedź `desk` (appka nie sortuje),
  a po sygnale `GET desk` idzie do serwera mimo pamięci podręcznej OkHttp (log serwera albo proxy); (19) Lakiernia:
  lista w kolejności odpowiedzi `/stations/painting/orders` (grupy wykończenia w jednym ciągu, separatory z
  `grupa_wykonczenia`), ZAKOŃCZ bez bramki przy `priorytety_tryb_painting = stol` na podglądzie, brak przycisku Odłóż
  i zero wywołań `/stations/painting/desk` w logu serwera.
- [x] **Step 3: Sekcja 15 Czego ten dokument nie rozstrzyga** (wzór §10 krawędzi): układ graficzny i animacje kafli,
  Room/kolejka offline wewnątrz appki, nazwy stanowisk w buildzie, kolejność czynności przy przełączaniu stanowisk
  (K7), raport odłożeń (spec 14), monitory hali (nie są częścią kontraktu — K4b).
- [x] **Step 4: Przegląd treści** — przeczytaj cały kontrakt od góry: każde twierdzenie o serwerze ma odnośnik; żadnych
  danych klientów (grep po nazwach miast i nazwiskach z raportów K3/K5, po `@`, po wzorcach telefonu `\d{3}[ -]?\d{3}[ -]?\d{3}`);
  brak sekretów (`grep -niE "api_key|hmac|secret|password|token\": \"eyJ[^…]"`) — każde trafienie przejrzane: dopuszczalne
  tylko nazwy pól/funkcji z kodu (np. `_hmac_secret` w odnośniku), nigdy wartość; lista trafień do raportu.
- [x] **Step 5 (tylko sesja lokalna z podglądem wskazanym przez centralę; w cloud pomiń i zapisz w raporcie):** żywe
  odpowiedzi. Na podglądzie: Sklejanie w tryb `stol` (`PUT /production/api/priorytety/ustawienia` z K2 albo Konfiguracja),
  `POST /api/mobile/register` dwóch urządzeń `gluing` (identyfikatory `TEST-K6-1`, `TEST-K6-2`), `GET /stations/gluing/desk`
  ×2, `POST …/postpone` (200, potem do limitu → 409), `POST …/complete` kafla spoza stołu (409 `nie_na_stole`),
  `GET /realtime-token` (200 albo 503), `GET /stations/formatting/desk` (jednostka `zamowienie`). Odpowiedzi do
  `<scratchpad>/odpowiedzi/`, porównaj z przykładami w sekcjach 4–8; różnice → popraw kontrakt (kod ma rację) i wpisz do
  raportu. Przykłady w kontrakcie dalej z danymi fikcyjnymi. Po wszystkim usuń urządzenia testowe z podglądu (panel
  urządzeń) i przywróć tryb `stary`.
- [x] **Step 6:** sprawdzacz na całym pliku → `bledow 0`; liczba odnośników i sekcji do raportu.
- [x] **Step 7: Commit** `docs(priorytety): kontrakt appki - ekrany, kryteria odbioru, weryfikacja odnosnikow`

---

### Task 5: Karta dla sesji appki (`docs/superpowers/plans/2026-10-05-priorytety-karta-appki.md`)

**Files:**
- Create: `docs/superpowers/plans/2026-10-05-priorytety-karta-appki.md` (`git add -f`)

**Stan obecny:** wzory kart: podręcznik centrali 8.0 (szablon), 8.7 (dodatki K6); zakres appki: spec 6.4; precedensy
z logistyki: spec etapu 4 sekcja 12 (`docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md:1185`
— m.in. „Room: nowe tabele/kolumny z migracją, bez `fallbackToDestructiveMigration`”), plan etapu 1 (repo appki
`C:\Users\Grafik\Documents\woodpower_prod_app`, Kotlin, `docs/superpowers/plans/2026-09-24-logistyka-etap-1-sposob-dostawy.md:44`).

**Interfaces (Produces — na tym polega K7 część 2):**
- Raport sesji appki z polami: `version_code` i `version_name` APK (→ `priorytety_min_app_version_code` w K7, PRZED
  przełączeniem pierwszego stanowiska na `stol`), hash commita appki, wynik checklisty z sekcji 14 kontraktu punkt po
  punkcie, lista odstępstw od kontraktu, pytania do Konrada.

- [x] **Step 1: „Test, który pada”** — lista kontrolna karty (w scratchpadzie): nagłówek z typem sesji, modelem
  i effortem; źródło = kontrakt pod hashem; zakaz czytania kodu CRM; lista zmian (Teraz/Odłożone/Niekompletne, Odłóż
  z modalem, SSE + odpytywanie, `X-Operation-Id`, obsługa 409, heartbeat, fallback bez `/desk`, Krawędzie: stół + lista
  Lakierni); zasady;
  STOP; kryteria odbioru; raport; podgląd zamiast produkcji. Pusty plik → 0/12.
- [x] **Step 2: Karta** — jeden blok ```markdown do wklejenia, nad nim linia dla Konrada: „**sesja lokalna w repo
  `woodpower_prod_app`, tablet po USB, Fable 5.1, effort extra** — kolejka offline, idempotencja i SSE to logika, której
  testy appki nie złapią”. Treść bloku:
  ```
  # Karta: appka tabletów — stół stanowiska, Odłóż, sygnały (program „Priorytety produkcji”)
  Sesja: lokalna, repo woodpower_prod_app, tablet po USB. Model: Fable 5.1. Effort: extra. Bez trybu szybkiego.
  ## Źródło — JEDYNE
  Kontrakt: docs/api-mobile-priorytety.md z repo kkmiecik-coder/CRM pod hashem <HASH> (Konrad kopiuje go do repo
  appki jako docs/kontrakt-api-priorytety.md albo podaje plik). Pracujesz WYŁĄCZNIE z kontraktu. Nie czytasz kodu CRM,
  nie zgadujesz zachowania serwera. Niejasność albo serwer na podglądzie robi co innego niż kontrakt → STOP, pytanie
  do Konrada (centrala odpowie albo zleci poprawkę kontraktu). Nie „naprawiasz” serwera po stronie appki.
  ## Start
  1. git status czysty; gałąź robocza appki (np. claude/priorytety-stol), nigdy gałąź wydań.
  2. Przeczytaj kontrakt w całości. Spisz, jak appka dziś robi: ekran stanowiska, kolejkę offline (Room, X-Operation-Id,
     reakcja na 4xx), heartbeat (kiedy pierwszy), odświeżanie listy, ETag. To jest „stan przed” do raportu.
  3. Napisz krótki plan w repo appki (Task po Tasku, testy najpierw) i pokaż Konradowi przed kodowaniem.
  ## Zmiany (każda z sekcją kontraktu)
  1. Ekran stanowiska: „Teraz” (stół), „Odłożone”, „Niekompletne” (Formatowanie, Pakowanie), nagłówek „w kolejce: N”;
     bez listy kolejki; kafle w kolejności z odpowiedzi serwera — appka nie sortuje ani nie grupuje (§4, §13).
  2. Kafel: gwiazdki, plakietka szczebla, „poz. i/n”; Odłóż (lewy), ZAKOŃCZ (prawy), licznik sztuk jak dotąd (§7, §13).
  3. Modal Odłóż: 5 powodów, notatka wymagana przy „Inne” (≤ 255), tylko online; 409 → `message` (§5, §10).
  4. SSE: token z /realtime-token przy każdym połączeniu, drabinka ponowień, ping 40 s; sygnał = GET desk;
     łączenie sygnałów; 503 → samo odpytywanie (§8, §9).
  5. Odpytywanie awaryjne: 30 s przy pustym stole, 5 min przy pełnym, ZAWSZE; GET desk po własnym ZAKOŃCZ/Odłóż (§9).
     GET desk z If-None-Match i bez serwowania z pamięci podręcznej OkHttp (Cache-Control: max-age=0, §4).
  6. X-Operation-Id: nowy na akcję, ten sam przy ponowieniu; tabela kodów z §10 (porzucić / zostawić / pokazać).
  7. 409: nie_na_stole, limit_odlozen, delivery_method_not_set — wg §6 i §10.
  8. Heartbeat zaraz po starcie i po aktualizacji (§11). Fallback do listy, gdy GET desk → 404 bez JSON (§12).
  9. Tablet Krawędzi: stół Krawędzi, lista Lakierni i dwa kanały (§8, §13). Room: migracja bez fallbackToDestructiveMigration.
  10. Lakiernia bez stołu: lista w kolejności serwera, separatory z `grupa_wykonczenia`, bez Odłóż, nie woła `desk`
      (§13; 409 `stanowisko_bez_stolu` w §10).
  ## Zasady
  - Tylko podgląd wskazany przez Konrada (dotąd appka: port 5005). Nigdy produkcja, nigdy rejestracja urządzenia na
    produkcji. Kolejka offline: zero utraty akcji — testy jednostkowe porzucania i ponawiania dla każdego kodu z §10.
  - Testy appki przed implementacją; commity małe, po polsku; push wg Konrada.
  ## Koniec
  Odbiór z tabletem: checklista z §14 kontraktu punkt po punkcie (wynik, dowód: zrzut/log). Raport w repo appki
  (docs/raporty/<data>-priorytety-appka-raport.md albo katalog raportów appki) i pełna treść w odpowiedzi do Konrada:
  Zrobione, Testy (polecenia i wyniki), Checklista §14, Odstępstwa od kontraktu, Rozstrzygnięcia (numerowane),
  Pytania do Konrada, version_code i version_name APK, hash commita, Co K7 musi wiedzieć.
  ```
  Wstaw prawdziwy `HASH` i numery sekcji zgodne z kontraktem z Task 1–4.
- [x] **Step 3:** lista kontrolna z Step 1 → 12/12; każde `§N` w karcie istnieje w kontrakcie (`grep -n "^## N" docs/api-mobile-priorytety.md`).
- [x] **Step 4: Commit** `docs(priorytety): karta sesji appki - stol, Odloz, sygnaly`

---

### Task 6: Raport kroku

**Files:**
- Create: `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K6-raport.md` (`git add -f`)

- [x] **Step 1: Kontrola przed raportem:** `git diff --name-only <hash startu>..HEAD` → dokładnie dwa pliki (kontrakt,
  karta); `git log --oneline <hash startu>..HEAD` → 5 commitów, po jednym na Task 1–5; `main` nietknięty
  (`git log origin/main -1` bez zmian wobec startu). Po Step 3 to samo: trzy pliki, 6 commitów.
- [x] **Step 2: Raport** z sekcjami karty centrali: **Zrobione** (po Taskach, z hashami), **Testy** (krok bez pytest —
  wynik sprawdzacza: liczba odnośników, `bledow 0`, sekcje; lista kontrolna pól JSON z Task 2 Step 6; curl z podglądu
  albo „sesja cloud — przykłady z kodu”), **Odstępstwa od planu** (nazwy z kodu inne niż spec/plan K3), **Rozstrzygnięcia
  podjęte w trakcie** (numerowane; koszt, jeśli błędne — co najmniej Doprecyzowania 1–11), **Pytania do Konrada**,
  **Stan gałęzi** (hash, czy wypchnięte), **Co następny krok musi wiedzieć**:
  - **Konrad / sesja appki:** ścieżka karty i hash kontraktu; plik kontraktu do skopiowania do repo appki;
  - **K7:** `priorytety_min_app_version_code` = `version_code` z raportu sesji appki, ustawiony PRZED przełączeniem
    pierwszego stanowiska na `stol`; tablety muszą wysłać heartbeat z nową wersją; REALTIME i namespace `station` na
    produkcji sprawdzić przed przełączeniem (bez nich tablety działają na samym odpytywaniu);
  - **centrala:** Doprecyzowania 1–11 do naniesienia w specu (sekcje 6, 10, 12) kartą dokumentacyjną; odpowiedź
    Konrada o crontabie `flask cleanup-mobile-operations` (Pytania p. 4);
  - **K8:** `refresh_interval_seconds`, lista `/stations/<kod>/orders` i `/orders/since` zostają, dopóki jakikolwiek
    tablet ma starą appkę (sekcja 12 kontraktu).
- [x] **Step 3: Commit raportu i push** wg karty: `docs(priorytety): raport kroku K6 kontrakt appki`.

---

## Kryteria zakończenia (DoD)

1. `docs/api-mobile-priorytety.md` ma sekcje 0–15 w układzie z Task 1; sprawdzacz na hashu z nagłówka: `bledow 0`,
   każda sekcja `##` poza 14 i 15 ma ≥ 1 odnośnik; odnośniki pełną ścieżką, kotwica przy każdej funkcji i stałej.
2. Pełne przykłady JSON: `desk` ×2 (jednostka `pozycja` i `zamowienie` z `niekompletne`), `postpone` 200 + 409
   `limit_odlozen` + 409 `nie_na_stole` + 400 `powod_niepoprawny` + 400 `dane_niepoprawne`, ZAKOŃCZ 409 `nie_na_stole`,
   `realtime-token` 200 + 503, obiekt `priorytet`, pozycja listy Lakierni z `grupa_wykonczenia` i 409
   `stanowisko_bez_stolu`. Każde pole pokryte kodem albo testem (lista w raporcie).
3. Sekcje 9–12 zawierają: 30 s / 5 min, `GET desk` po własnej akcji, łączenie sygnałów, tabelę kodów kolejki offline
   z regułą porzucenia, `X-Operation-Id` przy ponowieniu, retencję wpisów idempotencji (Doprecyzowania p. 10), dwa progi wersji, heartbeat po starcie,
   zachowanie nowej appki bez `/desk` i starej appki z nowym backendem.
4. Review Focus 1 rozstrzygnięty w kodzie (przepuszczenie pozycji z „Niekompletne” z testem) — albo STOP z meldunkiem
   (wtedy krok nie jest zakończony, raport z opisem).
5. Karta appki: lista kontrolna 12/12, każde `§N` istnieje w kontrakcie, hash wstawiony, model i effort w nagłówku.
6. Zero zmian poza trzema plikami; zero danych klientów i sekretów (grep z Task 4 Step 4 — każde trafienie przejrzane,
   żadnej wartości sekretu; lista w raporcie).
7. Raport zacommitowany; 6 commitów na `claude/priorytety-produkcji`, `main` nietknięty.

## Poza zakresem

- Kod appki, jej plan i testy (repo `woodpower_prod_app`, osobna sesja z karty). Wydanie APK i instalacja na tabletach
  (Konrad, S-4).
- Jakiekolwiek zmiany w kodzie CRM, testach, migracjach, specu, CLAUDE.md — także drobne poprawki zauważone przy czytaniu
  (do raportu, centrala robi kartę naprawczą).
- Monitory hali, zakładka Stanowiska, panel biura (K4a/K4b). Weryfikacja i Dostawa (`/api/mobile/verification/*`,
  `/api/mobile/delivery/*`) i trakownia — bez zmian, jedno zdanie w sekcji 3.
- Przełączanie stanowisk na `stol` i ustawianie progu wersji na produkcji (K7). Zdjęcie `REFRESH_INTERVAL_SECONDS` (K8).

## Ryzyka i co robić przy blokadzie

| # | Ryzyko | Skutek | Co robić |
|---|---|---|---|
| R1 | `stol.bramka_zakoncz` w kodzie (K3) nie przepuszcza ZAKOŃCZ/licznika pozycji zamówienia z „Niekompletne”, choć plan K3 (Doprecyzowania p. 12, test `test_bramka_przepuszcza_pozycje_niekompletnego_zamowienia`), spec 5.6 p. 2 i P-9 tego wymagają | po przełączeniu Formatowania na `stol` pracownik nie zamknie pozycji, która już przyszła; Formatowanie stoi | **STOP** przed Task 2: meldunek do centrali (karta K3-poprawka: bramka przepuszcza pozycję w statusie stanowiska, gdy jej zamówienie jest w `niekompletne` tego stanowiska, + test). Kontraktu nie pisze się „na obietnicę” |
| R2 | Brak końcówki albo pola ze specu 6 w kodzie K3 (np. `realtime-token`, `niekompletne`, `priorytet`) | appka zbudowałaby się na nieistniejącym API | nazwa inna przy tej samej semantyce → kontrakt podaje nazwę z kodu, raport „Odstępstwa”; brak funkcji → STOP i meldunek |
| R3 | K5 nie zakończony | brak wyniku `zakoncz-zakoncz-ten-sam-kafel`, brak sekcji CLAUDE.md | pisz z dopiskiem „do potwierdzenia przez K5”, pytanie w raporcie; nie zgaduj wyniku wyścigu |
| R4 | Sesja cloud bez podglądu — przykłady JSON tylko z kodu | rozjazd w szczegółach (kolejność kluczy, `null` vs brak klucza) | najpierw curl-e z podglądu z raportu K5 (Task 5 K5; dane podmienione na fikcyjne), dopiero w ich braku przykłady składane z `serialize_order` i asercji testów K3, nagłówek przykładu „zbudowane z kodu pod `<HASH>`”; centrala może zlecić Task 4 Step 5 w sesji lokalnej przed wydaniem karty appki |
| R5 | Dane klientów w przykładach (podgląd bywa kopią produkcji, repo publiczne) | wyciek danych | tylko dane fikcyjne; grep z Task 4 Step 4; przy wątpliwości — STOP przed commitem |
| R6 | Linie przesuną się po kolejnej karcie naprawczej przed wydaniem APK | odnośniki w kontrakcie nieaktualne | hash w nagłówku przypina stan; centrala przy wydaniu karty appki porównuje HEAD z hashem — różnica w plikach z odnośnikami → karta dokumentacyjna „odśwież odnośniki” (ten sam sprawdzacz) |
| R7 | `ustawienia.tryb/min_app_version` przez pamięć podręczną procesu (`config_service`, 60 min) | przełączenie trybu dociera do tabletów z opóźnieniem, różnym na workerach | sprawdzić w kodzie pod `HASH` (Task 3 Step 6) i opisać w sekcji 12 z odnośnikiem, jeśli tak działa; nie naprawiać — raport K6 „Pytania”/K7 |
| R8 | Spór spec ↔ kod w czymkolwiek innym, czego kontrakt dotyczy | appka pracuje z niewłaściwą wersją prawdy | kontrakt opisuje kod (z odnośnikiem), raport wymienia rozbieżność; gdy rozbieżność zmienia zachowanie widoczne dla pracownika → STOP i meldunek (podręcznik 6) |

## Pytania do Konrada

Brak pytań blokujących start. Do potwierdzenia przy bramce K6 (plan przyjmuje rekomendacje):
1. Odłóż tylko online, a 409 `nie_na_stole`/`limit_odlozen` z kolejki porzucają wpis z komunikatem (Doprecyzowania p. 1–2)
   — rekomendacja: tak; inaczej wpis krąży bez końca, bo oba kody są „do ponowienia”.
2. Nazwa sekcji stołu na tablecie: „Teraz” (robocza) — do akceptacji przy odbiorze appki.
3. Czy centrala ma zlecić żywe odpowiedzi z podglądu (Task 4 Step 5) przed wydaniem karty appki, jeśli K6 idzie w cloud
   — rekomendacja: tak, krótka sesja lokalna tylko na ten krok.
4. Czy `flask cleanup-mobile-operations` jest w crontabie produkcji (i z jakim `--days`) — od tego zależy, po ilu dniach
   akcja z kolejki offline może wykonać się drugi raz (Doprecyzowania p. 10). Rekomendacja: kontrakt zakłada „≥ 7 dni”,
   appka nie dosyła starszych wpisów bez potwierdzenia człowieka; dopisanie crona — osobna karta, poza programem.
