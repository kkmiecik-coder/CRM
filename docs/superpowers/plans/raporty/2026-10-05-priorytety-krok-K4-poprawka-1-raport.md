# Raport karty naprawczej K4-poprawka-1 — program „Priorytety produkcji”

- **Karta:** decyzje Konrada 5.10 i centrali po bramkach K4a/K4b (dziennik centrali, rozstrzygnięcie 18).
- **Plan:** sekcja „K4-poprawka-1” (Taski P1–P4) dopisana na końcu
  `docs/superpowers/plans/2026-10-05-priorytety-krok-K4a-lista-produkcyjna.md` przed pierwszą linią kodu (`c3a159da`);
  kroki odhaczone `- [x]`.
- **Gałąź:** worktree `.claude/worktrees/priorytety-k4p` (gałąź `claude/priorytety-k4p`, start `9b17e526` — nowszy
  od `fa6c5c2a` o commit K6, same dokumenty). Push wyłącznie `HEAD:claude/priorytety-produkcji` po każdym commicie,
  rebase przed pushem (przeplecione z commitami K6 i centrali, bez konfliktów).
- **Data:** 2026-10-05. **Sesja:** lokalna, Opus 5.5 (`claude-opus-5-5`), effort high. Przegląd: osobny agent Opus
  w świeżym kontekście (sekcja „Przegląd”).

## Zrobione

| Punkt karty | Commit | Co weszło |
|---|---|---|
| plan | `c3a159da` | Taski P1–P4 z testami w planie K4a. |
| 3 — serwer odmawia stołu przy progu 0 | `8195ba04` | `ustawienia.sprawdz_prog_wersji(zmiany)`: stan wynikowy (żądanie nałożone na bazę, Lakiernia pomijana) ze stanowiskiem w `stol` przy `priorytety_min_app_version_code` = 0 → **400 `prog_wersji_wymagany`**, `pole` = `min_app_version_code`, komunikat „Najpierw wpisz minimalną wersję appki (kod wersji nowej appki). Przy progu 0 stół objąłby też starą appkę: dostałaby odmowę ZAKOŃCZ na wszystkim spoza stołu.” Odmowa tylko, gdy żądanie kombinację **wprowadza** (nowe `stol` przy progu wynikowym 0 albo obniżenie progu z > 0 do 0). Router `ustawienia_put` woła ją po `waliduj`, przed zapisem (błąd odczytu → 500 z rollbackiem). „Włącz stoły” przy progu 0 nie pyta „Włączyć stoły?” (odmowa i tak nic nie zmienia) — toast z komunikatem serwera, pole progu podświetlone; stare ostrzeżenie „UWAGA: próg wersji 0” usunięte. |
| 1 — Logistyka, ★ w wąskim widoku | `a4d1243a` | Sam CSS: `@container lg-tabela (max-width: 1035px)` chowa `th/td.lg-k-gwiazdki`. Stare zwężenie ★ w bloku ≤ 860 px usunięte (kolumny tam już nie ma). `colspan="11"` bez zmian (kolumna ukryta jak `lg-k-adres`). Wersja `logistics.css` `20261005b`. |
| 2 — potwierdzenie hurtu gwiazdek | `b731c75e` | `Priorytety.potwierdz({tytul, tresc, zatwierdz})` — natywny `<dialog>` z „Anuluj” (fokus startowy) i przyciskiem zatwierdzającym bez autofocusu; Esc (`cancel`) = odmowa, fokus wraca od razu; treść przez `textContent`. `showBulkStarsPicker`: okno przy `n === 0` albo `ids.size > PROG_POTWIERDZENIA_HURTU` (10) — „Zdjąć gwiazdki? Zaznaczone zamówienia: N. Każde zostanie bez gwiazdek (0 z 5).” / „Ustawić gwiazdki hurtem? Zaznaczone zamówienia: N. Każde dostanie 3 z 5 gwiazdek (★★★).”; przyciski „Zdejmij gwiazdki (N)” / „Ustaw ★★★ (N)”. Logistyka nie ma hurtu gwiazdek (jedyny wybór to komórka ★ pojedynczego wiersza) — bez zmian. Wersje: `priorytety.js` `20261005e`, `priorytety.css` `20261005d`, `products-module.js` `20261005c`. |
| poprawka z przeglądu | `8ad29f6e` | „Włącz stoły” przy progu 0 ostrzega o niezapisanych zmianach karty (serwer przepuszcza zapis bez zmian przy zastanym `stol` na sześciu stanowiskach + 0, a odpowiedź nadpisuje pola). Wersja `config-module.js` `20261005c`. |
| raport | (ten commit) | — |

### Próg kolumny ★ (punkt 1) — jak ustalony

Ramka tabeli zawsze ma `overflow: auto`, więc „lista przewija się w bok” wtedy, gdy minimalna szerokość treści tabeli
przekracza ramkę. Pomiar na podglądzie (kopia danych produkcji, 179 zamówień w zakładce), szerokość listy zmieniana
zmienną pastylki `--lg-mapa-kolumna`, minimalna szerokość treści z ★ / bez ★ wg kontenera `lg-tabela`
(skoki na istniejących progach 760 / 860 / 1100):

| kontener `lg-tabela` | z ★ | bez ★ |
|---|---|---|
| ≤ 760 px | 858 | 804 |
| 761–860 px | 890 | 836 |
| 861–1099 px | 1016 | 944 |
| ≥ 1100 px | 1080 | 1008 |

Tabela z ★ mieści się od 1016 px **widocznej** ramki; zapytanie kontenera wlicza pionowy suwak ramki (w podglądzie
6 px: przy kontenerze 1018 px widoczne 1012 px i tabela z ★ przewijała się o 4 px), w Windows klasycznym do 17 px →
próg 1035 px. Sprawdzone po zmianie: ★ widoczna od kontenera 1038 px, tabela z nią nigdzie się nie przewija.
Wąski widok z karty (lista obok mapy przy 1100–1440 px okna: ~680–900 px; mapa nad listą do ~890 px; tablet) — ★
schowana. 1920 px okna (lista ~1070 px z rozwiniętym panelem bocznym, ~1230 px ze zwiniętym) — bez zmian.
Próg 1100 (istniejący „szeroki układ”) odrzucony: chowałby ★ przy 1920 px z rozwiniętym panelem, gdzie tabela się
mieści.

## Testy

- Nowe / zmienione: `tests/test_priorytety_panel_api.py` (+9: `test_stol_z_progiem_zero_w_jednym_zadaniu_odrzucony`,
  `test_stol_przy_zapisanym_progu_zero_odrzucony[brak_wiersza|zero]`, `test_obnizenie_progu_do_zera_przy_stole_odrzucone`,
  `test_stol_z_progiem_w_jednym_zadaniu_przechodzi`, `test_stol_przy_zapisanym_progu_przechodzi`,
  `test_zastany_stol_przy_progu_zero_nie_blokuje_wycofania_ani_innych_zmian`,
  `test_lakiernia_w_stol_w_bazie_nie_wymaga_progu`, `test_prog_wersji_odmowa_po_walidacji_pol`; dwa testy K2 włączające
  `stol` dostały próg 173), `tests/test_priorytety_czytelnicy.py` (+1 `test_wlacz_stoly_przy_progu_zero_komunikat_serwera`;
  asercja `=== 0` w `test_skrypt_wlacz_stoly_jednym_put` zdjęta), `tests/test_priorytety_lista_produkcyjna_ui.py` (+3:
  `test_hurt_gwiazdek_potwierdzenie_przy_zdjeciu_albo_ponad_progu`, `test_okno_potwierdzenia_fokus_na_anuluj`,
  `test_podbite_wersje_po_potwierdzeniu_hurtu`), `tests/test_priorytety_logistyka_ui.py` (+1
  `test_kolumna_gwiazdek_chowana_gdy_tabela_przewija_sie_w_bok`), `tests/test_druk_panel_ui.py` (wersja
  `config-module.js` 20261005 → 20261005c).
- TDD: każdy punkt RED obejrzany przed implementacją (punkt 3: 5 failed bez kodu; punkt 2: 3 failed; punkt 1: 1 failed;
  poprawka z przeglądu: 1 failed).
- Pliki dotknięte: `docker compose -p priorytety run --rm --no-deps app pytest tests/test_priorytety_panel_api.py
  tests/test_priorytety_ustawienia.py tests/test_priorytety_czytelnicy.py tests/test_druk_panel_ui.py
  tests/test_priorytety_lista_produkcyjna_ui.py tests/test_priorytety_logistyka_ui.py -q -p no:cacheprovider` — zielone;
  pliki logistyki czytające `logistics.css` (7 plików) — 157 passed.
- **Pełny pakiet:** `docker compose -p priorytety run --rm --no-deps app pytest tests/ -q -p no:cacheprovider` na `8ad29f6e` (po `docker ps` — poczekał na cudzy przebieg `priorytety-app-run-*`): **6779 passed, 3 skipped, 0 failed** (7 min 36 s). Różnica wobec punktu wyjścia 6765: +14 nowych testów (9 + 1 + 3 + 1).

## Oględziny (podgląd 127.0.0.1:5006, kontener `priorytety-k4p`, baza `priorytety_podglad`)

Wbudowana przeglądarka, sesja admina z ciasteczka wygenerowanego w kontenerze (`login_user`, host
`podglad-k4p.localhost`, chwilowa strona na 5016 wyłączona zaraz potem), bez haseł. Zapis gwiazdek przechwycony
w stronie (podmieniony `fetch` dla `PUT /zamowienia/gwiazdki`) — nic nie trafiło do bazy.
1. Logistyka 1440 px (rozwinięty panel): bez kolumny ★; 1920 px: ★ jest, tabela bez przewijania w bok.
2. Hurt, 1 zamówienie, Enter na „Bez gwiazdek” → okno „Zdjąć gwiazdki?”, fokus na „Anuluj”, zero zapisów; drugi
   Enter → okno zamknięte, zero zapisów, fokus na przycisku „Ustaw gwiazdki”. 3 ★ dla 1 zamówienia → bez okna, jeden
   zapis (przechwycony). Wszystkie zaznaczone (179 zamówień), 3 ★ → okno „Ustawić gwiazdki hurtem?”; Esc → bez zapisu.
3. Konfiguracja, próg 0, „Włącz stoły” → toast z komunikatem serwera, pole progu podświetlone; `GET /ustawienia` po
   tym: wszystkie stanowiska `stary`, próg 0.
- Konsola: tylko błędy CSP ramki widżetu czatu (`chat.woodpower.pl`, środowisko podglądu).
- Zrzuty (poza repo, katalog wyników narzędzi sesji): Logistyka 1440 i 1920 px, okno „Zdjąć gwiazdki?”, okno
  „Ustawić gwiazdki hurtem?”, toast „Włącz stoły”.
- Po oględzinach: kontener `priorytety-k4p` usunięty, pusty `config/core.json` z worktree usunięty, rozmiar okna
  przeglądarki przywrócony.

## Odstępstwa

1. Próg punktu 1 to 1035 px, nie istniejący próg 1100 ani 860 z CSS (uzasadnienie wyżej). Karta: „ustal na kodzie” —
   na kodzie nie było progu odpowiadającemu przewijaniu (ramka przewija się zawsze, gdy treść jest szersza; komentarze
   „~706 px” i „~750 px” były nieaktualne), więc próg z pomiaru.
2. Dodatkowy commit `8ad29f6e` (poprawka z przeglądu) poza zasadą „jeden commit na punkt” — regresja wprowadzona
   w punkcie 3, poprawiona osobnym `fix`.

## Rozstrzygnięcia (numerowane; koszt, jeśli błędne)

1. **Odmowa tylko przy wprowadzeniu kombinacji** `stol` + próg 0, nie przy każdym stanie wynikowym z tą kombinacją.
   Zastany stan (sprzed poprawki albo wpisany ręcznie w bazie) nie blokuje wycofania stanowiska na `stary`, zmiany K
   ani innych pól. — Koszt: zastany `stol` + 0 może trwać, dopóki ktoś go nie poprawi (K7: stan sprawdzany po
   włączeniu stołów).
2. **Lakiernia pomijana** w regule (zastany wiersz `priorytety_tryb_painting = stol` nie wymaga progu) — bramka i tak
   traktuje ją jako `stary` (spec 5.5). — Koszt: żaden.
3. **Kod błędu `prog_wersji_wymagany`, `pole` = `min_app_version_code`** (UI podświetla pole progu, nie wiersz
   stanowiska). Kolejność: najpierw błędy pól (`waliduj`), potem reguła stanu wynikowego. — Koszt: żaden.
4. **Reguła bez blokady** (odczyt bazy, potem zapis): dwa równoległe `PUT /ustawienia` (A obniża próg do 0 przy braku
   `stol`, B ustawia `stol` przy progu 5) mogą razem dać `stol` + 0 — ten sam wyścig dwóch `PUT /ustawienia`, który
   już jest na liście K5. — Koszt: dwóch adminów w tej samej chwili; skutek jak przed poprawką.
5. **„Włącz stoły” przy progu 0 bez pytania „Włączyć stoły?”** — żądanie idzie, serwer odmawia; jedyne pytanie to
   ostrzeżenie o niezapisanych zmianach karty, gdy są. — Koszt: żaden zapis bez decyzji (serwer przepuszcza wtedy
   tylko zapis bez zmian).
6. **Próg potwierdzenia hurtu 10 w `products-module.js`** (`PROG_POTWIERDZENIA_HURTU`), nie w `priorytety.js` —
   jedynym hurtem gwiazdek jest Lista produkcyjna. — Koszt: druga stała przy dodaniu hurtu gdzie indziej.
7. **Okno potwierdzenia własne (`<dialog>`), nie `confirm()`** — w natywnym `confirm()` Enter zatwierdza (OK ma fokus),
   więc „Enter nie zatwierdza” nie byłoby spełnione. — Koszt: ~50 linii JS i CSS.
8. **Kolumna ★ chowana samym CSS** — bez JS i bez mierzenia w przeglądarce; reaguje też na pastylkę. Próg z danych
   kopii produkcji — przy dłuższych nazwach klientów tabela z ★ może przewijać się o kilka px tuż nad progiem. —
   Koszt: kosmetyka; K5 może powtórzyć pomiar.

## Przegląd

Agent Opus w świeżym kontekście (tylko odczyt) na commitach `8195ba04`, `a4d1243a`, `b731c75e`: nic ważnego, 4 drobne.
- D1 wyścig dwóch `PUT /ustawienia` → Rozstrzygnięcie 4, K5.
- D2 „Włącz stoły” przy progu 0 pomijało ostrzeżenie o niezapisanych zmianach, a przy zastanym `stol` na sześciu
  stanowiskach + 0 serwer przepuszcza zapis bez zmian i nadpisuje pola karty → **poprawione** (`8ad29f6e`, test najpierw).
- D3 sortowanie Logistyki po ★ (zapamiętane w `localStorage`) działa dalej w wąskim widoku, ale nagłówka z kierunkiem
  sortowania nie widać → pytanie 1, bez zmiany (poza zakresem karty).
- D4 zapas na suwak może chować ★ przy kontenerze 1016–1035 px, gdy tabela by się zmieściła — pomiar w podglądzie
  potwierdza, że kontener wlicza suwak (6 px), więc zapas 17 px jest na Windows klasyczny; w podglądzie ★ znika
  ~13 px za wcześnie. Bez zmiany (Rozstrzygnięcie 8).

## Pytania do Konrada

1. **Sortowanie Logistyki po ★ w wąskim widoku:** kolumna znika, ale zapamiętane sortowanie po gwiazdkach zostaje
   (lista ułożona po czymś, czego nie widać). Zostawić, czy w wąskim widoku przełączać sortowanie ★ na domyślne?
2. Próg potwierdzenia hurtu = **ponad 10** zamówień (11 i więcej pyta), zdjęcie gwiazdek pyta zawsze, także przy
   jednym zamówieniu — tak jak w decyzji?

## Stan gałęzi

- `origin/claude/priorytety-produkcji`: commity karty `c3a159da`, `8195ba04`, `a4d1243a`, `b731c75e`, `8ad29f6e`
  (przeplecione z commitami K6 i centrali), commit tego raportu — hash w odpowiedzi sesji. Wszystko wypchnięte.
- `main` i główny checkout nietknięte. Kontener `priorytety-k4p` (5006) usunięty, pusty `config/core.json` usunięty
  z worktree. 5002–5005 i 5008 (K6) nieruszane.

## Co następny krok musi wiedzieć

### K5 (przegląd P1, spec, CLAUDE.md)
- Do specu (10. Obsługa błędów): `PUT /ustawienia`, stan wynikowy z `tryb = stol` (bez Lakierni) przy
  `min_app_version_code = 0`, który żądanie wprowadza → 400 `prog_wersji_wymagany` (`pole` = `min_app_version_code`);
  zastany stan nie blokuje innych zapisów ani wycofania. Spec 5.8 krok 4 i 8.6 („0 = brak bramki”): przy `stol`
  próg 0 jest teraz niedostępny z panelu.
- Wyścig dwóch `PUT /ustawienia` obejmuje też regułę progu (Rozstrzygnięcie 4) — przy decyzji o blokadzie zapisu
  ustawień objąć nią także `sprawdz_prog_wersji`.
- Spec 7.1/7.2: hurt „Ustaw gwiazdki” z potwierdzeniem (zdjęcie gwiazdek albo > 10 zamówień); Logistyka: kolumna ★
  tylko przy kontenerze tabeli ≥ 1036 px. Ewentualny ponowny pomiar progu na świeżej kopii (Rozstrzygnięcie 8).
- `window.Priorytety.potwierdz` — wspólne okno potwierdzenia do ponownego użycia.
- Usterka `config_service.update_multiple_configs` (K4b) — nietknięta, zgodnie z kartą.

### K6 / K7
- K6: kod `prog_wersji_wymagany` jest błędem panelu, nie trafia do kontraktu appki (API mobilne bez zmian).
- **K7 runbook (krok 4 z raportu K4b):** „Przy progu 0 przycisk ostrzega — serwer tego nie blokuje” jest nieaktualne:
  przy progu 0 „Włącz stoły” dostaje odmowę serwera z komunikatem „Najpierw wpisz minimalną wersję appki…”. Kolejność
  zostaje: wpisać kod wersji nowej appki, potem „Włącz stoły” (jeden zapis). Gdyby wszystkie tablety miały już nową
  appkę i próg miał być 0 — nie da się; wpisać kod wersji nowej appki (działa tak samo dla nowych tabletów).
- K7 notatka dla biura: hurtowe „Ustaw gwiazdki” pyta o potwierdzenie przy zdjęciu gwiazdek i przy więcej niż
  10 zamówieniach; w Logistyce na węższym ekranie (lista obok mapy) kolumny ★ nie ma — gwiazdki w Liście produkcyjnej.
- Wersje statyk podbite: `config-module.js` `20261005c`, `priorytety.js` `20261005e`, `priorytety.css` `20261005d`,
  `products-module.js` `20261005c`, `logistics.css` `20261005b`.
