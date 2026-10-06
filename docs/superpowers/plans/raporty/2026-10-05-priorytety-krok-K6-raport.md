# Raport kroku K6 „Kontrakt API mobilnego dla appki i karta sesji appki” — program „Priorytety produkcji”

- **Plan:** `docs/superpowers/plans/2026-10-05-priorytety-krok-K6-kontrakt-appki.md` — Taski 1–5 odhaczone (`- [x]`),
  Task 6 = ten raport.
- **Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` (wersja po bramce K3 i poprawkach
  centrali z 5.10 — 6.1/6.3 o polu `tryb`). Nad specem i planem — kod.
- **Gałąź:** `claude/priorytety-produkcji`; praca w worktree `.claude/worktrees/priorytety-k6` na gałęzi lokalnej
  `claude/priorytety-k6`, push wyłącznie `HEAD:claude/priorytety-produkcji` (rebase przed każdym). Start: `4c0a2d3f`
  (nowszy niż `cfa60c16` z karty — commity K4a/K4b, dokumenty). `main` nietknięty (`31a0b014`).
- **Data:** 2026-10-05. **Sesja:** lokalna, Opus 5.5 (`claude-opus-5-5`), effort high — zgodnie z kartą.
- **Kod CRM:** zero zmian. Testów pytest krok nie uruchamia (krok bez kodu).

## Zrobione (po Taskach)

| Task | Commit | Co weszło |
|---|---|---|
| 1 | `9b17e526` | Kontrakt `docs/api-mobile-priorytety.md`: sekcja 0 (hash, „nie na `main`”, nazwa repo appki), 1 (pięć zdań), 2 (stan przed / po), 3 (26 tras: 3 nowe, 7 zmienionych, 16 bez zmian; trakownia, Weryfikacja, Dostawa bez zmian). |
| 2 | `cef1d7ba` | Sekcje 4–7: `desk` (kolejność sprawdzeń, dopełnianie, 1205/1213, ETag i `max-age=0`, tabela pól, kolejność bez sortowania, dwa pełne przykłady — Sklejanie i Formatowanie), `postpone` (body, powody z etykietami, kolejność sprawdzeń, 200 bez dopełnienia, wszystkie błędy z dosłownymi komunikatami, co zapamiętane), bramka ZAKOŃCZ i licznika (kolejność, co przechodzi, „Niekompletne”, Pakowanie dziś i po 4.6), pole `priorytet` (tabela szczebli i plakietek, gdzie występuje, KSZTALT 6). |
| 3 | `a19cc2d6` | Sekcje 8–12: realtime (token, SSE krok po kroku wg agenta druku, tabela zdarzeń → kanał z odnośnikami), siatka odpytywania i łączenie sygnałów, kolejka offline (tabela kodów, reguła 409 `nie_na_stole`, retencja), dwa progi wersji i heartbeat, kompatybilność. Do tego `DeliveryGate` z wiadomości centrali. |
| 4 | `65f79d86` | Sekcje 13–15 (ekrany, 25+2 kryteria odbioru, czego nie rozstrzyga); żywe odpowiedzi z podglądu wpięte w przykłady; nagłówek przeniesiony na `e65d2d3c` (K4-poprawka-1 w kodzie); stan docelowy **[K3-poprawka-2]** (pole `tryb`, `desk` w `stary` bez dopełniania), nowa appka na starym backendzie, wdrożenie 8.10 — wg wiadomości centrali. |
| 5 | `22c9a789` | Karta sesji appki `docs/superpowers/plans/2026-10-05-priorytety-karta-appki.md` (wspólna z logistyką 4.6). |
| przegląd | `42275bcf` | Poprawki po przeglądzie całości (sekcja „Przegląd końcowy”), akapit „Dwa tablety, ten sam kafel — do potwierdzenia przez K5”, **kontrakt przeniesiony na kod po scaleniu logistyki 4.6** (`4299267d`): odnośniki `mobile_api.py` od linii 849 przesunięte o −7, opis Pakowania przepisany. |
| przegląd (karta) | (ten commit) | Karta: hash kontraktu `42275bcf`, kod `4299267d`, środowisko odbioru = lokalny CRM Konrada (wiadomość centrali), reguły z przeglądu. |
| 6 | (ten commit) | Raport. |

## Testy

Krok bez kodu — „testami” są sprawdzacz odnośników, lista kontrolna pól, lista kontrolna karty i żywe odpowiedzi.

- **Sprawdzacz odnośników** (`sprawdz_odnosniki.py` w scratchpadzie sesji, poza repo; `git show <hash>:<ścieżka>`,
  zakres linii, kotwica w ±3 liniach, ≥ 1 odnośnik na sekcję `##` poza 14 i 15): RED na pustym pliku (`BRAK
  ODNOSNIKOW`, kod 1), RED po dodaniu pustych nagłówków (×4 w Tasku 2, ×5 w Tasku 3). Wynik końcowy na
  `4299267d` (hash z nagłówka; scalona logistyka 4.6) i na HEAD gałęzi: **328 odnośników, 16 sekcji, 0 błędów**; sprawdzacz wypisuje jawnie
  **10 akapitów [K3-poprawka-2]** (stan docelowy bez odnośników — na polecenie centrali).
- **Pola przykładów JSON** (Review Focus 2): przykład kafla-pozycji porównany skryptem z listą kluczy
  `serialize_order` — 49/49, ta sama kolejność; kafel-zamówienie 17 pól (14 `POLA_ZAMOWIENIA_KAFLA` + `order_id`,
  `deadline`, `priorytet`) = żywa odpowiedź; wszystkie bloki ```json parsują się. Lista kontrolna: desk
  (`mobile_api.py:493-502`, `test_desk_ksztalt_odpowiedzi_pozycja`), `stol[]`/`odlozone[]`/`niekompletne[]`
  (`mobile_api.py:480-492`, `test_desk_ksztalt_odpowiedzi_zamowienie`), `priorytet` (`stol.py:826-837`,
  `test_serialize_order_ma_priorytet_i_ksztalt_6`, `test_priorytet_szczebel_z_rangi_i_drabiny`), `transport`
  (`sposoby.py:123-128`), `postpone` 200 (`test_postpone_200_zwraca_stol_z_odlozonym`), `realtime-token` 200
  (`test_realtime_token_kanaly_stanowiska`), `grupa_wykonczenia` (`lista.py:46-49`,
  `test_serialize_order_grupa_wykonczenia`), 409 `stanowisko_bez_stolu` (`mobile_api.py:363-370`). Pól bez pokrycia: 0.
- **Karta appki:** lista kontrolna 12/12; każde `§N` w karcie istnieje w kontrakcie.
- **Żywe odpowiedzi (Task 4 Step 5)** — podgląd lokalny na porcie 5008, kontener `priorytety-k6`, baza `priorytety_podglad`;
  5 urządzeń testowych `TEST-K6-1…5` przez `POST /register` (podgląd). Sprawdzone na żywo: heartbeat 204 i 422;
  `desk` Sklejania ×2 (ten sam stół i ETag), 304 z `If-None-Match`, `desk` Formatowania (jednostka `zamowienie`,
  `niekompletne`, źródło `dorobka`), 409 `stanowisko_bez_stolu` (desk i postpone Lakierni), 403 `station_mismatch`,
  404 `unknown_station` (JSON), **404 HTML dla nieistniejącej trasy** (podstawa fallbacku), 401 `missing_token`,
  `realtime-token` 503 (`REALTIME` wyłączony na podglądzie — przykład 200 złożony z kodu i testu); po przełączeniu
  Sklejania na `stol` (limit 1): `postpone` 200 + powtórka idempotentna 200 (ta sama odpowiedź), 400
  `powod_niepoprawny` ×2, 400 `dane_niepoprawne` ×2, 409 `nie_na_stole` (już odłożony i spoza stołu), 404
  `order_not_found`, 409 `limit_odlozen`, ZAKOŃCZ i licznik spoza stołu 409 `nie_na_stole`, `desk` po Odłóż dołożył
  kafel; `orders` Lakierni z `grupa_wykonczenia`; `orders/<id>` i `since` z `priorytet`. Ustalone przy okazji: bramka
  pracowników włączona → bez `X-Worker-Ids` 400 `worker_ids_required`; pusty nagłówek → 422 `invalid_worker_ids`,
  **zapamiętany** pod `X-Operation-Id` (w kontrakcie). ZAKOŃCZ zakończonego sukcesem nie robiłem (zmieniłby dane
  produkcyjne kopii wspólnej z innymi sesjami) — pokrywa to test `test_zakoncz_odlozonego_200`.
  **Sprzątanie:** usunięte wiersze stołu (5), wpis logu (1), wpisy idempotencji `k6-*` (2), urządzenia `TEST-K6-*` (5);
  tryb i limit Sklejania przywrócone; zrzut stanu przed/po identyczny (stół pusty, 37 kluczy, log max 95, 46441
  wpisów idempotencji). Surowe odpowiedzi w scratchpadzie, nie w repo.
- **Grep danych i sekretów** (Task 4 Step 4) na kontrakcie: `@` — 1 trafienie (`@mobile_api_bp.route` w poleceniu
  grep); wzorzec telefonu — 0; `api_key|hmac|secret|password|token": "eyJ…` — 0 (token w przykładzie
  `"eyJ…(skrócony)"`); adresy IP — 0; nazwy, numery zamówień, trasy, pojazd i adres CDN z kopii produkcji — 0.
  `sse_url` w przykładzie = adres publiczny już obecny w repo (docstring `print_agent_api.py:280`).

## Odstępstwa od planu

1. **Plik planu w diffie kroku** — karta kazała odhaczać `- [x]`, więc commity Tasków zmieniają też plan (DoD p. 6
   mówił o trzech plikach). Pliki kroku: kontrakt, karta, raport + plan.
2. **Hash w nagłówku kontraktu** nie jest HEAD sprzed pierwszego commitu K6 (`4c0a2d3f`), tylko `4299267d`: w trakcie
   sesji na gałąź weszły K4-poprawka-1 (odmowa `stol` przy progu 0 — sekcja 11) i **scalenie logistyki 4.6**
   (`8f60b221` — `order_complete` bez 409 `delivery_method_not_set`). Karta centrali kazała opisać 4.6 jako „zmieni
   się po”; ponieważ scalenie weszło przed końcem kroku, a kontrakt służy wdrożeniu 8.10, opisuję kod po scaleniu
   (rozstrzygnięcie 21). Sprawdzacz uruchomiony na `4c0a2d3f`, `fa6c5c2a`, `e65d2d3c` i `4299267d` — za każdym razem
   0 błędów (po mechanicznym przesunięciu odnośników `mobile_api.py` o −7 od linii 849 i ręcznej kontroli wyrywkowej).
   Żywe odpowiedzi zebrane na kodzie `4c0a2d3f`; różnica w API mobilnym do `4299267d` to wyłącznie zniknięcie 409
   `delivery_method_not_set`.
3. **Zakres rozszerzony wiadomościami centrali** (w trakcie sesji, 4 wiadomości): `DeliveryGate` i zmiany Pakowania
   po logistyce 4.6 (sekcje 6, 13, 14 i karta), wdrożenie 8.10 o 10:30 z APK przed backendem (sekcja 12 —
   „nowa appka na starym backendzie”, kryteria 17, 18, 25), stan docelowy **[K3-poprawka-2]** (pole `tryb` w `desk`,
   `desk` w `stary` bez dopełniania — sekcje 4, 9, 11, 12, 13, 14, 18a/18b). Karta appki jest wspólna dla logistyki
   i priorytetów (decyzja Konrada przekazana przez centralę).
4. **Kryteriów odbioru 27** (1–25 + 18a, 18b) zamiast 19 z planu — dopisane z wiadomości centrali i z treści
   kontraktu (plakietki źródła, Lakiernia, stary backend).
5. **Sekcje oparte na K5** (wynik wyścigu `zakoncz-zakoncz-ten-sam-kafel`, czasy `desk` na produkcji, CLAUDE.md)
   — K5 się nie odbył; w sekcji 6 akapit „do potwierdzenia przez K5”, czasów `desk` z produkcji brak (kontrakt
   podaje tylko limit 5 s i zalecany limit czasu żądania ≥ 15 s).
6. **Nazwy z kodu inne niż w specu/planie K3:** `grupa_wykonczenia` ma 4 pola (`typ_koloru` — spec 6.3 wymieniał 3,
   poprawione już przez centralę); w odpowiedzi `realtime-token` pole `ttl_seconds` (agent druku: `expires_in`);
   `STANOWISKA_BEZ_STOLU` w `ustawienia.py`, nie w `stale.py` (jak raport K3). Pozostałe nazwy z planu = kod.

## Rozstrzygnięcia podjęte w trakcie (numerowane; koszt, jeśli błędne)

Doprecyzowania planu 1–11 przyjęte w kontrakcie; różnice zaznaczone.

1. **409 `nie_na_stole` z kolejki** (Dopr. 1) — reguła w sekcji 10; dodatkowo `GET /orders/<id>` → 404 porzuca wpis.
   — Koszt: wpis porzucony, choć kafel by wrócił — tylko gdy pozycja zmieniła status albo zniknęła, więc praktycznie żaden.
2. **Odłóż tylko online** (Dopr. 2, decyzja karty) — 409 `limit_odlozen`/`nie_na_stole` z kolejki porzucają wpis. — Koszt: brak Odłóż bez sieci.
3. **Fallback bez `/desk`** (Dopr. 3) — 404 bez JSON (sprawdzone na żywo: HTML) → lista; 404 JSON `unknown_station` → błąd konfiguracji. — Koszt: gdyby ktoś dodał JSON-owy handler 404, reguła wymaga rozróżnienia po polu `error`.
4. **Heartbeat po starcie** (Dopr. 4). — Koszt: jedno żądanie więcej przy starcie.
5. **Łączenie sygnałów** (Dopr. 5) — jedno `desk` w locie i jedno oczekujące. **Odstępstwo od Dopr. 6:** tablet
   z dwoma kanałami odświeża po KAŻDYM sygnale oba widoki (desk Krawędzi i listę Lakierni), bo kontrakt nie
   gwarantuje formatu ramki brokera (kanał w ramce). — Koszt: zbędne `desk`/`orders` (zwykle 304) na tablecie Krawędzi.
6. **Krawędzie i Lakiernia** (Dopr. 6) — kanały tabletu zarejestrowanego na Lakierni opisane z kodu
   (`["station:painting", "station:edges"]`), bez testu. — Koszt: żaden (appka nie zależy od kolejności kanałów).
7. **`GET desk` jest zapisem** (Dopr. 7) — w stanie docelowym tylko w `stol`. — Koszt: żaden.
8. **Format odnośników** (Dopr. 8): pełne ścieżki, kotwice przy funkcjach i stałych. — Koszt: dłuższy tekst.
9. **Kolejność i pamięć podręczna** (Dopr. 9) — appka nie sortuje; `desk` zawsze do serwera. — Koszt: żaden.
10. **Retencja wpisów idempotencji** (Dopr. 10) — „co najmniej 7 dni”, starsze wpisy tylko po potwierdzeniu człowieka. — Koszt: dodatkowe potwierdzenie po długim offline.
11. **`priorytet` wszędzie** (Dopr. 11) — sprawdzone: pojedyncza pozycja liczy go sama (`mobile_api_service.py:1236-1239`). — Koszt: żaden.
12. **Siatka: 30 s, gdy na stole mniej kafli niż `miejsca`** (nie tylko pusty), 5 min przy co najmniej `miejsca` —
    zalecenie raportu K3 (D4) zamiast dosłownego P-7 („pusty / pełny”); P-7 jest szczególnym przypadkiem. — Koszt:
    częstsze `desk` przy stole 1/2 (tanie, ETag).
13. **Przykłady JSON** — kształt i wartości sterujące z żywych odpowiedzi, dane klienta fikcyjne; klucze w kolejności
    z kodu z uwagą, że na drucie przychodzą alfabetycznie. — Koszt: żaden (appka i tak nie może zależeć od kolejności).
14. **200 `desk` bez pola `tryb`: build debug = `"stol"`, build release = `"stary"`** (poprawione po przeglądzie —
    pierwotnie „zawsze `stol`”, co przy wdrożeniu bez K3-poprawka-2 pokazałoby stół w trybie `stary`). — Koszt:
    wdrożenie bez K3-poprawka-2 zostawi tablety release na liście (bezpiecznie, ale stołów nie będzie).
15. **Stan docelowy [K3-poprawka-2] w kontrakcie bez odnośników**, oznaczony i wypisywany jawnie przez sprawdzacz (polecenie centrali). — Koszt: centrala musi uzupełnić odnośniki po bramce karty.
16. **Pozycja bez docięcia na kaflu Formatowania** (pytanie 2 raportu K3-poprawka-1): serializacja ma już
    `cut_to_size` i `status` → kontrakt każe wyróżnić („idzie prosto do pakowania”, bez przycisków); reguła =
    `product_in_route` dla Formatowania (`cut_to_size is True`). Nie wpisane do „Czego nie rozstrzyga”. — Koszt:
    gdyby reguła ścieżki Formatowania zależała kiedyś od czegoś więcej niż `cut_to_size`, appka by się rozjechała.
17. **Lakiernia — separator** przy zmianie dowolnego z 4 pól, tylko między pozycjami w `czeka_na_lakiernie`; etykieta
    jak w panelu (`nazwa_grupy_wykonczenia`). — Koszt: żaden.
18. **Etykiety powodów** wielką literą na tablecie (panel ma małą). — Koszt: tekst.
19. **Ekran po kodzie stanowiska dla Lakierni, po `tryb` dla reszty** (decyzja centrali przekazana w trakcie). — Koszt: żaden.
20. **Żywe ZAKOŃCZ z sukcesem pominięte** (dane wspólnej kopii). — Koszt: ścieżka 200 tylko z testów.
21. **Kontrakt opisuje kod po scaleniu logistyki 4.6** (`4299267d`), nie stan sprzed (odstępstwo od karty i od
    wiadomości centrali „zostaw stan obecny” — scalenie weszło w trakcie). Zostaje obsługa 409
    `delivery_method_not_set` dla backendu sprzed 4.6 (produkcja przed deployem). — Koszt: gdyby scalenie cofnięto,
    sekcja 6 wymaga powrotu do opisu sprzed.
22. **ZAKOŃCZ i licznik tylko dla pozycji w statusie stanowiska** — zasada dla appki (krytyczne znalezisko
    przeglądu), bo serwer jej nie pilnuje. — Koszt: żaden po stronie appki; po stronie serwera luka zostaje (Pytania p. 4).
23. **409 `nie_na_stole` z kolejki: ponowienie najwyżej raz na takt siatki**, nigdy po `desk` wywołanym przez samą
    regułę (pierwotna „raz na pobranie stołu” sama się napędzała). — Koszt: wpis czeka do 30 s dłużej.
24. **Kolejka offline decyduje po polu `error`**, nieznany `error` przy 4xx → zostaw; dopisane `worker_not_found`,
    `worker_inactive`, `missing_or_invalid_quantity_done`, `ip_not_allowed`. — Koszt: żaden.
25. **Po każdym połączeniu SSE jedno `GET desk`; lista Lakierni po sygnale z `Cache-Control: no-cache`** (lista ma
    `max-age=15`). — Koszt: jedno żądanie na połączenie.

## Przegląd końcowy

Świeży recenzent (osobny agent, Opus) na całym kontrakcie i karcie, z weryfikacją w kodzie. Wynik: 1 krytyczne,
5 ważnych, 7 drobnych. Review Focus 1, 2, 4, 5, 6 — OK; 3 (kolejka offline) i 7 (karta) — problemy, poprawione.

| # | Znalezisko | Poziom | Co zrobione |
|---|---|---|---|
| 1 | Kontrakt nie mówił, że ZAKOŃCZ/licznik tylko dla pozycji w statusie stanowiska; bramka przepuszcza każdą pozycję zamówienia z kafla na stole, `complete_task` nie sprawdza statusu (`models.py:668-701`) | krytyczne | zasada w sekcjach 6 i 13, kryterium 23a, karta (rozstrz. 22); luka serwera — Pytania p. 4 |
| 2 | Reguła 409 `nie_na_stole` mogła kręcić się w pętli (desk → ponowienie → 409) | ważne | ponowienie raz na takt siatki (rozstrz. 23) |
| 3 | Brak `worker_not_found` / `worker_inactive` w tabeli kolejki — ten sam status HTTP raz porzucić, raz zostawić | ważne | wiersze + reguła „po polu `error`” (rozstrz. 24) |
| 4 | „200 bez `tryb` = stół” groźne w release | ważne | debug vs release (rozstrz. 14) |
| 5 | Po scaleniu 4.6 stół Pakowania dalej odfiltrowuje zamówienia bez sposobu (`stol.py:495-503`) | ważne | kontrakt na kodzie po scaleniu, opis filtra i zadania CRM w sekcji 6; do centrali (Co następny krok) |
| 6 | Karta: nieaktualny hash kontraktu, sprzeczność „podgląd” vs lokalny CRM | ważne | hash `42275bcf`, jednolite „serwer CRM do odbioru” |
| 7–13 | `tryb` w wierszu „brak pól”, `max-age=15` listy po sygnale, `desk` po połączeniu SSE, „bez ładunku”, co nie przełącza ekranu, brakujące kody (403 `ip_not_allowed`, kody pracowników w Odłóż), adres produkcyjny w przykładzie `sse_url` | drobne | wszystkie naniesione |

## Pytania do Konrada

1. **`flask cleanup-mobile-operations` w crontabie produkcji?** (z jakim `--days`) — kontrakt zakłada „co najmniej
   7 dni”, appka nie dosyła starszych wpisów bez potwierdzenia; dopisanie crona — osobna karta, poza programem.
2. **Nazwa sekcji stołu „Teraz”** — robocza; do akceptacji przy odbiorze appki.
3. **Realtime na produkcji dla tabletów:** czy `REALTIME.enabled` i `REALTIME.sse_url` są ustawione w `core.json`
   produkcji (pusty `sse_url` → appka składa adres z adresu CRM) i czy nginx wystawia `/realtime/connection/uni_sse`
   dla tabletów z sieci hali — do sprawdzenia w K7 przed „Włącz stoły” (bez tego tablety działają na samej siatce).
4. **Bramka statusu po stronie serwera?** ZAKOŃCZ pozycji, która nie czeka na stanowisku, przeskakuje albo cofa
   stanowisko (`complete_task` nie sprawdza statusu; raport K3 „Poza zakresem” p. 8). Nowa appka tego nie wyśle
   (kontrakt, sekcja 6), ale stara appka, błąd appki albo kolejka offline mogą. Rekomendacja: krótka karta CRM
   (409 przy pozycji spoza statusu stanowiska, poza trybem `stary` dla starej appki) — decyzja centrali/Konrada.
5. **Wynik wyścigu `zakoncz-zakoncz-ten-sam-kafel`** — do potwierdzenia przez K5; szczególnie Formatowanie/Pakowanie,
   gdzie drugie ZAKOŃCZ tej samej pozycji przechodzi bramkę (raport K3, „Poza zakresem” p. 8: `complete_task` nie
   sprawdza statusu pozycji).

## Stan gałęzi

- Wypchnięte na `origin/claude/priorytety-produkcji` po każdym Tasku (rebase bez konfliktów; w międzyczasie weszły
  commity centrali, K4-poprawka-1 i logistyki). Ostatni commit kroku — ten raport (hash w odpowiedzi sesji).
- `main` nietknięty (`31a0b014`). Główny checkout i worktree `priorytety-produkcji` nietknięte.
- Kontener `priorytety-k6` (5008) zatrzymany i usunięty, pusty `config/core.json` z worktree skasowany (po raporcie).

## Co następny krok musi wiedzieć

- **Konrad / sesja appki:** karta `docs/superpowers/plans/2026-10-05-priorytety-karta-appki.md`; kontrakt do
  skopiowania do repo appki: `docs/api-mobile-priorytety.md` z commita `42275bcf` (odnośniki na kod `4299267d`).
  Odbiór przeciw lokalnemu serwerowi CRM Konrada, we wtorek 6.10 po południu (próba wdrożenia, harmonogram centrali, rozstrz. 21 dziennika).
- **Centrala:** (a) po bramce **K3-poprawka-2** uzupełnić odnośniki w 10 akapitach `[K3-poprawka-2]` i hash w sekcji 0
  (ten sam sprawdzacz — skrypt w raporcie poniżej); (b) **karta CRM przed 8.10: zdjęcie filtra „Pakowanie bez sposobu
  dostawy” w stole i w „Wyślij”** (`stol.py:495-503`, `:923`, `:1027`) — po scaleniu 4.6 ZAKOŃCZ przechodzi, ale w
  trybie `stol` takie zamówienie nie trafi na tablet Pakowania; potem aktualizacja akapitu w sekcji 6; (c) Doprecyzowania 1–11 planu K6 i rozstrzygnięcia 5, 12, 14 tego raportu do specu (sekcje 6, 10, 12);
  (d) przy wydaniu karty appki porównać HEAD z hashem kontraktu (R6 planu).
- **K7:** `priorytety_min_app_version_code` = `version_code` z raportu sesji appki, ustawiany przy „Włącz stoły”
  (panel odmawia `stol` przy progu 0 — K4-poprawka-1); tablety muszą wysłać heartbeat z nową wersją (appka robi to
  zaraz po starcie); REALTIME i namespace `station` na produkcji sprawdzić przed przełączeniem; APK trafia na tablety
  przed deployem — nowa appka pracuje do 10:30 na starym backendzie (sekcja 12).
- **K5:** wynik `zakoncz-zakoncz-ten-sam-kafel` wpisać do sekcji 6 kontraktu (akapit „do potwierdzenia przez K5”).
- **K8:** lista `/stations/<S>/orders`, `/orders/since` i `refresh_interval_seconds` zostają, dopóki jakikolwiek tablet
  ma starą appkę — a nowa appka używa listy dla Lakierni, w trybie `stary` i na starym backendzie (sekcja 12).

### Sprawdzacz odnośników (do ponownego użycia, poza repo)

Uruchamiać z katalogu repo: `python sprawdz_odnosniki.py <hash> docs/api-mobile-priorytety.md`. Szkic w planie K6
(Task 1 Step 2) plus: ścieżki `docs/` w wyrażeniu, akapity z `[K3-poprawka-2]` wypisywane jako „POMINIETE”, na
Windows `PYTHONIOENCODING=utf-8`.

## Poza zakresem (zauważone, nie ruszane)

1. Pusty `X-Worker-Ids` → 422 `invalid_worker_ids` jest zapamiętywane pod `X-Operation-Id` (422 nie jest „do
   ponowienia”) — zachowanie sprzed priorytetów, w kontrakcie opisane jako ostateczne.
2. `REALTIME.sse_url` może być pusty (`realtime_service.py:81-84`) — tablet musi wtedy składać adres sam; dla
   tabletów lepiej ustawić go w konfiguracji produkcji (pytanie 3).
3. Docstring heartbeatu mówi „co 15 min” — nowa appka wysyła też zaraz po starcie (bez zmiany serwera).
4. Alert `realtime_service` „wydruki spadły na polling” dotyczy też sygnałów stanowisk (znane z raportu K3).
