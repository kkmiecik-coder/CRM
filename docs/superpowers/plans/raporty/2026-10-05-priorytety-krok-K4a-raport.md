# Raport kroku K4a „Lista produkcyjna” — program „Priorytety produkcji”

- **Plan:** `docs/superpowers/plans/2026-10-05-priorytety-krok-K4a-lista-produkcyjna.md` — rozszerzony przed kodem o
  **Task 3a** z karty (commit `2f4554bc`); kroki odhaczone `- [x]` (wyjątek: Task 3 Step 6 — opcjonalny drag&drop,
  świadomie pominięty, Rozstrzygnięcie 6).
- **Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` (wersja po bramce K3; wiążący przy
  różnicach z planem: 5.7, 7.1 — Odstępstwa p. 1–2).
- **Gałąź:** praca w worktree `.claude/worktrees/priorytety-k4a` (gałąź `claude/priorytety-k4a`), push wyłącznie
  `HEAD:claude/priorytety-produkcji` po każdym Tasku (rebase przed pushem). Start `2634c5b8` (zgodny z kartą).
- **Data:** 2026-10-05. **Sesja:** lokalna, Opus 5.5 (`claude-opus-5-5`), effort high. Przegląd końcowy: osobny agent
  Opus w świeżym kontekście (sekcja „Przegląd końcowy”).

## Zrobione (po Taskach)

| Task | Commit | Co weszło |
|---|---|---|
| plan | `2f4554bc` | Task 3a dopisany do planu z karty (spec 5.7, 7.1) — przed pierwszą linią kodu. |
| 1 | `5c9f6b04` | Zakładka „Lista produkcyjna” (przycisk, komunikat błędu, toast archiwum), nagłówek `il-lista-naglowek` w szablonie zakładki. `_serialize_product` i `_serialize_production_item`: `order_id`, `order_priority_stars` (z doczytanego zamówienia, zero nowych zapytań). `lista.serializuj` (Logistyka, przystanki tras): `gwiazdki`. |
| 2 | `6f1d1ba6` | `priorytety/static/js/priorytety.js` + `css/priorytety.css` (statyka blueprintu `priorytety_panel`, ładowane w `dashboard.html` przed `products-module.js`): `window.Priorytety` — klient API (`Blad` z `status`/`kod`), `esc`, `gwiazdkiHtml`, wybierak 0–5 (`div.pr-wybierak`, ←/→/Enter/Esc/klik obok), **jedyny zapis gwiazdek** `ustawGwiazdki` (unikalne id, ≤ 500, ostrzeżenie przy `przeliczenie: "nieudane"`), `pobierzKolejke`/`pobierzOdlozenia` (mapy po `order_id`), `etykietaOdlozenia` z miejscownikiem stanowisk, modal priorytetu (`<dialog>`; gwiazdki, szczebel „szczebel n z z”, termin i tagi, trasa, „Gdzie leży”, odłożenia, historia). |
| 3 | `4a63465f` | Modal „Drabina priorytetów”: szczeble gwiazdek stałe (kłódka), tagi i trasy ze strzałkami ↑↓ (`disabled` na krańcach, `aria-disabled` w trakcie zapisu), licznik „n w produkcji”, daty i status trasy, ostrzeżenia o datach (`role="status"`), informacja o samonaprawie. **Jedyny zapis drabiny** `przesunSzczebel` z `oczekiwane`; 409 `drabina_zmieniona` → odczyt od nowa + komunikat. Przycisk w nagłówku zakładki. |
| 3a | `f2d6c864` | **Karta:** „Wyślij na stanowisko” przy każdym stanowisku modalu (bez Lakierni — „bez stołu”), „Zdejmij ze stołu” przy kaflu na stole i odłożonym (klucz z `GET /stoly`), komunikaty dla wszystkich 8 kodów błędów stołu, opis „Kafel wróci przy następnym dopełnieniu stołu” (doróbka przed kliknięciem; po zdjęciu, gdy `GET /kolejka?stanowisko=S&limit=1` oddaje ten sam kafel), historia z `wyslanie`, `zdjecie`, `odlozenie`, `odlozenie_zamkniete`, `start_stolow`; pracownik pełnym imieniem i nazwiskiem. |
| 4 | `4261671a` | Lista produkcyjna: karty po randze z `/kolejka` (spoza kolejki na końcu po terminie i numerze; błąd → po terminie + ostrzeżenie `#il-priorytety-ostrzezenie`), kolumna rangi `#n`, przycisk gwiazdek → modal, plakietki trasy/tagów/„Odłożone na …”, hurt „Ustaw gwiazdki” (unikalne zamówienia, limit przed wysyłką, selekcja zostaje), nasłuch `priorytety:zmiana` (wyrejestrowanie funkcją z `on`), `handleKeydown` pomija otwarte okna, przycisk drabiny. **Usunięte:** `products-dragdrop.js`, stara gwiazdka true/false i `set-priority` w JS, progi rangi, `priority-indicator`, przycisk/formularz priorytetu w martwym szablonie akcji grupowych. CSS: siatka 32/24/60 px, media 1200/900/mobilne, style plakietek i przycisków. Wersje podbite. |
| 5 | `f169aa46` | Usunięta końcówka `POST /production/api/set-priority` (+ import `admin_required`); test K2 `test_martwe_koncowki_priorytetow_usuniete` obejmuje ją teraz (asercja „jest” odwrócona). |
| 6 | `55feb17a` | Logistyka: kolumna `★` (11 kolumn, `colspan="11"` w JS ×2 i w wierszu ładowania szablonu), wybór przez `window.Priorytety`, sortowanie `gwiazdki`, fokus (`lg-gwiazdki` w `KLASY_FOKUSU`), tylko odczyt dla zamkniętych/anulowanych/wydanych, aktualizacja wiersza po `priorytety:zmiana`; gwiazdki przy przystankach w edytorze trasy (tylko odczyt, bez zależności od komponentu). Wersje podbite. |
| poprawki | `3bc0af4b` | Z oględzin (test najpierw, RED → GREEN): Esc zamyka oba okna przez `cancel` i od razu oddaje fokus (`close` przychodzi dopiero z klatką animacji); po przerysowaniu kart fokus wraca na przycisk tej samej karty; po 409 drabiny fokus na strzałkę szczebla; plakietka odłożeń zawijana zamiast wielokropka; pusty szczebel nie przygasza strzałek. |
| przegląd | `11ef1451` | Poprawki po przeglądzie końcowym (test najpierw, RED → GREEN): dymek gwiazdek zamyka się przy zmianie rozmiaru okna (wcześniej `TypeError` z `contains(window)`) i przy przewijaniu; spóźniony odczyt `/kolejka` nie nadpisuje nowszego; opis powrotu kafla z pola `wroci_przy_dopelnieniu` z `GET /stoly`. |
| 7 | (ten commit) | Raport. |

## Testy (polecenia i wyniki)

Polecenie (karta, Start 4), z worktree: `docker compose -p priorytety run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider`.

| Co | Wynik |
|---|---|
| Punkt wyjścia (centrala, `2634c5b8`) | 6592 passed, 3 skipped |
| Pełny pakiet nr 1 (`6f1d1ba6`, po rebase na commity K3-poprawka-1 i K4b; w trakcie przebiegu kolejny rebase podmienił pliki K4b) | 6588 passed, 3 skipped, **1 failed + 40 errors** — wszystkie w 4 plikach (`test_app_bootstrap_schematu`, `test_daily_report_cli`, `test_klucz_sesji`, `test_sekret_crona`) przez **pusty `config/core.json`**, który Docker założył w worktree, montując plik podglądu 5006. Po usunięciu pliku te 4 pliki: 70 passed. Środowisko, nie kod. |
| Pełny pakiet nr 2 (`3bc0af4b`, podgląd zatrzymany, pusty plik usunięty) | 6755 passed, 3 skipped, 0 failed |
| **Pełny pakiet końcowy** (`11ef1451`, po poprawkach przeglądu; podgląd usunięty) | **6762 passed, 3 skipped, 0 failed** (7 min 02 s) |
| `tests/test_priorytety_lista_produkcyjna_ui.py` (38) + `tests/test_priorytety_logistyka_ui.py` (5) | 43 passed |
| Regresja Task 1 (plan Step 4, 9 plików) | 152 passed |
| Regresja Task 4 (plan Step 10, 14 wzorców plików) | 262 passed |
| Regresja Task 5 (`kolejnosc_zapisow`, lista, masowa zmiana statusu, `panel_api`) | 282 passed |
| Regresja Task 6 (plan Step 8) | 405 passed |

**Bilans:** 6592 (punkt wyjścia centrali) + 127 (testy sesji równoległych K3-poprawka-1 i K4b, wypchnięte w trakcie
— rebase przed każdym pushem) + 43 (nowe testy K4a) = **6762**. Zmieniony test K2
`test_martwe_koncowki_priorytetow_usuniete` (odwrócona asercja) liczby nie zmienia. Żaden test nie został wyłączony
ani usunięty; 3 `skipped` jak w punkcie wyjścia.

**TDD:** każdy Task: test → obejrzany RED → kod → GREEN. Wyjątek (Rozstrzygnięcie 5): testy Taska 3 napisane przed kodem,
ale RED obejrzany na wersji sprzed Taska (`git show HEAD:plik`), bo Docker zajmował wtedy pełny pakiet. Testy
strukturalne JS dodatkowo sprawdzone mutacją (usunięte `esc(` → test escapowania czerwony). Składnia JS: `node --check`
(node 22 na hoście) po każdej zmianie `priorytety.js`, `products-module.js`, `logistics.js`, `logistics-routes.js`.

**Składnia 3.9:** `python:3.9-slim` (3.9.25), `compile` 5 plików `.py` zmienionych w K4a (`lista.py`,
`products_api.py`, 3 pliki testów) — OK.

**Grepy kontrolne:**
- Task 5 Step 4 (`set-priority|set_product_priority|products-dragdrop|ProductsDragDrop|showEditPriorityModal|handleStarClick|getPriorityClass|updatePriorityColor|il-drag-handle|il-product-star|bulk-priority-form` w `modules app.py tests`) → trafienia wyłącznie w testach nieobecności: `tests/test_priorytety_kolejnosc_zapisow.py` (3), `tests/test_priorytety_lista_produkcyjna_ui.py` (13). `products-dragdrop.js` nie istnieje.
- `grep -rn "Lista produktów" modules/production/templates modules/production/static/js` → pusto (zostają nazwy arkuszy eksportu w `products_api.py` — Poza zakresem planu).
- `grep -rn "priorytety_panel" modules/production/logistics/templates` → pusto.
- Zapisy we froncie: `'/zamowienia/gwiazdki'`, `'/drabina/kolejnosc'`, `'/wyslij'`, `'/zdejmij'` — po jednym trafieniu, wszystkie w `priorytety.js`.

**Pomiary na podglądzie** (`priorytety_podglad`, serwer deweloperski Flaska z debugiem, 5 przebiegów, mediana / max):
`GET /kolejka` 181 / 427 ms, `GET /zamowienia/<id>/priorytet` 185 / 199 ms, `GET /odlozenia` 138 / 184 ms,
`GET /drabina` 212 / 232 ms, `GET /stoly` 174 / 264 ms — wszystko pod progiem 1 s z planu (narzut serwera
deweloperskiego ~130 ms na żądanie). „Gdzie leży” modalu = `GET /kolejka?stanowisko=gluing` (10 z 78).

## Oględziny (Task 7 Step 1)

Podgląd `127.0.0.1:5006` (kontener `priorytety-k4a`, baza `priorytety_podglad`), wbudowana przeglądarka, sesja admina
z ciasteczka wygenerowanego w kontenerze (`login_user` + `user_email`/`user_id` w sesji; ciasteczko ustawione przez
chwilową stronę na innym porcie i osobnym hoście `podglad-k4a.localhost`, bo każda odpowiedź Flaska zakłada
ciasteczko sesji `HttpOnly`, którego JS nie nadpisze — serwer pomocniczy wyłączony zaraz potem).

1. Lista: karty `#1, #2, …` po randze, plakietki trasy, tagów („Blisko terminu”, „Po terminie”, „Rozpoczęte”),
   „Odłożone na Sklejaniu: brak materiału, 15:08, …” (odłożenie zrobione wpisem SQL na podglądzie — godzina z `NOW()`
   bazy w UTC; w produkcji odłożenie zapisuje czas lokalny), kolor terminu bez zmian. 1440 i 390 px.
2. Modal: gwiazdki 0 → 5 → 0 (karta #13 → #1 → #13), historia rośnie, „Gdzie leży” zgodne z `/kolejka?stanowisko=`.
   „Wyślij na stanowisko” → kafel na stole ze źródłem „wysłane przez biuro”, wpis w historii; „Zdejmij ze stołu” → kafel
   wraca do kolejki („Kafel wrócił do kolejki stanowiska.”), wpis w historii.
3. Drabina: „Rozpoczęte” ↑ klawiaturą (fokus zostaje na strzałce); drugi klient (bezpośredni `PUT` bez `oczekiwane`)
   przesuwa „Blisko terminu”, klik w nieaktualnym modalu → 409, komunikat i drabina od nowa; ostrzeżenie o datach
   tras widoczne (dwie trasy w odwrotnej kolejności dat są w danych podglądu); „Rozpoczęte” na szczyt → pierwsza karta
   „Rozpoczęte, miejsce 1”.
4. Hurt: 26 zaznaczonych pozycji z 2 zamówień → „zaznaczonych: 2”, „Gwiazdki ★: zmieniono 2, bez zmian 0.”,
   selekcja zostaje; cofnięcie hurtem „Bez gwiazdek”.
5. Logistyka: kolumna ★, wybór klawiaturą (→ ×3, Enter) → „Gwiazdki zamówienia 1301: 3.”, fokus zostaje na przycisku
   po zapisie, sortowanie ★ (`aria-sort="descending"`), gwiazdki przy przystanku w edytorze trasy („★★★★”).
6. Konsola: zero błędów JS z kodu K4a. W konsoli tylko: błędy CSP ramki widżetu czatu (`chat.woodpower.pl`, spoza
   zakresu) i wpis sieciowy 409 celowo wywołanego konfliktu drabiny.
7. Klawiatura: Tab/fokus na przycisku gwiazdek karty, Enter otwiera modal, Esc zamyka i fokus wraca (także po
   przerysowaniu listy — poprawka `3bc0af4b`), strzałki drabiny działają z klawiatury, Esc w oknie nie czyści selekcji.
8. Czasy — sekcja „Pomiary”.

**Stan danych podglądu po oględzinach (wspólna baza z K4b):** wszystko przywrócone — gwiazdki zamówień testowych z
powrotem 0, drabina w identycznej kolejności (porównanie listy id), stół Sklejania pusty (kafel wysłany i zdjęty,
odłożenie zdjęte). Zostały wyłącznie wpisy `prod_priority_log` (gwiazdki, szczebel, wysłanie, zdjęcie) — zgodnie
z kartą niczego nie usuwałem.

## Zrzuty (poza repo)

Katalog `C:/Users/Grafik/Documents/woodpower-podglady/priorytety/k4a/zrzuty/` — nazwy klientów, adresy, kierowcy i
pracownicy zamaskowani przed zrzutem:

| Plik | Co pokazuje |
|---|---|
| `przed-1440-lista-rozwinieta.jpg`, `przed-1440-pasek-hurtu.jpg`, `przed-390-lista-hurt.jpg` | stan przed K4a: „Lista produktów”, uchwyt przeciągania, gwiazdka true/false, pasek hurtu bez gwiazdek |
| `po-1440-lista-rozwinieta.jpg` | Lista produkcyjna: ranga `#n`, gwiazdki, plakietki trasy/tagów, rozwinięta karta, przycisk „Drabina priorytetów” |
| `po-390-lista-hurt.jpg` | układ kart mobilnych: nazwa klienta w pełnym wierszu, plakietki, „Ustaw gwiazdki” w pasku hurtu |
| `po-1440-plakietka-odlozone.jpg` | plakietka „Odłożone na Sklejaniu: …” |
| `po-modal-wyslij-zdejmij.jpg` | modal priorytetu po „Wyślij na stanowisko”: kafel „wysłane przez biuro” z „Zdejmij ze stołu” |
| `po-1440-modal-odlozenia.jpg` | modal z sekcją „Odłożenia” (z „Zdejmij”) i historią wysłań/zdjęć/gwiazdek |
| `po-390-modal.jpg` | modal priorytetu na 390 px |
| `po-1440-drabina-konflikt.jpg` | modal drabiny po 409 `drabina_zmieniona` (komunikat, ostrzeżenie o datach, liczniki, kłódki) |
| `po-1440-hurt-gwiazdki.jpg` | wybierak hurtu „Gwiazdki dotyczą całych zamówień (zaznaczonych: 2)” |
| `po-1440-logistyka-kolumna.jpg` | Logistyka z kolumną ★ |
| `po-1440-trasa-przystanki.jpg` | edytor trasy z gwiazdkami przy przystanku |

## Odstępstwa od planu

1. **Zakres rozszerzony kartą:** Task 3a („Wyślij”/„Zdejmij” w modalu) — dopisany do planu przed kodem (`2f4554bc`).
2. **Historia w modalu** pokazuje także akcje stołu (spec 5.7, karta) — sekcja „Historia”, nie „Historia gwiazdek”
   z samym filtrem `akcja === 'gwiazdki'` (plan Task 2 Step 5 p. 8).
3. **„Zdejmij” bierze klucz kafla z `GET /stoly`** (K3), bo modal K2 podaje na stole same napisy bez `unit_key`.
   Czytany tylko, gdy zamówienie ma coś na stole albo odłożone. Bez zmian w K2/K3.
4. **Commity:** 10 zamiast 7 (plan, Task 3a, poprawki po oględzinach, poprawki po przeglądzie końcowym) + raport.
5. **Polecenia środowiska wg karty** (`docker compose -p priorytety run …`), nie planu (`docker compose exec`).
6. **Kolumny siatki 32/60 px** zamiast 36/76 (kolumna klienta traciła ~70 px), plakietki tylko w `.il-order-ids`
   (bez dublowania w `populateCardMeta`, bo `.il-order-ids` jest widoczne też w układzie kart).
7. **Logistyka nasłuchuje `priorytety:zmiana`** (Doprecyzowania p. 12) — kroki Taska 6 tego nie wymieniały.
8. **Zdarzenie `priorytety:zmiana` przy gwiazdkach niesie też `gwiazdki`** (addytywnie wobec kontraktu p. 12).
9. Nazwy pól K2/K3 — wszystkie zgodne z tabelą „Consumes” (adapterów nie było trzeba).

## Rozstrzygnięcia podjęte w trakcie (numerowane; koszt, jeśli błędne)

1. „Zdejmij” z kluczem z `GET /stoly` (Odstępstwa p. 3). — Koszt: ~0,17 s / 66 zapytań przy otwarciu modalu
   zamówienia, które coś ma na stole; `GET /stoly` pomija „widma” (raport K3, D2), więc kafel-widmo widać bez „Zdejmij”.
2. „Kafel wróci przy następnym dopełnieniu stołu”: przy doróbce zawsze (przed kliknięciem); po zdjęciu — gdy pierwszy
   kafel `GET /kolejka?stanowisko=S&limit=1` to ten sam kafel. Błąd tego podglądu nie psuje „Zdejmij” (opis neutralny).
   — Koszt: „pierwszy w kolejce” to porównanie z jednym kaflem, nie z liczbą wolnych miejsc K (kafel drugi przy dwóch
   wolnych miejscach też wróci, a opis tego nie powie).
3. Lakiernia bez „Wyślij” (stała `STANOWISKA_BEZ_STOLU = ['painting']` w JS, lustro serwera) — opis „bez stołu
   (pracuje z listy)”. — Koszt: druga kopia listy (jedna pozycja).
4. Komunikaty błędów stołu ze słownika UI (z miejscownikiem stanowiska i numerem zamówienia), nie z `message`
   serwera; nieznany kod → `message` serwera. — Koszt: tekst.
5. TDD Taska 3: RED obejrzany na wersji sprzed Taska (Docker zajęty pełnym pakietem). — Koszt: żaden.
6. Drag&drop drabiny pominięty (opcja planu, karta: strzałki obowiązkowe). — Koszt: przesunięcie o kilka pozycji to
   kilka kliknięć.
7. `pozycji` w wierszu `GET /kolejka` — przyjęta definicja K2 (pozycje w produkcji); Lista jej nie wyświetla. — Koszt: żaden.
8. Siatka 32/24/60 px, mała gwiazdka 11 px, mobilnie nazwa klienta w pełnym wierszu, plakietki z wielokropkiem
   (odłożenia zawijane). — Koszt: kosmetyka CSS.
9. Plakietki tylko w `.il-order-ids`. — Koszt: jedna linia, gdyby układ kart chował `.il-order-ids`.
10. Gwiazdki w zdarzeniu `priorytety:zmiana` — lista i Logistyka poprawiają wiersze lokalnie (także zamówień spoza
    kolejki). — Koszt: żaden.
11. Przycisk „Drabina priorytetów” obsługuje `products-module.js`; bez `window.Priorytety` przycisk wyłączony
    z podpowiedzią. — Koszt: żaden.
12. Kolumna ★ w Logistyce w wąskim kontenerze (≤ 860 px) ciaśniej (≈54 px). Lista obok mapy przewijała się w bok już
    przed K4a (1100 i 1440 px: 804 px treści w ramce 742/732 px); ★ dokłada ~54 px przewijania. — Koszt: pytanie 1.
13. Esc w oknach przez `cancel` (zamykamy sami, fokus od razu), `close` zostaje jako drugi tor z flagą „fokus oddany
    raz”. Lekcja z pamięci projektu (wbudowana przeglądarka bez klatek nie dostarcza `close`). — Koszt: żaden.
14. Fokus po zamknięciu modalu: pierwotny przycisk, a gdy lista go przerysowała — przycisk okna tej samej karty
    (`[data-order-id] [aria-haspopup="dialog"]`). — Koszt: żaden.
15. Poprawki z oględzin w osobnym commicie `fix` przed raportem (wzór K2/K3). — Koszt: commit więcej niż plan.
16. Ciasteczko sesji podglądu: osobny host `podglad-k4a.localhost` (izolacja od K4b na `127.0.0.1:5007`, które ma tę samą
    nazwę ciasteczka `session_prio`). — Koszt: żaden.

17. Przegląd końcowy: Minor 1 (spóźnione odczyty `/kolejka`) i Minor 4 (`wroci_przy_dopelnieniu`) przeszacowane na
    „ważne” wg skutku dla biura (zła kolejność kart; brak opisu wymaganego kartą przed kliknięciem) i poprawione.
    Pozostałe drobne — odłożone (niżej). — Koszt: żaden.

## Przegląd końcowy

Osobny agent (Opus, świeży kontekst, tylko odczyt) przejrzał commity K4a (`5c9f6b04` … `3bc0af4b`) względem planu,
specu i 8 punktów Review Focus. **Wynik: 0 krytycznych, 1 ważne, 7 drobnych; werdykt „tak, po poprawkach”.** Review
Focus 1–8 spełnione (XSS, martwy kod, kolejność kart, drabina z `oczekiwane`, jedna droga zapisu gwiazdek, serializery
bez nowych zapytań, 11 kolumn Logistyki, nazwa zakładki); z rozstrzygnięciami wykonawcy recenzent się zgodził.

Poprawione w jednej turze (commit `11ef1451`, każda z testem RED → GREEN, potem pełny pakiet 6762/0):
- **Ważne 1 — dymek gwiazdek:** `resize` wołał `klikObok` z `e.target === window` → `TypeError` i dymek się nie
  zamykał; przy przewinięciu listy (Logistyka ma własny suwak) dymek `position: fixed` stał obok innego wiersza niż
  zamówienie, do którego zapisze wybór. Test `test_wybierak_zamyka_sie_przy_resize_i_przewijaniu_bez_wyjatku`;
  sprawdzone w przeglądarce (zamyka się, zero błędów).
- **Drobne 1 → ważne — spóźnione odczyty kolejki:** dwie szybkie strzałki drabiny dawały dwa odczyty `/kolejka`;
  starszy, który wrócił później, zostawiał kolejność kart niezgodną z drabiną. Licznik żądań jak w modalu. Test
  `test_spoznione_odczyty_kolejki_odrzucane`.
- **Drobne 4 → ważne — opis „wróci”:** `GET /stoly` (K4b) liczy `wroci_przy_dopelnieniu`; modal używa go przed
  kliknięciem (zgodnie z zakładką Stanowiska). Test `test_opis_powrotu_z_pola_stolow`.

**Odłożone drobne (bez poprawek w K4a):**
1. `wczytajPriorytety` idzie po `loadProductsData` (plan Step 4 i test tak każą) — przy wiszącym (nie padającym)
   `/kolejka` lista czeka na odpowiedź zamiast renderować się po terminie; do rozważenia `Promise.all` albo limit czasu.
2. Przycisk gwiazdek karty bierze `order.gwiazdki` z listy produktów, a ranga przychodzi z `/kolejka` — gdy gwiazdki
   zmieni ktoś inny, do odświeżenia listy przycisk może pokazać stan sprzed zmiany (`wpis.gwiazdki ?? order.gwiazdki`).
3. Komunikat ładowania w `products-module.js`: „Nie udało się załadować listy produktów” → „listy produkcyjnej”.
4. Klik w kotwicę przy otwartym dymku zamyka go (`mousedown`) i od razu otwiera ponownie (`click`).
5. Po 409 `trasa_nieaktywna` modal drabiny pokazuje komunikat, ale nie czyta drabiny od nowa.

Recenzent odłożył bez oceny (rozstrzygnięte wyżej albo poza zakresem): drag&drop drabiny (Rozstrzygnięcie 6), historia
z akcjami stołu (Odstępstwa 2), plakietki bez `populateCardMeta` (9), szerokości kolumn (8), rozszerzone zdarzenie (10),
ranga ukryta ≤ 900 px (Doprecyzowania 9), `priority_range` i martwy szablon (K8, Poza zakresem), **brak potwierdzenia
przy hurcie do 500 zamówień — fokus startuje na „Bez gwiazdek”, więc mimowolny Enter zdejmie gwiazdki całej selekcji**
(pytanie 4), uprawnienia biura (spec 7.3), dokumenty programu w publicznym repo (decyzja programu, dziennik centrali
rozstrz. 9), wspólna flaga `zapisTrwa` (oba okna modalne).

## Pytania do Konrada

1. **Lista Logistyki obok mapy przewija się w bok** (1100–1440 px z panelem bocznym) już przed K4a; kolumna ★ dokłada
   ~54 px. Zostawić tak (sortowanie i wybór gwiazdek z listy), czy w wąskim widoku chować kolumnę ★ (gwiazdki zostają
   w Liście produkcyjnej i przy przystankach)?
2. **„Kafel wróci przy następnym dopełnieniu stołu”** — po „Zdejmij” pokazuję go, gdy kafel jest pierwszy w kolejce
   stanowiska (i zawsze przy doróbce). Wystarczy, czy liczyć „wróci” względem liczby wolnych miejsc na stole?
3. **Hurt „Ustaw gwiazdki”** nie pyta o potwierdzenie (spec i plan nie wymagają), a wybierak startuje na „Bez
   gwiazdek” — mimowolny Enter zdejmie gwiazdki wszystkim zaznaczonym zamówieniom (do 500). Dodać potwierdzenie przy
   hurcie powyżej np. 10 zamówień albo zdjęciu gwiazdek?
4. Pytania 1–3 planu K4a — przyjęte kartą (gwiazdki i drabina dla każdego z modułem produkcji; strzałki obowiązkowe;
   plakietka odłożeń zbiorcza na stanowisko). Bez nowych.

## Stan gałęzi

- `origin/claude/priorytety-produkcji`: commity K4a `2f4554bc` … `11ef1451` (przeplecione z K4b i K3-poprawka-1 —
  rebase przed każdym pushem, bez konfliktów; `dashboard.html` scalony automatycznie), commit tego raportu — hash
  w odpowiedzi sesji. Wszystko **wypchnięte**.
- `main` i główny checkout nietknięte; worktree `priorytety-produkcji` nietknięty. Kontener `priorytety-k4a` zatrzymany
  i usunięty, pusty `config/core.json` usunięty z worktree. Kontenery i bazy 5002–5005 nieruszane; 5007 (K4b) nieruszany.

## Co następny krok musi wiedzieć

**K4b (równolegle):**
- `window.Priorytety` (ładowany przez `dashboard.html` na każdej zakładce panelu) do ponownego użycia: `zapytanie`,
  `esc`, `gwiazdkiHtml(n, {male})`, `opisGwiazdek`, `wybierzGwiazdki(kotwica, aktualne, {opis})`, `ustawGwiazdki`,
  `pobierzKolejke`, `pobierzOdlozenia`, `etykietaOdlozenia`, `opisOdlozen`, `etykietaTagu`, `naStanowisku`
  (miejscownik), `dataPl`, `otworzModalPriorytetu(orderId)`, `otworzDrabine()`, `wyslijNaStanowisko(kod, orderId)`,
  `zdejmijZeStolu(kod, unitKey) → {odp, wroci}`, `komunikatStolu(blad, kod, numer)`, `LIMIT_HURTU`.
- Zdarzenie `ProductionShared.eventBus` `'priorytety:zmiana'` `{rodzaj: 'gwiazdki'|'drabina'|'stol', order_ids,
  gwiazdki?}` — po każdym zapisie z komponentu (także „Wyślij”/„Zdejmij” → `rodzaj: 'stol'`). Zakładka Stanowiska może
  na nie odświeżać stoły. Słuchacza zdejmować funkcją zwróconą przez `on`.
- Wersje w `dashboard.html`: `priorytety.js` `20261005d`, `priorytety.css` `20261005c`, `products-module.js`
  `20261005b`, `products-tab.css` `20261005b`.

**K5 (przegląd P1, wyścigi, CLAUDE.md, spec):**
- CLAUDE.md, akapit pisarzy pozycji bez blokady zamówienia: znika „hurtowa i ręczna zmiana priorytetu” —
  `set-priority` usunięte w K4a, `bulk-action update_priority` w K2.
- Do specu: Doprecyzowania 1–14 planu K4a (zwłaszcza 9.1 bez `templates/priorytety/` — modale budowane w JS; 7.1
  kolejność kart z `/kolejka`, a gdy nie odpowie — po terminie z ostrzeżeniem), Odstępstwa 2, 3, 8 i Rozstrzygnięcia
  1–2, 13–14 (Esc przez `cancel`).
- Spec 7.3: gwiazdki i drabina już nie tylko dla admina (było `set-priority` z `@admin_required`) — do notatki K7.
- Wyścigi z panelu (K4a nie dodaje pisarzy): UI wysyła jedno żądanie na akcję i nie ponawia 500; „Wyślij”/„Zdejmij”
  z modalu wołają końcówki K3 (tryby `wyslij-*`, `zdejmij-*` z listy K5 w raporcie K3).

**K6 (kontrakt appki):** K4a nie zmienia API mobilnego. Skutki dla tabletu: biuro ma w panelu „Wyślij na stanowisko”
(kafle `zrodlo='biuro'` ponad K, na początek stołu — plakietka „wysłane przez biuro”) i „Zdejmij ze stołu” (kafel
znika ze stołu; sygnał `station:<kod>` wysyła serwer K3). Pracownik odłożenia w panelu — pełne imię i nazwisko; na
tablecie format z K3-poprawka-1.

**K7 (wdrożenie):** po wdrożeniu stara karta przeglądarki z wczytanym starym `products-module.js` dostanie 404 na
kliknięcie starej gwiazdki, aż odświeży stronę (wersje `?v=` podbite). Notatka dla biura: zakładka nazywa się „Lista
produkcyjna”, nowy przycisk „Drabina priorytetów”, gwiazdki 0–5 może ustawiać każdy z modułem produkcji (nie tylko admin).

**K8:** filtr `priority_range` w `GET /products/filters-data` nikt nie czyta (`products-module.js`, TODO) — do usunięcia
razem z `priority_service`. `is_priority`, `priority_rank`, `priority_manual_override` w serializerach listy zostają do P4
(`priority_rank` dalej jako `sort_by` listy — kolejność pozycji w karcie).

## Poza zakresem (zauważone, nie ruszane)

1. `products-module.js` `populateOrderHeader` składa numery zamówienia (`internalOrderNumber`, `clientOrderNumber`,
   `quoteNumber`, `baselinkerOrderId`) przez `innerHTML` bez escapowania — dane z Base./klienta (kod sprzed K4a; nowe
   plakietki K4a są escapowane).
2. Martwa ścieżka `_createOldProductRow`/`populateProductRow`/`attachRowEventListeners` i reszta szablonu
   `bulk-actions-modal-template` (plan: tylko fragmenty o priorytecie).
3. Lista Logistyki obok mapy przewija się w bok już bez kolumny ★ (pytanie 1).
4. Konsola podglądu: błędy CSP ramki widżetu czatu (`frame-ancestors crm.woodpower.pl`) na `localhost`.
5. Testy uruchamiane z worktree, w którym działa podgląd z zamontowanym `config/core.json`, padają w 4 plikach przez
   pusty plik montażu (pułapka znana z K3) — pełny pakiet tylko z zatrzymanym podglądem.
