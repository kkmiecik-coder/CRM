# Priorytety produkcji — podręcznik centrali i karty kroków

- **Data:** 2026-10-05
- **Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` (wersja 2, decyzje Konrada 4–5.10)
- **Symulacja na produkcji:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-symulacja.md` (sekcje „Analiza wyniku” i „E”)
- **Plany kroków:** `docs/superpowers/plans/2026-10-05-priorytety-krok-K*.md` (lista w sekcji 3)
- **Raporty kroków i dziennik centrali:** `docs/superpowers/plans/raporty/`
- Repo jest publiczne — żadnych sekretów, adresów IP ani uwag bezpieczeństwa w plikach.

## 1. Jak to działa

Trzy role, trzy rodzaje sesji:

| Rola | Kto | Co robi |
|---|---|---|
| **Konrad** | człowiek | uruchamia sesje z kart, podejmuje decyzje z list „Pytania do Konrada”, scala do `main`, wydaje appkę |
| **Centrala** | jedna długa sesja Claude (sekcja 9: prompt startowy) | pilnuje kolejności kroków, przed każdym krokiem sprawdza warunki i wydaje kartę, po kroku czyta raport, przechodzi bramkę, prowadzi dziennik, zbiera pytania do Konrada, zakłada karty naprawcze |
| **Sesja kroku** | osobna sesja Claude na kartę (lokalna albo cloud) | wykonuje JEDEN plan z `docs/superpowers/plans/`, commituje na gałąź roboczą, pisze raport kroku, kończy |

Centrala **nie koduje** i **nie wykonuje planów sama**. Jej produktem są karty, bramki i dziennik. Sesja kroku **nie wychodzi poza plan** — usterki spoza zakresu zgłasza w raporcie, centrala robi z nich kartę naprawczą.

## 2. Zasady wspólne (kopiowane do każdej karty)

1. **Gałąź robocza:** `claude/priorytety-produkcji`. Zakłada ją K1 z `origin/claude/logistyka-etap-4` (tam leżą spec,
   symulacja i plany). Każda kolejna sesja zaczyna od `git fetch origin && git checkout claude/priorytety-produkcji &&
   git pull --ff-only`. **Nigdy `main`** (push do `main` = deploy na produkcję). Scalenie do `main` wyłącznie na polecenie
   Konrada, w kroku K7.
2. **Zależność od logistyki:** priorytety opierają się na trasach z etapu 3 i statusach z etapu 4 logistyki. Gałąź
   `claude/logistyka-etap-4` nie jest jeszcze na produkcji. Jeśli w trakcie programu zmieni się `origin/claude/logistyka-etap-4`
   albo `origin/main`, centrala przed wydaniem następnej karty zleca scalenie tych zmian do gałęzi roboczej (osobna
   karta naprawcza „merge + testy”), nigdy odwrotnie.
3. **Commity:** Conventional Commits po polsku, temat bez polskich znaków, jeden commit na Task planu; stopka
   z atrybucją własnej sesji. Pliki w `docs/superpowers/` dodaje się przez `git add -f` (katalog jest w `.gitignore`).
4. **Push:** sesja pushuje na gałąź roboczą, jeśli ma dostęp do zdalnego; jeśli nie, zostawia commity lokalnie i pisze
   to w raporcie — Konrad pushuje (`git push origin claude/priorytety-produkcji`).
5. **Testy:** `docker compose exec app pytest <ścieżki> -q -p no:cacheprovider` (lokalnie); pełny pakiet w K5. Sesja
   cloud bez Dockera nie uruchamia testów — dlatego kroki z kodem są lokalne (sekcja 4).
6. **Zakres:** sesja wykonuje plan Task po Tasku, zaznacza `- [x]`, nie poprawia „przy okazji” niczego spoza planu. Przy
   blokadzie: STOP, opis w raporcie, bez obejść.
7. **Raport kroku** (ostatni Task każdego planu): `docs/superpowers/plans/raporty/2026-MM-DD-priorytety-krok-<ID>-raport.md`
   z sekcjami: Zrobione (po Taskach), Testy (polecenia i wyniki), Odstępstwa od planu, Rozstrzygnięcia podjęte w trakcie
   (numerowane; koszt, jeśli błędne), Pytania do Konrada, Stan gałęzi (hash, czy wypchnięte), Co następny krok musi
   wiedzieć. Bez raportu krok nie jest zakończony.
8. **Python 3.9**, komentarze po polsku, w UI „Base.”, reguły blokad z CLAUDE.md i spec 9.4, migracje idempotentne,
   żadnych blokad przy HTTP do Base., żadnych `db.session.commit()` w handlerach API mobilnego pod `with_idempotency`.
   Jedyny wyjątek, celowy i opisany w planie K3: `GET /api/mobile/stations/<kod>/desk` nie jest pod `with_idempotency`
   i commituje sam (commit → blokada stanowiska → dopełnienie → commit), bo dopełnienie stołu musi zacząć transakcję
   od nowa (spec 5.2).
9. **Podglądy i porty:** sesja lokalna używa podglądów wg wskazań centrali (Konrad podaje porty/katalogi przy starcie
   programu, sekcja 7); nie rusza podglądów innych sesji; **nigdy** nie uruchamia kodu gałęzi na bazie produkcyjnej
   (import `create_app()` odpala migracje).

## 3. Mapa kroków

| Krok | Plan | Cel | Sesja | Model / effort | Zależy od | Orientacyjnie |
|---|---|---|---|---|---|---|
| **K1** | `…-krok-K1-fundament-rangi.md` | migracja całego P1, pakiet `priorytety`, nowy algorytm rangi (`policz`/`utrwal`), drabina i szczeble tras, gwiazdki (serwis), terminy robocze/kalendarzowe, przepięcia (sync, doróbka, trasy, cron), warstwa zgodności `priority_service` | **lokalna** | **Fable 5.1 / extra** | — | 1 sesja (duża) |
| **K2** | `…-krok-K2-panel-api.md` | blueprint `/production/api/priorytety`: drabina, gwiazdki, kolejka, ustawienia, przelicz; usunięcie martwych końcówek | **lokalna** | Opus 5.5 / high | K1 | 1 sesja |
| **K3** | `…-krok-K3-stol-odloz-sygnaly.md` | stół stanowiska, Odłóż, bramka ZAKOŃCZ, sygnały Centrifugo, końcówki mobilne `desk`/`postpone`/`realtime-token`, `priorytet` w serializerze | **lokalna** | **Fable 5.1 / extra** | K1 (K2 zalecane) | 1 sesja (duża) |
| **K4a** | `…-krok-K4a-lista-produkcyjna.md` | zakładka „Lista produkcyjna”, modal priorytetu, modal drabiny, gwiazdki 0–5 w Produktach i Logistyce, usunięcie przeciągania | **lokalna** | Opus 5.5 / high | K2, K3 | 1 sesja |
| **K4b** | `…-krok-K4b-czytelnicy-rangi.md` | Stanowiska, dashboard, Konfiguracja (Terminy, Stół stanowisk), monitory hali | **lokalna** | Opus 5.5 / high | K3 (równolegle z K4a) | 1 sesja |
| **K5** | `…-krok-K5-przeglad-p1.md` | pełne testy, migracja ×2 i na kopii produkcji, wyścigi MySQL, oględziny, CLAUDE.md, doprecyzowania do specu, werdykt „P1 gotowe” | **lokalna** | **Fable 5.1 / extra** | K1–K4b | 1 sesja |
| **K6** | `…-krok-K6-kontrakt-appki.md` | `docs/api-mobile-priorytety.md` z odnośnikami do kodu + karta dla sesji appki (repo `woodpower_prod_app`) | **cloud dopuszczalna** | Opus 5.5 / high | K3 (po K5 najlepiej) | 1 sesja |
| **K7** | `…-krok-K7-wdrozenie-i-przelaczenie.md` | runbook: scalenie do `main` (po logistyce), deploy, ręczny cron, weryfikacja; P3: wersja appki, przełączanie stanowisk na `stol`, pomiar skryptem symulacji | **lokalna z ssh**, prowadzona przez centralę i Konrada | model centrali (Opus 5.5 / high) | K5; logistyka na `main`; appka z K6 | rozłożone w czasie |
| **D1** | karta dokumentacyjna (sekcja 8.10, bez osobnego planu) | przeniesienie „Doprecyzowań (do specu)” z planów K6, K7, K8 do specu (sekcja „Doprecyzowania z realizacji”) i do CLAUDE.md (próg wersji appki 999999 jako wycofanie, restart przy zmianie ustawień jeśli dotyczy, tryb `stol`) | **cloud** | Opus 5.5 / medium | K7 część 2 (P3 włączone) | krótka sesja |
| **K8** | `…-krok-K8-sprzatanie-p4.md` | DROP martwych kolumn/tabel, usunięcie `priority_service.py` i reszty | **lokalna** | Opus 5.5 / high | K7 + 2–3 tygodnie stabilnej pracy, D1 | 1 sesja |
| sesja appki | karta z K6 (repo `woodpower_prod_app`) | ekran stołu, Odłóż, SSE, odpytywanie awaryjne | lokalna (tablet po USB) | **Fable 5.1 / extra** | K6 | 1–2 sesje |
| **centrala** | ten podręcznik, sekcja 9 | bramki, karty, dziennik, K7 | lokalna | **Opus 5.5 / high** | — | cały program |

Kolejność: K1 → K2 → K3 → (K4a ∥ K4b) → K5 → [Konrad: wdrożenie logistyki] → K7 część 1 (P1 na produkcji) → K6 →
[sesja appki w repo `woodpower_prod_app`] → K7 część 2 (P3: przełączanie) → D1 → K8.

K4a i K4b mogą iść jednocześnie w dwóch sesjach, bo dotykają innych plików (K4a: Lista produkcyjna, Logistyka;
K4b: Stanowiska, dashboard, Konfiguracja, monitory). Jeśli obie pracują na tej samej gałęzi, centrala każe drugiej
zaczynać od `git pull` i zleca scalenie, gdy pierwsza skończy.

## 4. Lokalna czy cloud

| Potrzeba kroku | Sesja |
|---|---|
| uruchamianie testów (`docker compose exec app pytest`) | lokalna |
| migracja na kontenerze `db` albo na kopii produkcji | lokalna |
| wyścigi MySQL na dwóch sesjach, podgląd w przeglądarce, tablet po USB | lokalna |
| ssh na serwer produkcyjny | lokalna |
| tylko czytanie kodu i pisanie dokumentu (K6, karty naprawcze dokumentacyjne) | cloud |
| centrala | **lokalna zalecana** (może sama uruchomić testy przy bramce i zajrzeć na podgląd); cloud możliwa, wtedy bramka opiera się wyłącznie na raporcie i centrala każe sesji kroku wkleić pełne wyniki testów do raportu |

Środowisko cloud nie ma zainstalowanych zależności aplikacji (Flask, SQLAlchemy, WeasyPrint z bibliotekami systemowymi),
więc testów tam nie ma. Gdyby to miało się zmienić, trzeba skonfigurować skrypt startowy środowiska (skill
`session-start-hook`) — poza zakresem programu.

## 4a. Modele i effort do sesji

Zasada (Konrad 5.10): **trudniejsze kroki na Fable 5.1, pozostałe na Opusie 5.5.** Trudny = taki, w którym błąd nie
wychodzi w testach: kolejność blokad i odczyt bieżący (MySQL 1213), algorytm całej kolejki, migracja na danych
produkcyjnych, werdykt przed wdrożeniem, kolejka offline i idempotencja w appce. Skala effortu w aplikacji:
low < medium < high < extra < max < ultracode. Centrala pisze model i effort w nagłówku każdej karty i w wiadomości do
Konrada („sesja lokalna, Fable 5.1, extra”).

| Model | Effort | Kroki | Dlaczego |
|---|---|---|---|
| **Fable 5.1** | **extra** | K1, K3, K5, sesja appki | współbieżność, blokady, 1213, algorytm, werdykt „gotowe”; koszt tokenów tańszy niż zakleszczenie na produkcji |
| **Opus 5.5** | **high** | K2, K4a, K4b, K6, K8, centrala, K7 | jasny plan i testy, które łapią błędy; centrala czyta raporty i grepuje kod, nie rozwiązuje trudnych problemów |
| Opus 5.5 | medium | karty naprawcze dokumentacyjne (poprawka planu, literówka w specu) | mało ryzyka |
| Sonnet 5.5 | high | oszczędnościowo zamiast Opusa w K4a, K4b, K8, gdy budżet ciśnie | UI i sprzątanie pod testami strukturalnymi |
| Haiku 4.5 | — | nie używać w tym programie | — |

Eskalacja dla centrali:
1. Krok niezaliczony → karta naprawcza **tym samym modelem, effort o poziom wyżej** (zwykle to luka w planie, nie w modelu).
2. Ta sama usterka drugi raz → model o poziom wyżej (Sonnet → Opus → Fable), effort bez zmian.
3. MySQL 1213 w K5 albo na produkcji → analiza `SHOW ENGINE INNODB STATUS` od razu na **Fable 5.1, max**, zanim ktokolwiek
   zmieni kod.
4. `ultracode` tylko w sesjach planujących (jak ta), nie w krokach wykonawczych — krok ma plan, nie potrzebuje fan-outu.
5. Tryb szybki (fast mode) wolno włączać w K2, K4a, K4b, K6, K8; w K1, K3, K5, sesji appki i centrali — nie.

## 5. Pętla centrali

Dla każdego kroku K:

1. **Przed kartą.** Sprawdź w dzienniku, że wszystkie zależności K mają raport z werdyktem „zakończony” i przeszły bramkę.
   Sprawdź, czy `origin/claude/logistyka-etap-4` albo `origin/main` nie poszły do przodu od ostatniego scalenia; jeśli tak,
   najpierw karta naprawcza „scalenie”. Przeczytaj plan K i sekcję „Co następny krok musi wiedzieć” z raportów zależności.
   Jeśli plan wymaga decyzji Konrada (sekcja „Pytania do Konrada” w planie), zebrać je **przed** wydaniem karty.
2. **Karta.** Weź szablon z sekcji 8, wstaw: ID kroku, ścieżkę planu, typ sesji, **model** (sekcja 4a), hash gałęzi,
   **effort**, decyzje Konrada dla tego kroku, wskazania podglądów. Podaj Konradowi w jednym bloku do wklejenia i powiedz
   wprost: „sesja lokalna, Fable 5.1, extra” albo „sesja cloud, Opus 5.5, high”.
3. **W trakcie.** Centrala nie ingeruje. Jeśli Konrad przekazuje pytanie od sesji kroku, centrala odpowiada na podstawie
   specu i planów; jeśli pytanie wymaga decyzji projektowej — do Konrada, z rekomendacją.
4. **Po kroku — bramka.** Przeczytaj raport. Sprawdź kolejno:
   - każdy Task planu odhaczony albo wyjaśniony w „Odstępstwa”,
   - testy z planu uruchomione i zielone (wyniki w raporcie; centrala lokalna może uruchomić je sama),
   - DoD planu spełnione punkt po punkcie,
   - interfejsy, na które liczą następne kroki, istnieją pod nazwami ze specu (grep w kodzie: nazwy modułów, końcówek,
     kluczy `prod_config`),
   - commity na gałęzi roboczej, stan `git log origin/claude/priorytety-produkcji -1` zgodny z raportem, `main` nietknięty,
   - brak sekretów i danych klientów w commitach (grep po `api_key`, nazwach klientów w raportach).
   Wynik: **zaliczony** → wpis do dziennika, następny krok; **zaliczony z uwagami** → karta naprawcza przed następnym krokiem
   zależnym; **niezaliczony** → karta naprawcza o tym samym ID z sufiksem (K2-poprawka), bez przechodzenia dalej.
5. **Dziennik.** `docs/superpowers/plans/raporty/2026-10-05-priorytety-dziennik-centrali.md`: data, krok, sesja (lokalna/cloud),
   hash przed i po, wynik bramki, odstępstwa, pytania zebrane dla Konrada i jego odpowiedzi (numerowane, jak
   „Rozstrzygnięcia” w przekazaniu etapu 3). Commit dziennika na gałąź roboczą po każdej bramce.
6. **Komunikacja z Konradem.** Krótko. Stan w trzech linijkach (ostatni krok, wynik bramki, następna karta), potem pytania
   numerowane, każde z rekomendacją. Decyzje Konrada trafiają do dziennika i, gdy zmieniają spec, centrala zleca ich
   naniesienie do specu w najbliższej karcie (K5 ma na to Task).

## 6. Blokady i karty naprawcze

Sesja kroku zatrzymuje się (STOP w raporcie), gdy: test spoza zakresu pada po jej zmianach i naprawa wymaga zmiany
projektu; MySQL 1213 w wyścigu; spec i kod mówią co innego; plan odwołuje się do czegoś, czego nie ma. Centrala
wtedy:

1. ocenia, czy to błąd planu (→ poprawia plan sama albo kartą dokumentacyjną w cloud), błąd kodu z poprzedniego kroku
   (→ karta naprawcza do tamtego kroku), czy decyzja projektowa (→ Konrad, z rekomendacją);
2. karta naprawcza ma ten sam szablon co karta kroku, z zakresem ograniczonym do jednej usterki i własnym raportem
   `…-krok-<ID>-poprawka-<n>-raport.md`;
3. nigdy nie „odpuszcza” testu ani nie wyłącza blokady, żeby przejść dalej.

## 7. Decyzje i dane od Konrada przed startem

| # | Pytanie | Rekomendacja |
|---|---|---|
| S-1 | Gałąź robocza `claude/priorytety-produkcji` odbita od `claude/logistyka-etap-4` (nie praca na gałęzi logistyki) | tak — logistyka i priorytety wdrażają się osobno, a priorytety potrzebują kodu tras |
| S-2 | Czy sesje kroków pushują same, czy push robi Konrad | sesje pushują, jeśli mają poświadczenia; inaczej Konrad po każdym raporcie |
| S-3 | Podglądy: które porty/katalogi są wolne dla tego programu (poprzednio: 5004 logistyka, 5005 appka, 5003 — nie ruszać) | wskazać jeden podgląd + bazę dla K3/K5 (wyścigi MySQL) |
| S-4 | Kto i kiedy wydaje appkę po K6 (sesja appki w repo `woodpower_prod_app` + instalacja na tabletach) | Konrad po akceptacji kontraktu; K7 część 2 czeka na to |
| S-5 | Czy centrala ma być lokalna (zalecane) czy cloud | lokalna |
| S-6 | Kolejność przełączania stanowisk na `stol` w P3 | **Decyzja Konrada 5.10 (wariant C, dziennik centrali — „Decyzje startowe” S-6, rozstrzygnięcie 4):** Sklejanie → Formatowanie → Składanie → Wycinanie → Krawędzie → Pakowanie, po 2 dniach obserwacji każde; **Lakiernia zostaje na stałe w trybie `stary`** — pełna lista, pracownik wybiera, lista po wykończeniu (rodzaj, kolor, połysk), potem ranga (spec ustalenie 15, 3.2 „Lista Lakierni”) |

Pytania specyficzne dla kroków zbiera sekcja „Pytania do Konrada” każdego planu; centrala wyciąga je przed kartą.
Stan po recenzji planów (5.10):

| Krok | Przed kartą trzeba rozstrzygnąć | Rekomendacja / stan |
|---|---|---|
| K1 | nic blokującego; p. 3 (gwiazdki przed grupą materiału) rozstrzygnięty przez sesję planującą: obowiązuje spec 3.2, przykład 3.3 poprawiony | start bez pytań |
| K2 | pamięć podręczna ustawień 60 min na worker gunicorna | **przyjęte przez sesję planującą:** K2 naprawia — `ustawienia.*` czyta wiersz `prod_config` wprost (jedno zapytanie po kluczu), bez cache; Konrad może zawetować przed kartą K2 |
| K3 | nic blokującego | K2 przed K3 (plan K3 zakłada kod K2) |
| K4a | nic blokującego | — |
| K4b | zakładka „Stanowiska” nie jest dziś podpięta w panelu: (A) podpiąć i przerobić, (B) przerobić bez podpinania, (C) usunąć w K8 | **rekomendacja A** — biuro ma widzieć stoły wszystkich stanowisk, nie tylko hala na monitorach; **decyzja Konrada** |
| K5 | zrzut bazy produkcyjnej na podgląd (mysqldump, poza repo) | **decyzja Konrada:** skąd i kiedy; bez zrzutu odpada połowa Task 2 |
| K6 | nic blokującego | — |
| K7 | A1 ile dni stabilnej logistyki przed P1; A2 kto wykonuje polecenia na serwerze; A3 PR z merge commitem; A4 zgoda na zrzut produkcji do lokalnego `db` | rekomendacje w planie K7 (≥3 dni, odczyty sesja / zapisy Konrad, merge commit, tak); **decyzje Konrada** przed Task 1 |
| D1 | nic | po K7 część 2 |
| K8 | dowód zdjęcia starej appki z tabletów (W-3); świeży zrzut produkcji po P3 i hash kodu z serwera (W-4, W-5) | bez W-3 K8 idzie bez Taska 4 (lista i `refresh_interval_seconds` zostają do karty K8-b) |

Uwaga krytyka kompletności, przyjęta jako świadome odstępstwo (do zapisu w specu przez K5): monitory hali układają
karty po randze zamówienia, a tablet stanowiska pozycyjnego po kafelkach pogrupowanych po materiale — telewizor
pokazuje więc tę samą kolejność zamówień, nie tę samą kolejność desek. Druga luka krytyka (brak przeliczenia po
„Cofnij do pakowania” z Weryfikacji) została naniesiona do planu K1.

## 8. Karty kroków (prompty do wklejenia w nową sesję)

### 8.0 Szablon wspólny

Centrala wkleja ten blok na początek każdej karty, uzupełniając pola w nawiasach:

```markdown
# Karta kroku {ID}: {tytuł} — program „Priorytety produkcji”

Sesja: {lokalna | cloud}. Model: {Fable 5.1 | Opus 5.5}. Effort: {extra | high}. (Konrad ustawia model i effort przy
starcie sesji; jeśli sesja widzi, że działa na innym modelu, pisze to w raporcie.)

Jesteś sesją wykonującą JEDEN krok programu. Twoim zleceniem jest plan:
`{ścieżka planu}` w repo kkmiecik-coder/CRM. Wykonaj go Task po Tasku, zaznaczając `- [x]`.

## Start
1. `git fetch origin && git checkout claude/priorytety-produkcji && git pull --ff-only origin claude/priorytety-produkcji`
   (K1: zamiast tego `git checkout -b claude/priorytety-produkcji origin/claude/logistyka-etap-4`).
   Oczekiwany stan gałęzi: `{hash}`. Jeśli inny — zatrzymaj się i zapytaj.
2. Przeczytaj w całości: plan, spec `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md`,
   `docs/superpowers/specs/2026-10-04-priorytety-produkcji-symulacja.md` (sekcje „Analiza wyniku” i „E”),
   raporty kroków, od których zależysz: {lista raportów}. CLAUDE.md obowiązuje.
3. Decyzje Konrada dla tego kroku: {lista albo „brak”}.
4. Podglądy/porty do użycia: {wskazania centrali albo „nie dotyczy”}.

## Zasady
- Gałąź robocza `claude/priorytety-produkcji`. Nigdy `main`. Commity Conventional Commits po polsku (temat bez polskich
  znaków), jeden na Task, stopka atrybucji własnej sesji. `docs/superpowers/` przez `git add -f`. Push na gałąź roboczą
  {„po każdym Tasku” | „nie pushuj — zrobi to Konrad”}.
- Testy: `docker compose exec app pytest <ścieżki> -q -p no:cacheprovider`; TDD — test przed implementacją; na końcu
  wszystkie testy wymienione w planie zielone, wyniki w raporcie.
- Python 3.9, komentarze po polsku, w UI „Base.”, reguły blokad z CLAUDE.md i specu 9.4, migracje idempotentne, żadnych
  `db.session.commit()` w handlerach API mobilnego, żadnych blokad przy HTTP do Base., repo publiczne (bez sekretów).
- Nie wychodź poza plan. Usterki spoza zakresu opisz w raporcie („Poza zakresem”), nie naprawiaj.
- Blokada (padający test spoza zakresu, MySQL 1213, spec vs kod, brak czegoś, co plan zakłada): STOP, raport z opisem,
  bez obejść i bez wyłączania testów.

## Koniec
Ostatni Task planu to raport: `docs/superpowers/plans/raporty/{data}-priorytety-krok-{ID}-raport.md` z sekcjami:
Zrobione (po Taskach), Testy (polecenia i wyniki), Odstępstwa od planu, Rozstrzygnięcia podjęte w trakcie (numerowane;
koszt, jeśli błędne), Pytania do Konrada, Stan gałęzi (hash, czy wypchnięte), Co następny krok musi wiedzieć.
Commit raportu na gałąź roboczą. Odpowiedz Konradowi jednym akapitem: co zrobione, co nie, hash.
```

### 8.1 K1 — fundament rangi (lokalna, Fable 5.1, extra)

Dodatki do szablonu: „Zakładasz gałąź roboczą (polecenie w Start p. 1, wariant K1). Migracja ma objąć CAŁY P1 (także
`prod_station_desk` dla K3). Po Tasku z migracją uruchom ją dwa razy na kontenerze `db` (`docker compose exec app flask
migrate` ×2) i wklej wynik do raportu. Nie dotykaj końcówek HTTP ani UI.”

### 8.2 K2 — panel API (lokalna, Opus 5.5, high)

Dodatki: „Końcówka `POST /production/api/set-priority` ZOSTAJE (woła ją jeszcze JS) — usuwa ją K4a. Każdą końcówkę
pokaż w raporcie jednym `curl` z odpowiedzią (z podglądu albo z testu klienta Flaska).”

### 8.3 K3 — stół, Odłóż, sygnały (lokalna, Fable 5.1, extra)

Dodatki: „Konfiguracja Centrifugo na podglądzie: jeśli nie ma brokera, testuj z `REALTIME.enabled=false` (publish ma
zwracać False bez wyjątku) i opisz to w raporcie; K5 sprawdzi sygnały na podglądzie z brokerem. Lista wyścigów MySQL
z planu — nie wykonuj, tylko upewnij się, że plan K5 ma je wszystkie (dopisz w raporcie, czego brakuje).”

### 8.4 K4a — Lista produkcyjna (lokalna, Opus 5.5, high)

Dodatki: „Przed zmianą JS zrób zrzuty ekranu obecnej zakładki Produkty na podglądzie (do raportu, bez danych klientów —
użyj bazy podglądu). Po zmianach: zrzuty Listy produkcyjnej, modalu priorytetu, modalu drabiny. Jeśli K4b pracuje
równolegle: `git pull` przed każdym commitem; konflikty tylko w `dashboard.html` — rozwiąż, nie nadpisuj.”

### 8.5 K4b — czytelnicy rangi (lokalna, Opus 5.5, high)

Dodatki: „Monitory hali sprawdź w przeglądarce na podglądzie (`/production/monitors/<kod>` i `/production/monitor`).
Zrzuty do raportu. Konfiguracja: jedna droga zapisu ustawień (ta, którą wybrał plan) — nie dubluj.”

### 8.6 K5 — przegląd P1 (lokalna, Fable 5.1, extra; podgląd MySQL z dwiema sesjami)

Dodatki: „Kryterium wyścigów: zero 1213 bez ponowienia, zero zdublowanych kafli na stole, zero niekompletnych
kafli-zamówień na stole. Pierwsze 1213 → `SHOW ENGINE INNODB STATUS` (sekcja LATEST DETECTED DEADLOCK, bez danych
klientów), dokończ serię dla częstości, STOP i raport. Werdykt na końcu raportu: „P1 GOTOWE DO WDROŻENIA” albo lista blokad.
CLAUDE.md: nowa sekcja „Priorytety produkcji” w stylu istniejących; spec: sekcja „Doprecyzowania z realizacji”.”

### 8.7 K6 — kontrakt appki (cloud dopuszczalna, Opus 5.5, high)

Dodatki: „Każde twierdzenie w `docs/api-mobile-priorytety.md` z odnośnikiem ścieżka:linia na gałęzi roboczej (hash
w nagłówku dokumentu). Nie zmieniaj kodu. Druga część kroku to karta dla sesji appki (repo `woodpower_prod_app`) —
gotowy prompt, który Konrad wklei w sesji z tamtym repo (sesja lokalna z tabletem po USB, **Fable 5.1, extra** — kolejka offline,
idempotencja i SSE to logika, której testy appki nie złapią); ma kazać pracować wyłącznie z kontraktu i zakończyć
checklistą odbioru z tabletem.”

### 8.8 K7 — wdrożenie i przełączenie (lokalna z ssh; prowadzi centrala z Konradem, Opus 5.5, high)

To nie jest karta do kodowania. Centrala prowadzi runbook z planu K7 krok po kroku razem z Konradem: część 1 po
wdrożeniu logistyki na `main`, część 2 po wydaniu appki. Każdy punkt runbooka odhaczony w dzienniku centrali z datą.
Zmiany w kodzie, jeśli się okażą potrzebne — osobna karta naprawcza.

### 8.9 K8 — sprzątanie P4 (lokalna, Opus 5.5, high)

Dodatki: „Warunek wejścia potwierdza centrala w karcie: data wdrożenia P3, brak wycofań, stara appka zdjęta z tabletów
(inaczej `REFRESH_INTERVAL_SECONDS` i lista `/stations/<kod>/orders` zostają). Migracja DROP + migracja cofająca
w raporcie.”

### 8.10 D1 — karta dokumentacyjna (cloud, Opus 5.5, medium)

Bez osobnego planu. Treść karty: „Przeczytaj spec (`docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md`),
CLAUDE.md oraz sekcje „Doprecyzowania (do specu)” w planach K6, K7 i K8 i raporty tych kroków. Przenieś doprecyzowania
do specu (sekcja „Doprecyzowania z realizacji”, numeracja ciągła po wpisach z K5) i do CLAUDE.md (sekcja „Priorytety
produkcji”: próg `priorytety_min_app_version_code` = 999999 jako wycofanie P3, zachowanie przy zmianie ustawień, tryb
`stol` per stanowisko, co uruchomić po wdrożeniu). Nie zmieniaj kodu. Raport jak w kroku, z listą przeniesionych punktów.”

## 9. Prompt startowy centrali

```markdown
# Centrala programu „Priorytety produkcji” (repo kkmiecik-coder/CRM)

Jesteś sesją-centralą (zalecany model: Opus 5.5, effort high, sesja lokalna). Nie kodujesz i nie wykonujesz planów. Sterujesz programem wdrożenia nowego systemu priorytetów
produkcji: wydajesz Konradowi karty do uruchamiania osobnych sesji Claude (lokalnych albo cloud), czytasz ich raporty,
prowadzisz bramki i dziennik, zbierasz decyzje.

## Źródła (przeczytaj na start, w tej kolejności)
1. `docs/superpowers/plans/2026-10-05-priorytety-produkcji-centrala.md` — ten podręcznik: zasady, mapa kroków, pętla,
   bramki, karty (sekcja 8), pytania startowe (sekcja 7).
2. `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` — spec v2.
3. `docs/superpowers/specs/2026-10-04-priorytety-produkcji-symulacja.md` — wynik symulacji na produkcji (sekcje „Analiza
   wyniku” i „E”).
4. Plany kroków `docs/superpowers/plans/2026-10-05-priorytety-krok-K*.md` — przeczytaj nagłówki, Review Focus, DoD
   i „Pytania do Konrada” każdego.
5. CLAUDE.md repo.
Gałąź z tymi plikami: `claude/logistyka-etap-4`. Gałąź robocza programu: `claude/priorytety-produkcji` (zakłada ją K1).

## Pierwsza tura
1. Zadaj Konradowi pytania startowe S-1…S-6 z sekcji 7 podręcznika, każde z rekomendacją, w jednej wiadomości.
2. Dziennik `docs/superpowers/plans/raporty/2026-10-05-priorytety-dziennik-centrali.md` już istnieje (szkielet): wpisz
   decyzje startowe i stan. Commit na `claude/logistyka-etap-4` (git add -f), potem — gdy K1 założy gałąź roboczą —
   dziennik żyje na gałęzi roboczej.
3. Zbierz z planu K1 „Pytania do Konrada”; gdy są odpowiedzi, wydaj kartę K1 wg sekcji 8.0 + 8.1 podręcznika i powiedz:
   „sesja lokalna, Fable 5.1, effort extra”.

## Każda kolejna tura
Stosuj pętlę z sekcji 5 podręcznika: przed kartą — zależności, scalenia z `origin/claude/logistyka-etap-4` i `origin/main`,
pytania; po kroku — bramka z sekcji 5 p. 4 (czytasz raport; jeśli jesteś sesją lokalną, uruchom też testy z planu sam);
wpis do dziennika i commit; następna karta. Przy blokadzie — sekcja 6 (karta naprawcza, nigdy wyłączanie testów).

## Jak mówisz do Konrada
Krótko. Najpierw stan w trzech linijkach: ostatni krok i wynik bramki, co teraz, czego potrzebujesz. Potem pytania
numerowane, każde z rekomendacją. Karty podajesz w jednym bloku ```markdown do skopiowania, a nad blokiem jedną linią:
**typ sesji (lokalna/cloud), model i effort (sekcja 4a podręcznika) z jednym zdaniem dlaczego**. Przy karcie naprawczej stosuj
reguły eskalacji modelu z sekcji 4a. Nie opisuj planów — Konrad decyduje, nie wykonuje.

## Czego nie robisz
- Nie wykonujesz Tasków z planów sama (nawet małych) — od tego są sesje kroków.
- Nie scalasz do `main`, nie wydajesz poleceń deployu; K7 prowadzisz z Konradem punkt po punkcie, on wykonuje.
- Nie zmieniasz specu bez decyzji Konrada; zmiany zlecasz kartą (K5 ma Task na doprecyzowania).
- Nie pomijasz bramki, żeby „nie blokować”. Niezaliczony krok = karta naprawcza.
- Nie przepisujesz raportów sesji kroków; cytujesz je.

## Stan początkowy
Zrobione: spec v2, symulacja na produkcji z analizą, plany K1–K8 (napisane, zrecenzowane dwiema soczewkami i sprawdzone
krytykiem kompletności 5.10), ten podręcznik, szkielet dziennika. Nic z kodu nie jest jeszcze napisane. Decyzje już
podjęte przez sesję planującą (nie pytaj o nie ponownie, chyba że Konrad zawetuje): K1 p. 3 (gwiazdki przed grupą
materiału), K2 p. 1 (ustawienia bez pamięci podręcznej).
Zacznij od pytań startowych.
```
