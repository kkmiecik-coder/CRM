# Priorytety produkcji, krok K2 — API panelu biura (`/production/api/priorytety`) — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Biuro dostaje komplet końcówek HTTP nowego systemu priorytetów: odczyt i przesuwanie drabiny, hurtowe gwiazdki
0–5, podgląd kolejki (całej i stanowiska), dane do modalu priorytetu zamówienia, ustawienia stołów, progu i terminów oraz
ręczne przeliczenie. Martwe końcówki starego systemu w `products_api.py` znikają. Interfejsu nie ma: to K4a i K4b.

**Architecture:** Blueprint `priorytety_panel` w `modules/production/priorytety/__init__.py`, rejestrowany w `app.py`
pod `/production/api/priorytety` obok logistyki. Router `priorytety/routers/panel_api.py` jest cienki: waliduje ciało,
pilnuje kolejności commit → blokada → zapis → commit → `kolejka.utrwal()` i mapuje błędy na
`{success, error, message}`. Logika zostaje w serwisach z K1 (`drabina`, `gwiazdki`, `kolejka`, `ustawienia`). K2 dokłada
**tylko odczyt** dla panelu (`priorytety/services/widok.py`: drabina z licznikami i ostrzeżeniem o datach, kolejka,
dane modalu) oraz zapis ustawień (`ustawienia.waliduj`/`ustawienia.zapisz`). Kolejka w panelu liczy się na żywo przez
`kolejka.policz` i `kolejka.kandydaci_stanowiska`. Kolumny `priority_rank`/`priority_rung` to pamięć podręczna innych
czytelników.

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, MySQL 8.4 (produkcja) / SQLite in-memory (testy), pytest.

**Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md`: 3.1 (drabina, ostrzeżenie o datach),
3.2 (kolejność), 4.1–4.4 (pojęcia, `utrwal`, terminy, cykl życia szczebla trasy z samonaprawą), 5.1/5.6 (stół, kompletne
i niekompletne, tylko do odczytu), 7.1–7.3 (panel, uprawnienia), 8.1–8.6 (dane, klucze `prod_config`), 9.1–9.5 (pakiet,
kontrakty funkcji, wyzwalacze `utrwal`, współbieżność, co znika), 10 (błędy), 13 (testy). Symulacja:
`docs/superpowers/specs/2026-10-04-priorytety-produkcji-symulacja.md`, „Analiza wyniku” i „E. Decyzje”. Podręcznik
centrali: `docs/superpowers/plans/2026-10-05-priorytety-produkcji-centrala.md` (sekcje 2, 8.0, 8.2).

**Sesja:** lokalna (Docker: `docker compose exec app pytest`). Krok ma kod i testy, a cloud nie ma zależności aplikacji
(podręcznik, sekcja 4). Model wg podręcznika 3 i 4a (Konrad: trudniejsze kroki na Fable 5.1, pozostałe na Opusie):
**Opus 5.5, effort high**, tryb szybki dozwolony. Sonnet 5.5 podręcznik dopuszcza oszczędnościowo tylko dla K4a, K4b
i K8, nie dla K2. Wyścigi MySQL nie należą do tego kroku, robi je K5.

**Zależności:** K1 zakończony i zaliczony na bramce. Od K1 potrzebne są: migracja P1 (tabele `prod_priority_rungs`,
`prod_priority_log`, `prod_station_desk`, kolumny `prod_orders.priority_*`, wiersze `prod_config`), modele, `stale.py`,
serwisy `kolejka`, `drabina`, `gwiazdki`, `ustawienia`. Pełna lista w Task 1, Step 0.

**Gałąź:** `claude/priorytety-produkcji` (zakłada ją K1 z `origin/claude/logistyka-etap-4`). Start:
`git fetch origin && git checkout claude/priorytety-produkcji && git pull --ff-only origin claude/priorytety-produkcji`.
Nigdy `main`. Numery linii w tym planie dotyczą stanu `claude/logistyka-etap-4` @ `b4b4a54d`, czyli sprzed K1. Jeśli
K1 przesunął linie, szukaj po nazwie funkcji (`grep -n`). Nazwy podane są w każdym miejscu.

## Global Constraints

- **Python 3.9:** `X | Y` w adnotacjach wolno tylko w plikach z `from __future__ import annotations`. Bez `match`.
- Komentarze i docstringi **po polsku**. W tekstach dla użytkownika (`message`) pisz „Base.”.
- **Błędy (spec 10):** każda odmowa z naszego routera to JSON `{"success": false, "error": "<kod>", "message": "<po polsku>"}`,
  czasem z dodatkowymi polami (`pole`, `nieznane`). Kody wymienia sekcja „Interfaces” w Task 1. Treści wyjątku
  (`str(e)`) nie oddajemy klientowi: 500 to `blad_serwera` z ogólnym komunikatem, szczegóły idą do logu. Wyjątki
  istniejących dekoratorów: `guard` odpowiada `{"error": "unauthorized"}` (401) albo 403 z `require_module_access`,
  a `admin_required` odpowiada `{"success": false, "error": "Brak uprawnień administratora"}` (403). Formatów obu
  dekoratorów nie zmieniamy.
- **Kolejność blokad** (CLAUDE.md, „Trasy logistyki — jeden piszący naraz”; spec 9.4):
  - zapis drabiny: `db.session.commit()` → `routes.zablokuj_trasy()` → odczyty i zapisy szczebli → commit;
  - gwiazdki: `db.session.commit()` → `FOR UPDATE` zamówień rosnąco po id (`blokady_zamowien.zablokuj_zamowienia`) →
    zapis → commit. **Bez blokady tras**;
  - `kolejka.utrwal()` zawsze **po** commicie routera, na własnej sesji.
  Między `commit` a pierwszą blokadą nie ma żadnego odczytu, także atrybutów ORM wygaszonych przez commit (wzór:
  `_zapis_pod_blokada`, `logistics/routers/panel_api.py:72-89`). Dlatego `current_user.id` czytamy **przed** commitem.
- **Odczyty panelu** (`GET`) nie biorą blokad. Jedyny wyjątek to samonaprawa w `GET /drabina` (Task 2).
- **Serwisy nie commitują.** Commituje router. Nowe funkcje w `widok.py` i `ustawienia.py` też nie commitują.
- Jedno ponowienie po MySQL 1213 (`blokady_zamowien.kod_mysql(e) == 1213`: rollback i cały zapis od nowa) dla gwiazdek
  i przesunięcia szczebla, jak w hurcie (`products_api.py:1599-1607`). Drugie 1213 kończy się 500 `blad_serwera`
  z rollbackiem. Każda próba ma **dwa** commity (koniec migawki przed blokadą i commit zapisu), więc testy wstrzykują
  błąd w commit zapisu: `_commit_z_bledami(monkeypatch, [None, _blad_mysql(1213)])` dla jednego ponowienia,
  `[None, 1213, None, 1213]` dla dwóch. Lista `[1213]` trafiłaby w pusty commit sprzed blokady i nie dowiodłaby, że
  zapis się cofa.
- Zakres: końcówki panelu i usunięcie martwych końcówek. **Nie** ruszaj: `set-priority` (zostaje do K4a), JS i szablonów
  (K4a/K4b), `priority_service.py` (K8), API mobilnego i stołu (K3), `config_api.py` (K4b), `tools/print_agent`.
  Usterki spoza zakresu wpisz do raportu.
- Testy: `docker compose exec app pytest <ścieżki> -q -p no:cacheprovider`. TDD: najpierw test, który pada. Testy idą
  na SQLite in-memory wg konwencji repo (`tests/logistyka_fixtures.py`, `tests/krawedzie_fixtures.py`,
  `tests/blokady_pomocnicze.py`). SQLite pomija `FOR UPDATE`, więc kolejności pilnujemy kolejnością zapytań, commitów
  i wywołań (szpiedzy).
- Commity: Conventional Commits po polsku, **temat bez polskich znaków**, jeden na Task, stopka atrybucji własnej sesji.
  `docs/superpowers/` dodawaj przez `git add -f`. Push na gałąź roboczą wg karty centrali (S-2).
- Repo jest publiczne: w kodzie, testach i raporcie nie ma sekretów, adresów IP ani danych klientów (w `curl` z raportu
  używaj bazy podglądu albo danych testowych).

## Review Focus

1. **Zapis drabiny bierze blokadę tras od świeżej transakcji.** Commit, zaraz potem blokada, bez odczytu pomiędzy.
   Status trasy (`trasa_nieaktywna`) sprawdzany jest pod blokadą. Testy:
   `test_przesun_szczebla_commit_i_blokada_tras_bez_odczytu_pomiedzy`, `test_przesun_trasy_zaladowanej_409_trasa_nieaktywna`,
   `test_samonaprawa_drabiny_pod_blokada_tras` (Task 2).
2. **Gwiazdki nie biorą blokady tras, blokują zamówienia rosnąco, a `utrwal()` idzie po commicie.** Testy:
   `test_gwiazdki_commit_blokada_zamowien_rosnaco_potem_zapis`, `test_gwiazdki_bez_blokady_tras`,
   `test_gwiazdki_utrwal_po_commicie`, `test_gwiazdki_ponawia_raz_po_1213`, `test_gwiazdki_dwa_1213_to_500_bez_zapisow` (Task 3).
3. **Nieudane przeliczenie nie cofa zapisu** (spec 10): gwiazdki i szczebel zostają, odpowiedź ma
   `"przeliczenie": "nieudane"`. Testy: `test_przeliczenie_nieudane_nie_cofa_gwiazdek`,
   `test_przeliczenie_nieudane_nie_cofa_przesuniecia` (Task 2, 3).
4. **Uprawnienia** (spec 7.3): bez sesji 401 JSON, bez modułu produkcji 403 JSON, ustawienia i przeliczenie tylko dla
   admina. Testy: `test_bez_sesji_401_json`, `test_bez_uprawnien_do_produkcji_403_json`, `test_ustawienia_i_przelicz_tylko_admin`
   (Task 1, 5).
5. **Ustawienia są walidowane w całości przed zapisem i widać je od razu w innych workerach.** Testy:
   `test_ustawienia_walidacja_wszystko_albo_nic`, `test_ustawienia_zmiana_progu_przelicza`,
   `test_ustawienia_czytane_bez_pamieci_podrecznej_procesu` (Task 5).
6. **Usunięte końcówki naprawdę zniknęły, a `set-priority` zostało.** Testy: `test_martwe_koncowki_priorytetow_usuniete`,
   `test_bulk_action_update_priority_400` (Task 6).
7. **Kolejka stanowiska w panelu to ten sam algorytm co stół** (`kolejka.kandydaci_stanowiska`, kafle ze stołu
   pominięte). Testy: `test_kolejka_stanowiska_z_kandydatow_k1`, `test_kolejka_stanowiska_pomija_kafle_na_stole`,
   `test_kolejka_formatowania_dzieli_na_kompletne_i_niekompletne`, `test_kolejka_stanowiska_niekompletne_brakuje_short_id`,
   `test_wejscie_kandydatow_ksztalt_i_zero_zapytan` (Task 4).

## Decyzje przyjęte (ze specu i symulacji)

1. Priorytetami zarządza biuro z backoffice produkcji: gwiazdki 0–5 na **zamówieniu**, trasy i tagi na drabinie
   (Konrad 4.10, spec 2 p. 1–3).
2. Szczeble gwiazdek są nieruchome. Tagi („Po terminie”, „Blisko terminu”, „Rozpoczęte”) i trasy biuro przesuwa.
   Szczebel trasy roboczej albo zatwierdzonej powstaje z trasą, a znika z drabiny przy innym statusie (spec 3.1, 4.4;
   Konrad 4.10).
3. Próg „Blisko terminu” to **3 dni robocze**, konfigurowalny bez wdrożenia (Konrad 5.10; symulacja, sekcja E). Spec 4.3
   podaje jeszcze „domyślnie 2”. Obowiązuje 8.6 i decyzja z 5.10 (3). Rozbieżność do poprawy w specu w K5 (Doprecyzowania,
   p. 9).
4. Domyślna drabina: ★★★★★, Po terminie, ★★★★, **Blisko terminu, Rozpoczęte**, ★★★, ★★, ★, bez gwiazdek (Konrad 5.10).
   Seed robi K1. K2 tego tylko nie psuje.
5. Uprawnienia: gwiazdki, drabina, podgląd kolejki i modal przez `guard` jak w Logistyce. Ustawienia i przeliczenie przez
   `admin_required` (spec 7.3).
6. `DEADLINE_DAY_TYPE` ∈ {`robocze`, `kalendarzowe`}, domyślnie `robocze`. Terminy już zaimportowanych zamówień się nie
   zmieniają (Konrad 4.10, spec 4.3).
7. `POST /production/api/set-priority` **zostaje** do K4a, bo woła je `products-module.js:2383` (karta centrali 8.2).
   Pozostałe końcówki z 9.5 usuwa K2.
8. Nieudane `utrwal()` nie cofa zapisu. Panel dostaje `"przeliczenie": "nieudane"`, a resztę nadrobi cron (spec 10).

## Doprecyzowania (do specu — K5 przeniesie)

1. **Format błędu:** `{"success": false, "error": "<kod>", "message": "<tekst>"}`, gdzie `error` to kod maszynowy, a nie
   tekst. Kody: `dane_niepoprawne`, `gwiazdki_niepoprawne`, `za_duzo_zamowien`, `zamowienie_nieznane`, `szczebel_nieznany`,
   `szczebel_staly`, `trasa_nieaktywna`, `pozycja_niepoprawna`, `drabina_zmieniona`, `stanowisko_nieznane`,
   `ustawienie_niepoprawne` (z polem `pole`), `przeliczenie_nieudane`, `blad_serwera`.
2. **`pozycja` w `PUT /drabina/kolejnosc`** to indeks 1..n w **widocznej** drabinie, w kolejności z `GET /drabina`.
   Szczeble tras załadowanych, w trasie i wykonanych nie są widoczne. Jeśli `drabina.przesun` z K1 liczy pozycję
   bezwzględnie (z ukrytymi wierszami), router tłumaczy: docelowa pozycja = `position` szczebla, który dziś stoi na
   indeksie `pozycja`.
3. **Opcjonalne `oczekiwane`** (lista id widocznych szczebli w kolejności, którą widział klient) w `PUT /drabina/kolejnosc`.
   Pod blokadą tras router porównuje ją z bieżącą drabiną. Różnica → 409 `drabina_zmieniona` bez zapisu. Wzór:
   `routes.zmien_kolejnosc(..., oczekiwane)`.
4. **Liczniki `w_produkcji`, tagi i szczebel w panelu liczy się na żywo** (`kolejka.policz` na migawce bez blokad).
   Kolumny `priority_rank`/`priority_rung` są pamięcią podręczną SQL-owych czytelników. Między zdarzeniem a najbliższym
   `utrwal()` mogą się różnić od panelu (np. tag po północy przed cronem).
5. **Samonaprawa w `GET /drabina`** nie przelicza rang. `policz()` liczy już trasę bez szczebla w miejscu domyślnym,
   a `uzupelnij()` wstawia szczebel właśnie tam. Nieudana samonaprawa nie psuje odczytu: wynik `uzupelniono: 0`
   i ostrzeżenie `samonaprawa_nieudana`.
6. **Ostrzeżenie o datach** (spec 3.1): sąsiednie szczeble tras w widocznej drabinie, gdzie wyższy ma późniejsze
   `date_from` niż niższy. Jedno ostrzeżenie na parę. Nic nie przesuwa się samo.
7. **`GET /kolejka?stanowisko=S`** to podgląd tego, co `stol.dopelnij(S)` z K3 wziąłby jako następne. Ten sam
   `kandydaci_stanowiska`, z pominięciem kafli leżących na stole i odłożonych (`prod_station_desk`). Parametr `limit`
   ma zakres 1–500, domyślnie 50. Wejście do algorytmu buduje jedna funkcja `widok.wejscie_kandydatow` (Task 4),
   którą woła też `stol.dopelnij` w K3. Na Pakowaniu kafel-zamówienie ma pole `sposob_dostawy_ustawiony`.
8. **Ustawienia:** `priorytety_blisko_terminu_dni` w zakresie 0–15, `priorytety_min_app_version_code` to liczba całkowita
   ≥ 0. Zakresy K (1–5) i limitu odłożeń (1–50) są ze specu 10. Zapis idzie jedną transakcją dla wszystkich kluczy.
   Każda zmiana daje wiersz `prod_priority_log` (`action='ustawienia'`, `old_value`/`new_value`, `note` = klucz). Zmiana
   progu „Blisko terminu” wywołuje `utrwal()` po commicie. Jedyna droga zapisu tych kluczy to `PUT /ustawienia`. K4b nie
   dopisuje ich do allowlisty `update-configs` (`config_api.py:506`).
9. Spec 4.3 „(`priorytety_blisko_terminu_dni`, domyślnie 2…)” → „domyślnie 3” (decyzja 5.10, już tak w 8.6 i 13).
10. **`POST /przelicz`** woła `kolejka.utrwal(zrodlo='panel', user_id=user_id)`. Wiersz `prod_priority_log`
    (`action='przeliczenie'`, `note` = źródło, `new_value` = liczba zmienionych zamówień, `user_id`) zapisuje **sam
    `utrwal()`** na własnej sesji (plan K1, Doprecyzowania „Wpis `przeliczenie`” i pseudokod Task 4), i tylko wtedy, gdy
    przeliczenie coś zmieniło. Router logu **nie** pisze (inaczej dwa wiersze na jedno kliknięcie). Przeliczenia z crona
    i zdarzeń nie logują się wcale (bez `zrodlo`).
11. **Liczba gwiazdek** musi być typu `int` (nie `bool`, nie tekst), 0–5. `order_ids` to niepusta lista liczb całkowitych,
    duplikaty są usuwane, długość ≤ `LIMIT_HURTU` (500, jak `logistics/routers/panel_api.py:24`). Zamówienia nieistniejące
    wracają w polu `nieznane`. 404 przychodzi tylko wtedy, gdy nie istnieje żadne.
12. **Kody `drabina.BladDrabiny` z K1 → kody routera:** `brak_szczebla` → `szczebel_nieznany` (404),
    `pozycja_poza_zakresem` → `pozycja_niepoprawna` (400), `szczebel_staly` i `trasa_nieaktywna` bez zmian. Spec 10 nie
    nazywa kodu dla 404 i złej pozycji, więc obowiązują nazwy routera z p. 1. `gwiazdki.BladGwiazdek` → 400
    `gwiazdki_niepoprawne`, a pole `brak` z wyniku `gwiazdki.ustaw` to w odpowiedzi `nieznane`.
13. **Kolejka stanowiska (`?stanowisko=`) liczy szczebel i rangę zamówienia z kolumn** `prod_orders.priority_rung`/
    `priority_rank` (pamięć podręczna z `utrwal()`), tak jak stół (spec 4.2: „Stół czyta `priority_rung` i
    `priority_rank` zamówienia z kolumn”; K1 `kandydaci_stanowiska`: „rung z kolumny”), a tag „Rozpoczęte” na żywo.
    Dzięki temu podgląd w panelu = to, co weźmie `stol.dopelnij` (p. 7). Cała kolejka `GET /kolejka` i modal liczą na
    żywo przez `policz` (p. 4). Różnica między nimi trwa najwyżej do najbliższego `utrwal()`.
14. **Pakowanie w podglądzie kolejki:** kafel-zamówienie bez sposobu dostawy (`sposoby.normalizuj(order.override_delivery_method)
    is None`, jak `mobile_api.py:471`) zostaje w `kafle` z `sposob_dostawy_ustawiony: false`, żeby biuro widziało, co
    stoi. Stół K3 go pomija przy pobieraniu (spec 5.1), więc `w_kolejce` w modalu liczy miejsce tylko wśród kafli
    z ustawionym sposobem, a zamówienie bez sposobu ma na Pakowaniu `w_kolejce: null`.
15. **Zmiana jednostki przy niepustym stole.** `PUT /ustawienia` może zmienić `jednostka` stanowiska, na którego stole
    leżą (albo są odłożone) wiersze w starej jednostce (`p:<id>` po przejściu na `zamowienie`, `o:<id>` odwrotnie).
    Odmowa 409 przy niepustym stole **nie** wchodzi w grę: stół dopełnia się przy każdym `GET desk` także w trybie
    `stary` (plan K3, `test_desk_w_trybie_stary_dziala`), a panel nie ma czym go opróżnić, więc jednostki nie dałoby się
    zmienić nigdy. Reguła: **wiersz stołu z kluczem innej jednostki niż bieżąca jest nieaktualny.** K2 stosuje ją
    w podglądzie: `desk_unit_keys` w `wejscie_kandydatow` zawiera tylko klucze bieżącej jednostki (stary wiersz nie
    ukrywa kandydata). K3 stosuje ją w stole: `stol.dopelnij` nie liczy takich wierszy do K, a
    `stol.zdejmij_nieaktualne` je zdejmuje (z logiem `odlozenie_zamkniete` dla odłożonych) — inaczej `kafel_pozycji`
    szuka klucza nowej jednostki, bramka odpowiada 409 `nie_na_stole`, a stare wiersze zajmują miejsca na zawsze.
    Przekazanie do K3: Task 7, Step 4. `PUT /ustawienia` przy zmianie jednostki niczego na stole nie zmienia (bez
    blokad, bez zapisu do `prod_station_desk` — Global Constraints, „Poza zakresem”).

## Mapa plików

| Plik | Task | Rola |
|---|---|---|
| `modules/production/priorytety/__init__.py` (zmiana pliku K1) | 1 | `priorytety_panel_bp`, import routera na końcu (wzór `logistics/__init__.py:9-19`) |
| `modules/production/priorytety/routers/__init__.py` (nowy, jeśli K1 nie założył) | 1 | pakiet |
| `modules/production/priorytety/routers/panel_api.py` (nowy) | 1–5 | `guard`, `_blad`, `_przelicz_po_zapisie`, wszystkie końcówki |
| `modules/production/priorytety/services/widok.py` (nowy) | 2, 4 | odczyty dla panelu: drabina z licznikami, ostrzeżenia, brakujące szczeble, `wejscie_kandydatow` (wspólne z K3), kolejka, modal |
| `modules/production/priorytety/services/ustawienia.py` (zmiana pliku K1) | 5 | `waliduj(dane)`, `zapisz(zmiany, user_id)`, `odczyt_panelu()`; odczyt bez pamięci podręcznej procesu tylko za zgodą z karty (Task 1, Step 0 p. 4) |
| `modules/production/priorytety/stale.py` (zmiana pliku K1, tylko jeśli brak) | 3 | `LIMIT_HURTU = 500` |
| `app.py:886-887` | 1 | rejestracja blueprintu pod `/production/api/priorytety` |
| `modules/production/routers/api/products_api.py` | 6 | usunięcie martwych końcówek i gałęzi `update_priority` w `bulk_action` |
| `modules/production/routers/__init__.py:172` | 6 | usunięcie `'/api/update-priority'` z `URL_PATTERNS` |
| `modules/production/services/blokady_zamowien.py:127-130` | 6 | docstring `kod_mysql` bez przeciągania |
| `tests/test_priorytety_panel_api.py` (nowy) | 1–5 | testy końcówek |
| `tests/test_priorytety_kolejnosc_zapisow.py` | 6 | test usuniętych końcówek; resztki testów przeciągania, jeśli K1 je zostawił |
| `tests/test_priorytety_wyzwalacze.py` (K1) | 6 | test hurtu: `update_priority` → 400 zamiast rangi 42 |
| `tests/test_produkty_masowa_zmiana_statusu.py:81-91` | 6 | `test_inne_akcje_nie_wymagaja_statusu` na `export`, nowy test 400 dla `update_priority` |
| `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K2-raport.md` (nowy) | 7 | raport kroku |

Usunięte w całości: brak plików. Usunięte fragmenty: Task 6.

---

### Task 1: Punkt wyjścia, blueprint, rejestracja, kontrola dostępu, format błędów

**Files:**
- Modify: `modules/production/priorytety/__init__.py` (z K1)
- Create: `modules/production/priorytety/routers/__init__.py` (jeśli brak), `modules/production/priorytety/routers/panel_api.py`
- Modify: `app.py:886-887` (`register_blueprints_lazy`, `app.py:863`)
- Create: `tests/test_priorytety_panel_api.py`

**Stan obecny (ugruntowanie):**
- Blueprint logistyki: `modules/production/logistics/__init__.py:9-14` (`Blueprint('logistics_panel', __name__,
  template_folder='templates', static_folder='static', static_url_path='/static/logistics')`), routery importowane na
  końcu pliku (`:19`). Rejestracja: `app.py:886-887` (`from modules.production.logistics import logistics_panel_bp`,
  `app.register_blueprint(logistics_panel_bp, url_prefix='/production/api/logistics')`).
- `guard`: `modules/production/logistics/routers/panel_api.py:55-61`. `require_module_access('production', as_json=True)`
  jest na zewnątrz, `login_required` wewnątrz, a dekorator wołany jest leniwie przez atrybut modułu
  `modules.users.decorators`. Uzasadnienie: `modules/production/sawmill/routers/panel_api.py:53` i dalej.
- `admin_required`: `modules/production/routers/api/common_api.py:25-45`. Sprawdza `current_user.role` w (`admin`,
  `administrator`) i zwraca 403 JSON.
- W `/production/api/*` nie ma tras łapiących wszystko (`<path:`), więc prefiks `/production/api/priorytety` jest wolny
  (sprawdzone grepem po `modules/production/routers`).
- `modules/production/priorytety/` **nie istnieje** na `b4b4a54d`. Zakłada go K1.

**Interfaces:**
- Consumes (K1, spec 9.1/9.2/8.x). Kolumna „Plan K1” to sygnatury z planu
  `docs/superpowers/plans/2026-10-05-priorytety-krok-K1-fundament-rangi.md` (Interfaces Task 1–4). Sprawdź w Step 0, czy
  kod K1 je ma:
  | Nazwa (spec) | Plan K1 / czego K2 oczekuje |
  |---|---|
  | `priorytety.models.PriorityRung`, `PriorityLog`, `StationDesk` | kolumny jak w spec 8.2–8.4; `PriorityRung.route` (relacja do `Route`) |
  | `ProductionOrder.priority_stars`, `.priority_stars_set_at`, `.priority_stars_set_by`, `.priority_rank`, `.priority_rung` | spec 8.1 |
  | `priorytety.stale` | `STATUSY_PRODUKCJI`, `TAGI`, `TAG_*`, `JEDNOSTKI`, `TRYBY`, `TYPY_DNI`, `DRABINA_DOMYSLNA`, `STANOWISKA`, `STANOWISKA_ZAMOWIENIOWE`, `GWIAZDKI_MAX`, `klucz_tryb/stol/jednostka/limit/blokady(S)`, `KLUCZ_BLISKO`, `KLUCZ_MIN_APP`, `KLUCZ_TYP_DNI` |
  | `drabina.szczeble(aktualny=False)` | **tylko widoczne** (gwiazdki, tagi, trasy `robocza`/`zatwierdzona`) po `position`; `aktualny=True` → `with_for_update().populate_existing()` (pod blokadą tras) |
  | `drabina.przesun(rung_id, pozycja, user_id=None)` | sam bierze `routes.zablokuj_trasy()` (ponowna blokada w tej samej transakcji jest bezpieczna); `pozycja` liczona wśród **widocznych**; renumeracja 1..n wszystkich wierszy; log `szczebel`; rzuca `drabina.BladDrabiny(kod, komunikat, status)` z kodami `szczebel_staly` 400, `brak_szczebla` 404, `trasa_nieaktywna` 409, `pozycja_poza_zakresem` 400 (mapowanie: Doprecyzowania p. 12) |
  | `drabina.uzupelnij(user_id=None) -> int` | sam bierze blokadę tras; dopisuje brakujące szczeble **stałe** (`DRABINA_DOMYSLNA`) i tras `robocza`/`zatwierdzona`; zwraca liczbę dopisanych; bez commita |
  | `drabina.pozycja_tagu(tag)`, `drabina.pozycja_szczebla(rung)` | indeks wśród widocznych, 1-based (`szczebel.pozycja`, „szczebel 1 z 11”, `szczebel_rozpoczete`) |
  | `gwiazdki.ustaw(order_ids, gwiazdki, user_id=None, teraz=None) -> dict` | `{'zmienione': [id], 'bez_zmian': [id], 'brak': [id]}`; `blokady_zamowien.zablokuj_zamowienia(ids)` jako **pierwsze** zapytanie, zapis tylko zmienionych, `priority_stars_set_*`, log `gwiazdki`, `flush`; bez commita i bez blokady tras; zła wartość → `gwiazdki.BladGwiazdek` |
  | `kolejka._migawka(sesja)` + `kolejka.policz(migawka) -> Wynik` | loader K1 z Task 4 (prywatny; K2 woła go z `db.session`, sam odczyt). `Wynik.zamowienia: {order_id: RangaZamowienia(rank, rung, szczebel, tagi, termin)}`, gdzie `rung` to indeks 1-based w `Wynik.drabina` (lista kluczy `('stars', n)`/`('tag', t)`/`('route', id)` po wstawieniu wirtualnych), a `szczebel` to rodzaj tekstem. Licznik szczebla = liczba zamówień z `Wynik.drabina[rung - 1]` równym kluczowi szczebla |
  | `kolejka.utrwal(zrodlo=None, user_id=None) -> dict` | własna sesja, jedno ponowienie po 1213, **nigdy nie rzuca**: porażka = `{'success': False, 'error': ...}`; z `zrodlo` sam loguje `przeliczenie` (Doprecyzowania p. 10) |
  | `kolejka.kandydaci_stanowiska(S, pozycje, statusy_zamowien, szczebel_rozpoczete=None) -> Kandydaci(kafle, niekompletne)` | `pozycje` = lista `kolejka.PozycjaStanowiska` (`id order_id status dorobka created_at sequence gatunek klasa grubosc dlugosc szerokosc numer gwiazdki termin rung rank na_trasie`) w statusie S, już **bez** stołu i odłożeń; `statusy_zamowien = {order_id: tuple((product_id, current_status) dla wszystkich pozycji zamówienia)}` — **pary**, nie same statusy (plan K1, Task 2 Interfaces); `kafle` = id pozycji (jednostka `pozycja`) albo `order_id` kompletnych (jednostka `zamowienie`); `niekompletne` = `[(order_id, na_stanowisku, pozycji, brakuje)]`, gdzie `brakuje = [(product_id, status), …]` rosnąco po `product_id`. `szczebel_rozpoczete` = `drabina.pozycja_tagu('rozpoczete')`. Uwaga: pomocnicze `kolejka.kompletne_na_stanowisku(statusy, S)` przyjmuje **same statusy**, a `kandydaci_stanowiska` pary |
  | `ustawienia.tryb(S)`, `miejsca(S)`, `jednostka(S)`, `limit(S)`, `prog_blisko()`, `min_app_version()`, `typ_dni_terminu()` | odczyt `prod_config` przez `config_service.get_config` (plan K1: pamięć podręczna procesu 60 min — patrz Step 0 p. 4 i „Pytania do Konrada”) |
- Produces: `priorytety_panel_bp = Blueprint('priorytety_panel', __name__, template_folder='templates',
  static_folder='static', static_url_path='/static/priorytety')` w `modules/production/priorytety/__init__.py`.
  Szablony i statykę doda K4a, katalogi mogą jeszcze nie istnieć. Blueprint rejestrowany pod `/production/api/priorytety`.
- Produces (router): `guard(f)` (kopia wzoru logistyki, bez importu z logistyki), `_blad(kod, komunikat, status, **pola)`
  zwracające `{"success": false, "error": kod, "message": komunikat, **pola}`, `_user_id()`.
- Produces (HTTP, wszystkie pod `/production/api/priorytety`):

  | Metoda | Ścieżka | Dekoratory | Task |
  |---|---|---|---|
  | GET | `/drabina` | `guard` | 2 |
  | PUT | `/drabina/kolejnosc` | `guard` | 2 |
  | PUT | `/zamowienia/gwiazdki` | `guard` | 3 |
  | POST | `/przelicz` | `guard` + `admin_required` | 3 |
  | GET | `/kolejka` | `guard` | 4 |
  | GET | `/zamowienia/<int:order_id>/priorytet` | `guard` | 4 |
  | GET | `/ustawienia` | `guard` + `admin_required` | 5 |
  | PUT | `/ustawienia` | `guard` + `admin_required` | 5 |

  Kolejność dekoratorów: `@priorytety_panel_bp.route(...)`, `@guard`, `@admin_required`, `def ...`. Brak sesji daje
  401 JSON z `guard` (zanim `admin_required` z wewnętrznym `login_required` mógłby przekierować na `/login`).

- [x] **Step 0: Punkt wyjścia i weryfikacja K1**

1. `git log -1 --oneline` → hash zgodny z kartą centrali. Inny hash → STOP, pytanie do centrali.
2. Przeczytaj raport K1 (`docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K1-raport.md`), sekcje „Co następny
   krok musi wiedzieć” i „Odstępstwa”.
3. Dla każdego wiersza tabeli „Consumes” znajdź definicję (`grep -n "def szczeble\|def przesun\|def uzupelnij\|def ustaw\|def policz\|def utrwal\|def kandydaci_stanowiska\|def prog_blisko" -r modules/production/priorytety`)
   i zapisz w notatce do raportu: ścieżka:linia, faktyczna sygnatura, typ zwracany, wyjątki.
4. Decyzja:
   - inna nazwa przy tej samej semantyce → używaj nazwy z kodu i wpisz ją w „Odstępstwa”;
   - `drabina.przesun` bez parametru `user_id` → dodaj opcjonalny `user_id=None` (zapis w `updated_by` i w logu), testy
     K1 mają zostać zielone. Odnotuj w „Rozstrzygnięciach”;
   - `gwiazdki.ustaw` niczego nie zwraca → dodaj zwrot listy id zmienionych rosnąco, testy K1 zielone, odnotuj;
   - `kolejka._migawka` pod inną nazwą albo bez parametru sesji → użyj tego, co K1 dał (bez kopii loadera w `widok.py`),
     odnotuj. Zapisz też, skąd `_migawka` bierze `dzis` (np. `get_local_now()`): testy Task 2 i 4 podmieniają to źródło
     albo liczą terminy od niego, nigdy od stałej daty kalendarzowej;
   - `kandydaci_stanowiska` w kodzie K1 przyjmuje w `statusy_zamowien` same statusy zamiast par `(product_id, status)`
     albo `brakuje` bez `product_id` → **STOP przed Task 4** i meldunek (karta naprawcza K1: bez `product_id` nie ma
     `brakuje[].short_id`);
   - **brak** `kandydaci_stanowiska`, loadera migawki albo szczebla i tagów w wyniku `policz` → **STOP przed Task 4**.
     Task 1–3 i 5–6 można zrobić. Meldunek do centrali z rekomendacją: karta naprawcza K1 albo parametr `stanowisko`
     przeniesiony do K3;
   - `ustawienia.*` czyta przez `config_service.get_config` (pamięć podręczna procesu, 60 min,
     `config_service.py:47-56`) → **plan K1 tak to przesądza** (Doprecyzowania K1, ostatni punkt), więc tego się
     spodziewaj. Zmiana trybu, K albo progu z `PUT /ustawienia` dotarłaby do innych workerów gunicorna dopiero po
     godzinie. Decyzja jest w „Pytaniach do Konrada” tego planu i centrala wpisuje ją do karty. Karta mówi „napraw” →
     w Task 5 `ustawienia.*` czyta `prod_config` bez pamięci podręcznej procesu (zwykły odczyt wiersza, ta sama walidacja
     i wartości domyślne), testy K1 zielone, wpis w „Rozstrzygnięciach”. Karta milczy → meldunek do centrali, a test
     z Task 5 dostaje `xfail(strict=True)` z powodem i numerem meldunku (DoD 2).
5. Pełny pakiet: `docker compose exec app pytest tests/ -q -p no:cacheprovider`. Zapisz liczby `passed/skipped/failed`
   jako punkt wyjścia. Zero `failed` to warunek startu. Inaczej STOP.

- [x] **Step 1: Testy, które padną**

`tests/test_priorytety_panel_api.py`. Fikstury w tym pliku. Jeśli K1 dał `tests/priorytety_fixtures.py`, importuj
z niego, a lokalnie tylko rozszerzaj.
- `app`: minimalna apka jak `tests/logistyka_fixtures.py:83-130` (SQLite `StaticPool`, `LOGIN_DISABLED=True`, podmiana
  `modules.users.decorators.require_module_access` na przelotkę, `routes.dzis` zamrożone) plus `LoginManager`
  z anonimowym „adminem” jak `tests/krawedzie_fixtures.py:76-105` (klasa `_UzytkownikTestowy` z `role`, którą test
  zmienia `monkeypatch.setattr`). Rejestruje tylko `priorytety_panel_bp` pod `/production/api/priorytety`. Tabele:
  `User, ProductionConfig, ProductionOrder, ProductionProduct, ProductionConfiguration, ProductionWorker, Vehicle, Route,
  RouteStop, PriorityRung, PriorityLog, StationDesk` (+ to, czego wymaga K1). Seed 9 szczebli w kolejności z decyzji 4,
  helperem K1 albo lokalnym `_seed_drabiny()`.
- Pomocniki danych: `zamowienie(...)` i `produkt(...)` wg `tests/logistyka_fixtures.py:133-174` z polami
  `deadline_date`, `priority_stars`, `parsed_thickness_cm`, `parsed_length_cm`, `parsed_width_cm`, konfiguracją
  (gatunek, klasa). Do tego `trasa(status=..., date_from=...)` z przystankami.
- **Daty:** tagi `po_terminie`/`blisko_terminu` liczy `policz` od `dzis` z `kolejka._migawka` (Step 0 p. 4), a nie od
  zamrożonego `routes.dzis`. Testy liczą `deadline_date` od tego samego źródła (albo je podmieniają), np.
  `DZIS + timedelta(days=1)`, nigdy stałą datą — inaczej zaczną padać same z upływem kalendarza. `date_from` tras
  zostaje w granicach `routes.dzis` (`tests/logistyka_fixtures.py:40-42`).
- **Pamięć podręczna ustawień:** każdy test, który zapisuje `prod_config` albo czyta próg „Blisko terminu”, używa
  `czyste_ustawienia` z `tests/priorytety_fixtures.py` (K1; singleton `config_service` z cache 60 min przeżywa między
  testami).

Testy (lista `KONCOWKI` na górze pliku — pary (metoda, ścieżka) z tabeli „Produces (HTTP)” — **rośnie z Taskami**:
Task 1 zostawia ją pustą, Task 2–5 dopisują swoje wiersze razem z końcówkami; dzięki temu każdy Task kończy się na
zielono bez `xfail`):
- `test_zestaw_koncowek`: reguły `app.url_map` zaczynające się od `/production/api/priorytety/` (bez `static`) to
  dokładnie `set(KONCOWKI)`. Wzór `tests/test_dostawa_api.py:667-669`. Task 5 dopisuje `assert len(KONCOWKI) == 8`.
- `test_blueprint_zarejestrowany_w_app`: strukturalnie na źródle `app.py`. Jest import `priorytety_panel_bp` i
  `register_blueprint(priorytety_panel_bp, url_prefix='/production/api/priorytety')` wewnątrz `register_blueprints_lazy`.
- `test_bez_sesji_401_json` i `test_bez_uprawnien_do_produkcji_403_json`: parametryzowane po `KONCOWKI` (w Task 1 pusty
  zestaw parametrów — pytest je pomija, to oczekiwane), wzór `tests/test_logistyka_panel_api.py:222-273` (fikstura
  `prawdziwy_dostep`: prawdziwy `require_module_access`, `LOGIN_DISABLED=False`, `secret_key`).
- `test_blad_ma_kod_i_komunikat` dochodzi w Task 2 (potrzebuje `PUT /drabina/kolejnosc`).

- [x] **Step 2: Testy padają.** Uruchom plik. Oczekiwany błąd to import (`priorytety_panel_bp`).

- [x] **Step 3: Implementacja szkieletu**

`priorytety/__init__.py`: dopisz blueprint **przed** importem routera, router importuj na samym końcu (cykl importów,
jak `logistics/__init__.py:16-19`). `panel_api.py`: `guard` (docstring odsyła do `sawmill/routers/panel_api.py:53`),
`_blad`, `_user_id`, `logger = get_structured_logger('production.priorytety.panel_api')`, `admin_required` importowany
z `modules.production.routers.api.common_api` (bez kopii). Końcówki z Task 2–5 dochodzą w swoich Taskach razem
z wierszami `KONCOWKI`.
`app.py`: za linią `app.register_blueprint(logistics_panel_bp, url_prefix='/production/api/logistics')`:
```python
        # Priorytety produkcji (krok K2): panel biura — drabina, gwiazdki, kolejka, ustawienia.
        from modules.production.priorytety import priorytety_panel_bp
        app.register_blueprint(priorytety_panel_bp, url_prefix='/production/api/priorytety')
```

- [x] **Step 4: Testy przechodzą.** **Step 5: Commit**
`feat(priorytety): blueprint panelu biura i kontrola dostepu`

---

### Task 2: Drabina — odczyt z licznikami, ostrzeżenie o datach, samonaprawa, przesunięcie

**Files:**
- Create: `modules/production/priorytety/services/widok.py`
- Modify: `modules/production/priorytety/routers/panel_api.py`, `tests/test_priorytety_panel_api.py`

**Stan obecny (ugruntowanie):**
- Blokada tras: `modules/production/logistics/services/routes.py:146-204` (`zablokuj_trasy(route=None)`, wiersz
  `prod_config` `logistyka_trasy_blokada`, `:42`; na SQLite bez wiersza działa „fail-open”). Statusy tras:
  `logistics/models.py:64` (`STATUSY_TRASY`); szczebel mają tylko `robocza`, `zatwierdzona`. Uwaga:
  `STATUSY_TRASY_AKTYWNE` (`:67`) obejmuje też `zaladowana` i `w_trasie`, więc **nie** wolno go użyć do drabiny.
- Wzór „commit, potem blokada”: `logistics/routers/panel_api.py:72-89` (`_zapis_pod_blokada`). Wzór
  `oczekiwane`: `routes.py:601` (`zmien_kolejnosc`).

**Interfaces:**
- Produces (`widok.py`, bez commitów i bez blokad):
  - `brakujace_szczeble_tras() -> List[int]`: id tras `robocza`/`zatwierdzona` bez wiersza w `prod_priority_rungs`, rosnąco.
  - `brak_szczebli() -> bool`: `brakujace_szczeble_tras()` niepuste **albo** brak któregoś szczebla stałego
    z `stale.DRABINA_DOMYSLNA` (tak samo jak `drabina.uzupelnij` z K1, które dopisuje jedne i drugie). To warunek
    samonaprawy w `GET /drabina`.
  - `drabina_panelu() -> dict`: `{"szczeble": [...], "ostrzezenia": [...]}`. Liczniki pochodzą z jednego `policz` na
    migawce `kolejka._migawka(db.session)`: licznik szczebla = liczba zamówień, których `Wynik.drabina[rung - 1]` to
    klucz tego szczebla. Bez blokad i bez samonaprawy (czyta go też dashboard K4b).
  - `ostrzezenia_dat(szczeble_widoczne) -> List[dict]`: czysta funkcja.
  - `szczebel_json(rung, pozycja=None) -> dict`: wspólny serializer (Task 4, K3, K4a, K4b). `pozycja=None` →
    `drabina.pozycja_szczebla(rung)`; wołający, który ma już listę widocznych, podaje indeks sam (bez zapytania na
    szczebel).
- Produces (HTTP):
  - `GET /drabina` → 200:
    ```json
    {"success": true, "uzupelniono": 0,
     "szczeble": [
       {"id": 1, "rodzaj": "gwiazdki", "gwiazdki": 5, "tag": null, "trasa": null, "pozycja": 1,
        "etykieta": "★★★★★", "ruchomy": false, "w_produkcji": 3},
       {"id": 12, "rodzaj": "trasa", "gwiazdki": null, "tag": null, "pozycja": 2, "etykieta": "Śląsk",
        "trasa": {"id": 7, "nazwa": "Śląsk", "status": "zatwierdzona", "date_from": "2026-10-08", "date_to": "2026-10-09"},
        "ruchomy": true, "w_produkcji": 0},
       {"id": 7, "rodzaj": "tag", "gwiazdki": null, "tag": "blisko_terminu", "trasa": null, "pozycja": 5,
        "etykieta": "Blisko terminu", "ruchomy": true, "w_produkcji": 14}],
     "ostrzezenia": [{"kod": "daty_tras", "route_ids": [9, 7],
                      "message": "Trasa „Pomorze” (od 12.10) stoi wyżej niż „Śląsk” (od 08.10)."}]}
    ```
    `pozycja` = indeks w widocznej drabinie. Etykiety: `★`×n, „bez gwiazdek”, „Po terminie”, „Blisko terminu”,
    „Rozpoczęte”, nazwa trasy.
  - `PUT /drabina/kolejnosc`, ciało `{"szczebel_id": int, "pozycja": int, "oczekiwane": [int]?}` → 200: odpowiedź jak
    `GET /drabina` plus `"przeliczenie": "ok" | "nieudane" | "niepotrzebne"`. Błędy: 400 `dane_niepoprawne`,
    404 `szczebel_nieznany`, 400 `szczebel_staly`, 409 `trasa_nieaktywna`, 400 `pozycja_niepoprawna`,
    409 `drabina_zmieniona`.

**Kolejność blokad (CLAUDE.md „Trasy logistyki”; spec 4.4, 9.4):**
```
GET /drabina, gdy widok.brak_szczebli() (zwykły odczyt, bez blokad):
  user_id = _user_id()                 # przed commitem (atrybuty wygasają)
  db.session.commit()                  # koniec migawki z before_request; NIC nie czytamy do blokady
  routes.zablokuj_trasy()              # FOR UPDATE prod_config 'logistyka_trasy_blokada'
  drabina.uzupelnij(user_id=user_id)   # K1: bierze blokadę tras jeszcze raz (bezpieczne), sprawdza brakujące pod nią,
                                       # INSERT, renumeracja
  db.session.commit()
  wyjątek → rollback, logger.error, uzupelniono=0, ostrzeżenie {"kod": "samonaprawa_nieudana"}; odczyt idzie dalej

PUT /drabina/kolejnosc:
  walidacja ciała; user_id = _user_id()           # PRZED commitem
  def _przesun():                                  # wołane drugi raz po rollbacku przy 1213
      db.session.commit()
      routes.zablokuj_trasy()
      widoczne = drabina.szczeble(aktualny=True)   # odczyt bieżący pod blokadą (FOR UPDATE + populate_existing)
      rung = szukany po id wśród widocznych; brak → osobny odczyt bieżący po id: nie ma wiersza → 404 szczebel_nieznany,
             jest (trasa ukryta) → 409 trasa_nieaktywna
      rung.kind == 'stars': 400 szczebel_staly
      oczekiwane is not None i != [r.id for r in widoczne]: 409 drabina_zmieniona
      1 <= pozycja <= len(widoczne) inaczej 400 pozycja_niepoprawna
      zmiana = (indeks rung w widocznych + 1 != pozycja)
      if zmiana: drabina.przesun(rung.id, pozycja, user_id=user_id)   # K1: pozycja wśród widocznych; log 'szczebel'
      db.session.commit()
      return zmiana
  drabina.BladDrabiny z przesun → rollback, _blad(MAPA_KODOW.get(e.kod, e.kod), e.komunikat, e.status)  # Doprecyzowania p. 12
  przeliczenie = _przelicz_po_zapisie() if zmiana else 'niepotrzebne'   # utrwal PO commicie, poza blokadą tras
```
Odmowa (404/400/409) oznacza `db.session.rollback()` przed odpowiedzią, bo blokada tras nie może wisieć do teardown.
Kontrole routera dublują te z `drabina.przesun` celowo: `drabina_zmieniona` i „bez zmiany = bez logu i bez
przeliczenia” zna tylko router, a `BladDrabiny` łapiemy jako siatkę na rozbieżność z K1.
`_przelicz_po_zapisie()` (wspólne dla Task 2, 3, 5):
```python
def _przelicz_po_zapisie():
    """utrwal() po commicie routera (spec 9.3). Porażka nie cofa zapisu (spec 10) — panel dostaje 'nieudane'."""
    try:
        raport = kolejka.utrwal()  # plan K1: nigdy nie rzuca, porażka = success False; try to siatka na rozbieżność
    except Exception:
        logger.error(...)          # utrwal() sam ponowił raz po 1213
        return 'nieudane'
    if not raport or not raport.get('success'):
        logger.error(...)          # `error` z raportu tylko do logu, nie do odpowiedzi
        return 'nieudane'
    return 'ok'
```
Testy podmieniają `kolejka.utrwal` dwoma wariantami porażki: rzucający wyjątek i zwracający `{'success': False, ...}`.

- [x] **Step 1: Testy, które padną**
- `test_drabina_szczeble_w_kolejnosci_z_etykietami_i_ruchomoscia`: seed daje 9 szczebli, gwiazdki `ruchomy: false`,
  tagi `true`, pozycje 1..9.
- `test_drabina_liczniki_w_produkcji_na_zywo`: trzy zamówienia aktywne (★5, termin jutro bez gwiazdek, bez gwiazdek
  z odległym terminem) i jedno spakowane. Liczniki 1/1/1, spakowane się nie liczy. Kolumn `priority_rung` nie ustawiamy,
  więc test dowodzi liczenia przez `policz`.
- `test_drabina_trasa_zaladowana_niewidoczna`, `test_drabina_trasa_bez_zamowien_w_produkcji_zero`.
- `test_ostrzezenie_dat_tylko_dla_odwroconych_sasiadow` (czysta funkcja: trzy trasy, jedna inwersja, jedno ostrzeżenie,
  komunikat z datami `dd.mm`) i `test_ostrzezenie_dat_brak_gdy_zgodne`.
- `test_samonaprawa_drabiny_pod_blokada_tras`: trasa `robocza` bez szczebla — wstawiona wprost modelem `Route`
  (z `vehicle`, `date_from`, `status`), **nie** przez `routes.utworz`, które od K1 zakłada szczebel samo. Szpiedzy na
  `db.session.commit`, `routes.zablokuj_trasy` i `drabina.uzupelnij` (monkeypatch obu modułów; szpieg zapisuje znacznik
  i woła oryginał). `uzupelnij` z K1 bierze blokadę tras jeszcze raz, więc asercja nie porównuje całej listy, tylko
  kolejność pierwszych wystąpień: pierwszy `commit` < pierwsza `blokada` < `uzupelnij`, a po `uzupelnij` jest `commit`.
  Szczebel istnieje, `uzupelniono == 1`. Drugi GET nie bierze blokady (szpieg pusty).
- `test_samonaprawa_dopisuje_brakujacy_szczebel_staly`: seed bez „Rozpoczęte” → GET dopisuje go (`uzupelniono == 1`).
- `test_blad_ma_kod_i_komunikat`: `PUT /drabina/kolejnosc` z ciałem `"x"`. Odpowiedź 400, `error == 'dane_niepoprawne'`,
  `message` niepusty, `success is False`.
- `test_samonaprawa_nieudana_nie_psuje_odczytu`: `drabina.uzupelnij` rzuca. 200, ostrzeżenie `samonaprawa_nieudana`.
- `test_przesun_tagu_zmienia_kolejnosc_i_loguje`: „Rozpoczęte” na pozycję 2. Kolejność w odpowiedzi się zmienia,
  jest jeden wiersz `PriorityLog(action='szczebel')` z `user_id`, `przeliczenie == 'ok'` (`kolejka.utrwal` podmienione
  szpiegiem), `utrwal` wołane raz.
- `test_przesun_trasy_na_koniec_pod_bez_gwiazdek` (spec 3.1: trasę wolno dać pod „bez gwiazdek”).
- `test_przesun_szczebla_gwiazdek_400_szczebel_staly`, `test_przesun_nieznanego_404`,
  `test_przesun_pozycja_poza_zakresem_400`, `test_przesun_zle_cialo_400` (parametryzowany: brak pól, `bool`, tekst,
  `pozycja` 0).
- `test_przesun_trasy_zaladowanej_409_trasa_nieaktywna`. Bez zapisu i bez `utrwal`.
- `test_przesun_z_nieaktualnym_oczekiwane_409_drabina_zmieniona`. Bez zapisu.
- `test_przesun_na_to_samo_miejsce_bez_przeliczenia`. `przeliczenie == 'niepotrzebne'`, brak wpisu w logu.
- `test_przesun_szczebla_commit_i_blokada_tras_bez_odczytu_pomiedzy`: `Zapytania` z `tests/blokady_pomocnicze.py`
  i `event.listen(db.session, 'after_commit', ...)`, który dopisuje `('COMMIT', None)` do `zapytania.lista`;
  `event.remove` w `finally` (wzór `tests/test_paczki_deklaracja.py:421-425` — słuchacz siedzi na klasie sesji
  i przeżyłby test). Pierwsze zapytanie po pierwszym `COMMIT` to blokada tras (`indeks_blokady_tras(z)`). Pierwszy
  `UPDATE prod_priority_rungs` idzie po niej.
- `test_przesun_ponawia_raz_po_1213` (`[None, _blad_mysql(1213)]`: 4 commity, kolejność zmieniona, jeden wpis logu)
  i `test_przesun_dwa_1213_to_500_bez_zapisow` (`[None, 1213, None, 1213]`: 500 `blad_serwera`, kolejność i log bez
  zmian, `utrwal` niewołane). `_blad_mysql` i `_commit_z_bledami` skopiuj do tego pliku ze stanu sprzed K1:
  `git show b4b4a54d:tests/test_priorytety_kolejnosc_zapisow.py` (`:163-183`) — K1 przepisuje ten plik i może ich już
  nie mieć.
- `test_przeliczenie_nieudane_nie_cofa_przesuniecia` (parametryzowany: `kolejka.utrwal` rzuca albo zwraca
  `{'success': False, 'error': 'x'}`). 200, `przeliczenie == 'nieudane'`, kolejność w bazie zmieniona, w odpowiedzi
  nie ma tekstu `'x'`.

- [x] **Step 2: Testy padają.** **Step 3: `widok.py`** (funkcje z „Produces”, bez blokad, bez commitów; `policz`
  na migawce z loadera K1, wynik dla zamówień aktywnych). **Step 4: końcówki** wg pseudokodu, z wierszami `GET /drabina`
  i `PUT /drabina/kolejnosc` w `KONCOWKI`. Każda ścieżka odmowy robi rollback. 1213 obsługuje wzór
  `products_api.py:1599-1607`. Każdy inny wyjątek: rollback, `logger.error`, 500 `blad_serwera`.
- [x] **Step 5: Testy przechodzą**, plik i `tests/test_priorytety*.py`. **Step 6: Commit**
`feat(priorytety): drabina w panelu - liczniki, ostrzezenie o datach, samonaprawa, przesuniecie`

---

### Task 3: Gwiazdki hurtem i ręczne przeliczenie

**Files:**
- Modify: `modules/production/priorytety/routers/panel_api.py`, `tests/test_priorytety_panel_api.py`,
  `modules/production/priorytety/stale.py` (tylko `LIMIT_HURTU = 500`, jeśli K1 go nie dał; K4a czyta
  `stale.LIMIT_HURTU`). Plan K1 każe `gwiazdki.ustaw` sprawdzać limit stałą `logistics/routers/panel_api.LIMIT_HURTU`:
  router i serwis mają używać tej samej wartości, więc dopisz test `stale.LIMIT_HURTU == panel_api.LIMIT_HURTU`
  (logistyka) zamiast drugiej, niezależnej liczby.

**Stan obecny (ugruntowanie):**
- `blokady_zamowien.zablokuj_zamowienia(order_ids)`: `modules/production/services/blokady_zamowien.py:58`. Postać
  zapytania `WHERE prod_orders.id IN (…) ORDER BY prod_orders.id` rozpoznaje `blokady_pomocnicze.blokada_zamowien`
  (`tests/blokady_pomocnicze.py`). `kod_mysql`: `:123-133`.
- Wzór hurtu z jednym ponowieniem: `products_api.py:1585-1607` (`user_id` czytany przed pierwszym commitem,
  `:1585-1587`).
- Dziś gwiazdka to `prod_products.is_priority` przez `set-priority` (`products_api.py:3679`). To zostaje do K4a. Nowe
  gwiazdki to `prod_orders.priority_stars` (spec 8.1).

**Interfaces:**
- Produces (HTTP):
  - `PUT /zamowienia/gwiazdki`, ciało `{"order_ids": [int, ...], "gwiazdki": int}` → 200
    `{"success": true, "zmienione": [ids], "bez_zmian": [ids], "nieznane": [ids], "przeliczenie": "ok"|"nieudane"|"niepotrzebne"}`.
    Błędy: 400 `dane_niepoprawne`, 400 `gwiazdki_niepoprawne`, 400 `za_duzo_zamowien` (z `limit`),
    404 `zamowienie_nieznane` (żadne nie istnieje).
  - `POST /przelicz` (admin) → 200 `{"success": true, "raport": {...}}` (raport `utrwal()` **bez** pola `error`) albo
    500 `przeliczenie_nieudane`, gdy `utrwal` zwróci `success: False` (albo rzuci). Wywołanie
    `kolejka.utrwal(zrodlo='panel', user_id=user_id)`, z `user_id` czytanym przed nim; wiersz logu `przeliczenie`
    zapisuje sam `utrwal()` (Doprecyzowania p. 10). Router niczego nie commituje (zapis jest na sesji `utrwal`).
- Consumes: `gwiazdki.ustaw(order_ids, gwiazdki, user_id=None, teraz=None) -> {'zmienione', 'bez_zmian', 'brak'}`,
  `gwiazdki.BladGwiazdek`, `kolejka.utrwal(zrodlo=None, user_id=None)`.

**Kolejność blokad (spec 9.2, 9.4; CLAUDE.md „Deklaracje paczek” — hurt blokuje zamówienia rosnąco po id):**
```
walidacja → user_id = _user_id() → istniejace = id z SELECT prod_orders.id WHERE id IN (...)   # przed commitem; żadne → 404 bez blokad
def _zapisz_gwiazdki(ids):                         # wołane drugi raz po rollbacku przy 1213
    db.session.commit()                            # koniec migawki; następne polecenie to blokada
    wynik = gwiazdki.ustaw(ids, gwiazdki, user_id=user_id)   # FOR UPDATE prod_orders rosnąco → UPDATE zmienionych → INSERT prod_priority_log
    db.session.commit()
    return wynik                                   # nieznane = wynik['brak'] (stan spod blokady, nie z odczytu przed commitem)
gwiazdki.BladGwiazdek → rollback, 400 gwiazdki_niepoprawne (siatka; router waliduje wcześniej)
przeliczenie = _przelicz_po_zapisie() if wynik['zmienione'] else 'niepotrzebne'   # utrwal: własna sesja, zamówienia → pozycje rosnąco
```
**Bez** `routes.zablokuj_trasy()`: gwiazdki nie zmieniają tras (spec 9.4). INSERT do `prod_priority_log` (FK do
`prod_orders`) bierze blokadę S na wierszu, który ta transakcja już trzyma w X, więc kolejność się nie zmienia.
Wyścigi gwiazdki ↔ ZAKOŃCZ na MySQL robi K5 (spec 13).

- [x] **Step 1: Testy, które padną**
- `test_gwiazdki_hurtem_zapisuje_i_loguje`: trzy zamówienia, jedno już ma 3. `gwiazdki: 3` daje dwa `zmienione` i jedno
  `bez_zmian`. Dwa wiersze `PriorityLog(action='gwiazdki', old_value, new_value, user_id)`, ustawione
  `priority_stars_set_at`/`_by`.
- `test_gwiazdki_nieznane_zwraca_w_polu`, `test_gwiazdki_wszystkie_nieznane_404`.
- `test_gwiazdki_walidacja_400` (parametryzowany): `gwiazdki` 6, -1, `True`, `"3"`, `None`; `order_ids` pusta, nie lista,
  z `True`, z tekstem.
- `test_gwiazdki_powyzej_limitu_hurtu_400`: `LIMIT_HURTU + 1` id daje `za_duzo_zamowien`.
- `test_gwiazdki_commit_blokada_zamowien_rosnaco_potem_zapis`: `Zapytania` + znacznik `COMMIT` (jak w Task 2). Kolejność:
  `COMMIT` → pierwsze `blokada_zamowien(sql)` z parametrami rosnąco (żądanie w kolejności malejącej) → pierwszy
  `UPDATE prod_orders` → `COMMIT`. Między pierwszym `COMMIT` a blokadą nie ma `SELECT`.
- `test_gwiazdki_bez_blokady_tras`: w zapytaniach brak parametru `'logistyka_trasy_blokada'`.
- `test_gwiazdki_utrwal_po_commicie`: szpieg `kolejka.utrwal` zapisuje liczbę commitów w chwili wywołania. `utrwal`
  idzie po drugim commicie i jest wołane raz. Przy `bez_zmian` wszystkich nie jest wołane wcale.
- `test_gwiazdki_ponawia_raz_po_1213` (`[None, _blad_mysql(1213)]`), `test_gwiazdki_dwa_1213_to_500_bez_zapisow`
  (`[None, 1213, None, 1213]`: gwiazdki, `priority_stars_set_*` i log bez zmian), `test_gwiazdki_inny_kod_bez_ponowienia`
  (`[None, _blad_mysql(1205, ...)]`: 500, dwa commity). Wzór testów: `git show b4b4a54d:tests/test_priorytety_kolejnosc_zapisow.py`
  (`:193-223`, przed przepisaniem pliku przez K1).
- `test_przeliczenie_nieudane_nie_cofa_gwiazdek` (parametryzowany jak w Task 2: `utrwal` rzuca albo zwraca
  `success: False`): wynik 200 i `nieudane`, gwiazdki w bazie zmienione.
- `test_gwiazdki_zmieniaja_kolejnosc_w_kolejce`: bez podmiany `utrwal`, czyli prawdziwy K1. Zamówienie bez gwiazdek po
  `gwiazdki: 5` wychodzi pierwsze w `priority_rank` (pamięć podręczna).
- `test_przelicz_admin_zwraca_raport_i_loguje` (dane, które `utrwal` zmienia: dokładnie **jeden** wiersz
  `PriorityLog(action='przeliczenie', user_id=1)` — z `utrwal`, nie z routera), `test_przelicz_porazka_500`
  (parametryzowany: `utrwal` rzuca albo zwraca `success: False` z `error`; odpowiedź `przeliczenie_nieudane` bez treści
  `error`, bez wpisu w logu).

- [x] **Step 2: Testy padają.** **Step 3: Implementacja** wg pseudokodu i wzoru hurtu, z wierszami
  `PUT /zamowienia/gwiazdki` i `POST /przelicz` w `KONCOWKI`. Odpowiedź `zmienione`, `bez_zmian` i `nieznane` daje
  rosnące listy id. **Step 4: Testy przechodzą.** **Step 5: Commit**
`feat(priorytety): gwiazdki hurtem i reczne przeliczenie w panelu`

---

### Task 4: Kolejka i dane modalu priorytetu (tylko odczyt)

**Files:**
- Modify: `modules/production/priorytety/services/widok.py`, `.../routers/panel_api.py`, `tests/test_priorytety_panel_api.py`

**Stan obecny (ugruntowanie):**
- Stanowiska i statusy oczekiwania: `modules/production/services/station_catalog.py:68-76` (`STATION_PENDING_STATUS`,
  7 kodów), nazwy `:37-45` (`STATION_LABELS`), `station_label()` `:79`.
- Materiał pozycji: gatunek i klasa w `ProductionConfiguration` (`models.py:99-101`, relacja z pozycji), wymiary
  `parsed_length_cm`/`parsed_width_cm`/`parsed_thickness_cm` (`models.py:340-342`), doróbka `original_product_id`
  (`:329`), termin `deadline_date` (`:380`).
- Sposób dostawy: `prod_orders.override_delivery_method` (CLAUDE.md, „Logistyka równoległa”).
- Stół (`prod_station_desk`) do K3 jest pusty, ale K2 czyta go już teraz: pomija kafle z wierszem stołu i pokazuje
  odłożenia w modalu.

**Interfaces:**
- Produces (`widok.py`):
  - `kolejka_zamowien() -> List[dict]` (na żywo: `kolejka._migawka(db.session)` → `policz`).
  - `wejscie_kandydatow(S, zamowienia, pozycje, trasa_zamowienia, desk_unit_keys) -> Tuple[List[kolejka.PozycjaStanowiska],
    Dict[int, tuple]]`: **czysta funkcja na obiektach już wczytanych** (zero zapytań, także leniwych relacji — wołający
    wczytuje `configuration` pozycji i kolekcje z wyprzedzeniem), jedyne miejsce budowania wejścia do
    `kolejka.kandydaci_stanowiska`. Używa jej `kolejka_stanowiska` (zwykły odczyt), a w K3 `stol.dopelnij` (listy
    z odczytu bieżącego `odczyt_biezacy_kandydatow`) — dzięki temu podgląd i stół nie mogą się rozjechać (Doprecyzowania
    p. 7, 13). Parametry: `zamowienia` — zamówienia z ≥ 1 pozycją w `STATION_PENDING_STATUS[S]` (ORM); `pozycje` —
    **wszystkie** pozycje tych zamówień (ORM; potrzebne do `statusy_zamowien` i terminu); `trasa_zamowienia` —
    `{order_id: route_id}` dla przystanków na trasach `robocza`/`zatwierdzona`; `desk_unit_keys` — zbiór `unit_key`
    wierszy `StationDesk` stanowiska S (na stole i odłożone) **w bieżącej jednostce** S (Doprecyzowania p. 15).
    Wynik: `PozycjaStanowiska` (K1, Task 2) dla pozycji w statusie S, z pominięciem pozycji, których `p:<id>` albo
    `o:<order_id>` jest w `desk_unit_keys`; `rung`/`rank`/`gwiazdki` z kolumn `prod_orders.priority_rung`/
    `priority_rank`/`priority_stars` (Doprecyzowania p. 13), `termin` = `kolejka.termin_zamowienia(...)`, `na_trasie`
    z `trasa_zamowienia`, gatunek i klasa z `ProductionConfiguration` (`species`, `wood_class`), wymiary z `parsed_*_cm`;
    oraz `statusy_zamowien = {order_id: tuple((product_id, current_status) dla wszystkich pozycji zamówienia)}` —
    **pary**, kształt z planu K1 (Task 2 Interfaces; K1 potrzebuje `product_id` do `brakuje`). Anulowane i wstrzymane
    pomija sam algorytm. Pakowania bez sposobu dostawy funkcja **nie** filtruje (K2 pokazuje je z flagą, K3 pomija
    przy pobieraniu — Doprecyzowania p. 14).
  - `kolejka_stanowiska(kod, limit=50) -> dict`: zwykły odczyt (zamówienia, pozycje, przystanki, wiersze stołu) →
    `wejscie_kandydatow(...)` → `kolejka.kandydaci_stanowiska(S, pozycje_stanowiska, statusy_zamowien,
    szczebel_rozpoczete=drabina.pozycja_tagu('rozpoczete'))`. Bez własnego sortowania — kolejność kafli to dokładnie
    `Kandydaci.kafle`. `niekompletne[].brakuje` (pary `(product_id, status)` z K1) `kolejka_stanowiska` mapuje na
    `{"short_id", "stanowisko"}`: `short_id` pozycji z `pozycje` po `product_id`, stanowisko = kod, którego
    `STATION_PENDING_STATUS` równa się `status` (status bez stanowiska, np. `w_realizacji` → `null`).
  - `priorytet_zamowienia(order_id) -> Optional[dict]`.
- Produces (HTTP):
  - `GET /kolejka` → 200 `{"success": true, "wyliczono": iso, "lacznie": N, "zamowienia": [
      {"order_id", "numer", "klient", "ranga", "gwiazdki", "szczebel": {"id", "rodzaj", "etykieta", "pozycja"},
       "tagi": ["po_terminie"|"blisko_terminu"|"rozpoczete", ...], "termin": "YYYY-MM-DD"|null,
       "trasa": {"id", "nazwa", "date_from"}|null, "pozycji": n, "etapy": {"<kod stanowiska>": n, ...}}]}`
    po randze z `policz` (na żywo).
  - `GET /kolejka?stanowisko=S[&limit=L]` → 200 `{"success": true, "stanowisko", "nazwa", "jednostka", "lacznie",
      "kafle": [...], "niekompletne": [...]}`. Kafel-pozycja: `{"product_id", "short_id", "order_id", "numer", "gwiazdki",
    "szczebel", "rozpoczete", "dorobka", "termin", "material": {"gatunek", "klasa", "grubosc_cm"},
    "wymiary": {"dlugosc_cm", "szerokosc_cm", "grubosc_cm"}}`. Kafel-zamówienie: `{"order_id", "numer", "gwiazdki",
    "szczebel", "termin", "pozycji", "sposob_dostawy_ustawiony"}`. `niekompletne` (tylko jednostka `zamowienie`):
    `{"order_id", "numer", "na_stanowisku", "pozycji", "brakuje": [{"short_id", "stanowisko"}]}`. Błędy:
    400 `stanowisko_nieznane`, 400 `dane_niepoprawne` (`limit` poza 1–500).
  - `GET /zamowienia/<id>/priorytet` → 200 `{"success": true, "zamowienie": {"order_id", "numer", "klient"},
      "gwiazdki", "gwiazdki_ustawione": {"kiedy", "kto"}|null, "aktywne": bool, "ranga"|null,
      "szczebel": {..., "z": <liczba widocznych szczebli>}|null, "tagi", "termin", "trasa",
      "stanowiska": [{"stanowisko", "nazwa", "pozycji", "na_stole": [short_id|numer], "odlozone": [{"short_id", "powod",
        "notatka", "kiedy", "pracownik"}], "w_kolejce": {"miejsce", "z"}|null, "niekompletne": bool}],
      "historia": [{"akcja", "stare", "nowe", "powod", "notatka", "stanowisko", "kiedy", "kto"}]}`. `historia` to
    ostatnie 50 wpisów `prod_priority_log` zamówienia, od najnowszych. `kto` to imię i nazwisko użytkownika albo
    pracownika, a gdy go nie ma, `null`. 404 `zamowienie_nieznane`.

- [x] **Step 1: Testy, które padną**
- `test_kolejka_przyklad_3_3_ze_specu`: drabina i zamówienia A–H z tabeli w spec 3.3 (trzy trasy na szczeblach 1, 5, 8,
  tagi przesunięte jak w przykładzie). Drabina 3.3 nie ma „Rozpoczęte” (seed ma 9 szczebli) — przesuń go na sam koniec
  i daj wszystkim A–H pozycje w jednym statusie, żeby żadne nie było rozpoczęte. Terminy z tabeli przelicz względem
  `dzis` migawki (H po terminie, E w progu 3 dni roboczych, reszta dalej). Kolejność `order_id` to A, B, C, H, D, E, F, G.
  Szczebel F to trasa Pomorze mimo ★5.
- `test_kolejka_tagi_i_termin` (`po_terminie`, `blisko_terminu` przy progu 3 dni roboczych, `rozpoczete`, zamówienie
  bez `deadline_date` ma `termin: null` i idzie na koniec szczebla).
- `test_kolejka_pomija_nieaktywne` (wstrzymane, anulowane, spakowane), `test_kolejka_etapy_pozycji`.
- `test_kolejka_stanowiska_z_kandydatow_k1`: szpieg na `kolejka.kandydaci_stanowiska` z kodem `gluing` i statusem
  `czeka_na_sklejanie`; dostaje `szczebel_rozpoczete == drabina.pozycja_tagu('rozpoczete')`. Kolejność kafli
  w odpowiedzi jest taka sama jak w wyniku K1. Przykład X/Y ze specu 5.6: pozycje X przed Y po rozpoczęciu X. Kolumny
  `priority_rung`/`priority_rank` wypełnia w przygotowaniu prawdziwe `kolejka.utrwal()` (Doprecyzowania p. 13) —
  bez tego `rung` jest `None`.
- `test_kolejka_stanowiska_czyta_szczebel_z_kolumn`: dwa zamówienia na Sklejaniu, `priority_rung` wpisane wprost
  odwrotnie niż wynikałoby z `policz` (bez `utrwal()`): `?stanowisko=gluing` układa kafle po kolumnie (jak stół),
  a `GET /kolejka` po `policz` (na żywo).
- `test_kolejka_stanowiska_pomija_kafle_na_stole`: wiersz `StationDesk(p:<id>)` (na stole) i drugi z `postponed_at`
  (odłożony). Oba poza `kafle`.
- `test_kolejka_formatowania_dzieli_na_kompletne_i_niekompletne` (jednostka `zamowienie`, `brakuje` z kodem
  stanowiska).
- `test_kolejka_stanowiska_niekompletne_brakuje_short_id`: Formatowanie, zamówienie X z czterema pozycjami — jedna
  w `czeka_na_formatowanie`, trzy w `czeka_na_sklejanie`. `niekompletne` ma X z `na_stanowisku == 1`, `pozycji == 4`,
  a `brakuje` to trzy wpisy z `short_id` tych trzech pozycji (rosnąco po id pozycji) i `stanowisko == 'gluing'`.
  Dowodzi, że `statusy_zamowien` niesie pary `(product_id, status)`, a nie same statusy.
- `test_wejscie_kandydatow_ksztalt_i_zero_zapytan`: czysta funkcja na obiektach wczytanych z wyprzedzeniem
  (`Zapytania` puste w trakcie wywołania). `statusy_zamowien[order_id]` to krotka par `(product_id, current_status)`
  wszystkich pozycji zamówienia (także spoza S); pozycja z kluczem `p:<id>` albo `o:<order_id>` w `desk_unit_keys`
  nie trafia do wyniku; `na_trasie` z `trasa_zamowienia`.
- `test_kolejka_stanowiska_ignoruje_wiersze_stolu_innej_jednostki` (Doprecyzowania p. 15): Formatowanie z jednostką
  `zamowienie`, wiersz `StationDesk(p:<id>)` pozostały po jednostce `pozycja`. Zamówienie tej pozycji (kompletne)
  jest w `kafle`.
- `test_kolejka_pakowania_flaga_sposobu_dostawy`.
- `test_kolejka_stanowisko_nieznane_400`, `test_kolejka_limit_400` (0, 501, `abc`).
- `test_priorytet_zamowienia_pelne_dane`: trasa, ★2, historia dwóch zmian gwiazdek, pozycje na dwóch stanowiskach,
  `w_kolejce.miejsce` zgodne z `GET /kolejka?stanowisko=`, odłożenie z `StationDesk` z powodem i pracownikiem,
  `szczebel.z` = liczba widocznych szczebli.
- `test_priorytet_zamowienia_nieaktywnego` (`aktywne: false`, `ranga: null`, `stanowiska: []`, historia jest),
  `test_priorytet_zamowienia_404`.
- `test_odczyty_nie_biora_blokad`: `Zapytania` dla `GET /kolejka`, `?stanowisko=` i modalu. Brak `COMMIT`, brak
  parametru `logistyka_trasy_blokada`, brak `UPDATE`/`INSERT`.

- [x] **Step 2: Testy padają.** **Step 3: Implementacja** w `widok.py`, bez N+1: pozycje i zamówienia wczytane jednym
  zapytaniem z `selectinload` albo `joinedload`, przystanki i trasy jednym; wiersze `GET /kolejka` i
  `GET /zamowienia/<int:order_id>/priorytet` w `KONCOWKI`. **Step 4: Testy przechodzą.**
  **Step 5: Commit** `feat(priorytety): kolejka i dane modalu priorytetu w panelu`

---

### Task 5: Ustawienia (admin)

**Files:**
- Modify: `modules/production/priorytety/services/ustawienia.py` (K1), `.../routers/panel_api.py`,
  `tests/test_priorytety_panel_api.py`

**Stan obecny (ugruntowanie):**
- `prod_config`: model `ProductionConfig` (`modules/production/models.py:909-941`; `config_key` UNIQUE, `config_type`
  ∈ `string|integer|boolean|json|ip_list`).
- `ProductionConfigService.set_config` (`modules/production/services/config_service.py:265-335`) **commituje przy każdym
  kluczu**, więc w hurcie się nie nadaje. `invalidate_cache()` jest w `:452-458` (cały cache bieżącego procesu,
  wrapper `invalidate_config_cache()` w `:1089`). Pamięć podręczna procesu trwa 60 min (`:47-56`).
- Allowlista `POST /production/api/update-configs` (`modules/production/routers/api/config_api.py:506-529`) nie zawiera
  kluczy priorytetów i **nie** dostaje ich w K2 (jedna droga zapisu, Doprecyzowania p. 8).
- `DEADLINE_FINISHED_DAYS` i `DEADLINE_DEFAULT_DAYS` zostają w Konfiguracji (`config_api.py:228`) i K2 ich nie dotyka.

**Interfaces:**
- Produces (`ustawienia.py`):
  - `odczyt_panelu() -> dict`
  - `waliduj(dane) -> Tuple[Dict[str, Tuple[str, str]], Optional[Tuple[str, str, str]]]`: zwraca
    `({klucz_prod_config: (wartość_tekst, config_type)}, None)` albo `({}, (kod, pole, komunikat))`, gdzie `kod` ∈
    `dane_niepoprawne`, `stanowisko_nieznane`, `ustawienie_niepoprawne` (router nie zgaduje kodu po polu). Czysta, bez bazy.
  - `zapisz(zmiany, user_id) -> List[str]`: klucze faktycznie zmienione. UPDATE albo INSERT wierszy `prod_config`
    oraz wiersz `prod_priority_log` (`action='ustawienia'`, `note`=klucz) na każdą zmianę. Bez commita.
- Produces (HTTP):
  - `GET /ustawienia` → 200:
    ```json
    {"success": true,
     "stanowiska": {"gluing": {"nazwa": "Sklejanie", "tryb": "stary", "miejsca": 2, "jednostka": "pozycja", "limit_odlozen": 10}, "...": {}},
     "blisko_terminu_dni": 3, "min_app_version_code": 0, "deadline_day_type": "robocze"}
    ```
    Siedem kodów z `STATION_PENDING_STATUS`.
  - `PUT /ustawienia`: ciało to dowolny podzbiór tego samego kształtu (bez `nazwa`). Odpowiedź 200 to stan jak w `GET`
    plus `"zmienione": [klucze prod_config]` i `"przeliczenie": "ok"|"nieudane"|"niepotrzebne"`. Błędy:
    400 `stanowisko_nieznane`, 400 `ustawienie_niepoprawne` (`pole`, np. `stanowiska.gluing.miejsca`),
    400 `dane_niepoprawne`.
  - Mapa pól na klucze (spec 8.6): `tryb` → `priorytety_tryb_<S>` (`stary`|`stol`), `miejsca` → `priorytety_stol_<S>`
    (int 1–5), `jednostka` → `priorytety_jednostka_<S>` (`pozycja`|`zamowienie`), `limit_odlozen` →
    `priorytety_limit_odlozen_<S>` (int 1–50), `blisko_terminu_dni` → `priorytety_blisko_terminu_dni` (int 0–15),
    `min_app_version_code` → `priorytety_min_app_version_code` (int ≥ 0), `deadline_day_type` → `DEADLINE_DAY_TYPE`
    (`robocze`|`kalendarzowe`). Klucz blokady `priorytety_blokada_<S>` **nie** jest edytowalny. `bool` nie przechodzi
    jako int.
- Kolejność: walidacja całości → `user_id` → `zapisz` → `db.session.commit()` → `invalidate_config_cache()` →
  `_przelicz_po_zapisie()` tylko wtedy, gdy zmienił się `priorytety_blisko_terminu_dni`. Bez blokad: zapis dotyka
  tylko `prod_config` i logu bez `order_id`.

- [x] **Step 1: Testy, które padną**
- `test_ustawienia_odczyt_domyslny` (wartości ze specu 8.6, także przy braku wiersza: `jednostka` Formatowania
  i Pakowania to `zamowienie`).
- `test_ustawienia_zapis_czesciowy_i_log` (dwa pola, dwa wiersze logu, odpowiedź z nowym stanem, `invalidate_config_cache`
  wołane raz — szpieg).
- `test_ustawienia_walidacja_wszystko_albo_nic`: jedno złe pole w ciele z trzema polami. 400 z `pole`, w bazie i w logu
  nic się nie zmienia.
- `test_ustawienia_walidacja_400` (parametryzowany: `miejsca` 0/6/`True`/`"2"`, `limit_odlozen` 0/51, `jednostka` `"x"`,
  `tryb` `"nowy"`, `blisko_terminu_dni` -1/16, `min_app_version_code` -1, `deadline_day_type` `"x"`, nieznane stanowisko
  daje `stanowisko_nieznane`, nieznane pole najwyższego poziomu daje `dane_niepoprawne`).
- `test_ustawienia_zmiana_progu_przelicza` (szpieg `utrwal`: wołany raz) oraz `test_ustawienia_inne_pola_bez_przeliczenia`.
- `test_ustawienia_bez_zmian_nic_nie_zapisuje` (ta sama wartość: `zmienione: []`, brak logu).
- `test_ustawienia_zmiana_jednostki_przy_niepustym_stole` (Doprecyzowania p. 15): Sklejanie z wierszem
  `StationDesk(p:<id>)` (na stole) i drugim odłożonym; `PUT` z `jednostka: "zamowienie"` → 200, klucz
  `priorytety_jednostka_gluing` zmieniony, oba wiersze stołu nietknięte (K2 nie pisze do `prod_station_desk`),
  a `GET /kolejka?stanowisko=gluing` pokazuje zamówienie tej pozycji w `kafle` (stary wiersz go nie ukrywa).
- `test_ustawienia_i_przelicz_tylko_admin`: rola `user` w fiksturze. 403 dla `GET`/`PUT /ustawienia` i `POST /przelicz`;
  `GET /drabina` dalej 200.
- `test_ustawienia_czytane_bez_pamieci_podrecznej_procesu`: zapis `PUT`, potem surowy `UPDATE prod_config` (zapis
  „innego workera”) i `ustawienia.tryb('gluing')` widzi wartość z bazy bez `invalidate`. Z odczytem K1 przez
  `config_service.get_config` ten test **padnie** — dalej wg decyzji z karty (Task 1, Step 0 p. 4): naprawa w
  `ustawienia.py` albo `xfail(strict=True)` z numerem meldunku.
- Wszystkie testy tego Taska używają `czyste_ustawienia` (K1, `tests/priorytety_fixtures.py`).
- Wiersze `GET /ustawienia` i `PUT /ustawienia` do `KONCOWKI`, a w `test_zestaw_koncowek` asercja `len(KONCOWKI) == 8`.

- [x] **Step 2: Testy padają.** **Step 3: Implementacja.** **Step 4: Testy przechodzą** (cały plik). **Step 5: Commit**
`feat(priorytety): ustawienia stolow, progu i terminow w panelu`

---

### Task 6: Usunięcie martwych końcówek starego systemu

**Files:**
- Modify: `modules/production/routers/api/products_api.py`, `modules/production/routers/__init__.py:172`,
  `modules/production/services/blokady_zamowien.py:127-130`
- Modify: `tests/test_priorytety_kolejnosc_zapisow.py`, `tests/test_produkty_masowa_zmiana_statusu.py:81-91`,
  `tests/test_priorytety_wyzwalacze.py` (K1: `test_hurt_statusu_utrwala_a_update_priority_nie`)

**Co zmienił już K1 (plan K1, Doprecyzowania i Task 4, 6):** testy przeciągania w
`tests/test_priorytety_kolejnosc_zapisow.py` K1 usuwa przy przepisaniu pliku (Step 4 niżej to tylko sprawdzenie),
`lock_priority`/`unlock_priority` są puste, a w `bulk_action` gałąź `update_status` woła po commicie
`kolejka.utrwal_po_commicie('hurt_statusu')` — to wywołanie **zostaje**. K1 dopisał też test
`test_hurt_statusu_utrwala_a_update_priority_nie` (`tests/test_priorytety_wyzwalacze.py`), który woła
`update_priority` i oczekuje rangi 42 — po K2 ta akcja daje 400, więc test trzeba przepiąć (Step 1).

**Stan obecny (ugruntowanie; `b4b4a54d`, po K1 szukaj po nazwie):**

| Co | Gdzie | Wołający (grep `--include=*.js --include=*.html --include=*.py`) |
|---|---|---|
| `PUT /products/<int:product_id>/priority` (`update_single_product_priority`) | `products_api.py:2534-2597` (z komentarzem `# 5. UPDATE…`) | brak |
| `_id_pozycji`, `POST /update-priority` (`update_priority`), `_zapisz_priorytety` | `products_api.py:2880-2996` | `products-dragdrop.js:535`, ścieżka martwa: `onDragStart` reaguje tylko na `.prod_list-drag-cell` (`products-dragdrop.js:225-229`), a takiej klasy nie ma w znacznikach (`grep -rn "prod_list-drag-cell" modules/production/templates modules/production/static/js/modules/products-module.js` → pusto). Skrypt ładuje `dashboard.html:361`, usuwa go K4a. Testy: `tests/test_priorytety_kolejnosc_zapisow.py:43-121, 186-233` |
| `POST /recalculate-all-priorities` (`reset_all_priorities`) z nagłówkiem sekcji | `products_api.py:3253-3374` | brak |
| `POST /products/<int:product_id>/set-manual-priority` (`set_manual_product_priority`) | `products_api.py:3378-3493` | brak |
| `GET /priority-statistics` (`get_priority_statistics`, router) | `products_api.py:3497-3676` | brak. Funkcja serwisu `priority_service.get_priority_statistics` **zostaje** (K8; test `tests/test_priority_statusy_krawedzi.py:95-116`) |
| akcja `update_priority` w `POST /products/bulk-action` | `products_api.py:1533`, `:1537` (docstring), `:1557` (`valid_actions`), `:1631-1635`, `:1657` | JS woła tylko `update_status` (`products-module.js:2916`) i `delete` (`:2999`). Formularz „Ustaw priorytet” w `products-tab-content.html:268-330` nie ma obsługi w JS (grep `new_priority`, `update_priority`, `change-priority` w `static/js` → pusto) i usuwa go K4a. Test: `tests/test_produkty_masowa_zmiana_statusu.py:81-91` |
| `'/api/update-priority'` w `URL_PATTERNS` | `modules/production/routers/__init__.py:172` | lista informacyjna |
| docstring `kod_mysql` (przeciąganie `products_api.update_priority`) | `blokady_zamowien.py:127-130` | — |
| **zostaje:** `POST /set-priority` (`set_product_priority`) | `products_api.py:3679-3798` | `products-module.js:2383` (K4a) |

Po usunięciu sprawdź importy `products_api.py:7-21`. `OperationalError` i `blokady_zamowien` zostają (używa ich
`bulk_action`, `:1599-1607`). `priority_service` jest importowany tylko lokalnie w usuwanej funkcji (`:3293`).

- [x] **Step 1: Testy, które padną**
- `tests/test_priorytety_kolejnosc_zapisow.py`: dopisz `test_martwe_koncowki_priorytetow_usuniete` na fiksturze
  `krawedzie_fixtures.app`. W `app.url_map` nie ma reguł `/production/api/update-priority`,
  `/production/api/products/<int:product_id>/priority`, `/production/api/products/<int:product_id>/set-manual-priority`,
  `/production/api/recalculate-all-priorities`, `/production/api/priority-statistics`. Reguła
  `/production/api/set-priority` **jest**.
- `tests/test_produkty_masowa_zmiana_statusu.py`: `test_inne_akcje_nie_wymagaja_statusu` przepnij na `action: 'export'`
  (200, `processed_count == 1`, status pozycji bez zmian). Nowy `test_bulk_action_update_priority_400`: 400,
  `priority_rank` bez zmian.
- `tests/test_priorytety_wyzwalacze.py` (K1): z `test_hurt_statusu_utrwala_a_update_priority_nie` zostaje część
  „hurt statusu woła `utrwal` po commicie”; część z `update_priority` zamień na „`update_priority` → 400 i `utrwal`
  niewołane”. Zmień nazwę na `test_hurt_statusu_utrwala_a_update_priority_odrzucone` i odnotuj w „Odstępstwach”
  (dotknięcie testu K1 wymuszone usunięciem akcji, spec 9.5).
- [x] **Step 2: Testy padają.**
- [x] **Step 3: Usunięcia** wg tabeli. W `bulk_action` usuń gałąź `update_priority`, wpis w `valid_actions`, linie
  docstringu i warunek commita (`if action in ['update_priority', 'delete']` → `if action == 'delete'`). Docstring
  `kod_mysql`: lista „priorytety (przeciąganie …, przeliczenie …)” → „przeliczenie priorytetów
  (`priority_service.recalculate_all_priorities`, od K1 `kolejka.utrwal`) i zapis gwiazdek oraz drabiny w panelu
  priorytetów (`priorytety/routers/panel_api.py`)”.
- [x] **Step 4: Testy przeciągania.** K1 powinien je już usunąć (plan K1, Task 4 Step 1). Sprawdź
  `grep -n "update-priority\|_przeciagnij" tests/test_priorytety_kolejnosc_zapisow.py`. Jeśli coś zostało, usuń testy
  wołające `/update-priority` i pomocniki używane tylko przez nie (`_przeciagnij`; `_commit_z_bledami` i `_rangi`, jeśli
  nie korzysta z nich nic innego). Testy `utrwal` z K1 zostają nietknięte. Docstring modułu nie mówi już „przeciąganie
  usuwa K2”, tylko że przeciąganie usunięto w K2. Wynik grepa (także „nic do usunięcia”) do raportu.
- [x] **Step 5: Grep kontrolny** (wynik do raportu):
  `grep -rn --include=*.py -E "update-priority|update_single_product_priority|set-manual-priority|recalculate-all-priorities|priority-statistics|'update_priority'|def update_priority|_zapisz_priorytety|_id_pozycji" modules tests app.py`
  Oczekiwane: brak trafień w `modules/` i `app.py`, a w `tests/` tylko nowe testy nieobecności. Trafienia w
  `products-dragdrop.js` i `products-tab-content.html` zostają dla K4a.
- [x] **Step 6: Testy przechodzą:** trzy zmienione pliki testów, `tests/test_priority_statusy_krawedzi.py`,
  `tests/test_priorytety_panel_api.py`. **Step 7: Commit**
`refactor(priorytety): usuniecie martwych koncowek starego systemu priorytetow`

---

### Task 7: Pełny pakiet, Python 3.9, raport kroku

**Files:**
- Create: `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K2-raport.md`

- [x] **Step 1: Pełny pakiet:** `docker compose exec app pytest tests/ -q -p no:cacheprovider`. Oczekiwane: 0 failed,
  `passed` = punkt wyjścia + nowe − usunięte testy przeciągania (liczby w raporcie). `blog_seo` nie dotyczy.
- [x] **Step 2: Składnia pod 3.9** dla plików `.py` zmienionych w K2 (`git diff --name-only <hash startu>..HEAD -- '*.py'`):
  `docker compose exec app python -c "import ast,sys; [ast.parse(open(p,encoding='utf-8').read(), p, feature_version=(3,9)) for p in sys.argv[1:]]; print('OK')" <pliki>`
  oraz grep `' | None'`/`'\w+ \| \w+'` w adnotacjach plików bez `from __future__ import annotations` → pusto.
- [x] **Step 3: Pokaz końcówek** (karta centrali 8.2): dla każdej z 8 końcówek jedno wywołanie z odpowiedzią. Wybierz
  jeden sposób i użyj go dla wszystkich:
  - `curl` na podglądzie wskazanym przez centralę (sesja zalogowana, cookie z przeglądarki; w raporcie bez wartości
    cookie);
  - zrzut z klienta testowego Flaska: test `test_pokaz_koncowek_do_raportu` z
    `@pytest.mark.skipif(not os.environ.get('POKAZ_K2'), reason=...)`, uruchamiany ręcznie:
    `docker compose exec -e POKAZ_K2=1 app pytest tests/test_priorytety_panel_api.py -k pokaz -s -q -p no:cacheprovider`.
    Wypisuje skrócone odpowiedzi.
  Dane testowe, nie klientów. Skróć długie listy do 2 elementów.
- [x] **Step 4: Raport** z sekcjami z karty: Zrobione (po Taskach), Testy (polecenia i wyniki, liczby z Step 0 i 1),
  Odstępstwa od planu (w tym nazwy z K1 inne niż w specu, Step 0 Task 1), Rozstrzygnięcia podjęte w trakcie
  (numerowane, z kosztem pomyłki), Pytania do Konrada, Stan gałęzi (hash, czy wypchnięte), Co następny krok musi wiedzieć.
  Ta sekcja ma co najmniej:
  - **K3:** panelowy kształt kafla z `GET /kolejka?stanowisko=` (`widok.py`) K3 używa tylko w `GET /stoly` panelu;
    kafel w `GET desk` to `serialize_order` + `priorytet` (spec 6.1, kontrakt appki), nie pola panelu. Wspólne jest
    wyłącznie wejście do `kolejka.kandydaci_stanowiska`: `stol.dopelnij` woła `widok.wejscie_kandydatow(S, zamowienia,
    pozycje, trasa_zamowienia, desk_unit_keys)` na listach z odczytu bieżącego (bez wydzielania funkcji w K3 i bez
    kopii), z `szczebel_rozpoczete = drabina.pozycja_tagu('rozpoczete')` (Doprecyzowania p. 13). `statusy_zamowien` to
    pary `(product_id, current_status)` (plan K1), a `kompletne_na_stanowisku(statusy, S)` przyjmuje same statusy —
    plan K3 (Interfaces Task 2, Step 0 p. 3) trzeba poprawić na pary. Wiersz stołu z kluczem innej jednostki niż
    bieżąca jest nieaktualny (Doprecyzowania p. 15): `dopelnij` nie liczy go do K i podaje do `wejscie_kandydatow`
    tylko klucze bieżącej jednostki, `zdejmij_nieaktualne` go zdejmuje — z testami w K3. `StationDesk` K2 tylko czyta;
  - **K4a:** kontrakty JSON z Task 2–4 (ścieżki, pola, kody błędów), `pozycja` = indeks widoczny, `oczekiwane`,
    wartości `przeliczenie`, a do tego to, co JS ma usunąć: `products-dragdrop.js` (z `dashboard.html:361`),
    formularz `bulk-priority-form` (`products-tab-content.html:316-330`) i wywołanie `set-priority` (`products-module.js:2383`)
    razem z końcówką `set-priority`;
  - **K4b:** `GET`/`PUT /ustawienia` jako jedyna droga zapisu kluczy priorytetów i `DEADLINE_DAY_TYPE` (bez allowlisty
    `update-configs`), format 403 `admin_required`;
  - **K5:** CLAUDE.md, sekcja „Ważne”, akapit pisarzy pozycji (dziś `CLAUDE.md:368` i `:384`) opisuje jeszcze
    „przeciąganie `update-priority`” i „hurtową i ręczną zmianę priorytetu”. Po K2 tych pisarzy nie ma, trzeba to
    poprawić razem z sekcją „Priorytety produkcji”. Do tego Doprecyzowania 1–15 tego planu do specu, decyzja w sprawie
    pamięci podręcznej `ustawienia.*` (Task 1, Step 0 p. 4) i wyścigi MySQL: gwiazdki ↔ ZAKOŃCZ, przesunięcie szczebla ↔
    przystanek (spec 13).
- [x] **Step 5: Commit raportu i push** wg karty: `git add -f docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K2-raport.md`,
  `docs(priorytety): raport kroku K2 panel api`.

---

## Kryteria zakończenia (DoD)

1. `app.url_map` ma pod `/production/api/priorytety/` dokładnie 8 końcówek z Task 1 (`test_zestaw_koncowek` zielony,
   bez `xfail`).
2. `tests/test_priorytety_panel_api.py` jest zielony. Każdy test wymieniony w Review Focus istnieje pod tą nazwą
   i przechodzi. Jedyny dopuszczalny wyjątek: `test_ustawienia_czytane_bez_pamieci_podrecznej_procesu` jako
   `xfail(strict=True)` z numerem meldunku — tylko gdy karta nie zawierała decyzji o naprawie (Task 1, Step 0 p. 4).
3. Pełny pakiet: 0 failed. Liczby w raporcie, różnica wobec Step 0 wyjaśniona (nowe i usunięte testy).
4. Grep z Task 6, Step 5 bez trafień w `modules/` i `app.py`. `POST /production/api/set-priority` dalej istnieje.
5. Każda odmowa routera ma `error` (kod z listy Doprecyzowań p. 1) i `message` po polsku. Żadna odpowiedź 500 nie
   zawiera treści wyjątku.
6. Żadnego `db.session.commit()` w `widok.py` ani `ustawienia.zapisz`. Commity są tylko w routerze (grep).
7. Składnia 3.9: OK dla wszystkich zmienionych plików `.py`.
8. Raport kroku zacommitowany, z pokazem 8 końcówek i sekcją „Co następny krok musi wiedzieć” z punktami K3, K4a, K4b
   i K5.
9. `main` nietknięty. Commity tylko na `claude/priorytety-produkcji`: 7, po jednym na Task.

## Poza zakresem

- UI: Lista produkcyjna, modale, gwiazdki w Logistyce, usunięcie `products-dragdrop.js` i `set-priority` (K4a).
  Konfiguracja, Stanowiska, dashboard, monitory (K4b).
- Stół, Odłóż, bramka ZAKOŃCZ, sygnały, końcówki mobilne (K3). K2 nie pisze do `prod_station_desk`.
- Zmiany algorytmu `policz`/`kandydaci_stanowiska`/`utrwal` (K1). Jedyne dopuszczalne dotknięcia plików K1 opisuje
  Task 1, Step 0 p. 4.
- `priority_service.py` i jego `get_priority_statistics` (K8). `config_api.py` i jego allowlista.
- Wyścigi na MySQL (K5). Zaobserwowane przy okazji usterki (np. `DEADLINE_FINISHED_DAYS` spoza allowlisty
  `update-configs`, `config_api.py:506-529`) idą do raportu, bez naprawy.

## Ryzyka i co robić przy blokadzie

| Ryzyko | Skutek | Co robić |
|---|---|---|
| Interfejsy K1 różnią się od specu (nazwy, typy zwracane, brak tagów i szczebla w `policz`, brak `kandydaci_stanowiska`) | Task 2/4 nie da się zrobić wg planu | Task 1, Step 0 p. 4: dopuszczalne drobne dopasowania. Brak funkcji → **STOP** przed Taskiem, który jej potrzebuje, i meldunek do centrali z rekomendacją. Bez własnej kopii algorytmu |
| `ustawienia.*` z K1 czyta przez pamięć podręczną `config_service` (60 min na proces) — plan K1 tak to zakłada | zmiana trybu, K albo progu dociera do innych workerów gunicorna po godzinie; wycofanie P3 „bez zmiany kodu” byłoby opóźnione | decyzja przed kartą („Pytania do Konrada” p. 1). Naprawa w `ustawienia.py` tylko za zgodą z karty; bez niej meldunek i `xfail(strict=True)` (DoD 2) |
| Linie w `products_api.py` przesunięte przez K1 | usunięcie złego fragmentu | usuwaj po nazwie funkcji i dekoratorze. Grep kontrolny z Task 6, Step 5 i pełny pakiet |
| `tests/test_priorytety_kolejnosc_zapisow.py` przepisany przez K1 (bez `_commit_z_bledami`, bez testów przeciągania) | brak wzoru do skopiowania; pusty Step 4 Task 6 | wzory 1213 z `git show b4b4a54d:tests/test_priorytety_kolejnosc_zapisow.py`. Usuwaj tylko testy wołające `/update-priority`, jeśli zostały. Testy `utrwal` z K1 zostają nietknięte |
| Testy K1 wołające usuwane końcówki (`test_hurt_statusu_utrwala_a_update_priority_nie`) | czerwony pełny pakiet po Task 6 | przepięcie wg Task 6, Step 1; inne trafienia grepa z Task 6, Step 5 w `tests/` → tak samo, każde w „Odstępstwach” |
| `GET /drabina` pisze (samonaprawa) | GET bierze blokadę tras i może chwilę czekać na zapis logistyki | samonaprawa uruchamia się tylko przy brakującym szczeblu (okno wdrożenia). Porażka nie psuje odczytu (Doprecyzowania p. 5) |
| `policz` na żywo przy każdym `GET` | czas odpowiedzi rośnie z liczbą zamówień | na produkcji ok. 250 zamówień aktywnych (symulacja). Zmierz czas `GET /kolejka` i modalu na podglądzie i wpisz go do raportu. Ponad 1 s → meldunek, bez optymalizacji na własną rękę |
| SQLite nie sprawdza `FOR UPDATE` ani REPEATABLE READ | błąd kolejności blokad niewidoczny w testach | testy kolejności zapytań i commitów (Review Focus 1–2). Wyścigi na MySQL robi K5 |
| Padający test spoza zakresu, spór spec ↔ kod, MySQL 1213 | — | **STOP**: opis w raporcie, meldunek do centrali, bez obejść i bez wyłączania testów (podręcznik, sekcja 6) |

## Pytania do Konrada

Do decyzji **przed wydaniem karty** (centrala wpisuje odpowiedź do karty, żeby sesja nie stanęła w Task 5):
1. Plan K1 każe `ustawienia.*` czytać przez `config_service.get_config` z pamięcią podręczną procesu (60 min). Zapis
   z `PUT /ustawienia` unieważnia ją tylko w workerze, który obsłużył żądanie; pozostałe workery gunicorna widzą stary
   tryb stanowiska, K, limit i próg „Blisko terminu” nawet godzinę (w P3 także wycofanie stanowiska na `stary`).
   Rekomendacja: **tak, K2 naprawia** — `ustawienia.*` czyta wiersz `prod_config` wprost (jedno małe zapytanie po
   kluczu), z tą samą walidacją i wartościami domyślnymi; testy K1 zostają zielone. Alternatywa: karta naprawcza K1.

Do potwierdzenia przy bramce (domyślne wartości w planie): zakres progu „Blisko terminu” 0–15 dni (Doprecyzowania
p. 8) oraz to, czy `GET /ustawienia` ma być tylko dla admina (tak w planie, wg spec 7.3), czy także dla biura.
