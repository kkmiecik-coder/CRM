# Raport kroku K4b „Czytelnicy rangi: Stanowiska, dashboard, Konfiguracja, monitory” — program „Priorytety produkcji”

- **Sesja:** lokalna, Opus 5.5, effort high (zgodnie z kartą). Worktree `.claude/worktrees/priorytety-k4b`, gałąź
  `claude/priorytety-k4b`, push na `origin/claude/priorytety-produkcji` po każdym Tasku (rebase przed pushem).
- **Baza:** `2634c5b8` (zgodna z kartą). Równolegle pracowały K4a i K3-poprawka-1 — ich commity weszły rebase'em bez
  konfliktów (także w `dashboard.html`).
- **Plan:** `docs/superpowers/plans/2026-10-05-priorytety-krok-K4b-czytelnicy-rangi.md`, uzupełniony przed kodem
  o Taski z karty 2a, 5a, 7a (`49ff09b4`); wszystkie kroki `- [x]`.

## Zrobione (po Taskach)

| Task | Commit | Co |
|---|---|---|
| plan | `49ff09b4` | Decyzje karty (wariant A, „Adam K.”, wartości domyślne pytań 2–4) i Taski 2a, 5a, 7a dopisane przed kodem |
| 1 | `e524a605` | `widok.stoly_panelu(stanowiska=None)` (filtr), `liczba_pilnych_zamowien()`, `priorytet_zamowien(order_ids)` z kolumn (indeks widocznego szczebla, nieaktywne bez rangi), `plakietka_szczebla`; `stale.ETYKIETY_POWODOW_ODLOZENIA` + `powod_etykieta` w odłożonych; makra Jinja `components/_priorytet_plakietki.html` (`gwiazdki`, `plakietka`) |
| 2 | `bce30f26` | Zakładka Stanowiska czyta `widok` (stół, odłożone z powodem/notatką/pracownikiem, niekompletne, 15 kafli kolejki; Lakiernia — 15 pozycji listy po wykończeniu z nazwą grupy); bez progów rangi, `priority-section`, `startProcessing`; kropka = odłożone; błąd priorytetów nie kładzie zakładki. **Podpięta w panelu (wariant A):** przycisk „Stanowiska”, `loadStationsTab()` przez `fetch` (bez pamięci GET-ów), odświeżanie przez `ProductionApp.loadTabContent` z osłoną timera, bez skrótu Ctrl |
| 2a | `8aabdc85` | Plakietki źródła kafla (wysłane przez biuro / rozpoczęte przed startem / doróbka), „Zdejmij ze stołu” (`POST …/stoly/<kod>/zdejmij`, potwierdzenie, podpis „kafel wróci przy następnym dopełnieniu” dla doróbki i kafla, który stanąłby pierwszy), stół dłuższy niż K (lista przewijana, „n/K — ponad K”), **widma** z D2 raportu K3 (`widma` w `GET /stoly`: kafel bez pozycji na stanowisku, pozycja już nie czeka, inna jednostka) z „Zdejmij” |
| 3 | `4ce210b4` | `/dashboard-stats`: `high_priority_count` = zamówienia na ★★★★★, ★★★★, „Po terminie”, trasach (suma liczników drabiny), alert „Dużo pilnych zamówień” > 10, `null` przy błędzie; test regresji `is_priority` w raporcie terminów |
| 4 | `aae0ca84` | `PUT/GET /ustawienia`: `deadline_default_days`, `deadline_finished_days` (1–90, bez przeliczenia); `update-configs` bez kluczy terminów i martwych; `update-config` odrzuca `priorytety_*` i `DEADLINE_*`; brak odczytu `prod_priority_config` w zakładce; `PRIORITY_RECALC_INTERVAL_HOURS` z `config_service` |
| 5 | `89c43dce` | Karty „Terminy” i „Stół stanowisk” (7 wierszy, Lakiernia „Lista (bez stołu)” bez pól), zapis własnym przyciskiem przez `PUT /ustawienia` (tylko zmienione pola, 400 → podświetlone pole, 403 → karty zablokowane); martwe klucze usunięte z JS/szablonu/`EXPECTED`; wersje `config-module.js`/`config-tab.css` → `20261005` |
| 5a | `1199a0b8` | Sekcja „Start stołów”: podgląd `GET /start` (kafle rozpoczęte per stanowisko, rozwijane), „Przygotuj stoły” (`POST /start/przygotuj`, potwierdzenie), „Włącz stoły” = **jeden** `PUT /ustawienia` (próg wersji z pola + `tryb=stol` dla 6 stanowisk, bez Lakierni) z ostrzeżeniem przy progu 0; kolejność kroków runbooka w sekcji |
| 6 | `ce49486e` | Monitory: karty po `ProductionOrder.id`, doróbki pierwsze, ranga z kolumny NULLS LAST, gwiazdki i plakietka z kolumn (bez `policz`), `stol` w AJAX (`_stol_monitora`, Lakiernia `null`), Lakiernia po liście tabletu z grupą wykończenia; monitor zbiorczy — jedna funkcja `_zamowienia_monitora_ogolnego()` dla HTML i AJAX, po randze, bez N+1; `lista.nazwa_grupy_wykonczenia` |
| 7 | `78d60381` | Szablony: „TERAZ”, „Odłożone”, „Dalej w kolejce” (tryb `stol`), gwiazdki/plakietki, karta „na stole”; JS: `escapeHtml`, `gwiazdkiHTML`, `plakietkaHTML`, `renderStolSekcje`, klucz karty `order_id`, przestawianie kart wg serwera (krok 3a) bez resetu przewijania; wersje statyk monitorów |
| 7a | `97d1049e` | Źródło kafla na monitorze (te same plakietki co zakładka), pracownik odłożenia „Imię I.” (`pracownik_krotko` przez `stol.imie_z_inicjalem`; panel dalej pełne imię i nazwisko) |
| przegląd | `aa738002` | Poprawki przeglądu końcowego: W1 (`wroci` z pozycjami omijającymi), odświeżanie zakładki tylko gdy widoczna, ostrzeżenie „Włącz stoły” o niezapisanych zmianach |
| 8 | (ten raport) | Pełny pakiet, składnia 3.9, grepy, przegląd końcowy, raport |

## Testy

- **Punkt wyjścia** (baza `2634c5b8`, przed kodem): `docker compose -p priorytety run --rm --no-deps app pytest tests/ -q
  -p no:cacheprovider` → **6592 passed, 3 skipped, 0 failed** (7 min 14 s).
- **Po K4b:** **6765 passed, 3 skipped, 0 failed** (7 min 14 s) na `aa738002` (kod K4b + commity K4a i K3-poprawki-1, które weszły rebase'em). Wcześniejszy przebieg przed poprawkami przeglądu: 6759 passed, 3 skipped, 0 failed. Różnica wobec punktu wyjścia (+173) to nowe testy K4b (58 w `test_priorytety_czytelnicy.py` — część parametryzowana, 23 w `test_priorytety_monitory.py` — część parametryzowana, 5 w `test_priorytety_panel_api.py`, 1 w `test_reports_service.py`) oraz testy równoległych sesji. Pakiet uruchamiany, gdy żaden inny kontener `priorytety-app-run-*` nie działał.
- Nowe pliki: `tests/test_priorytety_czytelnicy.py` (Taski 1–5a, 7a), `tests/test_priorytety_monitory.py` (Taski 6–7a);
  dopisane: `tests/test_priorytety_panel_api.py` (terminy w `PUT /ustawienia`, zbiór kluczy `GET /stoly` + `widma`),
  `tests/test_reports_service.py` (regresja `is_priority`), `tests/test_monitory_krawedzie.py` (nowe tabele w `TABELE`),
  `tests/test_druk_panel_ui.py` (znacznik `<!-- Terminy -->`, wersje `20261005`).
- Testy Review Focus planu: wszystkie istnieją pod nazwami z planu (wyjątki — „Odstępstwa” p. 4).
- RED przed implementacją pokazany dla każdego Taska; Task 1 — w osobnym worktree na czystej bazie (implementacja
  powstała przed pierwszym uruchomieniem), test regresji raportu terminów zielony od razu (z założenia).
- **JS:** `node --check` (lokalnie, v22) — `config-module.js`, `station-monitor.js` OK. Skrypt inline zakładki Stanowiska:
  test parzystości apostrofów (błąd składni wyszedł na podglądzie — „Rozstrzygnięcia” 9).
- **Składnia 3.9:** `ast.parse(..., feature_version=(3, 9))` dla zmienionych `.py` → OK; brak adnotacji `X | Y`.
- **Grep kontrolny (Task 8 Step 3):** progi rangi w czytelnikach — pusto; martwe klucze w `modules/` i `app.py` — pusto
  w kodzie (trafienia wyłącznie w lokalnym logu `modules/logging/logs/*.log`, ignorowanym przez git — to wiersze bazy
  podglądu wypisane w logu DEBUG); `DEADLINE_*` w `config_api.py` — pusto; `db.session.commit|dopelnij|with_for_update`
  w czytelnikach — jedno trafienie, docstring `widok.wejscie_kandydatow` sprzed K4b („stół (`stol.dopelnij` w K3)”).
- **Czasy na podglądzie** (kopia danych produkcji `priorytety_podglad`, serwer deweloperski Flaska):
  `GET /production/api/stations-tab-content` 247 / 263 / 276 ms; `GET /stations/ajax/monitors/gluing` 43 ms (21 zamówień,
  78 pozycji); `GET /stations/ajax/monitor` 52 ms (163 zamówienia, 0 powtórzonych numerów).

## Zrzuty

Poza repo (dane z kopii produkcji): `C:/Users/Grafik/Documents/woodpower-podglady/priorytety/k4b/zrzuty/` —
`task2-zakladka-gora.jpg`, `task2-zakladka-lakiernia.jpg`, `task2a-stol-zrodlo-zdejmij.jpg` (Wyślij → 4 kafle „wysłane
przez biuro”, podpis „wróci przy dopełnieniu”), `task5-karty-przed.jpg`, `task5-blad-pola-k9.jpg`,
`task5-stol-stanowisk-pelna-szerokosc.jpg`, `task5a-start-stolow.jpg`, `task5a-stol-15-ponad-k-po-przygotuj.jpg`
(Sklejanie 15/2 po „Przygotuj”), `task7-a-monitor-tryb-stary.jpg`, `task7-b-monitor-teraz-odlozone.jpg`,
`task7-monitor-zbiorczy.jpg`, `task7-monitor-lakierni.jpg`. Zrzutu z „Imię I.” nie zapisuję (imię pracownika z kopii
danych) — format sprawdzony wyrażeniem regularnym.

**Oględziny (wbudowana przeglądarka, port 5007):**
- Zakładka Stanowiska: 7 kart, kolejki, niekompletne Formatowania i Pakowania, Lakiernia z grupami. „Wyślij” (API panelu)
  4 kafli na Sklejanie → plakietki i podpisy, klik „Zdejmij ze stołu” → kafel znika, zakładka odświeża się sama.
- Konfiguracja: wartości z bazy; K Sklejania 1 + próg 4 → „Zapisano. Kolejka przeliczona.”; K = 9 → pole podświetlone
  i komunikat serwera; `DEADLINE_DAY_TYPE` → kalendarzowe i z powrotem.
- Start stołów: podgląd 21 kafli (1 / 0 / 15 / 5 / 0 / 0 — zgodnie z K3-poprawką: sam licznik); „Przygotuj” →
  `+1, +0, +15, +5, +0, +0`; zakładka Stanowiska pokazuje Sklejanie 15/2 „ponad K”; „Włącz” z progiem 0 → ostrzeżenie
  w potwierdzeniu, 6 stanowisk `stol`, Lakiernia `stary`.
- Monitory: (a) tryb `stary` — karty po randze, plakietki trasy/„Po terminie”/„Blisko terminu”/„Rozpoczęte”;
  (b) tryb `stol`, dopełnienie i Odłóż (symulacja tabletu po stronie serwera, „Rozstrzygnięcia” 13) → po
  auto-odświeżeniu (60 s), bez przeładowania strony: „TERAZ 1/2”, „Odłożone 1” z notatką (znaczniki `<b>` w notatce
  ucieczone), karta zamówienia z kafla wyróżniona, „Dalej w kolejce”; (c) ★★★★★ zamówieniu z 9. miejsca → po odświeżeniu
  pierwsze, ten sam węzeł DOM, `scrollTop` bez zmian. Monitor zbiorczy: kolejność HTML = AJAX. Lakiernia: bez stołu.
- **Stan bazy podglądu przywrócony:** stoły puste (wszystkie testowe kafle zdjęte „Zdejmij”), tryby `stary`, K = 2,
  próg 3, `robocze`, gwiazdki zamówienia z próby (c) = 0, lista IP monitorów przywrócona. Zostają wpisy
  `prod_priority_log` (`wyslanie`, `zdjecie`, `start_stolow`, `odlozenie`, `odlozenie_zamkniete`, `ustawienia`,
  `gwiazdki`) — log, bez wpływu na stan.

## Odstępstwa od planu

1. **Zakres rozszerzony kartą:** Taski 2a, 5a, 7a (dopisane do planu przed kodem, `49ff09b4`), osobne commity.
2. **`stoly_panelu()` bez filtra = 6 stanowisk** (plan: 7) — K3 Task 5a / spec ustalenie 15: Lakiernia bez stołu.
3. **Polecenia testów i podglądu wg karty** (`docker compose -p priorytety run …`, kontener `priorytety-k4b` na 5007),
   nie wg planu (`docker compose exec`).
4. **Testy Review Focus — podział między Taski:** asercje HTML sekcji „TERAZ”/„Odłożone” i gwiazdek monitora są
   w testach Taska 7 (`test_monitor_stol_teraz_i_odlozone` — HTML; `test_monitor_html_gwiazdki_i_plakietka_trasy`),
   a w Tasku 6 część AJAX (`test_monitor_stol_w_ajax_i_na_stole`) — szablony powstają w Tasku 7. Test planu
   `test_monitor_gwiazdki_i_plakietka_trasy` istnieje (AJAX obu monitorów). `test_monitor_bez_stolu_bez_sekcji` — Task 7.
5. **Test K3 `test_stoly_panelu_ksztalt`** (zbiór kluczy) uzupełniony o `widma` — plan „Files” Taska 2a.
6. **Plan Task 5a — test „fetch na literał adresu”:** sprawdzam stałą `ADRES_USTAWIEN_PRIORYTETOW` (jedna definicja
   adresu dla kart i „Włącz stoły”).
7. **Podgląd z własną kopią `core.json`** (inne nazwy ciasteczek) i montażem katalogu `config` zamiast pliku —
   „Rozstrzygnięcia” 10–11.
8. **Liczba commitów:** 12 (plan + 10 Tasków z 2a/5a/7a + poprawki przeglądu) + raport; plan przewidywał 8.

## Rozstrzygnięcia podjęte w trakcie (numerowane; koszt, jeśli błędne)

1. **Makro plakietki bierze kod tagu z etykiety** (mapa w makrze i w JS, odwrotność `widok.ETYKIETY_TAGOW` pilnowana
   testem) — krótki szczebel kafla K2 (`_krotki`) nie niesie `tag`, a dopisanie go łamie kontrakt K2 (test dokładnej
   równości). — Koszt: druga kopia trzech etykiet pod testem.
2. **Monitory czytają kolumny, nie `policz()`** (`priority_rank`, `priority_rung` → indeks wśród szczebli WIDOCZNYCH,
   `priority_stars`) — telewizor co 30–60 s nie liczy całej kolejki. — Koszt: tag „Po terminie”/„Rozpoczęte” spóźniony do
   najbliższego `utrwal()` (cron co godzinę).
3. **Monitory grupują po `ProductionOrder.id`** (numer zamówienia powtarza się co rok), klucz karty w JS = `order_id`. —
   Koszt: na kopii danych 0 powtórzonych numerów wśród 163 zamówień, więc dziś bez widocznej zmiany; po przełomie roku
   dwie karty zamiast jednej zlanej.
4. **Terminy przeniesione do `PUT /ustawienia`** (`deadline_default_days`/`finished_days`, 1–90, log `ustawienia`, bez
   `utrwal`); `update-configs` i `update-config` ich nie przyjmują. — Koszt: zakres 1–90 węższy niż walidacja
   `config_service` (1–365); import z Base. czyta je nadal przez `config_service` (pamięć podręczna 60 min na proces —
   inne workery gunicorna widzą nową wartość z opóźnieniem do godziny; tak samo było przed K4b).
5. **`widma` jako osobny klucz `GET /stoly`** (zawsze obecny), nie wpisy w `stol`/`odlozone` — kafel-widmo nie ma pól
   kafla (pozycji już nie ma na stanowisku). — Koszt: klucz więcej w kontrakcie panelu (K4a nie używa `GET /stoly`).
6. **`wroci_przy_dopelnieniu`** = doróbka albo kafel przed dzisiejszym pierwszym kandydatem w kolejności kandydatów
   liczonej bez ukrywania stołu (jedno dodatkowe `kandydaci_stanowiska` na stanowisko, bez zapytań); Pakowanie bez
   sposobu dostawy nie wraca. — Koszt: gdy po zdjęciu na stole nadal jest ≥ K kafli, podpis mówi „wróci”, choć wejdzie
   dopiero po zejściu stołu poniżej K.
7. **Nazwa grupy Lakierni: rodzaj · typ koloru · kolor · połysk** (puste pomijane; jedna funkcja
   `lista.nazwa_grupy_wykonczenia` dla zakładki i monitora) — plan: rodzaj · kolor · połysk; klucz grupy ma 4 pola (K3
   rozstrz. 26). — Koszt: dłuższy napis.
8. **Domyślne terminów 16/21 w `stale`** (`TERMIN_SUROWE_DNI`, `TERMIN_WYKONCZONE_DNI`) — `config_service._default_values`
   jest prywatne; równość pilnuje test. — Koszt: druga kopia dwóch liczb pod testem.
9. **Test parzystości apostrofów w skrypcie inline zakładki** — prawdziwy znak nowej linii w napisie JS wyłączał cały
   skrypt (wyszło dopiero w przeglądarce; obraz testowy nie ma node). — Koszt: test heurystyczny.
10. **Podgląd 5007 z własną kopią `core.json`** (`k4b_session`/`k4b_remember`) — ciasteczka nie rozróżniają portów,
    wspólna nazwa `session_prio` nadpisywałaby sesję K4a na 5006. Ciasteczko wstrzyknięte z `path=/production` (strona
    `/login` zakłada HttpOnly na `/`, którego JS nie nadpisze). — Koszt: żaden.
11. **Montaż katalogu `config` (kopia) zamiast pliku `core.json`** — montaż pliku zostawiał w worktree pusty
    `config/core.json`, przez który `tests/test_daily_report_cli.py` dawał 7 błędów. — Koszt: żaden.
12. **Karta „Stół stanowisk” na całą szerokość siatki**, przyciski kart i startu w klasach Bootstrap (podgląd: tabela
    7 stanowisk przewijała się poziomo, przyciski paska zmian wyglądały jak goły tekst). — Koszt: wygląd.
13. **Tablet na podglądzie symulowany skryptem w kontenerze** (`stol.dopelnij` jak `GET desk`, `stol.odloz` pod blokadą
    zamówienia jak `POST postpone`) zamiast tokenu urządzenia — bez poświadczeń. — Koszt: sam router `desk` niesprawdzony
    w przeglądarce (pokrywają go testy K3).
14. **Brama Dockera `172.19.0.1` dopisana na czas oględzin do `STATION_ALLOWED_IPS` w bazie podglądu** (karta: „IP
    podglądu na liście dozwolonych lokalnie”); oryginał zapisany i przywrócony po Tasku 7a. — Koszt: żaden.
15. **Wersje `?v=20261005` dla `station-monitor.js` i CSS monitorów** — telewizor ładował statyki bez wersji, więc po
    wdrożeniu mógłby użyć starego JS przy nowym HTML. — Koszt: żaden.
16. **Monitor zbiorczy: gwiazdki/plakietka osobnym wierszem** (w wierszu numeru zasłaniały numer Base.), `.stat-item[hidden]`
    `display: none` („Dalej w kolejce” był widoczny w trybie `stary`, bo `display:flex` wygrywał z `hidden`). — Koszt: wygląd.
17. **„Imię I.” przez `stol.imie_z_inicjalem` z K3-poprawki-1** zamiast własnej funkcji (jedna reguła dla tabletu
    i monitora); w `stoly_panelu` pole `pracownik_krotko` obok pełnego `pracownik`. — Koszt: żaden.
18. **`_get_monitor_station_data(kod, stol=None)`** — stół liczony raz w routerze i przekazany; kształt zwrotu bez zmian. —
    Koszt: żaden.

## Przegląd końcowy

Osobny agent (Fable 5.1, świeży kontekst, tylko odczyt) przejrzał 11 commitów K4b względem planu, specu, raportu K3
i rozstrzygnięć sesji. **Wynik: 0 krytycznych, 1 ważne, 10 drobnych.** Review Focus 1–7 potwierdzone (czytelnicy bez
blokad, zapisów i dopełniania; dashboard; jedna droga zapisu; martwe klucze; monitory; JS z ucieczką). Z rozstrzygnięciami
zgoda (przy 6 — patrz W1). Poprawki w jednym commicie (`aa738002`), każda z testem RED → GREEN:

- **W1 (ważne):** `wroci_przy_dopelnieniu` liczone bez pozycji omijających stanowisko — na Formatowaniu zamówienie
  z pozycją bez docięcia wyglądało na niekompletne, więc „Zdejmij” nie ostrzegało, że kafel wróci. Poprawione
  (`omijajace=dane['omijajace']`, jak dopełnienie); test `test_stoly_panelu_wroci_przy_dopelnieniu_z_pozycja_omijajaca`.
- **D2 → ważne (przegradowane po skutku):** timer 120 s zakładki żył na `window` także po przejściu na inną zakładkę,
  więc każde okno panelu, które raz pokazało Stanowiska, odpytywało ciężki endpoint w tle. Odświeżanie tylko widocznej
  zakładki w widocznym oknie; test `test_zakladka_odswieza_sie_tylko_gdy_widoczna`; sprawdzone w przeglądarce (1 żądanie
  na aktywnej zakładce, 0 po przejściu na Dashboard).
- **D7 → ważne (przegradowane):** „Włącz stoły” nadpisywało niezapisane zmiany karty „Stół stanowisk” bez słowa.
  Potwierdzenie ostrzega teraz o niezapisanych zmianach; test `test_wlacz_stoly_ostrzega_o_niezapisanych_zmianach`.

**Drobne odłożone (bez poprawek):** D1 napis „Brak oczekujących produktów” pod samymi „Niekompletnymi”/„Do zdjęcia”;
D3 N+1 po `rollback()` w ścieżce błędu monitorów (tylko przy awarii warstwy priorytetów); D4 klasa CSS plakietki z
`szczebel.tag` bez białej listy w JS (wartości ze stałego zbioru); D5 mapa etykieta→tag w JS monitora bez testu
odwrotności; D6 apostrof w `onclick="viewProductDetails('…')"` (wzorzec sprzed K4b); D8 drugie zapytanie o tych samych
pracowników (`_krotkie_nazwy_pracownikow`); D9 `date.today()` (UTC kontenera) w kolorach terminów zakładki — wzorzec
zastany; D10 `update-config` sprawdza prefiks bez `strip()`.

## Pytania do Konrada

1. **Zakres dni terminu 1–90** w Konfiguracji („Terminy”) — `config_service` dopuszczał 1–365. Zostawić 90?
2. **Ostrzeżenie przy „Włącz stoły” z progiem wersji 0** jest tylko w UI — `PUT /ustawienia` przyjmie `tryb=stol` przy
   progu 0 (K3 rozstrz. 39: stara appka dostaje wtedy 409 na wszystkim spoza stołu). Czy serwer ma odmawiać takiej
   kombinacji (K7)?
3. **Podpis „wróci przy następnym dopełnieniu”** — czy wystarczy, czy „Zdejmij” takiego kafla ma prosić o dodatkową
   decyzję (np. „wstrzymaj pozycję”)?

## Stan gałęzi

- `origin/claude/priorytety-produkcji`: ostatni commit kodu K4b `aa738002`, commit tego raportu jest HEAD-em
  (hash w odpowiedzi sesji — raport nie może zawierać własnego hasha). Wszystko wypchnięte.
- `main` nietknięty; główny checkout na `main`. Worktree K4b czysty (`git status` pusty).
- Kontener podglądu `priorytety-k4b` (5007) zatrzymany i usunięty; pusty `config/core.json` nie powstał (montaż katalogu).

## Co następny krok musi wiedzieć

### K5 (przegląd P1, spec, CLAUDE.md)

- **Doprecyzowania 1–15 planu K4b** do specu (7.2, 4.3, 8.6, 8.8) plus: `widma` w `GET /stoly`, `wroci_przy_dopelnieniu`,
  `pracownik_krotko`, terminy w `PUT /ustawienia` (`deadline_default_days`, `deadline_finished_days`, 1–90),
  `update-config` odrzuca prefiksy `priorytety_` i `DEADLINE_`.
- **CLAUDE.md:** zakładka Stanowiska, `/dashboard-stats` i monitory hali to czytelnicy bez blokad, zapisów i dopełniania
  stołu; jedyna droga zapisu ustawień priorytetów i terminów to `PUT /production/api/priorytety/ustawienia`.
- **`reset-configs`** (`config_api.py`, `@login_required`, bez UI) nadal może zresetować `DEADLINE_*`
  i `DEADLINE_DAY_TYPE` do domyślnych mimo „jednej drogi” — do decyzji.
- Progi rangi spoza zakresu K4b (bez zmian): `routers/admin_routers.py` (`high_priority_products`),
  `modules/production/__init__.py` (`get_high_priority_items_count`), `avg_priority` w `/dashboard-stats` (nowa skala,
  bez konsumenta), `pending_priority` w `/dashboard-stats-data` (termin, nie ranga).
- **Usterka sprzed K4b:** `config_service.update_multiple_configs` przy samym INSERT nowego klucza nie commituje
  (`total_changes` liczy tylko UPDATE) — nowy klucz zapisany przez `update-configs` ginie. Dotyczy kluczy bez wiersza
  w bazie.
- Wydajność zakładki Stanowiska: `stoly_panelu` (6 × `_dane_stanowiska`) + 6 × `kolejka_stanowiska` + 6 × dodatkowe
  `kandydaci_stanowiska` — 247–276 ms na kopii danych (serwer deweloperski); zakładka odświeża się co 120 s. Wspólne
  wyliczenie kandydatów na stanowisko — jeśli na produkcji będzie wolno.

### K6 (kontrakt appki)

- Monitory hali nie są częścią kontraktu appki; tablet dalej jedyny, kto dopełnia stół (`GET desk`).
- Plakietki źródła i „Imię I.” są takie same na tablecie (K3-poprawka-1), w zakładce (pełne imię i nazwisko) i na monitorze.

### K7 (wdrożenie i przełączenie) — runbook startu stołów w panelu

1. **Dzień wcześniej i w dniu startu:** Konfiguracja → „Stół stanowisk” → „Start stołów” → „Odśwież podgląd” (kafle
   rozpoczęte per stanowisko; to samo co `GET /production/api/priorytety/start`).
2. **Po zakończeniu zmiany (admin):** „Przygotuj stoły” (potwierdzenie) → toast z liczbą dodanych per stanowisko;
   przy błędzie toast podaje stanowisko `nieudane` — wystarczy kliknąć ponownie (idempotentne). Zakładka Stanowiska
   pokazuje kafle startowe z plakietką „rozpoczęte przed startem” (stół dłuższy niż K — to zamierzone).
3. **Poprawki biura:** „Wyślij na stanowisko” (modal priorytetu w Liście produkcyjnej, K4a) i „Zdejmij ze stołu”
   (zakładka Stanowiska albo modal). Widma (kafle bez pozycji na stanowisku) widać w zakładce w sekcji „Do zdjęcia”.
4. **Przed rozpoczęciem zmiany (admin):** wpisz w „Minimalna wersja appki” kod wersji NOWEJ appki, potem „Włącz stoły”
   (jeden zapis: próg + `tryb=stol` dla Wycinania, Składania, Sklejania, Formatowania, Krawędzi, Pakowania; Lakiernia
   zostaje na liście). Przy progu 0 przycisk ostrzega — serwer tego nie blokuje (pytanie 2).
5. **Drabina:** „Rozpoczęte” na szczyt (Drabina priorytetów w Liście produkcyjnej); po zejściu kafli startowych — z
   powrotem pod ★★★★.
6. **Po restarcie (okno wdrożenia):** sprawdzić monitory hali i zakładkę — przy braku tabel/kolumn priorytetów monitory
   pokazują karty bez rangi i `stol.blad: true` (log ERROR „Monitor: stol stanowiska niedostepny”), zakładka napis „Stół
   i kolejka chwilowo niedostępne”, dashboard `high_priority_count: null`.
7. **Wycofanie stołów:** Konfiguracja → „Stół stanowisk” → tryb „zgodność (stara appka)” per stanowisko → „Zapisz stół
   stanowisk” (bez wdrożenia). Wiersze startowe mogą zostać.
- Telewizory: po wdrożeniu nowe statyki monitorów mają `?v=20261005` — meta refresh (300 s) wczyta nowy JS sam.
- `STATION_ALLOWED_IPS`: monitory jak dotąd za filtrem IP (bez zmian w K4b).

### K8 (sprzątanie P4)

- Wiersze martwych kluczy w `prod_config` (`PRIORITY_RECALC_INTERVAL_HOURS`, `PRIORITY_ALGORITHM_VERSION`,
  `STATION_*_PRIORITY_SORT`) do usunięcia migracją — kod ich już nie zna (zakładka Konfiguracja ich nie pokazuje: szablon
  nie iteruje grup).
- `ProductionPriorityConfig`: brak czytelnika w `config_api.py`; import w `routers/api/__init__.py` do usunięcia razem
  z modelem; **czytelnik w `routers/main_routers.py`** (stary panel `panel/config.html`) — DROP bez usunięcia tego
  odczytu położy ten widok.
- `avg_priority` w `/dashboard-stats` — usunąć albo opisać (nowa skala rangi, brak konsumenta).

## Poza zakresem (zauważone, nie ruszane)

1. `config_service.update_multiple_configs` — nowy klucz bez commita (wyżej, K5).
2. Monitor zbiorczy po auto-odświeżeniu dokleja nowe karty w stylu monitora stanowiska (`generateOrderCardHTML`) —
   istniejąca niespójność wyglądu (plan „Poza zakresem”).
3. Monitor, który wystartował z pustą listą (brak `.orders-grid`), nie pokaże nowych zamówień do przeładowania strony
   (meta refresh) — `incrementalUpdateOrders` kończy się na braku siatki; sprzed K4b.
4. Komunikat alertu „Dużo pilnych zamówień” odmienia „zamówień” niezależnie od liczby (> 10, więc zwykle poprawnie;
   22 → „22 zamówień”).
