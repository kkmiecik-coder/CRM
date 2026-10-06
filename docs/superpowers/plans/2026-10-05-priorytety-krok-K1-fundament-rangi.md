# Priorytety produkcji, krok K1 — „fundament rangi” — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jedno źródło kolejności produkcji liczone na poziomie zamówienia (drabina szczebli: gwiazdki, tagi terminowe, trasy) i materializowane w kolumnach `prod_orders.priority_rank/priority_rung` oraz `prod_products.priority_rank/is_priority` przez `kolejka.utrwal()` na własnej sesji, z blokadami „zamówienie najpierw”; stary algorytm „więcej = wyżej” zostaje tylko jako warstwa zgodności. Po K1 kolejka tabletów (sort po `priority_rank`) jest już nową kolejką, choć żaden ekran ani końcówka HTTP jeszcze się nie zmieniły.

**Architecture:** Nowy pakiet `modules/production/priorytety/` (wzór `modules/production/logistics/`): `models.py` (`PriorityRung`, `PriorityLog`, `StationDesk`), `stale.py`, `services/{kolejka,drabina,gwiazdki,ustawienia}.py`. `kolejka.policz()` i `kolejka.kandydaci_stanowiska()` to czyste funkcje na migawce; `kolejka.utrwal()` czyta migawkę na własnej sesji, blokuje zamówienia `FOR UPDATE` rosnąco → pozycje tych zamówień rosnąco → zapisuje tylko zmienione wiersze jednym commitem (jedno ponowienie po MySQL 1213). Jedna migracja dla całego P1 (także `prod_station_desk` dla K3). Przepięcia: `priority_service` → warstwa zgodności, `routes.utworz` → `drabina.zapewnij_szczebel_trasy` pod trzymaną blokadą tras, `utrwal_po_commicie()` po commitach logistyki i panelu produktów, faza `priorytety_utrwalone` w cronie, `DEADLINE_DAY_TYPE` w `_calculate_deadline_date`, doróbka z rangą 0.

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, MySQL 8.4 (produkcja) / SQLite (testy), pytest, Python 3.9 na produkcji.

**Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` — sekcje 2 (p. 14), 3.1–3.3, 4.1–4.5, 8.1–8.7, 9.1–9.5, 10, 11, 13. Symulacja: `docs/superpowers/specs/2026-10-04-priorytety-produkcji-symulacja.md`, sekcje „Analiza wyniku” (C, D) i „E. Decyzje Konrada”. Podręcznik centrali: `docs/superpowers/plans/2026-10-05-priorytety-produkcji-centrala.md` (sekcje 2, 8.0, 8.1).

**Sesja:** lokalna — testy pytest w kontenerze `app`, migracja uruchamiana dwa razy na kontenerze `db` (SQLite nie zna `information_schema`, `PREPARE` ani `INSERT IGNORE`). **Model:** Fable 5.1 (decyzja Konrada przy wydaniu kart: trudniejsze kroki na Fable 5.1, lżejsze na Opusie; podręcznik centrali 4a wskazywał dla K1 Opus 5.5 — centrala aktualizuje tabelę w sekcji 3/4a). Bez trybu szybkiego (podręcznik 4a p. 4).

**Zależności:** brak — pierwszy krok programu. **Gałąź:** zakłada `claude/priorytety-produkcji` z `origin/claude/logistyka-etap-4` (stan `b4b4a54d`, równy lokalnemu HEAD i `origin/claude/logistyka-etap-4` w chwili pisania planu).

## Global Constraints

- **Python 3.9**: bez `X | Y` w adnotacjach poza plikami z `from __future__ import annotations` (jest w `rework_service.py:10`), bez `match`, bez `dict | dict`.
- Komentarze i docstringi **po polsku**; w tekstach dla ludzi „Base.”; nazwy modułów, funkcji i kluczy `prod_config` **dokładnie jak w specu 9.1/9.2/8.6** — K2–K4b na nich polegają.
- **Kolejność blokad (CLAUDE.md „Trasy logistyki — jeden piszący naraz”, „Deklaracje paczek”, „zamówienie najpierw”; spec 9.4):** [`routes.zablokuj_trasy()`] → [`paczki.zablokuj_deklaracje()`] → zamówienia `FOR UPDATE` rosnąco po id → paczki → pozycje rosnąco po id → zapisy. K1 wprowadza trzech nowych pisarzy i każdy wpisuje się w ten łańcuch (sekcja „Współbieżność” niżej). Nowy pisarz pozycji bez blokady zamówienia nie powstaje.
- **Odczyt bieżący po blokadzie** (`with_for_update().populate_existing()`); w panelu `_zapis_pod_blokada()` (commit tuż przed blokadą tras, bez odczytów pomiędzy).
- **Serwisy nie commitują** (`kolejka.utrwal()` to wyjątek z definicji: własna sesja, nigdy `db.session`). Żadnego `db.session.commit()` w handlerach API mobilnego (`with_idempotency`). Żadnych blokad w czasie HTTP do Base. — K1 nie dodaje żadnego wywołania Base.
- Migracja **idempotentna**, bez `DELIMITER`, nazwa `2026-10-05-priorytety-produkcji.sql`; żadnych zmian ENUM na istniejących tabelach (spec 8.7 — stary worker w oknie wdrożenia niczego nie rzuci).
- Testy: `docker compose exec app pytest <ścieżki> -q -p no:cacheprovider` (podręcznik 2 p. 5); TDD — test przed implementacją. Testy SQLite in-memory wg konwencji repo (`tests/krawedzie_fixtures.py`, `tests/logistyka_fixtures.py`, `tests/blokady_pomocnicze.py`). Pliki testów NIE zakładają `prod_product_events` (konwencja pakietu).
- Repo publiczne — bez sekretów, IP, danych klientów. `tools/print_agent` bez zmian.
- Commity Conventional Commits po polsku, temat bez polskich znaków, jeden na Task, stopka atrybucji własnej sesji; `docs/superpowers/` przez `git add -f`. Nigdy `main`.
- Poza zakresem nie naprawiać; usterki do raportu („Poza zakresem”). Blokada → STOP i meldunek (sekcja „Ryzyka i blokady”).

## Review Focus

1. **Trasa decyduje mimo ★★★★★, tag wyciąga ponad gwiazdki, termin jest rozjemcą** — tabela 3.3 jeden do jednego: `test_policz_tabela_3_3` (Task 2).
2. **Grupa materiału po najbliższym terminie, w grupie termin przed długością, tag „Rozpoczęte” na żywo i przed grupowaniem** (decyzje Konrada 5.10, wariant A2): `test_kandydaci_przyklad_konrada_dab_4cm_przed_3cm`, `test_kandydaci_przyklad_xy_rozpoczete_wskakuje_na_szczebel_tagu`, `test_kandydaci_gwiazdki_przed_grupa_w_szczeblu_trasy` (Task 2; gwiazdki przed grupą — Doprecyzowania, Pytanie 3).
3. **`utrwal()` blokuje zamówienia przed pozycjami i zapisuje tylko zmienione wiersze jednym flushem rosnąco** — bez tego nowy pisarz dałby 1213 z ZAKOŃCZ i hurtem: `test_utrwal_blokuje_zamowienia_przed_pozycjami_przed_zapisem`, `test_utrwal_zapisuje_tylko_zmienione_rosnaco_po_id` (Task 4).
4. **`utrwal()` nie dotyka `db.session`** (ani commit, ani rollback — znalezisko z 22.09 w `priority_service`): `test_utrwal_nie_commituje_ani_nie_cofa_sesji_wolajacego`, `test_nieudane_utrwal_zostawia_db_session_czysta` (Task 4; **jedyne kanoniczne miejsce** testu „błąd `utrwal` nie brudzi `db.session`” — `tests/test_priorytety_kolejnosc_zapisow.py`; na nim opiera się mapa równoważników K8, która kasuje `tests/test_priority_statusy_krawedzi.py`).
5. **Szczebel trasy powstaje pod blokadą tras trzymaną przez `utworz`, w miejscu domyślnym, i znika z widoku po załadunku, ale wraca po „Cofnij załadunek” w tym samym miejscu**: `test_utworz_zaklada_szczebel_pod_blokada_tras`, `test_szczebel_trasy_zaladowanej_ukryty_po_cofnieciu_wraca` (Task 3).
6. **Termin: `DEADLINE_DAY_TYPE` zmienia tylko nowe terminy** — żadnego przeliczania wstecz (decyzja Konrada 4.10): `test_kalendarzowe_licza_soboty_i_niedziele`, `test_deadline_date_nadawany_tylko_przy_tworzeniu_pozycji` (Task 5).
7. **Warstwa zgodności**: `get_priority_calculator().recalculate_all_priorities()` i `recalculate_all_priorities()` wołają `kolejka.utrwal()`, a `NewPriorityCalculator` zostaje nietknięty (15 testów w `tests/test_sales_ingest_wyzwalacze.py` bada jego wnętrze): `test_warstwa_zgodnosci_wola_utrwal` (Task 4) + pełny pakiet zielony.
8. **Wyzwalacze po commicie, nigdy w transakcji** (spec 9.3): `test_dodanie_przystanku_utrwala_po_commicie`, `test_zapis_dostawy_planuje_utrwal_a_dekorator_wykonuje_po_commicie`, `test_cofnij_do_pakowania_planuje_utrwal_a_dekorator_wykonuje_po_commicie`, `test_cron_ma_faze_priorytety_utrwalone` (Task 6).
9. **Brak cyklu importów** (pakiet `priorytety` ↔ `logistics/__init__` importujący routery): import pakietu w świeżym procesie z trzech wejść (Task 6 Step 3) i importy `priorytety` w routerach logistyki wyłącznie wewnątrz funkcji.

## Decyzje przyjęte (spec i symulacja)

1. Spec v2 z 4.10, zatwierdzony przez Konrada 4–5.10 (status w nagłówku specu); wdrożenie po logistyce etapy 1–4, nigdy przed.
2. **Próg „Blisko terminu” 3 dni robocze** (Konrad 5.10, spec 2 p. 14, 8.6, symulacja E) — klucz `priorytety_blisko_terminu_dni` = 3. Spec 4.3 mówi jeszcze „domyślnie 2” — to zaszłość, obowiązuje 3 (K5 poprawi spec).
3. **Grupa materiału = (gatunek, klasa, grubość)**, grupy po najbliższym terminie w grupie, w grupie termin przed długością, potem szerokość malejąco (Konrad 5.10, wariant A2; spec 3.2 p. 3–4).
4. **Domyślna drabina:** ★★★★★, Po terminie, ★★★★, **Blisko terminu, Rozpoczęte**, ★★★, ★★, ★, bez gwiazdek — 9 szczebli (Konrad 5.10, spec 3.1, P-8). Spec 13 pisze „seed 8 szczebli” — zaszłość sprzed tagu „Rozpoczęte”; obowiązuje 9.
5. Bloki po N zamówień — **odrzucone** (symulacja C/D, spec 14). Nie implementować nawet jako parametr.
6. Doróbki zawsze pierwsze na każdym stanowisku po `created_at`, ranga 0 (spec 3.2, 4.2).
7. Zamówienia już w bazie zachowują swój termin — `DEADLINE_DAY_TYPE` działa tylko przy nadawaniu terminu (Konrad 4.10, spec 4.3).
8. Jedna migracja dla całego P1, z `prod_station_desk` (karta K1 w podręczniku 8.1).

## Doprecyzowania (do specu — K5 przeniesie)

- **Termin zamówienia** = min `deadline_date` pozycji **aktywnych** (w `STATUSY_PRODUKCJI`), jak w algorytmie 4.2; 4.1 mówi „niezanulowanych” — przyjmujemy 4.2 (pozycja spakowana nie powinna wyciągać terminu).
- **Tag „Rozpoczęte” i kompletność** liczymy na pozycjach w `STATUSY_PRODUKCJI ∪ STATUSY_PO_SPAKOWANIU`; `anulowane` i `wstrzymane` pomijamy (wstrzymana pozycja nie blokuje kompletności — biuro świadomie ją zabrało z kolejki).
- **`kandydaci_stanowiska`** dostaje dodatkowo `szczebel_rozpoczete` (pozycja szczebla tagu „Rozpoczęte” na drabinie; `None` = nie podnosić) — tag liczony na żywo musi wiedzieć, gdzie stoi na drabinie, a spec 9.2 ma trzy parametry. K3 przekazuje `drabina.pozycja_tagu('rozpoczete')`.
- **Jednostka `zamowienie`** w `kandydaci_stanowiska`: zamówienia porządkuje ten sam klucz, co rangę (szczebel z tagiem na żywo, gwiazdki, termin, numer), nie goła kolumna `priority_rank` — inaczej kolejność kafli-zamówień różniłaby się od kolejności kafli-pozycji tego samego algorytmu.
- **Trasa bez szczebla** w `policz()`: wirtualny szczebel w miejscu domyślnym (3.1) — liczony na liście szczebli po wstawieniu, więc `priority_rung` takich zamówień to indeks na liście rozszerzonej; WARNING w logu. **Brak szczebli stałych** (gwiazdki/tagi, np. baza bez seedu) — tak samo, w kolejności `DRABINA_DOMYSLNA`; `drabina.uzupelnij()` dopisuje i jedne, i drugie (samonaprawa; testy SQLite nie mają seedu z migracji).
- **`utrwal()` nie dotyka pozycji nieaktywnych** (spakowane i dalej, anulowane, wstrzymane) ani zamówień nieaktywnych — ich `priority_rank` zostaje jak dziś (wyszukiwarka archiwum sortuje po dawnej randze, `tests/test_mobile_search_archiwum.py`). Zamówieniom aktywnym bez `deadline_date` termin = brak → koniec szczebla (4.5).
- **`utrwal()` zeruje `priority_manual_override`** napotkane na pozycjach aktywnych (spec 8.5) i podbija `updated_at` pozycji, którym zmienia rangę (ETag starej appki, 4.2).
- **Wpis `przeliczenie` w `prod_priority_log`** tylko gdy `utrwal(zrodlo=..., user_id=...)` dostanie źródło (K2: „Przelicz teraz”); cron i wyzwalacze nie logują (co godzinę byłby spam) — także wyzwalacze w `products_api` wołają `utrwal_po_commicie()` **bez** źródła.
- **`gwiazdki.ustaw`** nie commituje (zasada „serwisy nie commitują”): bierze `blokady_zamowien.zablokuj_zamowienia(ids)`, zapisuje i loguje; `commit` przed blokadą (`_zapis_pod_blokada`-podobny, ale **bez** blokady tras: zwykły `db.session.commit()`), `commit` po zapisie i `utrwal_po_commicie()` robi router K2. Spec 9.2 opisuje tę sekwencję jako całość — podział serwis/router jest nasz.
- **Doróbka** przy utworzeniu dostaje `priority_rank = 0` **i** `is_priority = True` (pochodna z 4.2: doróbka → `is_priority`); `priority_manual_override` zostaje `False`. Oba pola w konstruktorze `ProductionProduct(...)` (`rework_service.py:246-297`), a wiersz `:302` znika — jeden INSERT zamiast INSERT + UPDATE po `flush`. `complete_task` nie kasuje już rangi, ale **dalej zamyka** wpis `ProductionReworkLog` (`models.py:721-725`) — spec 9.5 usuwa tylko blok `:714-719`.
- **`lock_priority`/`unlock_priority` puste** od K1 → martwe końcówki `products/<id>/priority` (`products_api.py:2568`) i `set-manual-priority` (`:3442`) do czasu K2 przyjmują żądanie i nie zapisują rangi. `update-priority` (przeciąganie, `_zapisz_priorytety` — przypisania `:2969-2970`, `:2987-2988`) i `bulk-action update_priority` (`:1631-1635`) **nie** używają `lock_priority`: piszą kolumnę wprost i działają jak dotąd, a ich ranga żyje do najbliższego `utrwal()` (które zeruje też `priority_manual_override`). Wszystkie martwe w UI (spec 1.1). **Testy przeciągania w `tests/test_priorytety_kolejnosc_zapisow.py` (`:43-122`, `:193-233`) zostają w K1** — końcówka żyje do K2 i jest pisarzem pozycji z CLAUDE.md; usuwa je K2 razem z końcówką (plan K2, mapa plików). Spec 9.5 „przeciąganie znika” opisuje stan po P1, nie po K1.
- **Wywołania przeliczenia w `sync_service` (`:933`, `:3033`) zostają na warstwie zgodności** `priority_service`, a nie przepięte wprost na `kolejka.utrwal` (spec 9.5 mówi „→ `kolejka.utrwal()`”): `tests/test_sales_ingest_wyzwalacze.py` stubuje `priority_service.get_priority_calculator` w ścieżkach synchronizacji (`:525-535`, `:1165-1167`), a na `StaticPool` prawdziwe `utrwal()` na własnej sesji dzieliłoby połączenie z testem. K8 przepina wprost przy usuwaniu `priority_service.py`. Dlatego funkcje modułowe `recalculate_priorities()`/`recalculate_all_priorities()` (`:907`, `:923`) **zostają** w obecnej postaci `get_priority_calculator().recalculate_all_priorities()` (nazwa rozwiązywana w chwili wywołania): ścieżka `:3033` (`_update_product_priorities`) woła funkcję modułową, a stub z `:534` podmienia tylko `get_priority_calculator` — bezpośrednie `kolejka.utrwal()` w funkcji modułowej ominęłoby stub.
- **Wyzwalacze poza listą 9.3, dodane w K1:** `panel_api.handed_over` („Wydane klientowi” zdejmuje zamówienie z kolejki — pozycje `dostarczone`) i `routes.usun` → `drabina.usun_szczebel_trasy` z renumeracją (na MySQL robi to FK CASCADE, na SQLite testów nie; renumeracja i tak czeka na następny zapis). `trasy_api._akcja` woła `utrwal_po_commicie()` po każdej akcji trasy, także po zmianie kolejności przystanków (zbędne, ale tanie; raport zwraca „bez zmian”). **Weryfikacja „Cofnij do pakowania”** (`weryfikacja_api.verification_revert_to_packing`, `:296-315`, telefon Weryfikacji pod `with_idempotency`): pozycje `spakowane`/`zweryfikowane` → `czeka_na_pakowanie` (`weryfikacja.cofnij_do_pakowania`, `weryfikacja.py:677`), czyli zamówienie nieaktywne znów staje się aktywne — bez wyzwalacza jego `priority_rank`/`priority_rung` zostałyby z ostatniego przeliczenia aż do godzinnego crona (kafel Pakowania w złym miejscu, fałszywe duplikaty rang wśród aktywnych w kontrolach K5 `rangi_zbiezne` i K7 Task 3 Step 3). Handler tylko **planuje** (`kolejka.zaplanuj_po_commicie()` po udanym `cofnij_do_pakowania`, przed `_odpowiedz`; odmowa `WeryfikacjaBlad` nie planuje), wykonuje hook `with_idempotency` — jak Dostawa. `weryfikacja_api` nie ma pętli ponowienia 1213 (1213 = wyjątek → rollback i 500 w dekoratorze), więc `porzuc_zaplanowane()` nie ma gdzie wejść; flaga po 500 ginie z `g` żądania (jak plan `bl_sync`). To jedyny zapis Weryfikacji, który przestawia pozycje na status produkcji (pozostałe ustawiają `spakowane`/`zweryfikowane`; panelowa zmiana sposobu dostawy z przepakowaniem — `delivery._cofnij_do_pakowania` — jest już objęta wyzwalaczem `delivery_method`).
- **Dostawa (telefon kierowcy):** handler nie commituje, więc `dostawa_api._zapis` tylko **planuje** (`kolejka.zaplanuj_po_commicie()` w `g`), a `with_idempotency` **wykonuje** po udanym commicie (`kolejka.wykonaj_zaplanowane()`, obok `bl_sync.wyslij_zaplanowane()`); przy ponowieniu po 1213 `_zapis` porzuca plan (`kolejka.porzuc_zaplanowane()`). To rozszerzenie dekoratora o trzeci hook po commicie — K3 dołoży czwarty (sygnały stanowisk).
- **`is_priority` pochodna od K1** (`doróbka or gwiazdki ≥ 1 or po_terminie`): końcówka `POST /production/api/set-priority` (zostaje do K4a, woła ją JS) ustawia flagę na pozycji, a najbliższe `utrwal()` ją nadpisze. Do K4a gwiazdka admina żyje najwyżej do następnego przeliczenia — świadomie, bez obejścia.
- **`ustawienia.py`** czyta przez `config_service.get_config(klucz, domyślna)` (pamięć podręczna 60 min na proces, `config_service.py:47`). Zapis w K2/K4b musi iść przez `set_config` (unieważnia klucz w swoim procesie); inne workery gunicorna widzą starą wartość do 60 min — do odnotowania w planie K2 (kolejka stanowiska i próg „Blisko terminu” zmieniają się z opóźnieniem). Uwaga: `get_config` czyta `ProductionConfig.query`, czyli **`db.session`** (autoflush sesji wołającego) — dlatego `utrwal()` czyta próg **własną sesją** (`ustawienia.prog_blisko(sesja=...)`, niżej), a nie przez `config_service`.
- **Gwiazdki w kluczu kafla przed grupą materiału** (spec 3.2 p. 1 „szczebel zamówienia …, gwiazdki”; klucz `kolejka_pozycji` symulacji `:324-330`: `szczebel, -gwiazdki, rozpoczęte, grupa, …`). Narracja przykładu 3.3 („grupa dąb A/B 4 cm … w grupie najpierw A ★★, potem B bez gwiazdek”) przeczy temu kluczowi: z gwiazdkami przed grupą wszystkie pozycje A (★★) idą przed pozycjami B. Przyjmujemy **regułę 3.2 i klucz symulacji** (na nim Konrad podjął decyzje 5.10; produkcja nie ma jeszcze gwiazdek, więc symulacja tej różnicy nie widziała). Test przykładu Konrada idzie na równych gwiazdkach, osobny test dokumentuje „gwiazdki przed grupą”. Do potwierdzenia: Pytanie 3; K5 poprawia 3.3 albo 3.2 wg odpowiedzi.
- **`min_termin_grupy`** liczony jak w symulacji: klucz `(szczebel, gatunek, klasa, grubość)` — przez wszystkie pozycje szczebla (także różnych gwiazdek i rozpoczęte/nie), bez rozbijania na podgrupy klucza.
- **`priority_rank`/`priority_rung` zamówień nieaktywnych** zostają z ostatniego przeliczenia (nie zerujemy) — czytelnicy kolumn zamówienia (K2, K4a, K4b) filtrują zamówienia aktywne, inaczej trafią na stare, zdublowane rangi.
- **`kolejka.utrwal_po_commicie()` bez deduplikacji „raz na żądanie”.** Fikstury `app` w testach (`tests/logistyka_fixtures.py:124-127`, `tests/krawedzie_fixtures.py:126`) oddają aplikację wewnątrz `app_context()`, a Flask 2.0.3 nie zakłada wtedy nowego kontekstu aplikacji na żądanie klienta testowego — `g` jest wspólne dla wszystkich żądań testu. Znacznik „już utrwalone” w `g` wyłączyłby utrwalenie w drugim żądaniu testu. Router woła `utrwal_po_commicie()` raz; plan Dostawy idzie przez `g.pop(...)` w `wykonaj_zaplanowane()`/`porzuc_zaplanowane()` (zdjęcie znacznika przy wykonaniu, jak `bl_sync`), więc nie przecieka do następnego żądania.
- **Importy pakietu `priorytety` w routerach logistyki tylko wewnątrz funkcji** (`trasy_api`, `panel_api`, `dostawa_api`, `cron_api`, `weryfikacja_api`; jak `products_api.py:1307` z `bl_sync`). Powód: `modules/production/logistics/__init__.py:16-19` importuje routery, a `priorytety` sięga do logistyki (`stale` → `sposoby`, `drabina` → `routes`); import na górze routera daje cykl `priorytety.models` (w połowie) → `stale` → `logistics/__init__` → `trasy_api` → `priorytety.services.drabina` → `from ..models import PriorityRung` → `ImportError`. Z tego samego powodu `priorytety/models.py` odwołuje się do trasy wyłącznie napisem (`ForeignKey('prod_routes.id', ondelete='CASCADE')`, `relationship('Route')`), bez importu `logistics.models`.

## Ugruntowanie w kodzie (stan przed K1, gałąź `claude/logistyka-etap-4` @ `b4b4a54d`)

| Miejsce | Stan obecny | Co robi K1 |
|---|---|---|
| `modules/production/services/priority_service.py` (988 linii) | `NewPriorityCalculator` (`:96`), `recalculate_all_priorities` (`:167`, pętla 1213 `:206-215`), `_przelicz_raz` (`:234`), `nowa_sesja_priorytetow` (`:83`), singleton `get_priority_calculator` (`:886`), moduł `recalculate_priorities` (`:907`), `recalculate_all_priorities` (`:923`), `get_priority_statistics` (`:932`) | `get_priority_calculator()` zwraca warstwę zgodności → `kolejka.utrwal()`; funkcje modułowe `:907/:923` → `utrwal()`; klasa i `get_priority_statistics` zostają nietknięte do K8 |
| wołający `priority_service` | `sync_service.py:933-935` (`get_priority_calculator().recalculate_all_priorities()`, log `:938-939` czyta `products_updated`, `manual_overrides_preserved`), `:3033-3035` (`recalculate_all_priorities()` w `_update_product_priorities`), `services/__init__.py:54,249`, `production/__init__.py:42`, `products_api.py:3293,3312` (martwa końcówka `recalculate-all-priorities`) | bez zmian w wywołaniach (warstwa zgodności); w `:938-939` log z nowych kluczy raportu |
| `services/__init__.py:102-115` | **osobny** singleton `get_priority_calculator()` zwracający `NewPriorityCalculator()` wprost (i `recalculate_priorities` `:236-251` na nim); dziś bez wołających poza `reload_services` | ciało → `from .priority_service import get_priority_calculator as _g; return _g()` — żeby nikt nie trafił przez pakiet `services` na stary algorytm |
| `rework_service.py:302` | `rework.lock_priority(rank=1)` po `db.session.flush()` (`:299`); konstruktor `ProductionProduct(...)` `:246-297` | `priority_rank=0, is_priority=True` w konstruktorze, wiersz `:302` usunięty |
| `models.py` `ProductionProduct` | `priority_rank` `:383`, `priority_manual_override` `:384`, `is_priority` `:385`; `is_priority_locked` `:491-493`; `lock_priority` `:513-518`; `unlock_priority` `:520-521`; `complete_task` `:633`, blok doróbki `:712-725` (reset `:714-719`, zamknięcie logu `:721-725`) | `lock_priority`/`unlock_priority` puste (docstring „martwe od P1, usuwane w P4”), blok `:714-719` znika, `:721-725` zostaje |
| `models.py` `ProductionOrder` (`:147-316`) | brak kolumn priorytetów; `bl_status_pending_id` `:201`, blok Weryfikacji `verified_at` `:212` … `repack_reason` `:220`, `shipping_package_id` `:222`, `products = relationship` `:237` | nowe kolumny `priority_stars`, `priority_stars_set_at`, `priority_stars_set_by`, `priority_rank`, `priority_rung` (po `repack_reason` `:220`, przed `shipping_package_id` — nie rozcinać bloku Weryfikacji) |
| `modules/production/__init__.py:53-62` | blok importu modeli (try/except) | dopisany import `from .priorytety import models as _priorytety_models` (metadane dla `create_all`/`setup-db`) |
| `sync_service.py` | `_order_has_finished_product` `:3170`, `_calculate_deadline_date` `:3206-3255` (wybór dni `:3236-3249`, zawsze `_add_business_days` `:3251/:3253`), `_add_business_days` `:3257-3268`; wywołania `:1047` i `:3295` (tylko tworzenie pozycji) | `_calculate_deadline_date` czyta `DEADLINE_DAY_TYPE` i wybiera `_add_business_days` albo `timedelta` |
| `config_service.py:60-69` | `_default_values` z `DEADLINE_DEFAULT_DAYS: 16`, `DEADLINE_FINISHED_DAYS: 21`; cache 60 min (`:47`) | `'DEADLINE_DAY_TYPE': 'robocze'` w `_default_values` |
| `logistics/services/routes.py` | `KLUCZ_BLOKADY` `:42`, `zablokuj_trasy` `:146-204` (samonaprawa `INSERT IGNORE` `:207-228`), `utworz` `:406-416` (blokada pierwsza, `flush` `:415`), `zatwierdz` `:628`, `cofnij_do_roboczej` `:639`, `usun` `:658-665` | `utworz`: po `flush` `drabina.zapewnij_szczebel_trasy(trasa, user_id)`; `usun`: `drabina.usun_szczebel_trasy(route.id)` przed `db.session.delete(route)` |
| `logistics/routers/trasy_api.py` | `_akcja` `:333-385` (commit `:364`, `bl_sync.wyslij_zaplanowane()` `:380`), `route_create` `:543-553` (commit `:548`), `route_delete` `:639-650` (commit `:649`) | `kolejka.utrwal_po_commicie()` po `:380`, po `:548`, po `:649` |
| `logistics/routers/dostawa_api.py` | `_zapis` `:125-178` (pętla 1213, `flush` `:160`, `bl_sync.porzuc_zaplanowane()` `:169`) | `kolejka.zaplanuj_po_commicie()` po `:160`; `kolejka.porzuc_zaplanowane()` przy `:169` |
| `logistics/routers/weryfikacja_api.py` | `verification_revert_to_packing` `:296-315` (`with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)`, wywołanie `weryfikacja.cofnij_do_pakowania` `:310-313`, odmowa `WeryfikacjaBlad` → `_blad(e)`, potem `_odpowiedz`); bez pętli 1213; serwis `weryfikacja.cofnij_do_pakowania` (`weryfikacja.py:648-690`) przestawia pozycje na `czeka_na_pakowanie` (`:677`) i sam planuje `bl_sync.zaplanuj_po_commicie` | `kolejka.zaplanuj_po_commicie()` (import lokalny) po udanym `cofnij_do_pakowania`, przed `return _odpowiedz(...)` |
| `services/mobile_api_service.py` `with_idempotency` | commit `:602/:627`; hooki po commicie: BL `:630-637`, druk `:639-647`, `bl_sync.wyslij_zaplanowane` `:649-656` | czwarty blok `try`: `kolejka.wykonaj_zaplanowane()` |
| `logistics/routers/panel_api.py` | `_zapis_pod_blokada` `:72-89`, `_zapisz_zmiane_sposobu` (commit `:177`), `delivery_method` `:181-246` (`bl_sync.po_zmianie` `:233`), `handed_over` `:247-283` (commit `:276`) | `kolejka.utrwal_po_commicie()` po `:233` i po `:276` |
| `logistics/routers/cron_api.py:24-80` | fazy w osobnych transakcjach: `przenies_osierocone` → commit, `dostarcz_wydane` → commit, `przelicz_otwarte` → commit (`:62`), wątki w tle (`:63-64`), odpowiedź JSON; `except` → rollback i 500 | **po uruchomieniu wątków w tle** (`:64`), we własnym `try/except` (rollback, log ERROR, klucze `None`): `drabina.uzupelnij()` + commit, `kolejka.utrwal()`; klucze `szczeble_uzupelnione`, `priorytety_utrwalone` w odpowiedzi — błąd priorytetów nie może zatrzymać dopychacza Base. ani geokodera |
| `routers/api/products_api.py` | `admin_apply_baselinker_changes` `:1247` (serwis commituje; `bl_sync.wyslij_zaplanowane()` `:1308` przy `success`), `bulk_action` `:1523` (`update_status` commituje w `_zapisz_zmiane_statusu`, wynik `:1600-1612`; `update_priority` `:1631-1635`, `delete`; commit `:1658`) | `kolejka.utrwal_po_commicie()` po `:1308` i po gałęzi `update_status` z `results['success']` (NIE po `update_priority`: test `test_inne_akcje_nie_wymagaja_statusu` pilnuje rangi 42) |
| `logistics/models.py` | `Route` `:84` (`status` ENUM `STATUSY_TRASY` `:64`; `STATUSY_TRASY_AKTYWNE` `:67` obejmuje też `zaladowana`, `w_trasie`), `RouteStop` `:122` (`order_id` UNIQUE) | bez zmian; szczeble widoczne tylko dla `('robocza', 'zatwierdzona')` — **węższy** zbiór niż `STATUSY_TRASY_AKTYWNE` |
| `services/blokady_zamowien.py` | `zablokuj_zamowienia` (`WHERE prod_orders.id IN … ORDER BY prod_orders.id FOR UPDATE`), `zablokuj_pozycje(order)` (po `order_id`), `kod_mysql` — blokady na `db.session` (`ProductionOrder.query`) | `gwiazdki.ustaw` używa `zablokuj_zamowienia`; `utrwal()` **nie może** (własna sesja, nigdy `db.session`): ten sam kształt zapytania na `sesja.query(ProductionOrder)…with_for_update()`, a pozycje wielu zamówień własnym zapytaniem `WHERE prod_products.order_id IN (…) ORDER BY prod_products.id FOR UPDATE`; `kod_mysql` — tak |
| `services/station_catalog.py` | `STATION_ORDER` `:24-35`, `STATION_PENDING_STATUS` `:68-76` | `stale.py` importuje stąd kody i statusy stanowisk (bez duplikatu) |
| `scripts/symulacja_priorytetow.py` | `_przygotuj` `:233`, `_szczebel` `:288`, `_klucz_zamowienia` `:298`, `kolejka_pozycji` `:304-345` (klucz A2 `:324-330`), `kolejka_zamowien` `:348-378`, `STAGE_OF_STATUS` `:74-78` | wzór algorytmu dla `kolejka.py` (skrypt bez zmian — celowo nie importuje aplikacji) |
| testy | `tests/test_priorytety_kolejnosc_zapisow.py` (przeciąganie `:43-122` i jego ponowienia `:193-233` — zostają do K2; przeliczenie `:125-162`, `:235-298` na `NewPriorityCalculator`; pomocniki `:163-191` wspólne), `tests/test_logistyka_cron.py:141` (`podbite == {osierocony_id}` — utrwal w cronie podbije obie pozycje), `tests/test_produkty_masowa_zmiana_statusu.py:521` (`len(blokady_z) == 2` w całym żądaniu — utrwal po commicie dokłada trzecią blokadę zamówień na tym samym engine), `tests/test_priority_statusy_krawedzi.py` (`active_statuses` `:86-91`, statystyki `:94-120`, brudna sesja `:124-200`), `tests/test_routing_krawedzie.py:256-278` (doróbka na Formatowaniu gasi `priority_manual_override`), `tests/test_sales_ingest_wyzwalacze.py` (`NewPriorityCalculator` wprost `:909-1470`), `tests/test_produkty_masowa_zmiana_statusu.py:81-91` (`update_priority` → ranga 42) | przepisane/uaktualnione wg Tasków 4–6; `test_sales_ingest_wyzwalacze.py` **bez zmian** |
| fixtury z tabelami tras | `tests/logistyka_fixtures.py` `TABLES` `:46-51` (rejestruje `logistics_panel_bp`, `mobile_api_bp`, `dostawa_mobile_bp`), `tests/krawedzie_fixtures.py` `TABLES` `:47-53`, `tests/test_dorobka_dalsze_stanowiska.py`, `tests/test_dorobka_trasa_krawedzi.py`, `tests/test_mobile_api_alias_krawedzi.py`, `tests/test_worker_profiles.py` | dopisane `PriorityRung, PriorityLog, StationDesk` (bez nich `routes.utworz` pada na SQLite „no such table”) |
| migracje | wzór `migrations/2026-10-02-logistyka-niedostarczone-na-trasie.sql` (ADD COLUMN przez `information_schema` + `PREPARE/EXECUTE`), `2026-09-27-logistyka-trasy-flota.sql` (`CREATE TABLE IF NOT EXISTS … ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`), `2026-09-30-logistyka-paczki-blokada.sql` (`INSERT IGNORE INTO prod_config`); wzorzec nazwy `migrations/migration_service.py:34`; test nazw `tests/test_migration_service.py:130` | nowy plik wg tych wzorów |

**Czego w kodzie nie ma (żeby nikt nie szukał):** pakietu `priorytety`, kolumn priorytetów na `prod_orders`, tabel `prod_priority_*`/`prod_station_desk`, klucza `DEADLINE_DAY_TYPE`, przełącznika dni roboczych/kalendarzowych, jakiegokolwiek związku tras z rangą, funkcji `utrwal_po_commicie` ani wspólnej listy `STATUSY_PRODUKCJI` (dziś trzy kopie w `priority_service.py`, `tests/test_priority_statusy_krawedzi.py:5-8`). Nie ma też cyklicznego przeliczania — jedyne wyzwalacze to `sync_service.py:933/:3033`.

## Współbieżność — kolejność blokad nowych pisarzy (CLAUDE.md, spec 9.4)

| Pisarz | Kolejność (ta sama transakcja) | Co pisze | Test kolejności |
|---|---|---|---|
| `kolejka.utrwal()` (własna sesja) | zwykłe odczyty migawki → `prod_orders` `FOR UPDATE` rosnąco po id (tylko zamówienia, których wiersz albo pozycje się zmieniają) → `prod_products WHERE order_id IN (…) ORDER BY id FOR UPDATE` → jeden flush przy commicie (SQLAlchemy porządkuje UPDATE-y mappera po PK; zamówienia przed pozycjami) | `prod_orders.priority_rank/priority_rung`, `prod_products.priority_rank/is_priority/priority_manual_override/updated_at` | `test_utrwal_blokuje_zamowienia_przed_pozycjami_przed_zapisem`, `test_utrwal_zapisuje_tylko_zmienione_rosnaco_po_id` |
| `drabina.zapewnij_szczebel_trasy` / `przesun` / `uzupelnij` / `usun_szczebel_trasy` | `routes.zablokuj_trasy()` (wołający albo sama funkcja — ponowna blokada w tej samej transakcji jest bezpieczna) → `prod_priority_rungs` `FOR UPDATE` wszystkie wiersze po `position` → INSERT/UPDATE/DELETE | `prod_priority_rungs`, `prod_priority_log` (bez FK do zamówień) | `test_utworz_zaklada_szczebel_pod_blokada_tras`, `test_przesun_bierze_blokade_tras_przed_szczeblami` |
| `gwiazdki.ustaw` | (router K2: `db.session.commit()`) → `blokady_zamowien.zablokuj_zamowienia(ids)` rosnąco → zapis zamówień i wpisów logu (FK do już zablokowanego zamówienia) → (router: commit → `utrwal_po_commicie()`) | `prod_orders.priority_stars*`, `prod_priority_log` | `test_ustaw_blokuje_zamowienia_rosnaco_przed_zapisem` |
| cron (`cron_api.cron`) | fazy logistyki jak dotąd (każda commit) → `drabina.uzupelnij()` (blokada tras → szczeble) → commit → `kolejka.utrwal()` (własna sesja) | j.w. | `test_cron_ma_faze_priorytety_utrwalone` |

Dlaczego to nie tworzy cyklu: `utrwal()` bierze wyłącznie sufiks łańcucha (zamówienia → pozycje), bez blokady tras i stołu, więc wobec ZAKOŃCZ, doróbki, Weryfikacji, hurtu i Dostawy jest zgodny; wobec pisarzy pozycji bez blokady zamówienia (liczniki sztuk, druk TCP) najwyżej czeka. Drabina nie dotyka zamówień ani pozycji. Rzadkie 1213 na lukach indeksów (jak dotąd przy przeliczeniu) — jedno ponowienie na nowej sesji (`test_utrwal_ponawia_raz_po_1213_na_nowej_sesji`, `test_utrwal_dwa_1213_bez_zapisow`). Odczyt migawki `utrwal()` jest zwykły (REPEATABLE READ) i poprzedza blokady — rangi mogą być o chwilę nieaktualne wobec ZAKOŃCZ wykonanego w międzyczasie; to pamięć podręczna, a tag „Rozpoczęte” K3 liczy na żywo i cron nadrabia co godzinę (spec 4.2). Pozycja skasowana po migawce (zmiany z Base.) nie wraca z odczytu blokującego, więc nie dostaje przypisania (przypisujemy wyłącznie na obiektach z odczytu blokującego, nigdy na obiektach migawki); każdy nieoczekiwany błąd zapisu → raport `success: False`, bez wyjątku na zewnątrz.

**Warunek wstępny `utrwal()`** (MySQL): transakcja `db.session` wołającego nie ma niezatwierdzonych zapisów do `prod_orders`/`prod_products`. Własna sesja to osobne połączenie w **tym samym wątku** — czekałaby na blokady wołającego, który czeka na nią: InnoDB tego nie wykrywa jako zakleszczenia, kończy się `lock wait timeout` (1205) po 50 s. Dlatego tylko po commicie (`utrwal_po_commicie`, cron po commicie fazy, `sync_service :933` po commitach pętli zamówień) i dlatego `utrwal()` niczego nie czyta przez `db.session` (autoflush wypchnąłby cudze zmiany i wziął blokady w transakcji wołającego).

## Środowisko

- `cd <repo> && docker compose up -d`; `PYTEST <ścieżki>` = `docker compose exec app pytest <ścieżki> -q -p no:cacheprovider`.
- Pełny pakiet trwa długo i zajmuje dużo pamięci (plany 4.4a/4.4b: ~13 GiB) — nie uruchamiać dwóch pełnych pakietów naraz.
- Migracja na kontenerze `db`: `docker compose exec app flask migrate` (×2), `docker compose exec app flask migrate-status`, podgląd `docker compose exec db mysql -u<user> -p <baza> -e "..."` (dane dostępowe z lokalnego `config/core.json`, nie do raportu).
- Baza podglądu/porty: wg wskazań centrali (karta); K1 nie potrzebuje podglądu w przeglądarce.

## Mapa plików

| Plik | Task | Rola |
|---|---|---|
| `migrations/2026-10-05-priorytety-produkcji.sql` (nowy) | 1 | cały P1: kolumny `prod_orders`, trzy tabele, 38 wierszy `prod_config`, 9 szczebli |
| `modules/production/priorytety/__init__.py`, `models.py`, `stale.py`, `services/__init__.py`, `services/ustawienia.py` (nowe), `tests/test_priorytety_ustawienia.py` (nowy) | 1 | pakiet bez blueprintu (K2), modele, stałe, odczyt ustawień |
| `modules/production/models.py` (`ProductionOrder`) | 1 | pięć kolumn 8.1 |
| `modules/production/__init__.py:53-62` | 1 | import modeli pakietu |
| `tests/priorytety_fixtures.py` (nowy), `tests/logistyka_fixtures.py`, `tests/krawedzie_fixtures.py`, cztery pliki testów z `Route` w `TABLES` | 1 | nowe tabele w fixturach; pomocniki (`drabina_domyslna`, czyste ustawienia) |
| `tests/test_migracja_priorytety.py` (nowy) | 1 | kształt migracji (jak `tests/test_migracja_krawedzie.py`) |
| `modules/production/priorytety/services/kolejka.py` (nowy: `policz`, `kandydaci_stanowiska`) | 2 | czysta część algorytmu |
| `tests/test_priorytety_kolejka.py` (nowy) | 2 | tabele przypadków 3.3, przykłady Konrada i X/Y |
| `modules/production/priorytety/services/drabina.py` (nowy), `logistics/services/routes.py` (`utworz`, `usun`) | 3 | szczeble, miejsce domyślne, przesunięcie, samonaprawa |
| `tests/test_priorytety_drabina.py` (nowy) | 3 | |
| `kolejka.py` (`utrwal`, `utrwal_po_commicie`, plan w `g`), `services/gwiazdki.py` (nowy), `services/priority_service.py` (warstwa zgodności), `services/__init__.py:102-115` (singleton deleguje) | 4 | |
| `tests/test_priorytety_kolejnosc_zapisow.py` (część przeliczenia przepisana, przeciąganie zostaje), `tests/test_priority_statusy_krawedzi.py` (uaktualniony), `tests/test_priorytety_gwiazdki.py` (nowy), `tests/blokady_pomocnicze.py` (predykat `blokada_pozycji_zamowien`, `zapis` + `prod_priority_log`/`prod_station_desk`) | 4 | |
| `services/sync_service.py` (`_calculate_deadline_date`, log `:938`), `services/config_service.py:60-69`, `services/rework_service.py:302`, `models.py` (`complete_task`, `lock_priority`, `unlock_priority`) | 5 | terminy, doróbka, martwe metody |
| `tests/test_priorytety_terminy.py` (nowy), `tests/test_priorytety_dorobka.py` (nowy), `tests/test_routing_krawedzie.py:256-278` | 5 | |
| `logistics/routers/trasy_api.py`, `dostawa_api.py`, `weryfikacja_api.py`, `panel_api.py`, `cron_api.py`, `services/mobile_api_service.py` (`with_idempotency`), `routers/api/products_api.py` | 6 | wyzwalacze 9.3 (+ Weryfikacja „Cofnij do pakowania”) |
| `tests/test_priorytety_wyzwalacze.py` (nowy), `tests/test_logistyka_cron.py:141`, `tests/test_produkty_masowa_zmiana_statusu.py:521` (izolacja od `utrwal` po commicie) | 6 | |
| `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K1-raport.md` (nowy) | 7 | raport kroku |

---

### Task 1: Gałąź, migracja całego P1, modele, stałe, ustawienia, fixtury

**Files:**
- Create: `migrations/2026-10-05-priorytety-produkcji.sql`, `modules/production/priorytety/{__init__,models,stale}.py`, `modules/production/priorytety/services/{__init__,ustawienia}.py`, `tests/priorytety_fixtures.py`, `tests/test_migracja_priorytety.py`, `tests/test_priorytety_ustawienia.py`
- Modify: `modules/production/models.py` (`ProductionOrder`, po `repack_reason` `:220`), `modules/production/__init__.py:53-62`, `tests/logistyka_fixtures.py:46-51`, `tests/krawedzie_fixtures.py:47-53`, `TABLES` w `tests/test_dorobka_dalsze_stanowiska.py`, `tests/test_dorobka_trasa_krawedzi.py`, `tests/test_mobile_api_alias_krawedzi.py`, `tests/test_worker_profiles.py`

**Interfaces:**
- `priorytety/stale.py`: `STATUSY_PRODUKCJI = ('czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_sklejanie', 'czeka_na_formatowanie', 'czeka_na_krawedzie', 'czeka_na_lakiernie', 'czeka_na_pakowanie')` (7, bez `w_realizacji` i `czeka_na_logistyke`); `STATUSY_ZROBIONE = sposoby.STATUSY_PO_SPAKOWANIU`; `ETAP_STATUSU` (wyciecie/skladanie 0, sklejanie 1, formatowanie 2, krawedzie 3, lakiernie 4, logistyke/pakowanie 5, po spakowaniu 6); `ETAP_STANOWISKA` (`cutting`/`assembly` 0, `gluing` 1, `formatting` 2, `edges` 3, `painting` 4, `packaging` 5); `STANOWISKA = station_catalog.STATION_ORDER`; `STANOWISKA_ZAMOWIENIOWE = ('formatting', 'packaging')`; `TAG_PO_TERMINIE, TAG_BLISKO_TERMINU, TAG_ROZPOCZETE, TAGI`; `RODZAJE_SZCZEBLA = ('stars', 'tag', 'route')`; `DRABINA_DOMYSLNA = (('stars', 5), ('tag', 'po_terminie'), ('stars', 4), ('tag', 'blisko_terminu'), ('tag', 'rozpoczete'), ('stars', 3), ('stars', 2), ('stars', 1), ('stars', 0))`; `POWODY_ODLOZENIA`, `JEDNOSTKI = ('pozycja', 'zamowienie')`, `TRYBY = ('stary', 'stol')`, `AKCJE_LOGU = ('gwiazdki', 'szczebel', 'odlozenie', 'odlozenie_zamkniete', 'ustawienia', 'przeliczenie')`; `GWIAZDKI_MAX = 5`; domyślne `STOL_K = 2`, `LIMIT_ODLOZEN = 10`, `BLISKO_TERMINU_DNI = 3`, `LIMIT_HURTU = 500` (jak `logistics/routers/panel_api.py:24`; serwis nie importuje routera — plan K2 też oczekuje go w `stale`), `MIN_APP_VERSION_CODE = 0`, `DEADLINE_DAY_TYPE_DOMYSLNY = 'robocze'`, `TYPY_DNI = ('robocze', 'kalendarzowe')`; funkcje kluczy — **dosłownie** (spec 8.6; migracja, K2 i K3 piszą/czytają dokładnie te napisy): `klucz_tryb(S) == 'priorytety_tryb_' + S`, `klucz_stol(S) == 'priorytety_stol_' + S`, `klucz_jednostka(S) == 'priorytety_jednostka_' + S`, `klucz_limit(S) == 'priorytety_limit_odlozen_' + S` (**nie** `priorytety_limit_` — inaczej `ustawienia.limit(S)` zawsze odda domyślne 10, a zmiana limitu z Konfiguracji K2 nie zadziała), `klucz_blokady(S) == 'priorytety_blokada_' + S`; stałe `KLUCZ_BLISKO = 'priorytety_blisko_terminu_dni'`, `KLUCZ_MIN_APP = 'priorytety_min_app_version_code'`, `KLUCZ_TYP_DNI = 'DEADLINE_DAY_TYPE'`.
- `priorytety/models.py` (importuje tylko `extensions.db`, `modules.production.models.get_local_now` i `priorytety.stale`; **bez** importu `modules.production.logistics.models` — trasa wyłącznie napisem, Doprecyzowania „Importy …”): `PriorityRung` (`prod_priority_rungs`: `kind` Enum(`'stars','tag','route'`, name=`priority_rung_kind`), `stars` SmallInteger NULL, `tag` String(32) NULL, `route_id` `ForeignKey('prod_routes.id', ondelete='CASCADE')` UNIQUE, `position` Integer NOT NULL, `created_at`, `updated_at`, `updated_by`; `UniqueConstraint('kind','stars', name='uq_prod_priority_rungs_stars')`, `UniqueConstraint('kind','tag', name='uq_prod_priority_rungs_tag')`; `route = relationship('Route')`), `PriorityLog` (`prod_priority_log`, kolumny 8.3, `action` Enum(*AKCJE_LOGU, name=`priority_log_action`), indeksy na `order_id`, `route_id`, `station_code`, `created_at`), `StationDesk` (`prod_station_desk`, kolumny 8.4, `UniqueConstraint('station_code','unit_key', name='uq_prod_station_desk_unit')`). Wszystkie `created_at`/`pulled_at` z `get_local_now`.
- `models.ProductionOrder`: `priority_stars = Column(SmallInteger, nullable=False, default=0)`, `priority_stars_set_at = Column(DateTime)`, `priority_stars_set_by = Column(Integer)`, `priority_rank = Column(Integer, index=True)`, `priority_rung = Column(Integer)`.
- `priorytety/services/ustawienia.py`: `tryb(S) -> str`, `miejsca(S) -> int`, `jednostka(S) -> str`, `limit(S) -> int`, `prog_blisko(sesja=None) -> int` (z `sesja` — jeden odczyt wiersza `prod_config` **tą** sesją, bez `config_service` i bez dotykania `db.session`; dla `kolejka.utrwal`), `min_app_version() -> int`, `typ_dni_terminu() -> str` (wartość spoza `TYPY_DNI` → `'robocze'` + WARNING), `klucz_blokady(S) -> str`. Każda czyta `config_service.get_config(klucz, domyślna)` i waliduje typ (`int(...)`, wartości spoza list → domyślna + WARNING). Nieznany kod stanowiska → `ValueError`.
- `tests/priorytety_fixtures.py`: `drabina_domyslna()` — wstawia 9 wierszy `PriorityRung` jak seed migracji (`position` 1..9) i commituje; `czyste_ustawienia` — fixture `autouse=False` do importu, wołający `config_service.invalidate_config_cache()` przed i po teście (singleton z cache 60 min przeżywa między testami); `ustaw(klucz, wartosc, typ='string')` — wiersz `ProductionConfig` + unieważnienie cache.
- `priorytety/__init__.py`: docstring (pakiet, odesłanie do specu), `from . import models  # noqa: F401`; **bez** `Blueprint` (K2 dopisze `priorytety_panel_bp`).

- [x] **Step 0: Gałąź i punkt wyjścia**

```bash
git fetch origin && git checkout -b claude/priorytety-produkcji origin/claude/logistyka-etap-4
git log -1 --oneline   # b4b4a54d
```
Run: `PYTEST tests/` — zapisz wynik (liczba `passed`/`skipped`) do raportu jako punkt wyjścia; w tym środowisku planowania nie było Dockera, więc plan nie podaje liczby. Oczekiwane: 0 failed.

- [x] **Step 1: Test kształtu migracji (pada)**

Create `tests/test_migracja_priorytety.py` wg `tests/test_migracja_krawedzie.py` (czyta plik, `MigrationService.split_statements`, bez modeli): `test_plik_istnieje`, `test_runner_rozpoznaje_nazwe_pliku` (`MigrationService(db=None)._match(nazwa) is not None`), `test_sortuje_sie_po_ostatniej_migracji_logistyki` (`nazwa > '2026-10-02-raport-planowana-trasa.sql'`), `test_nie_uzywa_delimiter`, `test_kolumny_prod_orders_osloniete_information_schema` (5 bloków `SET @brak … PREPARE krok FROM @sql` z nazwami kolumn 8.1 oraz blok indeksu `ix_prod_orders_priority_rank` przez `information_schema.STATISTICS`), `test_trzy_tabele_create_if_not_exists` (`prod_priority_rungs`, `prod_priority_log`, `prod_station_desk`, każda z `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`, FK `ON DELETE CASCADE` do `prod_routes`/`prod_orders`/`prod_products`), `test_seed_dziewieciu_szczebli_w_kolejnosci_3_1` (jedno `INSERT IGNORE INTO prod_priority_rungs` z 9 krotkami: `('stars',5,NULL,1)`, `('tag',NULL,'po_terminie',2)`, `('stars',4,NULL,3)`, `('tag',NULL,'blisko_terminu',4)`, `('tag',NULL,'rozpoczete',5)`, `('stars',3,…,6)`, `('stars',2,…,7)`, `('stars',1,…,8)`, `('stars',0,…,9)`), `test_38_wierszy_prod_config` (7 stanowisk × {`priorytety_tryb_`→`'stary'`/string, `priorytety_stol_`→`'2'`/integer, `priorytety_jednostka_`→`'pozycja'` poza `formatting`/`packaging`=`'zamowienie'`, `priorytety_limit_odlozen_`→`'10'`/integer, `priorytety_blokada_`→`''`/string} + `priorytety_blisko_terminu_dni`=`'3'`/integer, `priorytety_min_app_version_code`=`'0'`/integer, `DEADLINE_DAY_TYPE`=`'robocze'`/string; wszystko `INSERT IGNORE`), `test_brak_zmian_enum_istniejacych_tabel` (żadnego `MODIFY`/`ALTER … ENUM` na `prod_products`, `prod_orders`, `prod_logistics_log`).

Run: `PYTEST tests/test_migracja_priorytety.py` → FAIL (`brak pliku migracji`).

- [x] **Step 2: Migracja**

Create `migrations/2026-10-05-priorytety-produkcji.sql`. Nagłówek: „Priorytety produkcji P1 (spec 2026-10-04, sekcja 8). Idempotentna: …”. Kolumny wzorem `2026-10-02-logistyka-niedostarczone-na-trasie.sql`:

```sql
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'priority_stars');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN priority_stars TINYINT NOT NULL DEFAULT 0',
              'SELECT ''priority_stars juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;
```
(analogicznie `priority_stars_set_at DATETIME NULL`, `priority_stars_set_by INT NULL`, `priority_rank INT NULL`, `priority_rung INT NULL`; indeks `ix_prod_orders_priority_rank (priority_rank)` przez `information_schema.STATISTICS` jak indeks logu w pliku-wzorze). Tabele `CREATE TABLE IF NOT EXISTS` z kolumnami 8.2–8.4 (`id INT NOT NULL AUTO_INCREMENT PRIMARY KEY`, `kind ENUM('stars','tag','route') NOT NULL`, `UNIQUE KEY uq_prod_priority_rungs_stars (kind, stars)`, `UNIQUE KEY uq_prod_priority_rungs_tag (kind, tag)`, `UNIQUE KEY uq_prod_priority_rungs_route (route_id)`, `CONSTRAINT fk_prod_priority_rungs_route FOREIGN KEY (route_id) REFERENCES prod_routes (id) ON DELETE CASCADE`; w logu `action ENUM(...)` z 6 akcjami, indeksy `order_id`, `route_id`, `station_code`, `created_at`, FK `order_id → prod_orders ON DELETE CASCADE`; stół: `unit_key VARCHAR(24) NOT NULL`, `UNIQUE KEY uq_prod_station_desk_unit (station_code, unit_key)`, FK do `prod_orders` i `prod_products` CASCADE). Seed szczebli i 38 wierszy `prod_config` przez `INSERT IGNORE … VALUES (...), (...)` z `NOW(), NOW()` (wzór `2026-09-30-logistyka-paczki-blokada.sql`). `INSERT IGNORE` szczebli jest idempotentny dzięki `uq_…_stars` (gwiazdki) i `uq_…_tag` (tagi) — kolumna NULL w drugim kluczu nie przeszkadza, bo każdy rodzaj ma swój klucz niepusty.

Run: `PYTEST tests/test_migracja_priorytety.py tests/test_migration_service.py` → PASS.

- [x] **Step 3: Migracja ×2 na kontenerze `db`**

```bash
docker compose exec app flask migrate && docker compose exec app flask migrate   # drugi przebieg: nic do zrobienia
docker compose exec app flask migrate-status
```
Sprawdź SQL-em (wynik do raportu, bez danych klientów): `SHOW CREATE TABLE prod_priority_rungs`, `SELECT kind, stars, tag, position FROM prod_priority_rungs ORDER BY position` (9 wierszy w kolejności 3.1), `SELECT COUNT(*) FROM prod_config WHERE config_key LIKE 'priorytety_%' OR config_key = 'DEADLINE_DAY_TYPE'` (38), `SHOW COLUMNS FROM prod_orders LIKE 'priority%'` (5). Drugi przebieg nie zmienia liczb.

- [x] **Step 4: Pakiet, modele, stałe, ustawienia, fixtury**

Create pliki pakietu wg Interfaces; `modules/production/__init__.py:53-62` — dopisz import modeli pakietu w **osobnym** bloku `try` tuż za blokiem modeli, z `logger.error` przy `ImportError` (nie `warning`: brak modeli pakietu = `setup-db`/`create_all` bez trzech tabel). `ProductionOrder` — pięć kolumn po `repack_reason` (`:220`), z komentarzem „Priorytety produkcji (spec 8.1): pamięć podręczna rangi, liczy ją wyłącznie `priorytety.services.kolejka.utrwal()`”. Fixtury: dopisz trzy modele do każdej listy `TABLES` z `Route` (sześć plików z tabeli ugruntowania). Create `tests/priorytety_fixtures.py`.

Testy jednostkowe w `tests/test_priorytety_ustawienia.py` (nowy, mały): domyślne bez wierszy w bazie (`miejsca('gluing') == 2`, `jednostka('formatting') == 'zamowienie'`, `jednostka('gluing') == 'pozycja'`, `prog_blisko() == 3`, `typ_dni_terminu() == 'robocze'`), wartość z `prod_config` wygrywa (`ustaw('priorytety_stol_gluing', '1', 'integer')` → `miejsca('gluing') == 1`; `ustaw('priorytety_limit_odlozen_gluing', '3', 'integer')` → `limit('gluing') == 3`; `ustaw('priorytety_jednostka_gluing', 'zamowienie')` → `jednostka('gluing') == 'zamowienie'`; `ustaw('priorytety_tryb_gluing', 'stol')` → `tryb('gluing') == 'stol'`), dosłowne klucze `test_klucze_dokladnie_jak_spec_8_6` (`stale.klucz_tryb/stol/jednostka/limit/blokady('gluing')` == `'priorytety_tryb_gluing'`, `'priorytety_stol_gluing'`, `'priorytety_jednostka_gluing'`, `'priorytety_limit_odlozen_gluing'`, `'priorytety_blokada_gluing'`; `ustawienia.klucz_blokady('gluing') == stale.klucz_blokady('gluing')`; każdy z 35 kluczy stanowiskowych migracji = `stale.klucz_*(S)` dla `S` ze `stale.STANOWISKA` — porównanie z napisami wyciętymi z pliku migracji, jak w `test_migracja_priorytety.py`), wartość spoza listy → domyślna (`typ_dni_terminu()` dla `'lunarne'` → `'robocze'`), nieznane stanowisko → `ValueError`; `prog_blisko(sesja=wlasna)` czyta wiersz własną sesją i nie autoflushuje `db.session` (obiekt dodany do `db.session` przed wywołaniem zostaje w `db.session.new`); `stale.STATUSY_PRODUKCJI` ma 7 pozycji z `czeka_na_krawedzie` i `czeka_na_lakiernie`, bez `w_realizacji`, `czeka_na_logistyke`, `czeka_na_wykanczanie`; `DRABINA_DOMYSLNA` ma 9 szczebli w kolejności 3.1 (`blisko_terminu` przed `rozpoczete`).

Run: `PYTEST tests/test_priorytety_ustawienia.py tests/test_logistyka_trasy_serwis.py tests/test_blokady_zamowien.py tests/test_produkty_masowa_zmiana_statusu.py` → PASS (fixtury z nowymi tabelami działają; `create_all` z FK do `prod_routes`/`prod_products` przechodzi na SQLite).

- [x] **Step 5: Commit**

```bash
git add migrations/2026-10-05-priorytety-produkcji.sql modules/production/priorytety modules/production/models.py modules/production/__init__.py tests/
git commit -m "feat(priorytety): migracja P1, modele, stale i ustawienia pakietu priorytety" -m "<stopka atrybucji sesji>"
```

---

### Task 2: `kolejka.policz()` i `kolejka.kandydaci_stanowiska()` — czysta część algorytmu

**Files:**
- Create: `modules/production/priorytety/services/kolejka.py` (część czysta; `utrwal` dochodzi w Task 4), `tests/test_priorytety_kolejka.py`

**Interfaces** (K3 i K4a polegają na nazwach):
- `kolejka.Migawka = namedtuple('Migawka', 'dzis prog_blisko_dni zamowienia pozycje trasa_zamowienia trasy szczeble')`: `zamowienia: {order_id: Zamowienie(id, numer, gwiazdki, rank, rung)}`, `pozycje: [Pozycja(id, order_id, status, deadline_date, sequence, dorobka, created_at, rank, is_priority, manual_override)]` — wszystkie pozycje zamówień aktywnych (także spakowane/anulowane: potrzebne do tagu „Rozpoczęte”), `trasa_zamowienia: {order_id: route_id}` tylko dla tras robocza/zatwierdzona, `trasy: {route_id: Trasa(id, name, date_from, status)}`, `szczeble: [Szczebel(id, kind, stars, tag, route_id, position)]` wszystkie wiersze (filtrowanie po statusie trasy robi `policz`).
- `kolejka.policz(migawka) -> Wynik`: `Wynik.zamowienia: {order_id: RangaZamowienia(rank, rung, szczebel, tagi, termin)}` (`szczebel` ∈ `'trasa'|'gwiazdki'|'po_terminie'|'blisko_terminu'|'rozpoczete'`), `Wynik.pozycje: {product_id: (priority_rank, is_priority)}` tylko dla pozycji aktywnych, `Wynik.ostrzezenia: [str]` (trasy bez szczebla, brak szczebli stałych), `Wynik.drabina: [klucz szczebla]` (lista po wstawieniu wirtualnych).
- Pomocnicze czyste: `termin_zamowienia(pozycje) -> Optional[date]`, `tagi_zamowienia(statusy, termin, dzis, prog_dni) -> set`, `rozpoczete(statusy) -> bool`, `dodaj_dni_robocze(d, n) -> date`, `kompletne_na_stanowisku(statusy, stanowisko) -> bool`, `klucz_zamowienia(pozycja_szczebla, gwiazdki, termin, numer) -> tuple`.
- `kolejka.PozycjaStanowiska = namedtuple(... 'id order_id status dorobka created_at sequence gatunek klasa grubosc dlugosc szerokosc numer gwiazdki termin rung rank na_trasie')`; `kolejka.Kandydaci = namedtuple('Kandydaci', 'kafle niekompletne')`.
- `kolejka.kandydaci_stanowiska(stanowisko, pozycje, statusy_zamowien, szczebel_rozpoczete=None) -> Kandydaci`: `pozycje` — `PozycjaStanowiska` w statusie `STATION_PENDING_STATUS[stanowisko]`, już bez stołu i odłożeń (filtruje K3); `statusy_zamowien: {order_id: tuple((product_id, status), …)}` — wszystkie pozycje zamówienia (para, nie sam status: K3 potrzebuje id brakującej pozycji do `short_id`). Jednostka `pozycja` → `kafle` = lista id pozycji w kolejności 3.2, `niekompletne = []`; jednostka `zamowienie` (stanowisko w `STANOWISKA_ZAMOWIENIOWE`) → `kafle` = lista `order_id` kompletnych po kluczu zamówienia, `niekompletne` = `[(order_id, na_stanowisku, pozycji, brakuje)]` w kolejności rangi, gdzie `brakuje = [(product_id, status), …]` (pozycje aktywne w statusie wcześniejszym niż stanowisko, rosnąco po `product_id`); K3 dokłada `short_id` i stanowisko (status → stanowisko) ze swojego odczytu. `pozycji` = liczba pozycji liczonych do kompletności (bez `anulowane`/`wstrzymane`). `rung is None` (zamówienie jeszcze nieutrwalone) → traktowane jak `len(drabina) + 1` (koniec), `szczebel_rozpoczete` nadal podnosi.

Pseudokod `policz` (spec 4.2, wzór `scripts/symulacja_priorytetow.py:233-345`):
```
drabina = lista kluczy szczebli po position: ('stars', n) | ('tag', t) | ('route', id) — route tylko gdy trasy[id].status in ('robocza','zatwierdzona')
brakujace_stale = DRABINA_DOMYSLNA − drabina → dopisz na końcu w kolejności domyślnej, ostrzeżenie
trasy_bez_szczebla = {route_id z trasa_zamowienia} − {route w drabinie} → wstaw ('route', id) za ostatnim ('route', …) albo za ('stars', 5); ostrzeżenie
pozycja_szczebla = {klucz: indeks+1}
dla zamówienia Z z pozycją w STATUSY_PRODUKCJI:
    aktywne = pozycje Z w STATUSY_PRODUKCJI; termin = min deadline (None gdy brak)
    statusy = statusy pozycji Z poza anulowane/wstrzymane
    tagi = {po_terminie: termin < dzis; blisko_terminu: dzis <= termin <= dodaj_dni_robocze(dzis, prog); rozpoczete: rozpoczete(statusy)}
    szczebel = ('route', trasa) jeśli Z w trasa_zamowienia, inaczej min po pozycja_szczebla z {('stars', gwiazdki)} ∪ {('tag', t) for t in tagi}
    klucz = (pozycja_szczebla[szczebel], -gwiazdki, termin or date.max, numer, id)
rangi 1..M po klucz; rung = pozycja_szczebla[szczebel]
pozycje aktywne: doróbka → 0; inne → rank*100 + sequence; is_priority = doróbka or gwiazdki >= 1 or 'po_terminie' in tagi
```
`rozpoczete(statusy)`: istnieje etap ≥ 2 i etap < 2, albo etap ≥ 5 i etap < 5 (`ETAP_STATUSU`), jak `_przygotuj` w symulacji `:259-260`. Klucz kafla jednostki `pozycja` — dokładnie `klucz` z `kolejka_pozycji` `:324-330` (doróbki po `created_at` na początku; `szczebel` na żywo = min(rung z kolumny, `szczebel_rozpoczete` gdy `rozpoczete` i nie na trasie); **`-gwiazdki`**; `0 if rozpoczete else 1`; `min_termin_grupy[(szczebel, gatunek, klasa, grubosc)]`; gatunek, klasa, `-grubosc`; termin; `-dlugosc`, `-szerokosc`; numer; sequence). `rozpoczete` w kluczu kafla liczone na żywo ze `statusy_zamowien` (nie z kolumny). Brak wymiaru/gatunku → `0.0`/`'?'` jak w symulacji.

- [x] **Step 1: Testy, które padną**

Create `tests/test_priorytety_kolejka.py` (bez Flaska i bazy — czyste struktury): 
- `test_policz_tabela_3_3` — drabina z 3.3 (11 szczebli: trasy Śląsk/Mazowsze/Pomorze między stałymi), zamówienia A–H z tabeli; oczekiwana kolejność `A B C H D E F G`, `szczebel` i `rung` jak w kolumnie „Szczebel”, `F` na szczeblu trasy mimo ★★★★★, `H` na `po_terminie` ponad ★★★★;
- `test_w_trasie_gwiazdki_potem_termin`, `test_termin_rozjemca_w_szczeblu_gwiazdek`, `test_blisko_terminu_dni_robocze_prog_3` (piątek + 3 dni robocze = środa; czwartek po progu bez tagu), `test_zamowienie_bez_terminu_na_koncu_szczebla`, `test_rangi_pozycji_rank_razy_100_plus_sekwencja_dorobki_zero`, `test_is_priority_pochodna` (doróbka, gwiazdki ≥ 1, po terminie; bez — False), `test_pozycje_nieaktywne_poza_wynikiem`, `test_trasa_bez_szczebla_w_miejscu_domyslnym_z_ostrzezeniem` (bez innych tras → tuż pod ★★★★★; z trasą → pod najniższą trasą), `test_brak_szczebli_stalych_uzupelniany_domyslnie`, `test_trasa_zaladowana_nie_liczy_sie_jako_trasa`, `test_rozpoczete_po_statusach_nie_po_nazwie_stanowiska` (pozycja `cut_to_size=False` prosto w `czeka_na_pakowanie`, druga na Sklejaniu → rozpoczęte), `test_rozpoczete_na_trasie_nie_zmienia_szczebla`;
- `kandydaci`: `test_kandydaci_przyklad_konrada_dab_4cm_przed_3cm` (A 17.10 i B 21.10 na trasie Śląsk, **oba bez gwiazdek** (albo równe — Doprecyzowania „Gwiazdki w kluczu kafla”), pozycje dąb A/B 4 cm i 3 cm: grupa 4 cm pierwsza, w grupie A po długości malejąco, potem B; potem grupa 3 cm tak samo), `test_kandydaci_gwiazdki_przed_grupa_w_szczeblu_trasy` (A ★★, B bez gwiazdek na tej samej trasie: wszystkie pozycje A — 4 cm i 3 cm — przed pozycjami B; klucz 3.2 p. 1 i symulacji; Pytanie 3), `test_kandydaci_grupy_po_najblizszym_terminie_w_grupie` (grupa 3 cm z pilnym zamówieniem przed grupą 4 cm bez pilnych — wariant A2, symulacja C), `test_kandydaci_w_grupie_termin_przed_dlugoscia`, `test_kandydaci_przyklad_xy_rozpoczete_wskakuje_na_szczebel_tagu` (X 4 pozycje, Y 3 po 4 cm; po zakończeniu 190×50×4 z X pozostałe trzy X przed resztą Y, `szczebel_rozpoczete=5`), `test_kandydaci_rozpoczete_przed_grupowaniem_w_tym_samym_szczeblu`, `test_kandydaci_dorobki_pierwsze_po_created_at`, `test_kandydaci_zamowienie_kompletne_na_stol_niekompletne_osobno` (Formatowanie: zamówienie z pozycją na Sklejaniu → `niekompletne` z `(na_stanowisku, pozycji, brakuje)`), `test_kandydaci_ostatnia_pozycja_czyni_zamowienie_kompletnym`, `test_kandydaci_pozycje_dalej_licza_sie_jako_zrobione`, `test_kandydaci_wstrzymana_nie_blokuje_kompletnosci`, `test_kandydaci_bez_szczebla_rozpoczete_nie_podnosi`.

Run: `PYTEST tests/test_priorytety_kolejka.py` → FAIL (`ImportError`/`AttributeError`).

- [x] **Step 2: Implementacja części czystej**

Create `kolejka.py` z docstringiem modułu (źródło: spec 3.2/4.2, decyzje 5.10, odwołanie do skryptu symulacji jako wzorca). Żadnego importu `db` w tej części (import `blokady_zamowien` i modeli dopiero w Task 4, w funkcjach `utrwal`).

Run: `PYTEST tests/test_priorytety_kolejka.py` → PASS.

- [x] **Step 3: Commit**

`feat(priorytety): algorytm rangi zamowien policz i kolejnosc kafli kandydaci_stanowiska`

---

### Task 3: Drabina — szczeble, miejsce domyślne, szczebel trasy, przesunięcie, samonaprawa

**Files:**
- Create: `modules/production/priorytety/services/drabina.py`, `tests/test_priorytety_drabina.py`
- Modify: `modules/production/logistics/services/routes.py:406-416` (`utworz`), `:658-665` (`usun`)

**Interfaces:**
- `drabina.szczeble(aktualny=False) -> List[PriorityRung]` — widoczne: `stars`, `tag` oraz `route` z trasą `robocza`/`zatwierdzona` (join `Route`), po `position`; `aktualny=True` → `with_for_update().populate_existing()` (wołać pod blokadą tras).
- `drabina.wszystkie_do_zapisu() -> List[PriorityRung]` — wszystkie wiersze `FOR UPDATE` po `position` (także ukryte trasy); tylko pod blokadą tras.
- `drabina.miejsce_domyslne(wszystkie, aktywne_route_ids) -> int` — indeks wstawienia (0-based) w liście `wszystkie`: za ostatnim szczeblem `route` trasy aktywnej, a gdy takiego nie ma — za `('stars', 5)`.
- `drabina.zapewnij_szczebel_trasy(route, user_id=None) -> PriorityRung` — **pod blokadą tras trzymaną przez wołającego** (`routes.utworz`, `uzupelnij`): `wszystkie_do_zapisu()`; istnieje → zwróć (idempotentne, także dla trasy po „Cofnij załadunek” — wiersz nigdy nie znikał); brak → `PriorityRung(kind='route', route_id=…)` w miejscu domyślnym, renumeracja `position` 1..n wszystkich wierszy, `flush`, log `szczebel` (`route_id`, `new_value=pozycja`). Nie commituje.
- `drabina.usun_szczebel_trasy(route_id) -> bool` — pod blokadą tras: DELETE wiersza (jeśli jest) + renumeracja; dla MySQL dubluje FK CASCADE, dla SQLite jedyna droga.
- `drabina.przesun(rung_id, pozycja, user_id=None) -> PriorityRung` — `routes.zablokuj_trasy()` (ponowna blokada w tej samej transakcji jest bezpieczna; K2 i tak woła `_zapis_pod_blokada()` wcześniej) → `wszystkie_do_zapisu()`; `kind == 'stars'` → `BladDrabiny('szczebel_staly', 400)`; brak → `BladDrabiny('brak_szczebla', 404)`; trasa poza `robocza`/`zatwierdzona` → `BladDrabiny('trasa_nieaktywna', 409)`; `pozycja` ∉ 1..len(widoczne) → `BladDrabiny('pozycja_poza_zakresem', 400)`. Pozycja docelowa liczona wśród **widocznych** szczebli; przesunięcie = wyjęcie i wstawienie przed widocznym szczeblem o indeksie `pozycja` (albo na koniec), potem renumeracja wszystkich wierszy. Log `szczebel` (`old_value`/`new_value` = pozycje, `route_id` dla tras). Nie commituje.
- `drabina.uzupelnij(user_id=None) -> int` — `routes.zablokuj_trasy()` → brakujące szczeble stałe z `DRABINA_DOMYSLNA` (dopisane w kolejności domyślnej na końcu, gdy drabina pusta — jak seed) + `zapewnij_szczebel_trasy` dla każdej trasy `robocza`/`zatwierdzona` bez szczebla; zwraca liczbę dopisanych. Nie commituje.
- `drabina.pozycja_tagu(tag) -> Optional[int]`, `drabina.pozycja_szczebla(rung) -> int` (indeks wśród widocznych, 1-based — do „szczebel 1 z 11” w K2/K4a).
- `drabina.BladDrabiny(Exception)`: `kod`, `komunikat` (po polsku), `status`.
- `routes.utworz` (`:406-416`): po `db.session.flush()` → `drabina.zapewnij_szczebel_trasy(trasa, user_id)` (import lokalny w funkcji — `routes.py` nie może importować pakietu na górze bez ryzyka cyklu: `drabina` importuje `routes`). `drabina.py` importuje **moduł** (`from modules.production.logistics.services import routes`) i woła `routes.zablokuj_trasy()` — nie `from … routes import zablokuj_trasy`: testy podmieniają `routes.zablokuj_trasy` (np. `tests/test_logistyka_trasy_flota.py:120`), a import nazwy ominąłby podmianę. `routes.usun` (`:658-665`): przed `db.session.delete(route)` → `drabina.usun_szczebel_trasy(route.id)`.

- [x] **Step 1: Testy, które padną**

Create `tests/test_priorytety_drabina.py` na `tests/logistyka_fixtures.py` (`app`, `client`, `zamowienie`, `pojazd`) + `tests/priorytety_fixtures.drabina_domyslna` + `tests/blokady_pomocnicze` (`Zapytania`, `indeks_blokady_tras`):
`test_seed_dziewieciu_szczebli_w_kolejnosci_3_1` (po `drabina_domyslna()`: `szczeble()` → `[('stars',5),('tag','po_terminie'),('stars',4),('tag','blisko_terminu'),('tag','rozpoczete'),('stars',3),('stars',2),('stars',1),('stars',0)]`), `test_utworz_zaklada_szczebel_pod_blokada_tras` (`Zapytania`: `indeks_blokady_tras(z) < pierwsze INSERT INTO prod_priority_rungs`; szczebel `route` tuż pod ★★★★★ gdy tras nie ma), `test_druga_trasa_wchodzi_pod_najnizsza_trase` (dwie trasy → `[g5, trasa1, trasa2, po_terminie, …]`; trzecia po przesunięciu trasy2 pod „bez gwiazdek” → za trasą2), `test_zapewnij_idempotentne`, `test_przesun_tag_i_trase_renumeruje_1_n`, `test_przesun_gwiazdek_odmowa_szczebel_staly` (400), `test_przesun_nieznany_404`, `test_przesun_trasy_nieaktywnej_409` (trasa `zaladowana` — status ustawiony wprost w teście), `test_przesun_pozycja_poza_zakresem_400`, `test_przesun_bierze_blokade_tras_przed_szczeblami` (`indeks_blokady_tras(z) < pierwszy SELECT … FROM prod_priority_rungs … FOR UPDATE`), `test_przesun_zapisuje_log_szczebel`, `test_szczebel_trasy_zaladowanej_ukryty_po_cofnieciu_wraca` (`route.status='zaladowana'` → brak w `szczeble()`; `'zatwierdzona'` → wraca na tej samej `position`), `test_usun_trase_usuwa_szczebel_i_renumeruje` (`routes.usun`), `test_uzupelnij_dopisuje_brakujace_trasy_i_szczeble_stale` (pusta tabela + dwie trasy → 11, drugi raz → 0), `test_pozycja_tagu_rozpoczete`, `test_serwis_nie_commituje` (po `przesun` `db.session.rollback()` cofa zmianę).

Run: `PYTEST tests/test_priorytety_drabina.py` → FAIL.

- [x] **Step 2: Implementacja**

Create `drabina.py`, zmień `routes.utworz`/`usun`. Renumeracja: `for i, r in enumerate(wszystkie): if r.position != i + 1: r.position = i + 1; r.updated_at = teraz`.

Run: `PYTEST tests/test_priorytety_drabina.py tests/test_logistyka_trasy_serwis.py tests/test_logistyka_trasy_api.py tests/test_logistyka_kierowcy.py tests/test_logistyka_routimo.py tests/test_logistyka_optymalizacja.py tests/test_logistyka_przeglad_koncowy.py tests/test_logistyka_trasy_routing.py tests/test_logistyka_trasy_integracja.py tests/test_logistyka_daleko_od_drogi.py tests/test_dostawa_api.py` → PASS (wszyscy wołający `routes.utworz`).

- [x] **Step 3: Commit**

`feat(priorytety): drabina szczebli, szczebel trasy przy utworzeniu trasy pod blokada tras`

---

### Task 4: `kolejka.utrwal()` na własnej sesji, `gwiazdki.ustaw`, warstwa zgodności `priority_service`

**Files:**
- Modify: `modules/production/priorytety/services/kolejka.py` (dopisane `nowa_sesja`, `_migawka`, `utrwal`, `utrwal_po_commicie`, `zaplanuj_po_commicie`, `porzuc_zaplanowane`, `wykonaj_zaplanowane`), `modules/production/services/priority_service.py` (`:886-905` + docstring), `modules/production/services/__init__.py:102-115`, `tests/blokady_pomocnicze.py` (predykaty), `tests/test_priorytety_kolejnosc_zapisow.py` (część przeliczenia przepisana), `tests/test_priority_statusy_krawedzi.py`
- Create: `modules/production/priorytety/services/gwiazdki.py`, `tests/test_priorytety_gwiazdki.py`

**Interfaces:**
- `kolejka.nowa_sesja()` → `db.create_session({})()` (jak `priority_service.nowa_sesja_priorytetow` `:83-94`) z `autoflush = False` (jak `_przelicz_raz` `:247`); testy podmieniają tę funkcję, żeby wstrzyknąć błąd commitu.
- `kolejka.utrwal(zrodlo=None, user_id=None) -> dict` (warunek wstępny: sekcja „Współbieżność”, akapit „Warunek wstępny”): `{'success': bool, 'zamowien': int, 'pozycji': int, 'zmienione_zamowienia': int, 'zmienione_pozycje': int, 'ostrzezenia': [str], 'duration_seconds': float, 'error': str|None}`. **Nigdy nie rzuca** i **nigdy nie dotyka `db.session`**. Dwie próby; druga tylko po `blokady_zamowien.kod_mysql(e) == 1213` (log WARNING), na nowej sesji; drugie 1213 i każdy inny błąd → `success: False`, log ERROR, rollback i `close()` własnej sesji w `finally`.
- `kolejka.utrwal_po_commicie(zrodlo=None) -> Optional[dict]` — do wołania **po** `db.session.commit()` w routerach panelu; każde wywołanie przelicza (bez znacznika „raz na żądanie” — Doprecyzowania); wyjątki tylko do logu (ERROR), zwraca `None` przy wyjątku.
- `kolejka.zaplanuj_po_commicie()`, `porzuc_zaplanowane()`, `wykonaj_zaplanowane()` — flaga w `g` tylko przy `has_request_context()` (wzór `bl_sync.zaplanuj_po_commicie` `:452-495`); `wykonaj_zaplanowane()` **zdejmuje** flagę (`g.pop`) i woła `utrwal_po_commicie()` tylko gdy była; `porzuc_zaplanowane()` też ją zdejmuje.
- `gwiazdki.ustaw(order_ids, gwiazdki, user_id=None, teraz=None) -> dict` `{'zmienione': [id], 'bez_zmian': [id], 'brak': [id]}`; `gwiazdki` musi być `int` 0..`GWIAZDKI_MAX` (bool odrzucony), `order_ids` niepuste, same `int` (bez `bool`) i ≤ `stale.LIMIT_HURTU` — inaczej `gwiazdki.BladGwiazdek(komunikat)` (K2 → 400). Sekwencja: `blokady_zamowien.zablokuj_zamowienia(ids)` → dla zmienianych `priority_stars`, `priority_stars_set_at = teraz`, `priority_stars_set_by = user_id`, `PriorityLog(action='gwiazdki', order_id, old_value, new_value, user_id)` → `flush`. Bez commita, bez blokady tras, bez `utrwal()`.
- `priority_service`: klasa `WarstwaZgodnosciPriorytetow` z `recalculate_all_priorities(self)` → `kolejka.utrwal()` przepisany na stare klucze (`success`, `products_updated` = `zmienione_pozycje`, `products_prioritized` = `pozycji`, `manual_overrides_preserved` = 0, `duration_seconds`, `error`) **plus** nowe klucze; `get_priority_calculator()` zwraca jej instancję (singleton); funkcje modułowe `recalculate_priorities()`/`recalculate_all_priorities()` **bez zmian w ciele** (dalej `get_priority_calculator().recalculate_all_priorities()` — stub testów, Doprecyzowania). `services/__init__.py:102-115` deleguje do `priority_service.get_priority_calculator()`. `NewPriorityCalculator`, `nowa_sesja_priorytetow`, `PriorityError`, `get_priority_statistics` zostają bez zmian (martwe, usuwa K8); docstring modułu dostaje akapit „WARSTWA ZGODNOŚCI (P1, 2026-10)”.
- `tests/blokady_pomocnicze.blokada_pozycji_zamowien(sql)`: `SELECT … FROM prod_products … WHERE prod_products.order_id IN … ORDER BY prod_products.id … FOR UPDATE`. Predykat `zapis` dostaje `'INSERT INTO prod_priority_log'` i `'INSERT INTO prod_station_desk'` (obie tabele mają FK do `prod_orders` — InnoDB sprawdza FK blokadą S na zamówieniu; K3 na tym polega).

Pseudokod `utrwal`:
```
start; for proba in (1, 2):
  sesja = nowa_sesja()
  try:
    migawka = _migawka(sesja)        # zwykłe odczyty: id zamówień z pozycją w STATUSY_PRODUKCJI → zamówienia (numer, gwiazdki, rank, rung) → wszystkie pozycje tych zamówień → RouteStop+Route (status robocza/zatwierdzona) → PriorityRung wszystkie → prog = ustawienia.prog_blisko(sesja) (WŁASNA sesja; nic przez db.session — autoflush wołającego); dzis = get_local_now().date()
    wynik = policz(migawka); log WARNING dla każdej pozycji ostrzezenia
    do_zam = {id: (rank, rung)} gdzie różni się od kolumn; do_poz = {id: (rank, is_priority)} gdzie różni się rank/is_priority albo manual_override True
    if not do_zam and not do_poz: sesja.rollback(); return raport(0, 0)
    ids = sorted(set(do_zam) | {order_id pozycji z do_poz})
    zam = sesja.query(ProductionOrder).filter(id.in_(ids)).order_by(id).with_for_update().populate_existing().all()
    poz = sesja.query(ProductionProduct).filter(order_id.in_(ids)).order_by(id).with_for_update().populate_existing().all()
    przypisz do_zam na zam, do_poz na poz (+ manual_override=False, updated_at=teraz) — same przypisania, bez zapytań
    if zrodlo: sesja.add(PriorityLog(action='przeliczenie', note=zrodlo, new_value=str(len(do_zam)), user_id=user_id))
    sesja.commit(); return raport(success=True, …)
  except OperationalError as e: rollback; close; if proba == 2 or kod_mysql(e) != 1213: return raport(success=False, error)
  except Exception as e: rollback; close; return raport(success=False, error)
  finally: close (idempotentne)
```
Blokada `IN (ids)` zamiast `zablokuj_pozycje(order)` po jednym zamówieniu: jedno zapytanie na tabelę, rosnąco po id, zgodnie z 4.2 („zamówienia FOR UPDATE rosnąco → pozycje tych zamówień rosnąco”). Pozycje czytane po `order_id IN` — jedno zapytanie, więc blokady następnego klucza na indeksie `order_id` jak w `zablokuj_pozycje`.

- [x] **Step 1: Testy, które padną**

Przepisz część przeliczenia `tests/test_priorytety_kolejnosc_zapisow.py` (usuń testy przeliczenia na `NewPriorityCalculator`: `:125-162` i `:256-298` z `_sesje_z_bledami` `:235-255`; testy przeciągania `:43-122` i ich ponowień `:193-233` **zostają** — końcówka żyje do K2, który usunie je razem z nią; pomocniki `:163-191` wspólne; docstring modułu: „przeciąganie (do K2) i `kolejka.utrwal` — nowa kolejność blokad: zamówienia → pozycje”): nowe testy na `tests/krawedzie_fixtures.py` (`app`, `produkt`) + `drabina_domyslna()`: `test_utrwal_blokuje_zamowienia_przed_pozycjami_przed_zapisem` (`Zapytania`: `blokada_zamowien` < `blokada_pozycji_zamowien` < `zapis`; parametry blokady zamówień rosnąco), `test_utrwal_zapisuje_tylko_zmienione_rosnaco_po_id` (dwa zamówienia, jedno już z poprawną rangą → w UPDATE-ach tylko drugie; `id_zapisow_pozycji` rosnąco; `UPDATE prod_orders` przed `UPDATE prod_products`), `test_utrwal_bez_zmian_nie_bierze_blokad` (drugi przebieg: zero `FOR UPDATE`, zero UPDATE), `test_utrwal_zeruje_manual_override_i_podbija_updated_at`, `test_utrwal_nie_dotyka_pozycji_nieaktywnych` (spakowana z `priority_rank=7` zostaje 7), `test_utrwal_nie_commituje_ani_nie_cofa_sesji_wolajacego` (szpieg `db.session.commit/rollback` jak `_szpieg_sesji` w `test_sales_ingest_wyzwalacze.py:758`; praca dodana do `db.session` zostaje niezatwierdzona — na SQLite plikowym jak `app_osobne_polaczenia` (`test_sales_ingest_wyzwalacze.py:100`), albo przez asercję, że `db.session.new` nadal zawiera obiekt — także przy zimnej pamięci podręcznej `config_service` (`invalidate_config_cache()` przed wywołaniem: odczyt progu nie może autoflushować `db.session`)), `test_utrwal_ponawia_raz_po_1213_na_nowej_sesji` (podmiana `kolejka.nowa_sesja` wzorem `_sesje_z_bledami` `:238-255`), `test_utrwal_dwa_1213_bez_zapisow`, `test_utrwal_inny_kod_bez_ponowienia`, `test_utrwal_nie_rzuca_przy_bledzie_odczytu` (`nowa_sesja` zwraca sesję, której `query` rzuca → `success False`, `error` niepusty), `test_nieudane_utrwal_zostawia_db_session_czysta` (**kanoniczny** test „błąd `utrwal` nie brudzi `db.session`”, na nim stoi mapa równoważników K8 — Review Focus 4: pozycja aktywna z rangą do zmiany, błąd wstrzyknięty po blokadach a przed/przy commicie własnej sesji (podmiana `kolejka.nowa_sesja` na sesję, której `commit` rzuca `RuntimeError`) → `success False`, `error` niepusty; `list(db.session.new) == []` i `list(db.session.dirty) == []` po wywołaniu; po `db.session.remove()` pozycja i zamówienie w bazie z rangą sprzed wywołania), `test_warstwa_zgodnosci_wola_utrwal` (`priority_service.get_priority_calculator().recalculate_all_priorities()` i `priority_service.recalculate_all_priorities()` → `success True`, klucze stare i nowe; monkeypatch licznika na `kolejka.utrwal`), `test_utrwal_loguje_przeliczenie_tylko_ze_zrodlem`.

`tests/test_priority_statusy_krawedzi.py`: `test_kalkulator_zna_obie_kolejki_po_rozdziale` → `test_stale_statusy_produkcji_znaja_obie_kolejki` na `stale.STATUSY_PRODUKCJI` (7, krawędzie i lakiernia, bez wykańczania); testy statystyk `:94-120` zostają (funkcja istnieje do K8); `test_nieudane_przeliczanie_priorytetow_czysci_sesje` (`:160`) **zostaje bez zmian** na `NewPriorityCalculator` (klasa żyje nietknięta do K8, który usuwa ją razem z tym plikiem) — K1 go nie przepisuje na `utrwal`, bo kanoniczny test tej własności dla `utrwal` to `test_nieudane_utrwal_zostawia_db_session_czysta` w `tests/test_priorytety_kolejnosc_zapisow.py` (jedno miejsce; dubel w pliku przeznaczonym do usunięcia w K8 zostawiłby po K8 lukę). Fixture `app` tego pliku bez nowych tabel (żaden jego test nie woła `utrwal`).

Create `tests/test_priorytety_gwiazdki.py` (logistyka_fixtures): `test_ustaw_blokuje_zamowienia_rosnaco_przed_zapisem`, `test_ustaw_zapisuje_gwiazdki_czas_autora_i_log`, `test_ustaw_pomija_bez_zmian_i_brakujace`, `test_ustaw_odmawia_poza_0_5_bool_i_ponad_limit`, `test_ustaw_nie_commituje`.

Run: wszystkie trzy → FAIL.

- [x] **Step 2: Implementacja**

Dopisz do `kolejka.py`, utwórz `gwiazdki.py`, przepisz `priority_service.py:886-905` (singleton; funkcje modułowe `:907-930` bez zmian w ciele) (+ docstring), `services/__init__.py:102-115` (delegacja), dodaj predykaty w `blokady_pomocnicze.py`. `sync_service.py:938-939`: log z `zmienione_pozycje`/`zamowien` (klucze nowe), bez zmiany wywołania.

Run: `PYTEST tests/test_priorytety_kolejnosc_zapisow.py tests/test_priority_statusy_krawedzi.py tests/test_priorytety_gwiazdki.py tests/test_sales_ingest_wyzwalacze.py` → PASS (ostatni bez zmian w pliku — potwierdzenie, że klasa została nietknięta i stuby `get_priority_calculator` nadal działają).

- [x] **Step 3: Commit**

`feat(priorytety): utrwal na wlasnej sesji z blokadami zamowienie-pozycje, gwiazdki i warstwa zgodnosci priority_service`

---

### Task 5: Terminy robocze/kalendarzowe, doróbka z rangą 0, `complete_task` bez kasowania rangi

**Files:**
- Modify: `modules/production/services/sync_service.py:3206-3255`, `modules/production/services/config_service.py:60-69`, `modules/production/services/rework_service.py:246-302`, `modules/production/models.py:513-521`, `:712-725`, `tests/test_routing_krawedzie.py:256-278`
- Create: `tests/test_priorytety_terminy.py`, `tests/test_priorytety_dorobka.py`

**Interfaces:**
- `BaselinkerSyncService._calculate_deadline_date(order)` — jak dotąd, ale po wyborze `deadline_days`: `typ = ustawienia.typ_dni_terminu()`; `'kalendarzowe'` → `base_date + timedelta(days=deadline_days)`; inaczej `_add_business_days`. Fallback przy wyjątku konfiguracji → `robocze` (zachowanie dzisiejsze). `_add_business_days` bez zmian.
- `config_service._default_values['DEADLINE_DAY_TYPE'] = 'robocze'`.
- `rework_service.reject_product_quantity`: `priority_rank=0, is_priority=True` w konstruktorze `ProductionProduct(...)` (`:246-297`), wiersz `:302` (`lock_priority`) usunięty (komentarz: spec 4.2 — doróbka 0, najbliższe `utrwal()` niczego tu nie zmienia).
- `ProductionProduct.lock_priority(rank)` / `unlock_priority()` — ciała puste z docstringiem „Martwe od P1 priorytetów (2026-10): rangę liczy `priorytety.services.kolejka.utrwal()`. Usuwane w P4 razem z `priority_manual_override`.” `is_priority_locked` bez zmian. `complete_task`: blok `:714-719` usunięty; `if self.original_product_id is not None and self.current_status == 'czeka_na_formatowanie':` zostaje tylko z zamknięciem `ProductionReworkLog`.

- [x] **Step 1: Testy, które padną**

Create `tests/test_priorytety_terminy.py` (fixture jak `tests/krawedzie_fixtures.py` albo własna minimalna z `ProductionConfig`; `BaselinkerSyncService` tworzony bez sieci — patrz jak `tests/test_sales_ingest_wyzwalacze.py` buduje `serwis_synchronizacji`): `test_domyslnie_dni_robocze_jak_dotad` (piątek 2026-10-09 + 1 → poniedziałek 12.10; 16 dni roboczych od 2026-10-05 → 2026-10-27), `test_kalendarzowe_licza_soboty_i_niedziele` (`DEADLINE_DAY_TYPE='kalendarzowe'`, piątek + 1 → sobota; +16 → 2026-10-21), `test_nieznany_typ_dni_to_robocze_z_ostrzezeniem`, `test_zamowienie_z_wykonczeniem_bierze_finished_days_w_obu_trybach`, `test_deadline_date_nadawany_tylko_przy_tworzeniu_pozycji` (strukturalny na źródle `sync_service.py`: `deadline_date = self._calculate_deadline_date(` występuje wyłącznie w `_create_product_from_order_data` i `_process_single_order_enhanced`; `apply_baselinker_changes` nie woła `_calculate_deadline_date` — nowa pozycja dopisana przez zmiany z Base. przejmuje `existing_product.deadline_date` (`sync_service.py:2789`), więc „nie zawiera `deadline_date`” byłoby fałszywe; brak przeliczania wstecz), `test_domyslna_wartosc_w_config_service`.

Create `tests/test_priorytety_dorobka.py` (`tests/logistyka_fixtures.py` + fixture `bez_statusow_base` jak w `tests/test_blokady_dorobka_base.py`): `test_dorobka_dostaje_range_0_i_is_priority_bez_manual_override` (`reject_product_quantity` → `priority_rank == 0`, `is_priority is True`, `priority_manual_override is False`), `test_utrwal_zostawia_dorobce_zero`, `test_complete_task_na_formatowaniu_nie_rusza_rangi_dorobki_ale_zamyka_log`, `test_lock_i_unlock_priority_nic_nie_robia`.

`tests/test_routing_krawedzie.py:256-278` — asercje `priority_manual_override is False` / `is_priority is False` zamienić na „ranga i flagi bez zmian po `complete_task('gluing')`” (`priority_rank == 0` gdy test ustawi 0; `is_priority is True`), `wpis.closed_at is not None` zostaje; docstring odsyła do specu 9.5.

Run: `PYTEST tests/test_priorytety_terminy.py tests/test_priorytety_dorobka.py tests/test_routing_krawedzie.py` → FAIL w nowych i w zmienionym.

- [x] **Step 2: Implementacja**

Zmiany wg Interfaces. W `_calculate_deadline_date` import `ustawienia` lokalny (jak dziś `config_service`).

Run: `PYTEST tests/test_priorytety_terminy.py tests/test_priorytety_dorobka.py tests/test_routing_krawedzie.py tests/test_blokady_dorobka_base.py tests/test_dorobka_dalsze_stanowiska.py tests/test_dorobka_trasa_krawedzi.py tests/test_dostawa_dorobka_na_trasie.py tests/test_sync_flaga_krawedzi.py` → PASS.

- [x] **Step 3: Commit**

`feat(priorytety): terminy robocze lub kalendarzowe, dorobka z ranga 0, complete_task bez kasowania rangi`

---

### Task 6: Wyzwalacze `utrwal()` — logistyka, Dostawa, cron, panel produktów; pełny pakiet

**Files:**
- Modify: `modules/production/logistics/routers/trasy_api.py` (`_akcja` po `:380`, `route_create` po `:548`, `route_delete` po `:649`), `dostawa_api.py` (`_zapis` po `:160` i przy `:169`), `weryfikacja_api.py` (`verification_revert_to_packing`, po udanym `cofnij_do_pakowania` `:310-313`), `panel_api.py` (po `:233`, po `:276`), `cron_api.py` (po trzecim commicie), `modules/production/services/mobile_api_service.py` (`with_idempotency`, po bloku `:649-656`), `modules/production/routers/api/products_api.py` (`admin_apply_baselinker_changes` po udanym zastosowaniu, `bulk_action` gałąź `update_status`)
- Create: `tests/test_priorytety_wyzwalacze.py`
- Modify (testy istniejące, izolacja od nowego wyzwalacza): `tests/test_logistyka_cron.py:119-145` (`test_cron_przenosi_osierocone_z_logistyki_do_pakowania` — `podbite == {osierocony_id}`: `utrwal` w cronie podbija `updated_at` obu aktywnych pozycji; w tym teście `monkeypatch.setattr(kolejka, 'utrwal', lambda *a, **k: {'success': True})`, sens testu — ETag przeniesionej pozycji — zostaje), `tests/test_produkty_masowa_zmiana_statusu.py:509-524` (`len(blokady_z) == 2` w całym żądaniu: `Zapytania` słucha `db.engine`, więc łapie też blokadę zamówień `utrwal()` z własnej sesji po commicie — w teście `monkeypatch.setattr(kolejka, 'utrwal_po_commicie', lambda *a, **k: None)`). Przed Step 2: `grep -n "len(blokady\|pierwsze(\|z.lista\[" tests/test_produkty_masowa_zmiana_statusu.py tests/test_blokady_dorobka_base.py tests/test_logistyka_*.py tests/test_dostawa*.py tests/test_weryfikacja*.py` — każdy test, który liczy blokady/zapisy w oknie `Zapytania` obejmującym commit **i** to, co po nim, dostaje tę samą izolację; listę wpisać do raportu.

**Interfaces:**
- Cron: **po** `przelicz_otwarte` + commit **i po uruchomieniu wątków w tle** (`bl_sync.uruchom_w_tle`, `geocoding.uruchom_w_tle`), we własnym `try/except Exception`: `uzupelnione = drabina.uzupelnij(); db.session.commit()`; `raport = kolejka.utrwal()`; odpowiedź dostaje `'szczeble_uzupelnione': uzupelnione` i `'priorytety_utrwalone': raport` (pełny słownik raportu). Błąd `utrwal` nie jest wyjątkiem (raport `success: False`), więc nie psuje 200 crona; błąd `uzupelnij` → `db.session.rollback()`, log ERROR, `szczeble_uzupelnione: None`, `priorytety_utrwalone: None`, dalej 200 (fazy logistyki są już zatwierdzone, a dopychacz Base. i geokoder nie mogą stać przez błąd priorytetów). Log o dopisanych szczeblach na poziomie INFO (`tests/test_logistyka_cron.py:135` liczy ostrzeżenia `cron_api.logger`).
- Importy w routerach logistyki (`trasy_api`, `panel_api`, `dostawa_api`, `cron_api`, `weryfikacja_api`): `from modules.production.priorytety.services import kolejka, drabina` **wewnątrz funkcji**, nie na górze modułu — `logistics/__init__.py:19` importuje routery, a pakiet `priorytety` sięga do logistyki (`stale` → `sposoby`, `drabina` → `routes`), więc import na górze routera domyka cykl (Doprecyzowania „Importy …”). Tak samo `with_idempotency` (import lokalny jak przy `bl_sync`).
- `with_idempotency`: czwarty blok po commicie — `from modules.production.priorytety.services.kolejka import wykonaj_zaplanowane; wykonaj_zaplanowane()` w `try/except` z logiem ERROR, jak trzy poprzednie.
- `weryfikacja_api.verification_revert_to_packing`: po bloku `try: weryfikacja.cofnij_do_pakowania(...) except WeryfikacjaBlad: return _blad(e)` → `from modules.production.priorytety.services import kolejka; kolejka.zaplanuj_po_commicie()`, potem `return _odpowiedz(...)`. Bez commita w handlerze; wykonanie robi hook `with_idempotency` z K1. Pozostałe zapisy Weryfikacji bez wyzwalacza (nie przestawiają pozycji na status produkcji) — przed Step 2 potwierdź: `grep -n "current_status = 'czeka_na" modules/production/logistics/services/weryfikacja.py` → jedno trafienie, w `cofnij_do_pakowania`; inne trafienie → dopisać ten sam wyzwalacz w handlerze, który je woła, i odnotować w raporcie.
- `products_api`: `kolejka.utrwal_po_commicie()` (bez źródła — bez wpisu `przeliczenie` w logu) gdy `apply_baselinker_changes` zwrócił sukces (po `bl_sync.wyslij_zaplanowane()` `:1308`); `kolejka.utrwal_po_commicie()` w gałęzi `update_status` po `results['success']` (po commicie w `_zapisz_zmiane_statusu`, za odmową 409 `:1613` — wzorem `if action == 'update_status' and results.get('success'):` tuż przed `return jsonify(results)` `:1668`; `update_priority` i `delete` — bez wyzwalacza).

- [x] **Step 1: Testy, które padną**

Create `tests/test_priorytety_wyzwalacze.py` (logistyka_fixtures; `drabina_domyslna()`; licznik wywołań przez monkeypatch `kolejka.utrwal` opakowany tak, że wywołuje oryginał i notuje, czy w chwili wywołania `db.session` nie ma otwartej, niezatwierdzonej pracy — `db.session.new/dirty` puste — „po commicie”): `test_route_create_zaklada_szczebel_i_utrwala_po_commicie`, `test_dodanie_przystanku_utrwala_po_commicie` (zamówienie dostaje `priority_rung` = pozycja szczebla trasy i `priority_rank` w bazie po żądaniu), `test_zatwierdzenie_i_cofniecie_utrwalaja`, `test_route_delete_utrwala` (zamówienie wraca na szczebel gwiazdek), `test_delivery_method_utrwala_po_commicie`, `test_handed_over_utrwala`, `test_zapis_dostawy_planuje_utrwal_a_dekorator_wykonuje_po_commicie` (telefon kierowcy, np. `finish-loading` z `tests/dostawa_pomocnicze.py`; licznik = 1, wywołanie po commicie; odmowa 409 → 0), `test_ponowienie_1213_w_dostawie_porzuca_plan_i_planuje_od_nowa` (wzór `tests/test_dostawa_ponowienie_1213.py`; licznik = 1), `test_cofnij_do_pakowania_planuje_utrwal_a_dekorator_wykonuje_po_commicie` (telefon Weryfikacji, wzór `tests/test_weryfikacja_problem.py` — `_post(..., 'revert-to-packing', ..., reason='inne')` na zamówieniu w całości `spakowane` z `priority_rank` z dawnego przeliczenia; licznik = 1, wywołanie po commicie, po żądaniu zamówienie i pozycje mają rangę z `policz()` (pozycje `czeka_na_pakowanie` w wyniku), a rangi zamówień aktywnych są unikatowe; odmowa — brak powodu, 422 `invalid_problem` — i zamówienie poza zakresem, 409 — → licznik 0), `test_cron_ma_faze_priorytety_utrwalone` (trasa bez szczebla → `szczeble_uzupelnione == 1`, `priorytety_utrwalone['success'] is True`, rangi w bazie; istniejące klucze odpowiedzi bez zmian), `test_cron_uzupelnia_pod_blokada_tras_przed_utrwal` (`Zapytania`: blokada tras przed `INSERT INTO prod_priority_rungs`, a `FOR UPDATE` zamówień dopiero po `COMMIT`/w kolejnych zapytaniach), `test_hurt_statusu_utrwala_a_update_priority_nie` (krawedzie_fixtures; ranga 42 z `update_priority` zostaje), `test_zmiany_z_base_utrwalaja` (na fixturze z `tests/test_blokady_dorobka_base.py`, Base. podmienione), `test_dwa_zadania_w_jednym_tescie_utrwalaja_dwa_razy` (fikstura trzyma `app_context`, więc `g` jest wspólne dla żądań klienta testowego: utworzenie trasy, potem usunięcie → dwa `utrwal`, rangi po drugim żądaniu aktualne), `test_wykonaj_zaplanowane_zdejmuje_plan_z_g` (drugie `wykonaj_zaplanowane()` bez nowego `zaplanuj` → bez `utrwal`), `test_wyjatek_w_utrwal_po_commicie_nie_psuje_odpowiedzi` (monkeypatch `kolejka.utrwal` rzucający → 200/201 i log ERROR).

Run → FAIL.

- [x] **Step 2: Implementacja**

Wg Interfaces i tabeli ugruntowania. W `dostawa_api._zapis`: `kolejka.zaplanuj_po_commicie()` tuż po `db.session.flush()` (`:160`) w `try`; w gałęzi `OperationalError` obok `bl_sync.porzuc_zaplanowane()` → `kolejka.porzuc_zaplanowane()`. W `weryfikacja_api.verification_revert_to_packing`: `kolejka.zaplanuj_po_commicie()` po udanym `cofnij_do_pakowania` (Interfaces).

Run: `PYTEST tests/test_priorytety_wyzwalacze.py tests/test_logistyka_cron.py tests/test_logistyka_trasy_api.py tests/test_dostawa_api.py tests/test_dostawa_ponowienie_1213.py tests/test_blokady_zamowien.py tests/test_produkty_masowa_zmiana_statusu.py tests/test_blokady_dorobka_base.py tests/test_weryfikacja_problem.py tests/test_weryfikacja_akcje.py tests/test_weryfikacja_przeglad_backendu.py` → PASS.

- [x] **Step 3: Pełny pakiet i składnia 3.9**

Run: `PYTEST tests/` → 0 failed; passed = punkt wyjścia + nowe − usunięte testy przeciągania (policz i zapisz). Dodatkowo `cd integrations/blog_seo && python -m pytest` (CLAUDE.md) — bez zmian, ale raport ma to potwierdzić.

Cykl importów (Review Focus 9): trzy świeże procesy, każdy musi przejść bez błędu — `docker compose exec app python -c "import modules.production.priorytety.models"`, `… -c "import modules.production.priorytety.services.drabina, modules.production.priorytety.services.kolejka"`, `… -c "import modules.production.logistics.routers.trasy_api"`; dodatkowo `… -c "from app import create_app"` **tylko** gdy lokalny `config/core.json` wskazuje bazę kontenera `db` (import `create_app()` odpala migracje; nigdy na bazie produkcyjnej — podręcznik 2 p. 9).

Składnia 3.9: dla plików `.py` zmienionych od `b4b4a54d` — `docker run --rm -v "$PWD":/src python:3.9-slim python -c "import ast,sys; [ast.parse(open(p).read(), p, feature_version=(3,9)) for p in sys.argv[1:]]" <pliki>` (wzór z planu 4.4a, Task 3 Step 7). Oczekiwane: bez błędów; brak `X | Y` poza plikami z `from __future__ import annotations`.

- [x] **Step 4: Commit**

`feat(priorytety): wyzwalacze utrwal po commicie w logistyce, Dostawie, cronie i panelu produktow`

---

### Task 7: Raport kroku K1

**Files:**
- Create: `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K1-raport.md`

- [x] **Step 1: Raport** z sekcjami (podręcznik 2 p. 7): **Zrobione** (po Taskach 1–6, z hashami commitów), **Testy** (polecenia i wyniki: punkt wyjścia, każdy plik testów, pełny pakiet, wynik `flask migrate` ×2 i zapytań kontrolnych z Task 1 Step 3, składnia 3.9), **Odstępstwa od planu**, **Rozstrzygnięcia podjęte w trakcie** (numerowane; koszt, jeśli błędne), **Pytania do Konrada**, **Stan gałęzi** (hash, czy wypchnięte — push wg karty), **Co następny krok musi wiedzieć** (co najmniej: sygnatury `kolejka.*`, `drabina.*`, `gwiazdki.ustaw`, `ustawienia.*`, klucze `prod_config`, zasada „router commituje, serwis nie”, `utrwal_po_commicie` vs `zaplanuj/wykonaj`, cache 60 min `config_service` dla K2, `set-priority` nadpisywane przez `utrwal`, kształt `statusy_zamowien`/`brakuje` w `kandydaci_stanowiska` (pary `(product_id, status)`), `stale.LIMIT_HURTU`, rangi zamówień nieaktywnych nieaktualne (czytelnicy filtrują aktywne), importy `priorytety` w routerach logistyki tylko w funkcjach, testy przeciągania zostawione dla K2, lista testów izolowanych od `utrwal` po commicie (Task 6), lista fixtur z nowymi tabelami, Weryfikacja „Cofnij do pakowania” planuje `utrwal` po commicie (K3: sygnał `station:packaging` po tym zapisie albo jawnie w „Poza zakresem”; K5: tryb regresji `weryfikacja-cofnij-desk`), dosłowne klucze `prod_config` z `stale.klucz_*` (K2 buduje mapę pól Konfiguracji przez `stale.klucz_*`, bez literałów), kanoniczny test czystej sesji `test_nieudane_utrwal_zostawia_db_session_czysta` w `tests/test_priorytety_kolejnosc_zapisow.py` (K8 Step 0: warunek usunięcia `tests/test_priority_statusy_krawedzi.py`; test `:160` tego pliku K1 zostawił na `NewPriorityCalculator`), czego K1 celowo nie zrobił: blueprint, końcówki, stół, sygnały, UI, CLAUDE.md).
- [x] **Step 2: Commit i odpowiedź**

```bash
git add -f docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K1-raport.md docs/superpowers/plans/2026-10-05-priorytety-krok-K1-fundament-rangi.md
git commit -m "docs(priorytety): raport kroku K1 fundament rangi" -m "<stopka>"
```
Jedna wiadomość do Konrada: co zrobione, co nie, hash.

---

## Kryteria zakończenia (DoD)

1. Gałąź `claude/priorytety-produkcji` istnieje, zaczyna od `b4b4a54d`, ma 7 commitów (po jednym na Task), `main` i `claude/logistyka-etap-4` nietknięte.
2. `migrations/2026-10-05-priorytety-produkcji.sql` przechodzi `flask migrate` dwa razy na kontenerze `db`; po migracji: 5 kolumn `priority*` na `prod_orders`, 3 nowe tabele, 9 szczebli w kolejności 3.1, 38 wierszy `prod_config`; `tests/test_migration_service.py` zielony.
3. Pakiet `modules/production/priorytety/` ma pliki z 9.1 poza `routers/`, `templates/`, `static/`, `stol.py`, `sygnaly.py`; `__init__.py` bez blueprintu; wszystkie nazwy z sekcji Interfaces istnieją (`grep -n "^def \|^class "` w raporcie).
4. `tests/test_priorytety_kolejka.py` odtwarza tabelę 3.3 i przykłady Konrada (dąb 4 cm przed 3 cm; X/Y) — zielony.
5. `tests/test_priorytety_kolejnosc_zapisow.py` dowodzi: blokada zamówień → blokada pozycji → zapis; tylko zmienione wiersze; jeden flush rosnąco; jedno ponowienie po 1213; `db.session` nietknięta, także po błędzie (`test_nieudane_utrwal_zostawia_db_session_czysta` istnieje w tym pliku: `grep -n "def test_nieudane_utrwal_zostawia_db_session_czysta" tests/test_priorytety_kolejnosc_zapisow.py`).
6. `tests/test_sales_ingest_wyzwalacze.py` zielony **bez zmian w pliku**.
7. Pełny pakiet: 0 failed; liczba passed = punkt wyjścia + nowe − usunięte (wymienione w raporcie); `integrations/blog_seo` zielony.
8. Składnia 3.9 potwierdzona dla zmienionych plików.
9. Raport kroku w `docs/superpowers/plans/raporty/` z wszystkimi sekcjami, w commicie.

## Poza zakresem (K2–K8)

Blueprint `priorytety_panel` i końcówki HTTP (drabina, gwiazdki, kolejka, ustawienia, przelicz), usunięcie martwych końcówek `products_api` (K2); `stol.py`, `sygnaly.py`, `desk`/`postpone`/`realtime-token`, bramka ZAKOŃCZ, `priorytet` w `serialize_order`, `KSZTALT` → 6 (K3); Lista produkcyjna, modale, gwiazdki w Logistyce, `products-dragdrop.js` (K4a); Stanowiska, dashboard, Konfiguracja (grupa „Terminy”/„Stół stanowisk”, `config_api.py`), monitory (K4b); CLAUDE.md, doprecyzowania do specu, wyścigi MySQL, kopia produkcji (K5); kontrakt appki (K6); wdrożenie i ręczny cron (K7); DROP i `priority_service.py` (K8). Znalezione „przy okazji”, bez zmian w kodzie: spec 4.3 „domyślnie 2” i spec 13 „seed 8 szczebli” — zaszłości do K5; spec 3.3 (narracja przykładu Konrada) kontra 3.2 p. 1 — gwiazdki przed grupą (Pytanie 3), K5 poprawia spec wg odpowiedzi.

## Pytania do Konrada

Blokujących start — **brak**. Do potwierdzenia przy okazji (plan zakłada rekomendację):
1. Między K1 a K4a gwiazdka admina z `POST /set-priority` żyje tylko do najbliższego `utrwal()` (po każdej akcji trasy, zmianie sposobu dostawy, imporcie, co godzinę). Rekomendacja: zaakceptować (martwa w praktyce, K4a zastępuje gwiazdkami zamówienia).
2. `utrwal()` po każdej akcji trasy wydłuża odpowiedź panelu o czas przeliczenia (szacunek: setki ms przy ~250 zamówieniach aktywnych). Rekomendacja: zaakceptować w P1, zmierzyć w K5; gdyby przeszkadzało — przenieść do wątku w tle jak dopychacz Base.
3. **ROZSTRZYGNIĘTE 5.10 (sesja planująca, nie wymaga odpowiedzi):** obowiązuje reguła 3.2 (gwiazdki przed grupą materiału); spec 3.3 poprawiony w tym samym commicie, więc K5 nie ma tu nic do zmiany. Pierwotna treść pytania dla kontekstu — **Gwiazdki przed grupą materiału w szczeblu (np. trasy)?** Spec 3.2 p. 1 i klucz symulacji: pozycje zamówienia ★★ idą przed pozycjami zamówienia bez gwiazdek z tej samej trasy (A 4 cm, A 3 cm, B 4 cm, B 3 cm). Narracja przykładu 3.3: grupa dąb 4 cm obejmuje A i B, potem 3 cm (A 4 cm, B 4 cm, A 3 cm, B 3 cm). Plan przyjmuje 3.2 (mniej przezbrojeń traci tylko szczebel z różnymi gwiazdkami; gwiazdki znaczą „pilniej”). Rekomendacja: zostawić 3.2; jeśli Konrad wybierze 3.3 — w kluczu kafla `-gwiazdki` schodzi za termin w grupie (zmiana jednej krotki i dwóch testów, bez wpływu na rangę zamówień).

## Ryzyka i co robić przy blokadzie

| Ryzyko | Objaw | Co robić |
|---|---|---|
| Testy `test_sales_ingest_wyzwalacze.py` padają po zmianie `priority_service` | asercje na `NewPriorityCalculator` | nie ruszać klasy; warstwa zgodności tylko w `get_priority_calculator` i funkcjach modułowych; jeśli mimo to pada — STOP, meldunek (błąd planu) |
| Brak nowych tabel w jakiejś fixturze | `no such table: prod_priority_rungs` w testach tras albo `utrwal` zawsze `success: False` | dopisać modele do `TABLES` tego pliku (dozwolone w zakresie: fixtury), odnotować w raporcie |
| `config_service` cache między testami | test ustawień widzi wartość poprzedniego testu | `czyste_ustawienia` z `tests/priorytety_fixtures.py` w każdym pliku, który pisze `prod_config` |
| `StaticPool` a własna sesja `utrwal()` | commit własnej sesji zatwierdza pracę testu, rollback ją cofa | testy własności sesji na SQLite plikowym (`app_osobne_polaczenia`-podobny fixture); pozostałe testy wołają `utrwal` po commicie |
| Migracja na kontenerze `db` pada (składnia, FK do `prod_routes` na bazie bez logistyki etapu 3) | `flask migrate` błąd | kontener `db` musi mieć wykonane migracje logistyki (runner robi je w kolejności nazw — automatycznie); jeśli błąd składni — poprawić i uruchomić ponownie (runner nie zapisuje nieudanej); jeśli błąd modelu danych — STOP |
| Cykl importów `priorytety` ↔ `logistics/__init__` | `ImportError: cannot import name … (most likely due to a circular import)` przy starcie albo w pierwszym teście pliku | importy `priorytety` w routerach logistyki tylko w funkcjach, `models.py` bez importu `logistics.models`, `drabina` importuje moduł `routes`; sprawdzenie z Task 6 Step 3 |
| Wspólne `g` w testach (fikstura trzyma `app_context`) | drugie żądanie testu nie utrwala albo wykonuje plan z poprzedniego | bez znacznika „raz na żądanie”; plan Dostawy zdejmowany `g.pop` |
| Istniejący test liczy blokady/zapisy w oknie obejmującym commit | np. `len(blokady_z) == 3` zamiast 2, `podbite` z dodatkową pozycją | izolacja `monkeypatch` na `kolejka.utrwal`/`utrwal_po_commicie` w tym teście (Task 6, Files), wpis w raporcie; zmiana asercji tylko gdy test sprawdza coś, co P1 świadomie zmienia |
| MySQL 1213 w testach ręcznych na kontenerze | log WARNING „ponawiam raz” | K1 nie robi wyścigów; odnotować, K5 mierzy |
| Spec kontra kod (np. `is_priority` oczekiwane gdzieś jako ręczna flaga) | niejasna odpowiedź w kodzie | STOP, meldunek do centrali z odnośnikami ścieżka:linia, bez obejść |
| Test spoza zakresu pada po zmianie (`complete_task`, `lock_priority`) | np. inny test asertuje `priority_rank == 1` doróbki | sprawdzić, czy to konsekwencja decyzji specu (wtedy test uaktualnić i wymienić w raporcie) czy regresja (STOP) |

**STOP** = zatrzymanie pracy, opis w raporcie („Odstępstwa”/„Pytania”), bez wyłączania testów, bez zmian poza planem, meldunek do centrali.

## Wdrożenie (informacyjnie, wykonuje K7)

Migracja wchodzi z całym P1 przed restartem (`deploy.sh`), bez zmian ENUM — stary worker w oknie wdrożenia niczego nie rzuci (spec 11). Po restarcie raz ręcznie `scripts/cron_endpoint.sh POST /production/api/logistics/cron`: faza `szczeble_uzupelnione` dopisze szczeble istniejących tras, `priorytety_utrwalone` nada rangi nowym algorytmem. Wycofanie K1: cofnięcie kodu; kolumny i tabele zostają; stary algorytm przelicza rangi przy następnej synchronizacji (nieaktywny `NewPriorityCalculator` wraca przez `get_priority_calculator`).
