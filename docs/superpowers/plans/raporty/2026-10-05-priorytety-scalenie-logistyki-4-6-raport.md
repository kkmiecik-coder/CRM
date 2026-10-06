# Raport — karta „scalenie logistyki 4.6 + testy” (S-1), program „Priorytety produkcji”

- **Data:** 2026-10-05
- **Sesja:** lokalna, Opus 5.5, effort high, bez trybu szybkiego.
- **Gałąź:** `claude/priorytety-produkcji` (worktree `.claude/worktrees/priorytety-produkcji`).
- **Hash przed:** `f031230a` (stan przy starcie karty; przed scaleniem pobrane jeszcze `8ad29f6e` i `ec30031a` —
  K4-poprawka-1, K6, dziennik centrali).
- **Scalona logistyka:** `origin/claude/logistyka-etap-4` @ `f07b21ec` (zgodnie z kartą, nowszego nie było).
- **Commity karty:** `8f60b221` (scalenie), `2f3e6ce7` (zdjęcie odmowy), ten raport.

## Zrobione

1. **Scalenie** `git merge --no-ff origin/claude/logistyka-etap-4` → merge commit `8f60b221`
   „merge: logistyka 4.6 (pakowanie bez sposobu dostawy) do priorytetow”, rodzice `ec30031a` + `f07b21ec`.
   Bez konfliktów tekstowych (sekcja „Konflikty”). Wypchnięte.
2. **Zdjęcie odmowy po stronie priorytetów** (spec 5.1, decyzja Konrada 5.10) — commit `2f3e6ce7`, TDD (testy
   odwrócone i nowe najpierw: 9 czerwonych, potem kod, zielono). Zamówienie bez sposobu dostawy jest na Pakowaniu
   zwykłym kandydatem we wszystkich miejscach, które je pomijały albo odrzucały:

   | Miejsce | Było | Jest |
   |---|---|---|
   | `stol._kandydaci` (dopełnianie stołu w `GET desk`, `stol.stan` → `kolejka_dalej` tabletu, „Niekompletne”) | filtr `moze_wejsc` wyrzucał Pakowanie bez sposobu z doróbek, kolejki i „Niekompletnych” | brak filtra — kolejność wyłącznie z `kolejka.kandydaci_stanowiska` |
   | `stol.wyslij` („Wyślij na stanowisko”, `POST …/stoly/packaging/wyslij`) | 409 `delivery_method_not_set` | kładzie kafel jak każde inne (`zrodlo='biuro'`) |
   | `stol._rozpoczete` (start stołów: `GET /start`, „Przygotuj stoły”) | pomijało rozpoczęte Pakowanie bez sposobu | wchodzi jak każde rozpoczęte |
   | `widok._w_kolejce` (modal priorytetu, „miejsce w kolejce”) | `None` dla Pakowania bez sposobu | miejsce w kolejce jak każde inne |
   | `widok._kolejka_dalej` (zakładka Stanowiska, monitory, licznik `kolejka_dalej` w `GET /stoly`) | nie liczyło Pakowania bez sposobu | liczy wszystkich kandydatów (= `stol.stan`) |
   | `widok._wroci_po_zdjeciu` (podpis „wróci przy dopełnieniu”) | kafel bez sposobu „nie wraca” | wraca jak każdy |
   | `priorytety.js` `KOMUNIKATY_STOLU` | komunikat dla `delivery_method_not_set` | usunięty (serwer tego kodu już nie zwraca z końcówek stołu) |
   | `mobile_api.order_complete` (komentarz przy bramce stołu) | „PO bramce sposobu dostawy — pakowacz ma najpierw usłyszeć…” | opis stanu po 4.6 (sekcja „Odstępstwa” p. 1) |

   Bramka ZAKOŃCZ stołu (`stol.bramka_zakoncz`) sposobu dostawy nigdy nie sprawdzała — po scaleniu 4.6 Pakowanie bez
   sposobu przechodzi przez nią jak każde inne (poza stołem 409 `nie_na_stole`, na stole 200). Logiki logistyki 4.6
   (status Base., etykieta, okno 8.7, `baselinker_status_sync`, `delivery.py`) nie ruszałem.

   **Zostało celowo:** pole `sposob_dostawy_ustawiony` na kaflu Pakowania w podglądzie kolejki (`GET /kolejka`, K2) —
   informacyjne, niczego nie blokuje (docstring `widok._sposob_ustawiony`); kształt odpowiedzi K2 bez zmian. Kolumna
   `override_delivery_method` zostaje w `stol._KOLUMNY_ZAMOWIENIA` (odczyt kandydatów) — usunięcie zmieniałoby zestaw
   wczytywanych kolumn obiektów, które dalej czyta serializer kafla (`transport`), czyli potencjalnie dodatkowe
   zapytania; poza zakresem karty. Parametry `stanowisko`/`kod` w `_w_kolejce`, `_kolejka_dalej`,
   `_wroci_po_zdjeciu` zostały w sygnaturach (nieużywane po zmianie) — bez ruszania wołających.

3. **Testy** — sekcja „Testy”.
4. **Migracja** — 4.6 nie ma migracji: `git diff --stat f731b77c f07b21ec -- migrations/` puste. `flask migrate-status`
   na `priorytety_podglad`: „Brak nowych migracji do wykonania” — **zero oczekujących** (ostatnie wykonane: `2026-10-05-priorytety-produkcji`, `2026-10-06-priorytety-stol-zrodlo`); pusty `config/core.json` po montowaniu skasowany z worktree.

## Konflikty

Brak konfliktów tekstowych — git połączył wszystkie pliki sam (`delivery.py`, `lista.py`, `logistics.js`,
`mobile_api.py`, `test_logistyka_mobile.py`; próbne `git merge-tree` przed scaleniem też czyste).

| Plik | Co | Jak rozwiązane |
|---|---|---|
| `modules/production/routers/mobile_api.py` (`order_complete`) | 4.6 zastąpiła blok 409 `delivery_method_not_set` komentarzem; priorytety (K3) mają tuż za nim bramkę stołu | auto-merge: bramka stołu `stol.bramka_zakoncz(...)` **zostaje**, blok 409 znika. Komentarz przy bramce („PO bramce sposobu dostawy…”) był po scaleniu nieaktualny — poprawiony na opis stanu po scaleniu (po polsku); trafił do commita zakresu 2, nie do merge commitu (Odstępstwa p. 1) |

Semantycznie sprawdzone po scaleniu (testy logistyki + priorytetów, 10 plików): logistyka cała zielona; jedyny
padający test — `test_priorytety_stol.py::test_bramka_delivery_method_not_set_przed_nie_na_stole` — pilnował 409,
które 4.6 usunęła; to test do odwrócenia w zakresie 2 (nie test logistyki, więc nie blokada z karty).

**`origin/main` poza gałęzią** (rozstrzygnięcia 2 i 5): 5 commitów — `c2b312f0`, `b910b07b`, `a71af794` (znane,
rozstrz. 2), `0310b6a7`, `31a0b014` (m² lakierni, rozstrz. 5). Z plikami **commitów priorytetów**
(`f731b77c..HEAD`) wspólnych plików: **zero**. Z plikami całej gałęzi (od `a5a0f1f9`, czyli z logistyką etapów 1–4)
wspólne: `31a0b014`/`0310b6a7` — `routers/api/reports_api.py`, `services/reports_service.py` (+ `0310b6a7`:
`reports-tab-content.html`, `reports/mix.html`), wszystkie dotknięte przez logistykę (`7ac5a865`, `47718f13`, statusy
po spakowaniu w raportach); `b910b07b` — `admin_routers.py`, `mobile_api_service.py` (znane z rozstrz. 2). Próbne
`git merge-tree --write-tree HEAD origin/main`: **bez konfliktów** (przed i po scaleniu 4.6). Nic z `main` nie
scalałem.

## Testy

| Punkt | Hash | Wynik | Zebranych |
|---|---|---|---|
| punkt wyjścia (przed scaleniem, pełny pakiet) | `f031230a` | **6775 passed, 3 skipped, 0 failed** (7 min 37 s) | 6778 |
| przed scaleniem po pobraniu K4-poprawki-1/K6 (tylko zbieranie) | `ec30031a` | — | 6782 (+4: testy K4-poprawki-1) |
| scalenie (tylko zbieranie; testy logistyki + priorytetów: 552 passed, 1 failed — wyżej) | `8f60b221` | — | 6805 (+23: testy logistyki 4.6) |
| po commicie zakresu 2 (pełny pakiet) | `2f3e6ce7` | **6805 passed, 3 skipped, 0 failed** (7 min 24 s) | 6808 |

Różnica 6778 → 6808: +4 K4-poprawka-1 (commity innej sesji pobrane przed scaleniem), +23 logistyka 4.6
(`test_logistyka_pakowanie_bez_sposobu.py` nowy, `test_logistyka_mobile.py`/`test_logistyka_pipeline.py`
zmienione), +3 nowe testy tej karty. Testy odwrócone (ta sama liczba):

| Test (było → jest) | Co pilnuje teraz |
|---|---|
| `test_priorytety_stol.py::test_bramka_delivery_method_not_set_przed_nie_na_stole` → `test_bramka_pakowanie_bez_sposobu_dostawy_tylko_bramka_stolu` | poza stołem 409 `nie_na_stole`, na stole 200 i `spakowane`, kafel schodzi |
| `test_priorytety_stol.py::test_dopelnij_pakowanie_bez_sposobu_dostawy_nie_wchodzi` → `…_wchodzi_jak_kazde` | bez sposobu wchodzi na stół w kolejności, `kolejka_dalej` = 2 (dopełnianie i `stol.stan`) |
| `test_priorytety_stol.py::test_wyslij_pakowanie_bez_sposobu_dostawy_409` → `…_kladzie_kafel` | „Wyślij” kładzie kafel `zrodlo='biuro'` |
| `test_priorytety_stol.py::test_rozpoczete_pakowanie_bez_sposobu_dostawy_nie_wchodzi` → `…_wchodzi` | start stołów bierze oba rozpoczęte zamówienia |
| `test_priorytety_panel_api.py::test_priorytet_zamowienia_niekompletne_i_na_stole` (ostatnia asercja) | modal priorytetu: `w_kolejce == {'miejsce': 1, 'z': 1}` zamiast `None` |
| `test_priorytety_panel_api.py::test_wyslij_kody_bledow` | przypadek 409 `delivery_method_not_set` usunięty |
| `test_priorytety_panel_api.py::test_stoly_panelu_kolejnosc_i_licznik_jak_na_tablecie` | `kolejka_dalej` Pakowania 2 zamiast 1 (= `stol.stan`) |
| `test_priorytety_lista_produkcyjna_ui.py::test_komunikaty_wszystkich_kodow_stolu` | słownik JS bez `delivery_method_not_set` |

Nowe: `test_priorytety_panel_api.py::test_wyslij_pakowanie_bez_sposobu_dostawy_200` (HTTP „Wyślij”),
`test_priorytety_mobile.py::test_desk_pakowanie_bez_sposobu_dostawy_na_stole` (`GET desk` tabletu),
`test_priorytety_czytelnicy.py::test_stoly_panelu_pakowanie_bez_sposobu_dostawy_wroci_i_liczy_sie` (zakładka
Stanowiska / monitory: „wróci” i `kolejka_dalej`).

- **blog_seo:** `integrations/blog_seo`: **89 passed** (bez zmian).
- **Składnia 3.9:** wszystkie pliki `.py` zmienione na gałęzi od `f731b77c` (z logistyką 4.6 i tą kartą, 86 plików)
  skompilowane na `python:3.9-slim` — OK.

## Odstępstwa

1. **Poprawka komentarza z konfliktu jest w commicie zakresu 2, nie w merge commicie.** Pierwotnie dopisałem ją do
   scalenia (`git merge --no-commit`), ale przed pushem `git pull --rebase=merges` (gałąź przesunęła się o
   `ec30031a`) odtworzył scalenie od nowa i zmianę „ponad” scalenie zgubił; merge commit `8f60b221` poszedł już do
   origin, a `--force` jest zakazany. Skutek: między `8f60b221` a `2f3e6ce7` komentarz przy bramce stołu
   w `order_complete` był nieaktualny (kod poprawny). Wniosek dla kolejnych kart scalenia: poprawki do scalenia
   robić osobnym commitem po merge, albo pullować przed scaleniem.
2. Karta: „Commity: scalenie + jeden commit zakresu 2 + raport” — zgodnie; żadnych innych.

## Rozstrzygnięcia

1. **Pole `sposob_dostawy_ustawiony` w `GET /kolejka` zostaje** jako informacja dla biura (nic nie blokuje, kształt K2
   bez zmian). — Koszt, jeśli błędne: jedno pole do usunięcia w K8 i test kształtu.
2. **Kolumna `override_delivery_method` zostaje w odczycie kandydatów stołu** (`_KOLUMNY_ZAMOWIENIA`), choć stół jej
   już nie używa — serializer kafla czyta ją z tych samych obiektów (`transport`). — Koszt: jedna kolumna więcej
   w zapytaniu.
3. **Komunikat `delivery_method_not_set` usunięty ze słownika panelu**, nie zostawiony „na zapas” — żadna końcówka
   stołu go już nie zwraca. — Koszt, jeśli wróci: surowy kod błędu w modalu zamiast zdania (fallback `komunikatStolu`).
4. **Kafel Pakowania, któremu logistyka zdejmie sposób dostawy** (raport K3, rozstrzygnięcie 40 / pytanie 7) — temat
   znika: ZAKOŃCZ nie odmawia, kafel spakuje się normalnie. — Koszt: żaden.
5. **Sygnał po zwykłej zmianie sposobu dostawy** (pytanie 1 raportu K3-poprawka-1) — niepotrzebny: ustawienie sposobu
   nie zmienia już zbioru kandydatów Pakowania. — Koszt: żaden.
6. Nieużywane po zmianie parametry funkcji w `widok.py` zostawione (bez zmian u wołających). — Koszt: kosmetyka do K8.

## Pytania do Konrada

Brak blokujących. Do wiadomości: `docs/api-mobile-priorytety.md` (kontrakt K6) opisuje jeszcze stan sprzed 4.6
w kilku miejscach — lista niżej, aktualizuje centrala (karta K6 zapowiedziała to w §6 i w ostatniej liście).

## Stan gałęzi

- `claude/priorytety-produkcji` @ commit tego raportu (hash w meldunku do centrali), wypchnięte. Commity karty:
  `8f60b221` (merge 4.6), `2f3e6ce7` (zdjęcie odmowy, nad dokumentami K4-poprawki-1/K6 `6e6e1689`), raport.
- `claude/logistyka-etap-4` @ `f07b21ec` — nietknięta. `main` nietknięty.

## Co następny krok musi wiedzieć

- **K3-poprawka-2** (`GET desk` z `tryb`, rozstrz. 19) startuje z gałęzi zawierającej 4.6: na Pakowaniu nie ma już
  żadnego filtra sposobu dostawy w `stol._kandydaci`/`stan`/`dopelnij` — tryb `stary` bez dopełniania dotyczy więc też
  zamówień bez sposobu.
- **K5:** liczba kafli startowych Pakowania na kopii produkcji wzrośnie o zamówienia bez sposobu z licznikiem > 0
  (w K3-poprawce-1 na kopii był dokładnie 1 taki — liczony teraz, Pakowanie 0 → 1). W przeglądzie wyścigów:
  ZAKOŃCZ Pakowania nie ma już bramki 409 przed bramką stołu — kontrakt blokad bez zmian (blokady i ich kolejność
  te same, ubył tylko odczyt kolumny). `test_logistyka_pakowanie_bez_sposobu.py` (4.6) dochodzi do przebiegów.
- **K6 — kontrakt do aktualizacji** (`docs/api-mobile-priorytety.md` @ `6e6e1689`; K6 w `42275bcf` opisał już ZAKOŃCZ
  po 4.6 — kolejność kontroli, tabela błędów, wymagania appki są aktualne):
  - l. 143–145 i akapit l. 655–660 „**Stół Pakowania jeszcze nie przyjmuje zamówień bez sposobu dostawy**…” →
    przyjmuje od `2f3e6ce7`: zamówienie bez sposobu dostawy wchodzi na stół, do „Niekompletnych”, do `kolejka_dalej`,
    do startu stołów i da się je „Wysłać”; odnośnik `stol.py:495-503` nieaktualny (filtr usunięty);
  - l. 1211 (otwarte: „kiedy stół Pakowania zacznie przyjmować…”) → zamknięte tą kartą;
  - odnośniki do `mobile_api.py` za bramką stołu przesunęły się o +1 wiersz (komentarz przy bramce ma teraz 3 wiersze
    zamiast 2): bramka `:850` (było `:849`), więc `843-851` → `843-852`, `866-877` → `867-878`, `885` → `886`,
    `847` → `848`; `829-851` → `829-852`. Odnośniki `838-841` (komentarz 4.6) i `834-836` bez zmian.
- Panel: „Wyślij” na Pakowanie nie zna już kodu `delivery_method_not_set`; JS go nie tłumaczy.
