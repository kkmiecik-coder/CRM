# Logistyka — runda 2 (uwagi po testach) — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zamknąć 7 uwag Konrada po testach na kopii produkcji: kierowcy tras jako wyróżnieni pracownicy, filtr województw, sposób dostawy w dymku pinezki, filtry przełączające mapę na „Zamówienia”, odstęp pola wyboru, kółko na mapce trasy i logistyka poza pipeline'em dashboardu produkcji.
**Architecture:** Backend: kolumna `prod_workers.is_driver` (idempotentna migracja) + serwis/API kierowców we `fleet.py`/`trasy_api.py` i reguła „nowy albo zmieniony kierowca musi mieć znacznik” w `routes._sprawdz_zasoby`; nowy moduł `logistics/wojewodztwa.py` (mapa kodów z `modules/reports/utils.py`) daje warunek SQL dla `lista.pobierz(woj=…)`. Frontend: punkty zaczepienia w istniejących plikach zakładki, nowy `logistics-wojewodztwa.js` (panel filtra, rozmowa zdarzeniem), most `window.LogisticsMap.onSposob` z dymku do ścieżki zapisu listy; dashboard produkcji traci węzeł szyny, zyskuje pasek pod listą stanowisk.
**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, MySQL 8.4 (produkcja) / SQLite (testy), Jinja2, pytest, vanilla JS + Leaflet (vendor), CSS.
**Spec:** docs/superpowers/specs/2026-09-28-logistyka-runda-2-uwagi-design.md

## Global Constraints

- Komentarze w kodzie po polsku; w UI „Base.”, nie „BaseLinker”; teksty z poprawną odmianą (1 trasa, 2 trasy, 5 tras).
- Każde zadanie UI (2, 4, 5, 6) ze skillem `frontend-design:frontend-design`, w stylu zakładki: klasy `lg-*`, okna `<dialog class="lg-dialog">`, komunikaty `pokazKomunikat` / `window.LogisticsTab.komunikat`; dashboard produkcji — klasy `il-*` i zmienne `--il-*`.
- `?v=` podbijane przy każdej zmianie pliku statycznego (wartości w tabeli „Wersje plików” niżej).
- Większy nowy kod JS w nowym pliku; w `logistics.js` (~2250 linii), `logistics-map.js` (~2160) i `logistics-routes.js` (~3850) tylko punkty zaczepienia.
- Blokady tras: piszący trasy biorą najpierw `routes.zablokuj_trasy()`; zmiana znacznika kierowcy NIE jest zapisem trasy (bez blokady); walidacja kierowcy przy zapisie trasy pod blokadą jak dziś.
- Gunicorn sync, timeout 30 s — żadnych wywołań zewnętrznych w nowych żądaniach.
- Migracja `migrations/2026-09-28-logistyka-kierowcy.sql`: idempotentna, bez `DELIMITER`, `ALTER` tylko w `PREPARE/EXECUTE`; wykonuje się przy starcie aplikacji i w `deploy.sh` (`flask migrate`).
- Kod zgodny z Pythonem 3.9 (produkcja): bez `match`, bez `X | None`; SQLAlchemy < 2.0 — wszystkie filtry listy przed `order_by/limit` (R3).
- Testy WYŁĄCZNIE z katalogu worktree: `docker compose -p logistyka3 run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider`; nigdy `docker compose exec`; nie twórz `config/core.json` w worktree.
- Pełny pakiet raz na zadanie, przed commitem: `docker compose -p logistyka3 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider` (punkt wyjścia rundy: `4704 passed, 3 skipped`; po każdym zadaniu: 0 failed, passed = poprzednio + nowe testy).
- Składnia JS: `node --check <plik>` na hoście (node jest w PATH Windows, w obrazie go nie ma).
- Commity: Conventional Commits po polsku, tytuł bez polskich znaków, scope `production`, `git commit -m "…" -- <ścieżki>`, stopka `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; nie commitujemy `docs/superpowers/**`, `config/core.json`, `.superpowers/**`; bez pusha.
- Implementer (także UI) NIE uruchamia przeglądarki (ani Chrome, ani chrome.exe) — oględziny robi kontroler we wbudowanej przeglądarce na 127.0.0.1:5003.
- Repo jest publiczne — bez sekretów i uwag bezpieczeństwa w kodzie, komentarzach i commitach.

## Review Focus

1. **Kody pocztowe z życia i zamówienia zagraniczne** — „35-310”, „35310”, „35 310”, pusty/NULL, śmieci, prefiksy 24/69/88/89 oraz niemiecki „35390” z krajem DE: każde zamówienie trafia do dokładnie jednej z 18 opcji, nic nie znika. Test: `test_kazde_zamowienie_w_dokladnie_jednym_kubelku` (Task 3).
2. **Kierowca, któremu zdjęto znacznik, a który jest na trasie** — edycja (np. nazwy) i przywrócenie trasy wykonanej przechodzą, dostępność pokazuje go tylko w jego trasie (`nie_kierowca`), po zmianie na innego powrót to 409. Test: `test_kierowca_bez_znacznika_zostaje_na_swojej_trasie` (Task 1).
3. **Odmowa zmiany sposobu z dymku przychodzi w `bledy` przy HTTP 200** (spakowane → „Nie ustawiono”, trasa zatwierdzona) — dymek musi pokazać wartość z serwera, nie wybór logistyka; select dymku nie może mieć klasy `lg-sposob` ani atrybutu `data-lg-sposob` (delegacja listy wzięłaby go za select wiersza albo licznik). Test: `test_dymek_przerysowuje_wybor_po_kazdej_odpowiedzi` (Task 5).
4. **Województwa razem z `zamkniete=1&q=…` (LIMIT 50) i `sposob=bez_trasy`** — filtr w SQL przed limitem, trafienie spoza pierwszych 50 nie ginie. Testy: `test_woj_przed_limitem_zamknietych`, `test_woj_razem_z_bez_trasy_i_sposobem` (Task 3).
5. **Przełączanie mapy** — każda zmiana filtra zamówień (także zdjęcie) przełącza z „Trasy” na „Zamówienia”, wyszukiwarka i „także zamknięte” nie; nic nie wraca samo na „Trasy”. Test: `test_filtry_przelaczaja_mape_a_wyszukiwarka_nie` (Task 4).

---

## Kontekst dla wykonawcy

Gałąź `claude/logistyka-etap-3-trasy` (jedyna gałąź logistyki, etapy 1–3 + runda 4.1), worktree
`C:\Users\Grafik\Documents\woodpower-crm\.claude\worktrees\logistyka-etap-3-trasy`. Nic nie jest w `main`.

*Backend (`modules/production/logistics/`)*
- `__init__.py` — blueprint `logistics_panel_bp` (`/production/api/logistics`), na końcu import routerów.
- `routers/panel_api.py` — `guard` (:54), `_blad(komunikat, status)` → `{success: false, error}` (:67), `tab_content()` (:71–75), `orders()` (:78–97, dziś waliduje tylko „zamknięte bez frazy” → 422).
- `routers/trasy_api.py` — `_cialo()` (:38–58; niepuste ciało nie-obiekt → 422), `_odmowa(e)` (:68–73, rollback + `e.status`), `GET /drivers` (:309–312), `GET /availability` (:315–334).
- `services/delivery.py:21` — `LogistykaBlad(komunikat, status=409, dane=None)`.
- `services/fleet.py` — `kierowcy()` (:123–127) zwraca dziś WSZYSTKICH aktywnych pracowników jako `[{id, nazwa}]`; `_ID_RE` (:17).
- `services/routes.py` — `zajetosc` (:276–293), `dostepnosc(date_from, date_to, pomin_route_id=None)` (:296–303), `_sprawdz_zasoby(od, do, vehicle_id, driver_id, route=None)` (:306–347; reguła I3 / rozstrzygnięcie 33: NIEZMIENIONY wyłączony pojazd i nieaktywny kierowca trasy przechodzą, zakaz dotyczy nowego przypisania; kierowca czytany `ProductionWorker.query.get` :336–338), `utworz` (:377), `edytuj` (:390), `przywroc` (:672).
- `services/lista.py` — `pobierz(sposob, etap, q, zamkniete)` (:181–220; docstring R3: filtry przed `order_by/limit`; `LIMIT_ZAMKNIETYCH = 50`).
- `modules/production/models.py:1367–1461` — `ProductionWorker` (`is_active` :1395, `sort_order`, `first_name`, `last_name`); `ProductionOrder.delivery_postcode` (String 20, :183), `delivery_country_code` (String 10, :184; pusty = Polska, jak `delivery.zmien_adres` :340).
- `modules/reports/utils.py:15–155` — `PostcodeToStateMapper.POSTCODE_RANGES` (16 województw, zakresy dwóch pierwszych cyfr; brak 24, 69, 88, 89), `STATE_NORMALIZATION` (nazwy kanoniczne). **Import pakietu `modules.reports` ładuje jego routery (pandas, `routimo.zbuduj_excel` z logistyki)** — dlatego `routimo.przygotuj_eksport` importuje mapę w funkcji (leniwie).

*Frontend (`modules/production/logistics/`)*
- `templates/logistics/tab_content.html` — narzędzia listy `.lg-narzedzia` (:98–132, przycisk `.lg-filtr-trasy[data-lg-sposob="bez_trasy"]` :127–130), Flota (:430–472, sekcja kierowców :462–469), okno pojazdu (:556–575), loader mapy/tras (:586–642), `<script src>` `logistics.js` (:644) i `logistics-fleet.js` (:645). **`<script src>` wstawiane przez production-app-loader wykonują się asynchronicznie — kolejność plików nie jest gwarantowana.**
- `static/js/logistics.js` — IIFE; `stan.filtr` (:133), `wczytaj(tryb)` (:278–336), `zawezonyWidok` (:462), `pustyStan()` (:615–659), `selectSposobu()` (:661–673), `podmienWiersze()` (:986–1001), `wyslijSposob(ids, sposob)` (:1163–1179), `podsumujZmiany()` (:1189–1216), `nowyWynik/dolacz` (:1240–1250), `zmianaSelecta()` (:1254–1283, zwłoka `ZWLOKA_SELECTA_MS`), `ustawFiltrGeo()` (:1592–1598), `mapa()` (:1635), `polaczZMapa()` (:1640–1650), `przekazDoMapy()` (:1664–1675), `ustawSposobFiltra()` (:1938–1947), `zdejmijFiltry()` (:1950–1962), `zmianaFrazy()` (:1964–1977), delegacja `click` (:1981–2096) i `change` (:2098–2121) na `#logistics-root`, `zniszcz()` (:2185–2200), `window.LogisticsTab` (:2204–2211).
- `static/js/logistics-map.js` — IIFE; `window.LogisticsMap` (api :2098–2117: `render`, `onSelect`, `onZmiana`, `onBlad`, `ustawWidok`, `widok`, …), `SPOSOBY/ETYKIETY` (:142–150, te same podpisy co lista), `dymekHtml(z)` (:355–407), `nowyZnacznik` (:978–1021, `bindPopup(() => dymekHtml(zamowienia.get(id)))`), `aktualizujZnacznik` (:1036–1060, przerysowuje dymek TYLKO gdy zmienił się klucz pinezki), `podepnijDymek(popup)` (:1155–1168), `onBlad` (:2003–2009), `zniszcz` (:2044–2096).
- `static/js/logistics-routes.js` — `renderujSelecty()` (:1247–1299), `bladZasobu` (:1503–1506), `zapewnijMapke()` (:2360–2402); nasłuch `logistics:flota-zmieniona` → `wczytajDostepnosc` (:3669–3674).
- `static/js/logistics-fleet.js` (505 linii) — `el(nazwa)` = `[data-lg-flota="…"]` (:43), `stan` (:54–60), `zapytanie()` (:116–138, `BladApi(message, status)`), `renderuj()` (:204–237, kierowcy :229–235), `wczytaj()` (:239–262, `/vehicles` + `/drivers`), `naKlik` (:444–456), `zniszcz` (:463–470), start (:476–504).
- `static/css/logistics.css` — `.lg-k-zaznacz` (:519), `.lg-k-stan` (:527), progi `@container lg-tabela (max-width: 860px)` (:1111–1127) i `(max-width: 760px)` (:1131–1135), dymek `.lg-dymek-*` (:2103–2226), `.lg-pozycje` (:2625–2630).
- `static/css/logistics-trasy.css` — `[hidden]` etapu 3 (:66–74), `.lg-filtr-trasy` (:96–133), przyciski nieaktywne `:is(…)` (:541–555), `.lg-ikona-przycisk` (:1386), Flota (:2017–2186), `@media (max-width: 900px)` (:2187–2209).

*Dashboard produkcji*: `modules/production/templates/components/dashboard-tab-content.html` („8 stanowisk” :122, szyna :139–145, bramka logistyki :273–282, koniec `.il-rail-wrap` :304), `modules/production/static/js/modules/dashboard-module.js` (`rysujSzyneProcesu` :487–543), `modules/production/static/css/production-panel.css` (`.il-rail-spine` :2665–2672, bramka :2679–2696, barwa :2756–2758), `modules/production/templates/panel/dashboard.html` (:13 CSS bez `?v=`, :345 `dashboard-module.js?v=20260410`). Liczbę daje `lista_logistyki.liczba_bez_sposobu()` w `dashboard_api.py:1001–1005` (bez zmian). **`logistics-pending` odświeża się dziś tylko przy renderze zakładki** — cykliczne `/dashboard-data` go nie niesie.

*Testy*: `tests/logistyka_fixtures.py` (`app`, `client`, `BASE`, `zamowienie(sposob, statusy, …, **kolumny)` — kod pocztowy zawsze `30-001`, `kierowca(imie, nazwisko, aktywny)`, `pojazd`, „dziś” tras zamrożone na 2026-09-26); testy UI czytają źródła (`_funkcja(js, nazwa)` = od `function nazwa(` do `\n    }\n`).

### Wersje plików (`?v=` w `tab_content.html` / `panel/dashboard.html`)

| Plik | Przed rundą | Task 2 | Task 4 | Task 5 | Task 6 |
|---|---|---|---|---|---|
| `css/logistics.css` | 20260925i | — | — | 20260928a | — |
| `css/logistics-trasy.css` | 20260926c | 20260928a | 20260928b | — | — |
| `js/logistics-map.js` (`data-skrypt-mapy`) | 20260926b | — | — | 20260928a | — |
| `js/logistics-routes.js` (`data-skrypt-trasy`) | 20260928b | 20260928c | — | 20260928d | — |
| `js/logistics.js` | 20260928a | — | 20260928b | 20260928c | — |
| `js/logistics-fleet.js` | 20260926a | 20260928a | — | — | — |
| `js/logistics-wojewodztwa.js` (nowy) | — | — | 20260928a | — | — |
| `js/modules/dashboard-module.js` | 20260410 | — | — | — | 20260928a |
| `css/production-panel.css` | (brak) | — | — | — | 20260928a |

Jeśli zastaniesz inną wartość niż w kolumnie „przed” — podbij do następnej wolnej litery i odnotuj w raporcie.

### Rozstrzygnięcia planu (kontroler może zmienić przed startem)

1. Zdjęcie/dodanie znacznika bez blokady tras; walidacja kierowcy w `_sprawdz_zasoby` czyta pracownika jak dziś (`query.get`) — obie kolejności „zapis trasy” vs „zdjęcie znacznika” kończą się stanem, który reguła 33 i tak dopuszcza.
2. `GET /drivers` niesie `trasy` (nazwy tras roboczych/zatwierdzonych kierowcy) — z nich potwierdzenie kosza; `POST/DELETE /drivers` zwracają też pełną listę `drivers`.
3. Kierowca trasy bez znacznika w wyborze: `disabled` + wybrany + „(nie jest już kierowcą)” — jak wyłączony pojazd (po zmianie nie da się wrócić).
4. Okno „Dodaj kierowcę”: każdy „Dodaj” zapisuje od razu, okno zostaje otwarte; kosz przez `window.confirm` (jak usunięcie trasy).
5. Opcje województw renderuje serwer z `wojewodztwa.py` (mapa raportów importowana leniwie). SQL bierze dwa pierwsze znaki kodu po usunięciu `-` i spacji, więc kod z literami z przodu („PL-35-310”) trafia do „Bez województwa” (mapa w Pythonie usunęłaby litery). Pusta wartość `?woj=` = brak filtra. Zamówienie zagraniczne nigdy nie trafia do województwa (opcje są rozłączne).
6. Panel województw rozmawia z listą zdarzeniem `logistics:wojewodztwa` (kolejność skryptów nie jest gwarantowana). „Zdejmij filtry” czyści też województwa.
7. Mapę na „Zamówienia” przełączają też „Pokaż wszystkie otwarte”, „Pokaż wszystkie etapy”, „Zdejmij filtry”, licznik „Bez lokalizacji” i „Wyczyść województwa” (zmieniają te same filtry); nie przełączają wyszukiwarka i „także zamknięte” (część wyszukiwania).
8. Select w dymku używa `ETYKIETY/SPOSOBY` mapy (już identycznych jak w liście) — zgodność przypina test porównujący oba pliki; blokady (wydane, anulowane) jak w wierszu, teksty przypięte testem.
9. `.lg-pozycje` (rozwinięty wiersz) dostaje wcięcie 66 px i 14 px z prawej, żeby zostać pod kolumną „Zamówienie” po poszerzeniu pierwszej kolumny.
10. `logistics-pending` zostaje (zawsze w DOM), stan zero/liczba przełącza klasa; `production-panel.css` dostaje pierwszy raz `?v=`.

---

## Mapa plików

**Nowe:** `migrations/2026-09-28-logistyka-kierowcy.sql`, `modules/production/logistics/wojewodztwa.py`, `modules/production/logistics/static/js/logistics-wojewodztwa.js`, testy `tests/test_logistyka_kierowcy.py`, `tests/test_logistyka_kierowcy_ui.py`, `tests/test_logistyka_wojewodztwa.py`, `tests/test_logistyka_wojewodztwa_ui.py`, `tests/test_logistyka_dymek_ui.py`, `tests/test_dashboard_logistyka_pasek.py`.

**Modyfikowane:** `modules/production/models.py`, `modules/production/logistics/services/fleet.py`, `…/services/routes.py`, `…/services/lista.py`, `…/routers/trasy_api.py`, `…/routers/panel_api.py`, `…/templates/logistics/tab_content.html`, `…/static/js/logistics.js`, `…/static/js/logistics-map.js`, `…/static/js/logistics-routes.js`, `…/static/js/logistics-fleet.js`, `…/static/css/logistics.css`, `…/static/css/logistics-trasy.css`, `modules/production/templates/components/dashboard-tab-content.html`, `modules/production/templates/panel/dashboard.html`, `modules/production/static/js/modules/dashboard-module.js`, `modules/production/static/css/production-panel.css`, `tests/logistyka_fixtures.py`, `tests/test_logistyka_trasy_schemat.py`, `tests/test_logistyka_panel_api.py`, `tests/test_logistyka_trasy_ui.py`, `tests/test_dashboard_krawedzie.py`, `tests/test_logistyka_sprzatanie.py`.

**Środowisko** (Git Bash): `cd /c/Users/Grafik/Documents/woodpower-crm/.claude/worktrees/logistyka-etap-3-trasy`; w krokach `PYTEST <ścieżki>` = `docker compose -p logistyka3 run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider`.

---

### Task 1: Kierowcy — dane, serwis, API, walidacja tras

**Files:**
- Create: `migrations/2026-09-28-logistyka-kierowcy.sql`
- Modify: `modules/production/models.py` (`ProductionWorker`, po `is_active` :1395)
- Modify: `modules/production/logistics/services/fleet.py` (zastąp `kierowcy()` :123–127 i dopisz funkcje)
- Modify: `modules/production/logistics/services/routes.py` (`dostepnosc` :296–303, `_sprawdz_zasoby` :306–347)
- Modify: `modules/production/logistics/routers/trasy_api.py` (`GET /drivers` :309–312 + nowe trasy)
- Modify: `tests/logistyka_fixtures.py` (`kierowca()` ze znacznikiem, nowy `pracownik()`)
- Modify: `tests/test_logistyka_trasy_schemat.py`, `tests/test_logistyka_panel_api.py` (`TRASY_PANELU` :224)
- Test: `tests/test_logistyka_kierowcy.py`

**Interfaces:**
- Consumes: `LogistykaBlad`, `STATUSY_TRASY_AKTYWNE`, `Route`, `_cialo`, `_odmowa`, `guard`.
- Produces:
  - `ProductionWorker.is_driver` (Boolean NOT NULL, domyślnie False).
  - `fleet.nazwa_pracownika(p) -> str`; `fleet.kierowcy() -> [{id, nazwa}]` (aktywni ze znacznikiem); `fleet.kandydaci_na_kierowcow() -> [{id, nazwa}]` (aktywni bez znacznika); `fleet.trasy_kierowcow(ids) -> {worker_id: [nazwa trasy]}`; `fleet.kierowcy_z_trasami() -> [{id, nazwa, trasy}]`; `fleet.serializuj_kierowce(p) -> {id, nazwa, is_driver, trasy}`; `fleet.dodaj_kierowce(worker_id)` / `fleet.usun_kierowce(worker_id)` → `ProductionWorker` (422 zły identyfikator, 404 brak, 409 nieaktywny przy dodaniu; nie commitują).
  - `routes.dostepnosc(...)['kierowcy']` — kierowcy + (tylko przy `pomin_route_id`) aktywny kierowca tej trasy bez znacznika z `nie_kierowca: True`; wpis: `{id, nazwa, [nie_kierowca], zajety, trasa}`.
  - `routes._sprawdz_zasoby`: nowy/zmieniony kierowca bez znacznika → `LogistykaBlad(„<Imię Nazwisko> nie jest kierowcą. …”, 409)`.
  - API: `GET /drivers` → `{success, drivers: [{id, nazwa, trasy}]}`; `GET /drivers/candidates` → `{success, candidates: [{id, nazwa}]}`; `POST /drivers` `{worker_id}` → 200 `{success, driver, drivers}`; `DELETE /drivers/<int:worker_id>` → 200 `{success, driver, drivers}`.
  - Fixtures: `kierowca(imie='Jan', nazwisko=None, aktywny=True)` ze znacznikiem; `pracownik(imie='Piotr', nazwisko=None, aktywny=True)` bez znacznika.

- [ ] **Step 1: Fixtures**

W `tests/logistyka_fixtures.py` zastąp `kierowca()` i dopisz `pracownik()`:
```python
def kierowca(imie='Jan', nazwisko=None, aktywny=True):
    """Kierowca trasy: pracownik produkcji ZE znacznikiem is_driver (runda 2 — tylko taki
    jest w wyborze kierowcy i przechodzi walidację nowego przypisania do trasy)."""
    k = ProductionWorker(first_name=imie, last_name=nazwisko or 'Kierowca %d' % next(_licznik),
                         is_active=aktywny, is_driver=True)
    db.session.add(k)
    db.session.commit()
    return k


def pracownik(imie='Piotr', nazwisko=None, aktywny=True):
    """Pracownik produkcji BEZ znacznika kierowcy (kandydat na kierowcę)."""
    p = ProductionWorker(first_name=imie, last_name=nazwisko or 'Pracownik %d' % next(_licznik),
                         is_active=aktywny, is_driver=False)
    db.session.add(p)
    db.session.commit()
    return p
```

- [ ] **Step 2: Testy (mają paść)**

Dopisz do `tests/test_logistyka_trasy_schemat.py` (na górze dołóż `import re` i `from modules.production.models import ProductionWorker`):
```python
MIGRACJA_KIEROWCOW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  'migrations', '2026-09-28-logistyka-kierowcy.sql')


def test_pracownik_domyslnie_nie_jest_kierowca(app):
    with app.app_context():
        p = ProductionWorker(first_name='Ala', last_name='Nowa')
        db.session.add(p)
        db.session.commit()
        assert p.is_driver is False


def test_migracja_kierowcow():
    sql = open(MIGRACJA_KIEROWCOW, encoding='utf-8').read()
    assert "TABLE_NAME = 'prod_workers'" in sql and "COLUMN_NAME = 'is_driver'" in sql
    assert 'ADD COLUMN is_driver TINYINT(1) NOT NULL DEFAULT 0' in sql
    assert 'PREPARE krok FROM @sql' in sql and 'DELIMITER' not in sql
    assert not re.search(r'^\s*ALTER TABLE', sql, re.MULTILINE)   # ALTER tylko w PREPARE
```

W `tests/test_logistyka_panel_api.py` dopisz na końcu listy `TRASY_PANELU` (przed `]`):
```python
    # Runda 2 (spec 2.6): kierowcy tras pod tą samą kontrolą dostępu.
    ('get', '/drivers'),
    ('get', '/drivers/candidates'),
    ('post', '/drivers'),
    ('delete', '/drivers/1'),
```

`tests/test_logistyka_kierowcy.py`:
```python
# -*- coding: utf-8 -*-
"""Runda 2 (spec 2.6): kierowcy tras jako wyróżnieni pracownicy (prod_workers.is_driver)."""
from datetime import date

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import fleet, routes
from modules.production.logistics.services.delivery import LogistykaBlad
from tests.logistyka_fixtures import BASE, app, client, kierowca, pracownik, zamowienie  # noqa: F401


def _trasa(nazwa='Kraków', od='2026-10-01', do=None, **dane):
    trasa = routes.utworz(dict(dane, name=nazwa, date_from=od, date_to=do or od))
    db.session.commit()
    return trasa


# ── Serwis ─────────────────────────────────────────────────────────────────

def test_kierowcy_i_kandydaci(app):
    with app.app_context():
        k = kierowca(imie='Adam', nazwisko='Nowak')
        kierowca(imie='Ex', nazwisko='Kierowca', aktywny=False)
        p = pracownik(imie='Piotr', nazwisko='Zwykły')
        pracownik(imie='Stary', nazwisko='Odszedł', aktywny=False)
        assert fleet.kierowcy() == [{'id': k.id, 'nazwa': 'Adam Nowak'}]
        assert fleet.kandydaci_na_kierowcow() == [{'id': p.id, 'nazwa': 'Piotr Zwykły'}]


def test_dodanie_i_zdjecie_znacznika_idempotentne(app):
    with app.app_context():
        p = pracownik()
        for _ in range(2):
            fleet.dodaj_kierowce(p.id)
            db.session.commit()
            assert p.is_driver is True
        assert [k['id'] for k in fleet.kierowcy()] == [p.id]
        for _ in range(2):
            fleet.usun_kierowce(str(p.id))
            db.session.commit()
            assert p.is_driver is False and p.is_active is True      # pracownik zostaje
        assert fleet.kierowcy() == []


def test_dodanie_nieistniejacego_i_nieaktywnego(app):
    with app.app_context():
        for funkcja in (fleet.dodaj_kierowce, fleet.usun_kierowce):
            with pytest.raises(LogistykaBlad) as e:
                funkcja(999999)
            assert e.value.status == 404
        p = pracownik(aktywny=False)
        with pytest.raises(LogistykaBlad) as e:
            fleet.dodaj_kierowce(p.id)
        assert e.value.status == 409 and p.is_driver is False


@pytest.mark.parametrize('wartosc', [None, '', 'abc', True, False, 1.0, 0, -3, '²', '9' * 20,
                                     10 ** 12, [1], {'id': 1}])
def test_zly_identyfikator_pracownika_422(app, wartosc):
    with app.app_context():
        with pytest.raises(LogistykaBlad) as e:
            fleet.dodaj_kierowce(wartosc)
        assert e.value.status == 422


def test_trasy_kierowcy_tylko_aktywne(app):
    with app.app_context():
        k = kierowca()
        _trasa('Robocza', od='2026-10-05', driver_worker_id=k.id)
        z = _trasa('Zatwierdzona', od='2026-10-01', driver_worker_id=k.id)
        w = _trasa('Wykonana', od='2026-10-10', driver_worker_id=k.id)
        z.status, w.status = 'zatwierdzona', 'wykonana'
        db.session.commit()
        assert fleet.trasy_kierowcow([k.id]) == {k.id: ['Zatwierdzona', 'Robocza']}
        assert fleet.kierowcy_z_trasami() == [{'id': k.id, 'nazwa': fleet.nazwa_pracownika(k),
                                              'trasy': ['Zatwierdzona', 'Robocza']}]


# ── Zapis trasy ────────────────────────────────────────────────────────────

def test_nowy_albo_zmieniony_kierowca_bez_znacznika_to_409(app):
    with app.app_context():
        p = pracownik(imie='Piotr', nazwisko='Zwykły')
        with pytest.raises(LogistykaBlad) as e:
            routes.utworz({'name': 'A', 'date_from': '2026-10-01', 'driver_worker_id': p.id})
        assert e.value.status == 409 and 'Piotr Zwykły nie jest kierowcą' in e.value.komunikat
        db.session.rollback()
        t = _trasa(driver_worker_id=kierowca().id)
        with pytest.raises(LogistykaBlad) as e:
            routes.edytuj(t, {'name': 'A', 'date_from': '2026-10-01', 'driver_worker_id': p.id})
        assert e.value.status == 409


def test_kierowca_bez_znacznika_zostaje_na_swojej_trasie(app):
    """Review Focus 2 (rozstrzygnięcie 33): zdjęcie znacznika nie psuje tras, na których
    kierowca już jest — edycja i przywrócenie przechodzą, wybór pokazuje go tylko w jego
    trasie (`nie_kierowca`), a po zmianie na innego kierowcę nie da się do niego wrócić."""
    with app.app_context():
        k = kierowca(imie='Adam', nazwisko='Nowak')
        inny = kierowca()
        t = _trasa('Kraków', od='2026-10-01', driver_worker_id=k.id)
        obca = _trasa('Rzeszów', od='2026-10-07', driver_worker_id=inny.id)
        w = _trasa('Tarnów', od='2026-10-03', driver_worker_id=k.id)
        a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
        routes.dodaj_przystanki(w, [a.id])
        routes.zatwierdz(w)
        routes.wykonaj(w, [a.id])
        db.session.commit()

        fleet.usun_kierowce(k.id)
        db.session.commit()

        routes.edytuj(t, {'name': 'Kraków 2', 'date_from': '2026-10-01', 'driver_worker_id': k.id})
        db.session.commit()
        assert (t.name, t.driver_worker_id) == ('Kraków 2', k.id)
        routes.przywroc(w)
        db.session.commit()
        assert w.status == 'zatwierdzona'

        dzien = date(2026, 10, 1)
        assert {'id': k.id, 'nazwa': 'Adam Nowak', 'nie_kierowca': True, 'zajety': False,
                'trasa': None} in routes.dostepnosc(dzien, dzien, t.id)['kierowcy']
        for route_id in (None, obca.id):                  # nowa trasa i cudza trasa — bez niego
            assert k.id not in [x['id'] for x in routes.dostepnosc(dzien, dzien, route_id)['kierowcy']]

        routes.edytuj(t, {'name': 'Kraków 2', 'date_from': '2026-10-01', 'driver_worker_id': inny.id})
        db.session.commit()
        with pytest.raises(LogistykaBlad) as e:
            routes.edytuj(t, {'name': 'Kraków 2', 'date_from': '2026-10-01', 'driver_worker_id': k.id})
        assert e.value.status == 409


def test_dostepnosc_bez_nieaktywnego_kierowcy_trasy(app):
    """Nieaktywnego nie dokładamy — UI pokazuje go z danych trasy jako „(nieaktywny)”."""
    with app.app_context():
        k = kierowca()
        t = _trasa(driver_worker_id=k.id)
        k.is_active, k.is_driver = False, False
        db.session.commit()
        dzien = date(2026, 10, 1)
        assert routes.dostepnosc(dzien, dzien, t.id)['kierowcy'] == []


# ── API ────────────────────────────────────────────────────────────────────

def test_api_kandydaci_dodanie_i_zdjecie(client, app):
    with app.app_context():
        pid = pracownik(imie='Piotr', nazwisko='Zwykły').id
    assert client.get(BASE + '/drivers').get_json()['drivers'] == []
    assert client.get(BASE + '/drivers/candidates').get_json()['candidates'] == \
        [{'id': pid, 'nazwa': 'Piotr Zwykły'}]
    for _ in range(2):                                           # idempotentne
        r = client.post(BASE + '/drivers', json={'worker_id': pid})
        assert r.status_code == 200
        assert r.get_json()['drivers'] == [{'id': pid, 'nazwa': 'Piotr Zwykły', 'trasy': []}]
    assert client.get(BASE + '/drivers/candidates').get_json()['candidates'] == []
    for _ in range(2):
        r = client.delete(BASE + '/drivers/%d' % pid)
        assert r.status_code == 200 and r.get_json()['drivers'] == []
    assert r.get_json()['driver'] == {'id': pid, 'nazwa': 'Piotr Zwykły', 'is_driver': False,
                                      'trasy': []}


@pytest.mark.parametrize('cialo, status', [
    ({'worker_id': 999999}, 404), ({}, 422), ({'worker_id': 'abc'}, 422),
    ({'worker_id': True}, 422), ([1, 2], 422),
])
def test_api_dodanie_bledy(client, cialo, status):
    r = client.post(BASE + '/drivers', json=cialo)
    assert r.status_code == status
    assert r.get_json()['success'] is False and r.get_json()['error']


def test_api_nieaktywny_zle_cialo_i_brak(client, app):
    with app.app_context():
        pid = pracownik(aktywny=False).id
    assert client.post(BASE + '/drivers', json={'worker_id': pid}).status_code == 409
    assert client.post(BASE + '/drivers', data='nie-json',
                       content_type='application/json').status_code == 422
    assert client.delete(BASE + '/drivers/999999').status_code == 404


def test_api_trasy_kierowcy_i_zapis_trasy(client, app):
    with app.app_context():
        kid = kierowca(imie='Adam', nazwisko='Nowak').id
        pid = pracownik().id
    rid = client.post(BASE + '/routes', json={'name': 'Kraków', 'date_from': '2026-10-01',
                                              'driver_worker_id': kid}).get_json()['route']['id']
    assert client.get(BASE + '/drivers').get_json()['drivers'][0]['trasy'] == ['Kraków']
    r = client.post(BASE + '/routes', json={'name': 'B', 'date_from': '2026-10-05',
                                            'driver_worker_id': pid})
    assert r.status_code == 409 and 'nie jest kierowcą' in r.get_json()['error']
    assert client.delete(BASE + '/drivers/%d' % kid).get_json()['driver']['trasy'] == ['Kraków']
    d = client.get(BASE + '/availability?date_from=2026-10-01&route_id=%d' % rid).get_json()
    assert [k for k in d['kierowcy'] if k['id'] == kid][0]['nie_kierowca'] is True
    d = client.get(BASE + '/availability?date_from=2026-10-01').get_json()
    assert kid not in [k['id'] for k in d['kierowcy']]
    assert client.put(BASE + '/routes/%d' % rid, json={'name': 'Kraków 2', 'date_from': '2026-10-01',
                                                       'driver_worker_id': kid}).status_code == 200
```

- [ ] **Step 3: Uruchom — mają paść**

Run: `PYTEST tests/test_logistyka_kierowcy.py tests/test_logistyka_trasy_schemat.py tests/test_logistyka_panel_api.py`
Expected: FAIL (brak kolumny `is_driver` — `TypeError` przy `ProductionWorker(..., is_driver=…)`, brak migracji, 404/405 nowych tras).

- [ ] **Step 4: Migracja i model**

`migrations/2026-09-28-logistyka-kierowcy.sql`:
```sql
-- Logistyka równoległa, runda 2 (spec 2026-09-28-logistyka-runda-2-uwagi-design.md, pkt 2.6):
-- kierowca trasy = wyróżniony pracownik produkcji (prod_workers.is_driver). Na start nikt
-- nie jest kierowcą — logistyk dodaje kierowców w zakładce Logistyka, podzakładka Flota.
-- Idempotentna (runner wykonuje katalog przy każdym deployu i przy starcie aplikacji).
-- ALTER ADD COLUMN nie ma IF NOT EXISTS, więc warunek z information_schema przez
-- PREPARE/EXECUTE (bez DELIMITER), jak w 2026-09-26-logistyka-zmiana-adresu.sql.

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_workers'
               AND COLUMN_NAME = 'is_driver');
SET @sql = IF(@brak, 'ALTER TABLE prod_workers ADD COLUMN is_driver TINYINT(1) NOT NULL DEFAULT 0',
              'SELECT "is_driver juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;
```

W `ProductionWorker` (`modules/production/models.py`), zaraz po linii `is_active = …` (:1395):
```python
    # Logistyka (runda 2): kierowca tras — ustawiany wyłącznie w zakładce Logistyka → Flota
    # (zakładka Pracownicy go nie zna). Migracja 2026-09-28-logistyka-kierowcy.sql.
    is_driver = Column(Boolean, nullable=False, default=False)
```

- [ ] **Step 5: Serwis floty**

W `modules/production/logistics/services/fleet.py` zmień docstring modułu na `"""Flota pojazdów i kierowcy tras (pracownicy produkcji ze znacznikiem is_driver) — spec 8.1, runda 2 (2.6)."""` i zastąp `def kierowcy()` (:123–127) tym blokiem:
```python
def nazwa_pracownika(p):
    return u'{} {}'.format(p.first_name, p.last_name).strip()


def _pracownicy(kierowca):
    """Aktywni pracownicy produkcji ze znacznikiem kierowcy (True) albo bez niego (False)."""
    return (ProductionWorker.query
            .filter(ProductionWorker.is_active.is_(True), ProductionWorker.is_driver.is_(kierowca))
            .order_by(ProductionWorker.sort_order, ProductionWorker.last_name).all())


def kierowcy():
    """
    (runda 2, spec 2.6) Kierowcy tras: AKTYWNI pracownicy ze znacznikiem is_driver (do rundy 2
    — wszyscy aktywni). Kształt bez zmian, [{id, nazwa}] — używają go GET /drivers
    (przez kierowcy_z_trasami) i routes.dostepnosc (wybór kierowcy w edytorze trasy).
    """
    return [{'id': p.id, 'nazwa': nazwa_pracownika(p)} for p in _pracownicy(True)]


def kandydaci_na_kierowcow():
    """Okno „Dodaj kierowcę” we Flocie: aktywni pracownicy BEZ znacznika."""
    return [{'id': p.id, 'nazwa': nazwa_pracownika(p)} for p in _pracownicy(False)]


def trasy_kierowcow(ids):
    """
    {worker_id: [nazwa trasy, …]} — trasy robocze i zatwierdzone (po dacie od, potem id),
    na których pracownik jest kierowcą. Potwierdzenie zdjęcia znacznika podaje je z nazwy:
    kierowca na nich zostaje (spec 2.6, rozstrzygnięcie 33).
    """
    if not ids:
        return {}
    wynik = {}
    for worker_id, nazwa in (db.session.query(Route.driver_worker_id, Route.name)
                             .filter(Route.driver_worker_id.in_(list(ids)),
                                     Route.status.in_(STATUSY_TRASY_AKTYWNE))
                             .order_by(Route.date_from, Route.id).all()):
        wynik.setdefault(worker_id, []).append(nazwa)
    return wynik


def kierowcy_z_trasami():
    """GET /drivers: kierowcy z nazwami ich aktywnych tras — dwa zapytania na całą listę."""
    lista = kierowcy()
    trasy = trasy_kierowcow([k['id'] for k in lista])
    return [dict(k, trasy=trasy.get(k['id'], [])) for k in lista]


def serializuj_kierowce(p):
    return {'id': p.id, 'nazwa': nazwa_pracownika(p), 'is_driver': bool(p.is_driver),
            'trasy': trasy_kierowcow([p.id]).get(p.id, [])}


def _id_pracownika(wartosc):
    """
    Identyfikator pracownika z ciała żądania: int (nie bool — `True` to w Pythonie 1) albo
    tekst z cyframi ASCII (_ID_RE), zakres 1…999 999 999. Wszystko inne → 422; nigdy gołego
    int() na nieznanym typie (wzór: routes._id).
    """
    liczba = None
    if isinstance(wartosc, int) and not isinstance(wartosc, bool):
        liczba = wartosc
    elif isinstance(wartosc, str) and _ID_RE.fullmatch(wartosc.strip()):
        liczba = int(wartosc.strip())
    if liczba is None or not 0 < liczba < 10 ** 9:
        raise LogistykaBlad(u'Wybierz pracownika z listy.', status=422)
    return liczba


def _pracownik(worker_id):
    pracownik = ProductionWorker.query.get(_id_pracownika(worker_id))
    if pracownik is None:
        raise LogistykaBlad(u'Nie ma takiego pracownika.', status=404)
    return pracownik


def dodaj_kierowce(worker_id):
    """
    (runda 2, spec 2.6) Znacznik kierowcy na aktywnym pracowniku. Idempotentne. 404 — nie ma
    pracownika, 409 — pracownik nieaktywny. To NIE jest zapis trasy: bez routes.zablokuj_trasy();
    trasy sprawdzają kierowcę przy własnym zapisie (_sprawdz_zasoby). Nie commituje.
    """
    pracownik = _pracownik(worker_id)
    if not pracownik.is_active:
        raise LogistykaBlad(u'{} nie jest już aktywnym pracownikiem — nie może zostać kierowcą.'.format(
            nazwa_pracownika(pracownik)), status=409)
    pracownik.is_driver = True
    db.session.flush()
    return pracownik


def usun_kierowce(worker_id):
    """
    Zdjęcie znacznika: pracownik zostaje w systemie, a na trasach, na których już jest
    kierowcą, zostaje (routes._sprawdz_zasoby przepuszcza niezmienionego kierowcę —
    rozstrzygnięcie 33). Idempotentne; 404 — nie ma pracownika. Bez blokady tras. Nie commituje.
    """
    pracownik = _pracownik(worker_id)
    pracownik.is_driver = False
    db.session.flush()
    return pracownik
```

- [ ] **Step 6: Trasy — dostępność i walidacja kierowcy**

W `modules/production/logistics/services/routes.py` zastąp `dostepnosc` (:296–303):
```python
def dostepnosc(date_from, date_to, pomin_route_id=None):
    z = zajetosc(date_from, date_to, pomin_route_id)   # podgląd UI — zwykły odczyt wystarczy
    kierowcy = fleet.kierowcy()
    # (runda 2, spec 2.6) Kierowca edytowanej trasy, któremu zdjęto znacznik, zostaje na niej
    # (rozstrzygnięcie 33) — w wyborze TEJ trasy jest widoczny z `nie_kierowca: True` (UI:
    # „(nie jest już kierowcą)”). Nieaktywnego nie dokładamy: UI pokazuje go z danych trasy
    # jako „(nieaktywny)”, jak dotąd. W nowej i w cudzej trasie go nie ma.
    obecny = _kierowca_trasy(pomin_route_id)
    if obecny is not None and obecny.is_active and not obecny.is_driver:
        kierowcy.append({'id': obecny.id, 'nazwa': fleet.nazwa_pracownika(obecny),
                         'nie_kierowca': True})
    return {
        'pojazdy': [dict(p, zajety=p['id'] in z['pojazdy'], trasa=z['pojazdy'].get(p['id']))
                    for p in fleet.lista_pojazdow(tylko_aktywne=True)],
        'kierowcy': [dict(k, zajety=k['id'] in z['kierowcy'], trasa=z['kierowcy'].get(k['id']))
                     for k in kierowcy],
    }


def _kierowca_trasy(route_id):
    if not route_id:
        return None
    trasa = Route.query.get(route_id)
    return trasa.driver if trasa is not None else None
```

W `_sprawdz_zasoby` dopisz w docstringu zdanie: `(runda 2) Kierowca nowego albo zmienionego przypisania musi mieć znacznik is_driver (409); niezmieniony kierowca trasy przechodzi i bez niego.` i zastąp blok `if driver_id:` (:335–338):
```python
    if driver_id:
        kierowca = ProductionWorker.query.get(driver_id)
        if kierowca is None or (not kierowca.is_active and driver_id != obecny_kierowca):
            raise LogistykaBlad(u'Nie ma takiego aktywnego kierowcy.', status=422)
        # (runda 2, spec 2.6) Kierowcą NOWEGO albo ZMIENIONEGO przypisania może być tylko
        # pracownik ze znacznikiem (Flota → Kierowcy). Niezmieniony kierowca trasy zostaje, choć
        # znacznik mu zdjęto — jak wyłączony pojazd (I3, rozstrzygnięcie 33). Odczyt zwykły, jak
        # dotąd: zdjęcie znacznika nie bierze blokady tras, a obie kolejności (zapis trasy przed
        # albo po zdjęciu) kończą się stanem, który ta reguła i tak dopuszcza.
        if not kierowca.is_driver and driver_id != obecny_kierowca:
            raise LogistykaBlad(u'{} nie jest kierowcą. Wybierz kogoś z listy kierowców albo dodaj '
                                u'tę osobę we Flocie.'.format(fleet.nazwa_pracownika(kierowca)),
                                status=409)
```

- [ ] **Step 7: API kierowców**

W `modules/production/logistics/routers/trasy_api.py` zastąp `drivers()` (:309–312) i dopisz pod nim:
```python
@logistics_panel_bp.route('/drivers', methods=['GET'])
@guard
def drivers():
    # (runda 2, spec 2.6) Tylko kierowcy (aktywni, is_driver) z nazwami tras roboczych
    # i zatwierdzonych — Flota podaje je w potwierdzeniu zdjęcia znacznika.
    return jsonify({'success': True, 'drivers': fleet.kierowcy_z_trasami()})


@logistics_panel_bp.route('/drivers/candidates', methods=['GET'])
@guard
def driver_candidates():
    return jsonify({'success': True, 'candidates': fleet.kandydaci_na_kierowcow()})


@logistics_panel_bp.route('/drivers', methods=['POST'])
@guard
def driver_add():
    """{worker_id} → {driver, drivers}. Znacznik kierowcy to nie zapis trasy — bez blokady tras."""
    try:
        pracownik = fleet.dodaj_kierowce(_cialo().get('worker_id'))
    except LogistykaBlad as e:
        return _odmowa(e)
    db.session.commit()
    return jsonify({'success': True, 'driver': fleet.serializuj_kierowce(pracownik),
                    'drivers': fleet.kierowcy_z_trasami()})


@logistics_panel_bp.route('/drivers/<int:worker_id>', methods=['DELETE'])
@guard
def driver_remove(worker_id):
    """Zdjęcie znacznika → {driver, drivers}; pracownik zostaje, na swoich trasach też."""
    try:
        pracownik = fleet.usun_kierowce(worker_id)
    except LogistykaBlad as e:
        return _odmowa(e)
    db.session.commit()
    return jsonify({'success': True, 'driver': fleet.serializuj_kierowce(pracownik),
                    'drivers': fleet.kierowcy_z_trasami()})
```

- [ ] **Step 8: Uruchom testy zadania**

Run: `PYTEST tests/test_logistyka_kierowcy.py tests/test_logistyka_trasy_schemat.py tests/test_logistyka_panel_api.py tests/test_logistyka_trasy_flota.py tests/test_logistyka_trasy_serwis.py tests/test_logistyka_trasy_api.py tests/test_migration_service.py`
Expected: PASS (stare testy tras przechodzą bez zmian — `kierowca()` ma teraz znacznik, a `kierowca(aktywny=False)` dalej daje 422 przed sprawdzeniem znacznika).

- [ ] **Step 9: Pełny pakiet**

Run: `docker compose -p logistyka3 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider`
Expected: 0 failed (≥ 4704 + nowe testy passed, 3 skipped).

- [ ] **Step 10: Commit**

```bash
git add migrations/2026-09-28-logistyka-kierowcy.sql tests/test_logistyka_kierowcy.py
git commit -m "feat(production): kierowcy tras jako wyroznieni pracownicy

Znacznik prod_workers.is_driver (migracja 2026-09-28-logistyka-kierowcy.sql),
API kierowcow i kandydatow, nowy albo zmieniony kierowca trasy tylko ze
znacznikiem; kierowca juz przypisany zostaje na trasie po zdjeciu znacznika.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- migrations/2026-09-28-logistyka-kierowcy.sql modules/production/models.py modules/production/logistics/services/fleet.py modules/production/logistics/services/routes.py modules/production/logistics/routers/trasy_api.py tests/logistyka_fixtures.py tests/test_logistyka_kierowcy.py tests/test_logistyka_trasy_schemat.py tests/test_logistyka_panel_api.py
```

---

### Task 2: Kierowcy — UI Floty i wybór kierowcy w trasie (skill `frontend-design`)

**REQUIRED:** przed HTML/CSS/JS wywołaj `frontend-design:frontend-design`. To rozbudowa podzakładki Flota (etap 3), nie nowy projekt: `lg-przycisk`, `lg-przycisk--glowny`, `lg-ikona-przycisk`, `<dialog class="lg-dialog">` (wzór: okno pojazdu `tab_content.html:556–575`), komunikaty przez `window.LogisticsTab.komunikat` (w `logistics-fleet.js` funkcja `komunikat(typ, tresc, opcje)` :87). Każdy tekst z API przez `esc()`.

**Files:**
- Modify: `modules/production/logistics/templates/logistics/tab_content.html` (sekcja kierowców :462–469, nowe okno po oknie pojazdu :575, `?v=` :19, :185, :645)
- Modify: `modules/production/logistics/static/js/logistics-fleet.js` (nagłówek :10–16, stałe DOM :43–53, `stan` :54–60, `renderuj` :229–235, `naKlik` :444–456, `zniszcz` :463–470, start :476–504)
- Modify: `modules/production/logistics/static/js/logistics-routes.js` (nagłówek :34, `renderujSelecty` :1271–1283, `bladZasobu` :1503–1506)
- Modify: `modules/production/logistics/static/css/logistics-trasy.css` (`[hidden]` :66–74, `:is(…)` :541–555, Flota :2139–2180, `@media` :2187–2209)
- Modify: `tests/test_logistyka_trasy_ui.py` (:357 — liczba tekstów „Zostaje na tej trasie…” 2 → 3)
- Test: `tests/test_logistyka_kierowcy_ui.py`

**Interfaces:**
- Consumes (Task 1): `GET /drivers` → `drivers: [{id, nazwa, trasy}]`; `GET /drivers/candidates` → `candidates: [{id, nazwa}]`; `POST /drivers {worker_id}` / `DELETE /drivers/<id>` → `{driver: {id, nazwa, is_driver, trasy}, drivers}`; `GET /availability` → `kierowcy[i].nie_kierowca`; odmowa zapisu trasy z tekstem zawierającym „nie jest kierowcą” (409).
- Produces: `[data-lg-flota-akcja="dodaj-kierowce"]`, okno `dialog[data-lg="kierowca-dialog"]` (pola `data-lg-flota="kandydaci-q|kandydaci|kandydaci-stan|kierowca-blad"`), wiersz kierowcy `li.lg-kierowca[data-kierowca-id]` z `[data-lg-flota-akcja="usun-kierowce"]`; zdarzenie `logistics:flota-zmieniona` po każdej zmianie kierowców.

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_kierowcy_ui.py`:
```python
# -*- coding: utf-8 -*-
"""Runda 2 (spec 2.6), interfejs: kierowcy we Flocie i wybór kierowcy w edytorze trasy."""
import os
import re

from tests.logistyka_fixtures import BASE, app, client  # noqa: F401

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'modules', 'production', 'logistics')


def _plik(*sciezka):
    return open(os.path.join(LOG, *sciezka), encoding='utf-8').read()


def _funkcja(js, nazwa):
    """Treść funkcji z IIFE (wcięcie 4 spacje) — od nagłówka do zamykającej klamry."""
    start = js.index('function ' + nazwa + '(')
    return js[start:js.index('\n    }\n', start)]


def _wersja(html, plik):
    m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
    assert m, plik
    return m.group(1)


def test_panel_kierowcow_we_flocie():
    html = _plik('templates', 'logistics', 'tab_content.html')
    sekcja = html[html.index('class="lg-flota-kierowcy"'):]
    sekcja = sekcja[:sekcja.index('</section>')]
    assert '>Kierowcy</h2>' in sekcja
    # „Dodaj kierowcę” nad listą.
    assert sekcja.index('data-lg-flota-akcja="dodaj-kierowce"') < sekcja.index('data-lg-flota="kierowcy"')
    assert 'każdy aktywny pracownik' not in html
    flota = _plik('static', 'js', 'logistics-fleet.js')
    wiersz = _funkcja(flota, 'kierowcaHtml')
    assert 'fa-trash-can' in wiersz and 'data-lg-flota-akcja="usun-kierowce"' in wiersz
    assert 'lg-kierowca-usun' in wiersz and "odmiana(trasy.length, ['trasa', 'trasy', 'tras'])" in wiersz
    assert 'Dodaj kierowców spośród pracowników.' in _funkcja(flota, 'renderujKierowcow')
    assert 'renderujKierowcow();' in _funkcja(flota, 'renderuj')
    css = _plik('static', 'css', 'logistics-trasy.css')
    assert '.logistics-tab .lg-kierowca-usun {' in css


def test_okno_dodawania_kierowcy():
    html = _plik('templates', 'logistics', 'tab_content.html')
    start = html.index('data-lg="kierowca-dialog"')
    znacznik = html[html.rindex('<dialog', 0, start):html.index('>', start)]
    assert 'class="lg-dialog lg-dialog--kierowca"' in znacznik and 'aria-labelledby=' in znacznik
    okno = html[start:html.index('</dialog>', start)]
    for fraza in ('data-lg-flota="kandydaci-q"', 'type="search"', 'data-lg-flota="kandydaci"',
                  'data-lg-flota="kandydaci-stan"', 'id="lg-kierowca-blad"', 'data-lg-flota-akcja="kierowca-zamknij"'):
        assert fraza in okno, fraza
    flota = _plik('static', 'js', 'logistics-fleet.js')
    assert "zapytanie('/drivers/candidates'" in _funkcja(flota, 'wczytajKandydatow')
    dodaj = _funkcja(flota, 'dodajKierowce')
    assert "zapytanie('/drivers', { metoda: 'POST', dane: { worker_id: id } })" in dodaj
    assert 'przyjmijKierowcow(odp.drivers)' in dodaj
    assert 'bezOgonkow(k.nazwa).includes(q)' in _funkcja(flota, 'renderujKandydatow')
    assert "new CustomEvent('logistics:flota-zmieniona'" in _funkcja(flota, 'przyjmijKierowcow')
    css = _plik('static', 'css', 'logistics-trasy.css')
    assert '.logistics-tab .lg-dialog--kierowca [hidden]' in css


def test_zdjecie_kierowcy_z_potwierdzeniem_tras():
    flota = _plik('static', 'js', 'logistics-fleet.js')
    usun = _funkcja(flota, 'usunKierowce')
    assert 'window.confirm(potwierdzenieUsuniecia(k))' in usun and "metoda: 'DELETE'" in usun
    assert usun.index('window.confirm(') < usun.index("metoda: 'DELETE'")
    potwierdz = _funkcja(flota, 'potwierdzenieUsuniecia')
    assert 'k.trasy' in potwierdz and 'dalej będzie kierowcą' in potwierdz


def test_wybor_kierowcy_trasy():
    trasy = _plik('static', 'js', 'logistics-routes.js')
    selecty = _funkcja(trasy, 'renderujSelecty')
    assert "' (nie jest już kierowcą)'" in selecty
    assert '!!k.zajety || !!k.nie_kierowca' in selecty          # widoczny, ale bez ponownego wyboru
    assert 'kierowca && kierowca.nie_kierowca' in selecty
    blad = trasy[trasy.index('const bladZasobu'):]
    assert 'nie jest kierowcą' in blad[:blad.index(';\n')]


def test_zakladka_renderuje_sie_z_oknem_kierowcy(client):  # noqa: F811
    r = client.get(BASE + '/tab-content')
    assert r.status_code == 200 and 'data-lg="kierowca-dialog"' in r.get_data(as_text=True)


def test_wersje_podbite():
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert _wersja(html, 'js/logistics-fleet.js') != '20260926a'
    assert _wersja(html, 'js/logistics-routes.js') != '20260928b'
    assert _wersja(html, 'css/logistics-trasy.css') != '20260926c'
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_kierowcy_ui.py`
Expected: FAIL (brak okna, funkcji i klas).

- [ ] **Step 3: Szablon**

Sekcja kierowców (`tab_content.html:462–469`) — zamień na:
```html
      <section class="lg-flota-kierowcy" aria-labelledby="lg-kierowcy-tytul">
        <div class="lg-sekcja-naglowek">
          <h2 class="lg-sekcja-tytul" id="lg-kierowcy-tytul">Kierowcy</h2>
          <span class="lg-sekcja-opis" data-lg-flota="kierowcy-ile"></span>
          <button type="button" class="lg-przycisk lg-przycisk--glowny" data-lg-flota-akcja="dodaj-kierowce">
            <i class="fas fa-user-plus" aria-hidden="true"></i>Dodaj kierowcę
          </button>
        </div>
        <p class="lg-flota-opis">Tylko te osoby wybierzesz na kierowcę trasy. Usunięcie z listy nie usuwa pracownika.</p>
        <ul class="lg-kierowcy" data-lg-flota="kierowcy"></ul>
      </section>
```
Po oknie pojazdu (za `</dialog>` z :575, przed `</div>` korzenia) dodaj:
```html
  {# Runda 2 (spec 2.6): kierowca trasy spośród aktywnych pracowników bez znacznika;
     logistics-fleet.js. Każdy „Dodaj” zapisuje od razu, okno zostaje otwarte (na start
     logistyk dodaje kilku kierowców naraz). #}
  <dialog class="lg-dialog lg-dialog--kierowca" data-lg="kierowca-dialog" aria-labelledby="lg-kierowca-tytul">
    <form class="lg-dialog-form" data-lg-flota="kierowca-form" novalidate autocomplete="off">
      <h2 class="lg-dialog-tytul" id="lg-kierowca-tytul">Dodaj kierowcę</h2>
      <p class="lg-dialog-opis">Aktywni pracownicy produkcji, którzy nie są jeszcze kierowcami.</p>
      <label class="lg-szukaj lg-szukaj--kierowcy">
        <i class="fas fa-magnifying-glass" aria-hidden="true"></i>
        <input type="search" data-lg-flota="kandydaci-q" spellcheck="false" placeholder="Szukaj pracownika"
               aria-label="Szukaj pracownika po imieniu albo nazwisku">
      </label>
      <p class="lg-kandydaci-kierowcy-stan" data-lg-flota="kandydaci-stan" role="status"></p>
      <ul class="lg-kandydaci-kierowcy" data-lg-flota="kandydaci" aria-label="Pracownicy do dodania"></ul>
      <p class="lg-dialog-blad" id="lg-kierowca-blad" data-lg-flota="kierowca-blad" role="alert" hidden></p>
      <div class="lg-dialog-akcje">
        <button type="button" class="lg-przycisk" data-lg-flota-akcja="kierowca-zamknij">Zamknij</button>
      </div>
    </form>
  </dialog>
```
Wersje: `logistics-trasy.css?v=20260928a` (:19), `data-skrypt-trasy … logistics-routes.js?v=20260928c` (:185), `logistics-fleet.js?v=20260928a` (:645).

- [ ] **Step 4: `logistics-fleet.js`**

Nagłówek (:10–16) — zamień linię `GET {API}/drivers …` na:
```js
 *   GET    {API}/drivers                kierowcy (aktywni ze znacznikiem) z nazwami tras roboczych/zatwierdzonych
 *   GET    {API}/drivers/candidates     aktywni pracownicy bez znacznika — okno „Dodaj kierowcę”
 *   POST   {API}/drivers                {worker_id} → {driver, drivers}
 *   DELETE {API}/drivers/<id>           zdjęcie znacznika → {driver, drivers} (na swoich trasach zostaje)
```
i w akapicie „Zdarzenia” dopisz: `…oraz po każdej zmianie kierowców (runda 2).`

Pod `const zapiszBtn = el('zapisz');` (:52):
```js
    // Runda 2 (spec 2.6): okno „Dodaj kierowcę” (poza panelem Floty, jak okno pojazdu).
    const dialogKierowcy = root.querySelector('[data-lg="kierowca-dialog"]');
    const formKierowcy = el('kierowca-form');
    const kandydaciQ = el('kandydaci-q');
    const kandydaciEl = el('kandydaci');
    const kandydaciStanEl = el('kandydaci-stan');
    const bladKierowcyEl = el('kierowca-blad');
```
W `stan` (:54–60) dopisz pola:
```js
        kandydaci: null,               // okno „Dodaj kierowcę”: GET /drivers/candidates (null = w drodze)
        dodaniKierowcy: new Set(),     // id pracowników, dla których leci POST /drivers
        usuwaniKierowcy: new Set(),    // id kierowców, dla których leci DELETE /drivers/<id>
        ostatnioDodany: '',            // nazwa ostatnio dodanego — potwierdzenie w oknie
```
Pod `let zniszczona = false;` (:63): `let kontrolerKandydatow = null;` i `let powrotKierowcy = null;`.

W `renderuj()` zastąp blok `if (kierowcyEl) { … }` i linię `if (kierowcyIleEl) …` (:229–235) jednym wywołaniem `renderujKierowcow();`.

Przed sekcją `// ── Zdarzenia` (:442) wstaw:
```js
    // ── Kierowcy (runda 2, spec 2.6) ────────────────────────────────────────

    // „Łukasz” znajduje się po „lukasz” — wyszukiwarka bez ogonków i wielkości liter.
    function bezOgonkow(tekst) {
        return String(tekst || '').toLocaleLowerCase('pl').replace(/ł/g, 'l')
            .normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    }

    const listaTras = (trasy) => trasy.map((t) => '„' + t + '”').join(', ');

    function kierowcaHtml(k) {
        const usuwany = stan.usuwaniKierowcy.has(k.id);
        const trasy = Array.isArray(k.trasy) ? k.trasy : [];
        return '<li class="lg-kierowca' + (usuwany ? ' is-zapisywany' : '') + '" data-kierowca-id="' + esc(k.id) + '">' +
            '<i class="fas fa-user" aria-hidden="true"></i>' +
            '<span class="lg-kierowca-nazwa">' + esc(k.nazwa) + '</span>' +
            (trasy.length ? '<span class="lg-kierowca-trasy" title="' + esc('Na trasach: ' + trasy.join(', ')) + '">' +
                trasy.length + ' ' + odmiana(trasy.length, ['trasa', 'trasy', 'tras']) + '</span>' : '') +
            '<button type="button" class="lg-ikona-przycisk lg-kierowca-usun" data-lg-flota-akcja="usun-kierowce"' +
                (usuwany ? ' aria-disabled="true"' : '') +
                ' aria-label="' + esc('Usuń ' + k.nazwa + ' z kierowców') + '" title="Usuń z kierowców">' +
                '<i class="fas fa-trash-can" aria-hidden="true"></i></button>' +
            '</li>';
    }

    function renderujKierowcow() {
        if (!kierowcyEl) return;
        // Fokus na koszu przeżywa przerysowanie; po usunięciu — następny kosz albo „Dodaj kierowcę”.
        const a = document.activeElement;
        const li = a && kierowcyEl.contains(a) ? a.closest('[data-kierowca-id]') : null;
        const indeks = li ? Array.from(kierowcyEl.children).indexOf(li) : -1;
        kierowcyEl.innerHTML = !stan.wczytano ? ''
            : (stan.kierowcy.length ? stan.kierowcy.map(kierowcaHtml).join('')
                : '<li class="lg-kierowcy-pusto">Dodaj kierowców spośród pracowników.</li>');
        if (kierowcyIleEl) kierowcyIleEl.textContent = stan.wczytano ? String(stan.kierowcy.length) : '';
        if (!li) return;
        const cel = kierowcyEl.querySelector('[data-kierowca-id="' + li.getAttribute('data-kierowca-id') + '"] .lg-kierowca-usun') ||
            (kierowcyEl.children[Math.min(indeks, kierowcyEl.children.length - 1)] || { querySelector: () => null })
                .querySelector('.lg-kierowca-usun') ||
            panel.querySelector('[data-lg-flota-akcja="dodaj-kierowce"]');
        if (cel) cel.focus({ preventScroll: true });
    }

    function przyjmijKierowcow(lista) {
        if (Array.isArray(lista)) stan.kierowcy = lista;
        renderujKierowcow();
        // Otwarta trasa ma od razu aktualny wybór kierowcy (logistics-routes.js, dostępność).
        document.dispatchEvent(new CustomEvent('logistics:flota-zmieniona', { detail: { root: root } }));
    }

    function potwierdzenieUsuniecia(k) {
        const trasy = Array.isArray(k.trasy) ? k.trasy : [];
        return 'Usunąć „' + k.nazwa + '” z kierowców?\n' + (trasy.length
            ? 'Na ' + (trasy.length === 1 ? 'trasie ' : 'trasach ') + listaTras(trasy) +
                ' dalej będzie kierowcą — tam nic się nie zmieni. Do nowych tras nie będzie do wyboru.'
            : 'Pracownik zostaje w systemie, tylko nie będzie do wyboru w trasach.');
    }

    async function usunKierowce(id) {
        const k = stan.kierowcy.find((x) => x.id === id);
        if (!k || stan.usuwaniKierowcy.has(id)) return;
        if (!window.confirm(potwierdzenieUsuniecia(k))) return;
        stan.usuwaniKierowcy.add(id);
        renderujKierowcow();
        try {
            const odp = await zapytanie('/drivers/' + encodeURIComponent(id), { metoda: 'DELETE' });
            if (zniszczona) return;
            const zostaje = odp.driver && Array.isArray(odp.driver.trasy) ? odp.driver.trasy : [];
            stan.usuwaniKierowcy.delete(id);
            przyjmijKierowcow(odp.drivers);
            komunikat('info', '„' + k.nazwa + '” nie jest już kierowcą.' + (zostaje.length
                ? ' Zostaje na ' + (zostaje.length === 1 ? 'trasie ' : 'trasach ') + listaTras(zostaje) + '.' : ''),
                { klucz: 'kierowcy' });
        } catch (e) {
            if (zniszczona) return;
            const niepewna = niepewnaOdpowiedz(e);
            komunikat('blad', 'Nie usunięto „' + k.nazwa + '” z kierowców. ' + e.message +
                (niepewna ? ' Zmiana mogła się zapisać — odświeżamy listę kierowców.' : ''), { klucz: 'kierowcy' });
            if (niepewna) wczytaj();
        } finally {
            if (!zniszczona && stan.usuwaniKierowcy.delete(id)) renderujKierowcow();
        }
    }

    function pokazBladKierowcy(tekst) {
        if (!bladKierowcyEl) return;
        bladKierowcyEl.textContent = tekst || '';
        bladKierowcyEl.hidden = !tekst;
    }

    function kandydatHtml(k) {
        const dodawany = stan.dodaniKierowcy.has(k.id);
        return '<li class="lg-kandydat-kierowcy" data-pracownik-id="' + esc(k.id) + '">' +
            '<span class="lg-kandydat-kierowcy-nazwa">' + esc(k.nazwa) + '</span>' +
            '<button type="button" class="lg-przycisk" data-lg-flota-akcja="wybierz-kierowce"' +
                (dodawany ? ' aria-disabled="true"' : '') + ' aria-label="' + esc('Dodaj ' + k.nazwa + ' do kierowców') + '">' +
                '<i class="fas fa-plus" aria-hidden="true"></i>' + (dodawany ? 'Dodawanie…' : 'Dodaj') + '</button>' +
            '</li>';
    }

    function renderujKandydatow() {
        if (!kandydaciEl) return;
        const a = document.activeElement;
        const fokusLi = a && kandydaciEl.contains(a) ? a.closest('[data-pracownik-id]') : null;
        const indeks = fokusLi ? Array.from(kandydaciEl.children).indexOf(fokusLi) : -1;
        const fraza = kandydaciQ ? kandydaciQ.value.trim() : '';
        const q = bezOgonkow(fraza);
        const teksty = [];
        let html = '';
        if (stan.ostatnioDodany) teksty.push('Dodano „' + stan.ostatnioDodany + '” do kierowców.');
        if (stan.kandydaci === null) {
            teksty.push('Wczytywanie pracowników…');
        } else {
            const pasujacy = stan.kandydaci.filter((k) => !q || bezOgonkow(k.nazwa).includes(q));
            html = pasujacy.map(kandydatHtml).join('');
            if (!stan.kandydaci.length) teksty.push('Wszyscy aktywni pracownicy są już kierowcami.');
            else if (!pasujacy.length) teksty.push('Nikt nie pasuje do „' + fraza + '”.');
        }
        kandydaciEl.innerHTML = html;
        if (kandydaciStanEl) kandydaciStanEl.textContent = teksty.join(' ');
        if (!fokusLi) return;
        const id = fokusLi.getAttribute('data-pracownik-id');
        const przyciski = Array.from(kandydaciEl.querySelectorAll('button'));
        const cel = kandydaciEl.querySelector('[data-pracownik-id="' + id + '"] button') ||
            przyciski[Math.min(indeks, przyciski.length - 1)] || kandydaciQ;
        if (cel) cel.focus({ preventScroll: true });
    }

    async function wczytajKandydatow() {
        if (kontrolerKandydatow) kontrolerKandydatow.abort();
        const moj = new AbortController();
        kontrolerKandydatow = moj;
        stan.kandydaci = null;
        renderujKandydatow();
        try {
            const odp = await zapytanie('/drivers/candidates', { signal: moj.signal });
            if (zniszczona || moj !== kontrolerKandydatow) return;
            stan.kandydaci = Array.isArray(odp.candidates) ? odp.candidates : [];
        } catch (e) {
            if ((e && e.name === 'AbortError') || zniszczona || moj !== kontrolerKandydatow) return;
            stan.kandydaci = [];
            pokazBladKierowcy('Nie wczytano pracowników. ' + e.message);
        } finally {
            if (moj === kontrolerKandydatow) kontrolerKandydatow = null;
        }
        renderujKandydatow();
    }

    function otworzKierowcow(powrot) {
        if (!dialogKierowcy || dialogKierowcy.open) return;
        powrotKierowcy = powrot || null;
        stan.ostatnioDodany = '';
        pokazBladKierowcy('');
        if (kandydaciQ) kandydaciQ.value = '';
        dialogKierowcy.showModal();
        if (kandydaciQ) kandydaciQ.focus();
        wczytajKandydatow();
    }

    // Zamknięcie zawsze możliwe: każdy „Dodaj” to osobny zapis, który kończy się sam (lista
    // kierowców za oknem i tak dostanie wynik), więc nie polegamy na zdarzeniu `close`.
    function zamknijKierowcow() {
        if (kontrolerKandydatow) kontrolerKandydatow.abort();
        if (dialogKierowcy && dialogKierowcy.open) dialogKierowcy.close();
        const cel = powrotKierowcy && powrotKierowcy.isConnected ? powrotKierowcy
            : panel.querySelector('[data-lg-flota-akcja="dodaj-kierowce"]');
        powrotKierowcy = null;
        if (cel) cel.focus({ preventScroll: true });
    }

    async function dodajKierowce(id) {
        const k = (stan.kandydaci || []).find((x) => x.id === id);
        if (!k || stan.dodaniKierowcy.has(id)) return;
        stan.dodaniKierowcy.add(id);
        pokazBladKierowcy('');
        renderujKandydatow();
        try {
            const odp = await zapytanie('/drivers', { metoda: 'POST', dane: { worker_id: id } });
            if (zniszczona) return;
            stan.kandydaci = (stan.kandydaci || []).filter((x) => x.id !== id);
            stan.ostatnioDodany = k.nazwa;
            przyjmijKierowcow(odp.drivers);
            komunikat('ok', 'Dodano kierowcę „' + k.nazwa + '”.', { klucz: 'kierowcy' });
        } catch (e) {
            if (zniszczona) return;
            const tekst = 'Nie dodano „' + k.nazwa + '”. ' + e.message;
            if (dialogKierowcy && dialogKierowcy.open) pokazBladKierowcy(tekst);
            else komunikat('blad', tekst, { klucz: 'kierowcy' });
            // 404/409 (pracownik zniknął albo przestał być aktywny) albo niepewna odpowiedź — od nowa.
            if (e.status === 404 || e.status === 409 || niepewnaOdpowiedz(e)) {
                wczytaj();
                if (dialogKierowcy && dialogKierowcy.open) wczytajKandydatow();
            }
        } finally {
            if (!zniszczona) {
                stan.dodaniKierowcy.delete(id);
                renderujKandydatow();
            }
        }
    }
```
W `naKlik` (:444–456) dopisz na końcu łańcucha `else if`:
```js
        else if (akcja === 'dodaj-kierowce') otworzKierowcow(przycisk);
        else if (akcja === 'usun-kierowce') {
            const li = przycisk.closest('[data-kierowca-id]');
            if (li) usunKierowce(Number(li.getAttribute('data-kierowca-id')));
        }
```
W `zniszcz()` przed `if (window.LogisticsFleet === api)`:
```js
        if (kontrolerKandydatow) kontrolerKandydatow.abort();
        if (dialogKierowcy && dialogKierowcy.open) dialogKierowcy.close();
```
W starcie, za blokiem `if (dialog && form) { … }` (:478–500):
```js
    if (dialogKierowcy) {
        dialogKierowcy.addEventListener('click', (e) => {
            if (e.target === dialogKierowcy) {
                zamknijKierowcow();
                return;
            }
            const b = e.target.closest('[data-lg-flota-akcja]');
            if (!b || b.disabled || b.getAttribute('aria-disabled') === 'true') return;
            const akcja = b.getAttribute('data-lg-flota-akcja');
            if (akcja === 'kierowca-zamknij') {
                zamknijKierowcow();
            } else if (akcja === 'wybierz-kierowce') {
                const li = b.closest('[data-pracownik-id]');
                if (li) dodajKierowce(Number(li.getAttribute('data-pracownik-id')));
            }
        }, naSluch);
        dialogKierowcy.addEventListener('cancel', (e) => {
            e.preventDefault();
            zamknijKierowcow();
        }, naSluch);
        if (formKierowcy) formKierowcy.addEventListener('submit', (e) => e.preventDefault(), naSluch);
        if (kandydaciQ) kandydaciQ.addEventListener('input', renderujKandydatow, naSluch);
    }
```

- [ ] **Step 5: Wybór kierowcy w edytorze trasy (`logistics-routes.js`)**

Nagłówek :34 — dopisz po „zajęci z nazwą trasy”: `; kierowca tej trasy bez znacznika: nie_kierowca (runda 2)`.

W `renderujSelecty` zastąp pętlę kierowców i warunek uwagi (:1271–1283):
```js
            (d.kierowcy || []).forEach((k) => {
                // (runda 2, spec 2.6) Kierowca tej trasy, któremu we Flocie zdjęto znacznik: zostaje
                // wybrany (serwer przyjmuje niezmienionego), ale po zmianie nie wrócisz do niego.
                const dopisek = k.nie_kierowca ? ' (nie jest już kierowcą)'
                    : (k.zajety ? ' (zajęty — ' + (k.trasa || 'inna trasa') + ')' : '');
                kierowcy += opcjaHtml(k.id, k.nazwa + dopisek, !!k.zajety || !!k.nie_kierowca, String(k.id) === wK);
            });
            const kierowca = (d.kierowcy || []).find((k) => String(k.id) === wK);
            if (wK && !kierowca) {
                const znany = t && t.kierowca && String(t.kierowca.id) === wK ? t.kierowca : null;
                kierowcy += opcjaHtml(wK, (znany ? znany.nazwa : 'Kierowca nr ' + wK) + ' (nieaktywny)', true, true);
                uwagaK = 'Kierowca nie jest już aktywnym pracownikiem. Zostaje na tej trasie; po zmianie nie wybierzesz go ponownie.';
            } else if (kierowca && kierowca.nie_kierowca) {
                uwagaK = 'Nie jest już kierowcą (zmiana we Flocie). Zostaje na tej trasie; po zmianie nie wybierzesz go ponownie.';
            } else if (kierowca && kierowca.zajety) {
                uwagaK = 'Kierowca jest zajęty w tych dniach na trasie „' + (kierowca.trasa || 'inna trasa') +
                    '”. Wybierz innego albo zmień daty.';
            }
```
`bladZasobu` (:1503–1506):
```js
    // Odmowa dotycząca pojazdu albo kierowcy (services/routes.py, _sprawdz_zasoby: zajęty
    // w tych dniach, wyłączony z floty, nieaktywny, bez znacznika kierowcy — runda 2) —
    // tylko taki błąd kasuje udana dostępność.
    const bladZasobu = (e) => !!e && (e.status === 409 || e.status === 422) &&
        /zajęty|wyłączony z floty|aktywnego kierowcy|nie jest kierowcą/i.test(String(e.message || ''));
```
W `tests/test_logistyka_trasy_ui.py:357` zmień `== 2` na `== 3` i dopisz komentarz `# + runda 2: kierowca bez znacznika (spec 2.6)`.

- [ ] **Step 6: CSS (`logistics-trasy.css`)**

W regule `[hidden]` (:66–74) dopisz selektor `.logistics-tab .lg-dialog--kierowca [hidden],` (przed ostatnim z listy); w trzech regułach przycisków nieaktywnych (:541, :546, :551) rozszerz `:is(…)` o `.lg-dialog--kierowca`. Za regułą `.logistics-tab .lg-kierowcy .lg-kierowcy-pusto` (:2175–2178):
```css
/* ─── Kierowcy (runda 2, spec 2.6): „Dodaj kierowcę” w nagłówku, kosz w wierszu ─── */
.logistics-tab .lg-flota-kierowcy .lg-sekcja-naglowek .lg-przycisk--glowny { margin-left: auto; min-height: 32px; }
.logistics-tab .lg-kierowcy li.lg-kierowca { padding-right: 4px; }
.logistics-tab .lg-kierowca-nazwa { flex: 1 1 auto; min-width: 0; overflow-wrap: break-word; }
.logistics-tab .lg-kierowca-trasy {
    flex: none; padding: 0 6px; border: 1px solid var(--il-border, #c8cdd5); border-radius: 999px;
    font-size: 11px; color: var(--il-text-secondary, #7a8291); white-space: nowrap;
}
/* Kosz czerwony od razu (spec 2.6), jak „Usuń trasę” (lg-przycisk--niebezpieczny). */
.logistics-tab .lg-kierowca-usun { color: #b91c1c; }
.logistics-tab .lg-kierowca-usun:hover:not([aria-disabled="true"]) {
    border-color: var(--lg-niebezpieczny); background: rgba(220, 38, 38, 0.06); color: #b91c1c;
}
.logistics-tab .lg-kierowca.is-zapisywany { opacity: 0.6; }

/* Okno „Dodaj kierowcę”: wyszukiwarka i przewijana lista kandydatów. */
.logistics-tab .lg-dialog--kierowca .lg-szukaj--kierowcy { display: block; margin: 0; }
.logistics-tab .lg-kandydaci-kierowcy {
    max-height: min(360px, 50vh); overflow-y: auto; margin: 0; padding: 0; list-style: none;
    border: 1px solid var(--il-border, #c8cdd5); border-radius: var(--il-radius, 3px);
}
.logistics-tab .lg-kandydaci-kierowcy:empty,
.logistics-tab .lg-kandydaci-kierowcy-stan:empty { display: none; }
.logistics-tab .lg-kandydat-kierowcy {
    display: flex; align-items: center; gap: 8px; padding: 5px 6px 5px 10px; font-size: 13px;
    border-bottom: 1px solid var(--il-border-light, #e2e5ea);
}
.logistics-tab .lg-kandydat-kierowcy:last-child { border-bottom: 0; }
.logistics-tab .lg-kandydat-kierowcy-nazwa { flex: 1 1 auto; min-width: 0; }
.logistics-tab .lg-kandydat-kierowcy .lg-przycisk { padding: 3px 9px 4px; font-size: 12px; }
.logistics-tab .lg-kandydaci-kierowcy-stan { margin: 0; font-size: 12.5px; color: var(--il-text-secondary, #7a8291); }
```
(Zapis zwarty — przy wklejaniu rozpisz deklaracje po jednej w linii, jak reszta pliku.)
W `@media (max-width: 900px)` (:2187–2209) dopisz:
```css
    .logistics-tab .lg-flota-kierowcy .lg-sekcja-naglowek .lg-przycisk { min-height: 38px; }
    .logistics-tab .lg-kierowca-usun { width: 36px; height: 36px; }
    .logistics-tab .lg-kandydat-kierowcy .lg-przycisk { min-height: 34px; }
```
Wygląd dopracuj skillem `frontend-design` (bez zmiany klas i atrybutów przypiętych testem).

- [ ] **Step 7: Uruchom testy**

Run: `node --check modules/production/logistics/static/js/logistics-fleet.js && node --check modules/production/logistics/static/js/logistics-routes.js`
Expected: bez błędów.
Run: `PYTEST tests/test_logistyka_kierowcy_ui.py tests/test_logistyka_trasy_ui.py tests/test_logistyka_mapa_ui.py tests/test_logistyka_zakladka.py tests/test_logistyka_poprawki_panelu.py`
Expected: PASS.

- [ ] **Step 8: Pełny pakiet**

Run: `docker compose -p logistyka3 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider`
Expected: 0 failed.

- [ ] **Step 9: Commit**

```bash
git add tests/test_logistyka_kierowcy_ui.py
git commit -m "feat(production): kierowcy we Flocie i wybor kierowcy trasy sposrod kierowcow

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- modules/production/logistics/templates/logistics/tab_content.html modules/production/logistics/static/js/logistics-fleet.js modules/production/logistics/static/js/logistics-routes.js modules/production/logistics/static/css/logistics-trasy.css tests/test_logistyka_kierowcy_ui.py tests/test_logistyka_trasy_ui.py
```

Oględziny (kontroler, 5003): pusta lista z podpowiedzią, dodanie 2 kierowców z wyszukiwaniem („lukasz”), kosz kierowcy bez tras i z trasą (tekst potwierdzenia), trasa z kierowcą bez znacznika — „(nie jest już kierowcą)” i uwaga, zapis nowej trasy z pracownikiem spoza listy niemożliwy; 1440/1024/768.

---

### Task 3: Województwa — backend

**Files:**
- Create: `modules/production/logistics/wojewodztwa.py`
- Modify: `modules/production/logistics/services/lista.py` (import :9, `pobierz` :181–220)
- Modify: `modules/production/logistics/routers/panel_api.py` (import :18, `orders()` :78–97)
- Test: `tests/test_logistyka_wojewodztwa.py`

**Interfaces:**
- Consumes: `PostcodeToStateMapper` (import leniwy), `ProductionOrder.delivery_postcode`, `delivery_country_code`.
- Produces: `wojewodztwa.ZAGRANICA = 'zagranica'`, `BEZ_WOJEWODZTWA = 'bez_wojewodztwa'`, `POZOSTALE = (('zagranica', 'Zagranica'), ('bez_wojewodztwa', 'Bez województwa'))`; `wojewodztwa.wojewodztwa() -> tuple[(identyfikator, nazwa)]` (16), `opcje()` (18), `prefiksy(identyfikator) -> tuple[str]`, `nieznane(identyfikatory) -> list`, `warunek(identyfikatory)` (wyrażenie SQL, ValueError dla nieznanych/pustej listy); `lista.pobierz(..., woj=None)`; `GET /orders?woj=a&woj=b` (nieznany → 422 `{success: false, error: 'Nieznany filtr województwa.'}`, pusta wartość pomijana).

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_wojewodztwa.py`:
```python
# -*- coding: utf-8 -*-
"""Runda 2 (spec 2.5): filtr województw listy Logistyki — z kodu pocztowego, w SQL."""
from datetime import date, datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics import wojewodztwa
from modules.production.logistics.models import Route, RouteStop
from modules.production.logistics.services import lista
from modules.reports.utils import PostcodeToStateMapper
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401


def _z(kod, kraj=None, **kolumny):
    """Zamówienie z danym kodem i krajem (fabryka zamowienie() stawia zawsze 30-001)."""
    order = zamowienie(**kolumny)
    order.delivery_postcode = kod
    order.delivery_country_code = kraj
    db.session.commit()
    return order.id


def _ids(woj, **filtry):
    return {w['id'] for w in lista.pobierz(woj=woj, **filtry)}


def test_opcje_z_mapy_raportow():
    assert [i for i, _ in wojewodztwa.wojewodztwa()] == [
        'dolnoslaskie', 'kujawsko-pomorskie', 'lubelskie', 'lubuskie', 'lodzkie', 'malopolskie',
        'mazowieckie', 'opolskie', 'podkarpackie', 'podlaskie', 'pomorskie', 'slaskie',
        'swietokrzyskie', 'warminsko-mazurskie', 'wielkopolskie', 'zachodniopomorskie']
    assert [n for _, n in wojewodztwa.wojewodztwa()] == [
        'Dolnośląskie', 'Kujawsko-Pomorskie', 'Lubelskie', 'Lubuskie', 'Łódzkie', 'Małopolskie',
        'Mazowieckie', 'Opolskie', 'Podkarpackie', 'Podlaskie', 'Pomorskie', 'Śląskie',
        'Świętokrzyskie', 'Warmińsko-Mazurskie', 'Wielkopolskie', 'Zachodniopomorskie']
    assert wojewodztwa.opcje()[16:] == (('zagranica', 'Zagranica'),
                                        ('bez_wojewodztwa', 'Bez województwa'))


def test_prefiksy_zgodne_z_mapa_raportow():
    """Jedno źródło prawdy: każdy prefiks 00–99 ma to samo województwo co Region w Routimo."""
    for n in range(100):
        kod = '%02d-100' % n
        oczekiwane = PostcodeToStateMapper.get_state_from_postcode(kod)
        znalezione = [nazwa for ident, nazwa in wojewodztwa.wojewodztwa()
                      if '%02d' % n in wojewodztwa.prefiksy(ident)]
        assert znalezione == ([oczekiwane] if oczekiwane else []), kod


@pytest.mark.parametrize('kod, woj', [
    ('34-100', 'malopolskie'), ('35-100', 'podkarpackie'),        # granica 34/35
    ('59-100', 'dolnoslaskie'), ('60-100', 'wielkopolskie'),      # granica 59/60
    ('35310', 'podkarpackie'), ('35 310', 'podkarpackie'), (' 35-310 ', 'podkarpackie'),
    ('00-950', 'mazowieckie'), ('26-600', 'mazowieckie'), ('25-001', 'swietokrzyskie'),
])
def test_granice_i_formaty_kodu(app, kod, woj):
    with app.app_context():
        oid = _z(kod)
        inne = _z('80-001')                                          # pomorskie
        assert _ids([woj]) == {oid}
        assert inne not in _ids([woj])


def test_kilka_wojewodztw_naraz(app):
    with app.app_context():
        a, b, _ = _z('35-100'), _z('31-100'), _z('80-100')
        assert _ids(['podkarpackie', 'malopolskie']) == {a, b}


def test_zagranica(app):
    with app.app_context():
        de = _z('35390', kraj='DE')                  # kod „jak z Podkarpacia”, ale kraj DE
        cz = _z('70200', kraj='cz')
        pl = _z('35-100', kraj='PL')
        pusty = _z('35-100', kraj='')
        assert _ids(['zagranica']) == {de, cz}
        assert _ids(['podkarpackie']) == {pl, pusty}


@pytest.mark.parametrize('kod', [None, '', '   ', 'brak', 'ab-123', '3', '24-100', '69-100',
                                 '88-100', '89-100', 'PL-35-310'])
def test_bez_wojewodztwa(app, kod):
    with app.app_context():
        oid = _z(kod)
        _z('35-100')
        assert _ids(['bez_wojewodztwa']) == {oid}


def test_kazde_zamowienie_w_dokladnie_jednym_kubelku(app):
    """Review Focus 1: 16 województw + Zagranica + Bez województwa dzielą zamówienia rozłącznie
    i w całości — żadne nie znika przy dowolnym wyborze, żadne nie jest w dwóch opcjach."""
    with app.app_context():
        ids = {_z(kod, kraj) for kod, kraj in [
            ('35-100', None), ('35310', 'PL'), ('35 310', 'pl'), ('00-001', ''), ('99-999', None),
            ('24-100', None), (None, None), ('', 'PL'), ('xx', None), ('35390', 'DE'),
            (None, 'UA'), ('26-600', ' PL '), ('96-100', None)]}
        opcje = [i for i, _ in wojewodztwa.opcje()]
        widziane = {}
        for opcja in opcje:
            for oid in _ids([opcja]):
                widziane.setdefault(oid, []).append(opcja)
        assert set(widziane) == ids
        assert all(len(v) == 1 for v in widziane.values()), widziane
        assert _ids(opcje) == ids


def test_woj_przed_limitem_zamknietych(app):
    """Review Focus 4 (R3): filtr w SQL przed LIMIT 50 zamkniętych — trafienie spoza
    pierwszych 50 (po id malejąco) nie może zginąć."""
    with app.app_context():
        szukane = _z('35-100', logistics_closed_at=datetime(2026, 9, 1))
        for _ in range(lista.LIMIT_ZAMKNIETYCH + 5):
            _z('80-100', logistics_closed_at=datetime(2026, 9, 1))
        wynik = lista.pobierz(q='Testowa', zamkniete=True, woj=['podkarpackie'])
        assert [w['id'] for w in wynik] == [szukane]


def test_woj_razem_z_bez_trasy_i_sposobem(app):
    """Review Focus 4: filtr województw składa się z `bez_trasy` (NOT EXISTS) i sposobem."""
    with app.app_context():
        t1 = _z('35-100', sposob=s.TRANSPORT)
        _z('80-100', sposob=s.TRANSPORT)
        _z('35-200', sposob=s.KURIER)
        na_trasie = _z('36-100', sposob=s.TRANSPORT)
        trasa = Route(name='A', date_from=date(2026, 10, 1), date_to=date(2026, 10, 1))
        db.session.add(trasa)
        db.session.flush()
        db.session.add(RouteStop(route_id=trasa.id, order_id=na_trasie, position=1))
        db.session.commit()
        assert _ids(['podkarpackie'], sposob='bez_trasy') == {t1}
        assert _ids(['podkarpackie'], sposob=s.TRANSPORT) == {t1, na_trasie}


def test_nieznane_wojewodztwo_w_serwisie_to_blad(app):
    with app.app_context():
        with pytest.raises(ValueError):
            lista.pobierz(woj=['mazowsze'])


def test_api_woj_wielokrotny_parametr(client, app):
    with app.app_context():
        a, b, _ = _z('35-100'), _z('31-100'), _z('80-100')
    dane = client.get(BASE + '/orders?woj=podkarpackie&woj=malopolskie').get_json()
    assert {o['id'] for o in dane['orders']} == {a, b}
    assert sum(dane['liczniki'].values()) == 3        # liczniki dalej liczą wszystkie otwarte


@pytest.mark.parametrize('zapytanie', ['?woj=mazowsze', '?woj=podkarpackie&woj=Podkarpackie',
                                       '?woj=zagranica&woj=%20'])
def test_api_nieznane_wojewodztwo_422(client, zapytanie):
    r = client.get(BASE + '/orders' + zapytanie)
    assert r.status_code == 422
    assert r.get_json() == {'success': False, 'error': 'Nieznany filtr województwa.'}


def test_api_pusty_woj_bez_filtra(client, app):
    with app.app_context():
        a, b = _z('35-100'), _z('80-100')
    assert {o['id'] for o in client.get(BASE + '/orders?woj=').get_json()['orders']} == {a, b}
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_wojewodztwa.py`
Expected: FAIL (`ImportError: cannot import name 'wojewodztwa'`).

- [ ] **Step 3: Moduł `wojewodztwa.py`**

`modules/production/logistics/wojewodztwa.py`:
```python
# -*- coding: utf-8 -*-
"""
Województwo zamówienia z kodu pocztowego — filtr listy Logistyki (runda 2, spec 2.5).

Jedno źródło prawdy: PostcodeToStateMapper z modules/reports/utils.py — te same zakresy dwóch
pierwszych cyfr kodu co kolumna „Region” w eksporcie Routimo i Analiza sprzedażowa. Tu tylko
opcje filtra (16 województw: identyfikator bez polskich znaków i nazwa kanoniczna ze
STATE_NORMALIZATION, oraz „Zagranica” i „Bez województwa”) i warunek SQL.

Znane ograniczenie mapy kodów (spec 2.5; poprawa poza zakresem, decyzja Konrada): prefiksy
24, 69, 88, 89 nie mają województwa (trafiają do „Bez województwa”), a prefiks obejmujący
dwa województwa (np. 27, 96) mapa przypisuje jednemu.

Warunek SQL bierze dwa pierwsze znaki kodu po usunięciu myślnika i spacji (REPLACE/SUBSTR —
SQLite w testach, MySQL na produkcji). Mapa w Pythonie usuwa WSZYSTKIE nie-cyfry, więc kod
z literami przed cyframi (np. „PL-35-310”) SQL wrzuca do „Bez województwa” — świadome
przybliżenie (podpowiedź przy filtrze: „wg kodu pocztowego, w przybliżeniu”).
"""
import unicodedata

from sqlalchemy import and_, func, or_

from modules.production.models import ProductionOrder

ZAGRANICA = 'zagranica'
BEZ_WOJEWODZTWA = 'bez_wojewodztwa'
POZOSTALE = ((ZAGRANICA, u'Zagranica'), (BEZ_WOJEWODZTWA, u'Bez województwa'))
# Kraj dostawy „Polska”: PL albo pusty — jak delivery.zmien_adres i eksport Routimo.
KRAJ_POLSKA = ('', 'PL')

_dane = None   # (województwa, prefiksy wg identyfikatora) — liczone raz na proces


def _identyfikator(nazwa):
    """'małopolskie' → 'malopolskie', 'łódzkie' → 'lodzkie' (ł nie rozkłada się w NFKD)."""
    tekst = nazwa.replace(u'ł', u'l').replace(u'Ł', u'L')
    return unicodedata.normalize('NFKD', tekst).encode('ascii', 'ignore').decode('ascii')


def _wczytaj():
    """
    Import leniwy: pakiet modules.reports przy imporcie ładuje swoje routery (pandas, eksport
    Routimo z modułu logistyki) — z poziomu modułu tworzyłby cykl z panelem logistyki
    (routimo.przygotuj_eksport importuje tę mapę tak samo, w funkcji).
    """
    global _dane
    if _dane is None:
        from modules.reports.utils import PostcodeToStateMapper
        lista, po_ident = [], {}
        for klucz, zakresy in PostcodeToStateMapper.POSTCODE_RANGES.items():
            ident = _identyfikator(klucz)
            nazwa = PostcodeToStateMapper.STATE_NORMALIZATION.get(klucz) or klucz.capitalize()
            lista.append((ident, nazwa))
            po_ident[ident] = tuple('%02d' % n for od, do in zakresy for n in range(od, do + 1))
        _dane = (tuple(lista), po_ident)
    return _dane


def wojewodztwa():
    """16 województw: ((identyfikator, nazwa kanoniczna), …) w kolejności mapy (alfabet)."""
    return _wczytaj()[0]


def opcje():
    """Wszystkie opcje filtra: 16 województw, „Zagranica”, „Bez województwa”."""
    return wojewodztwa() + POZOSTALE


def prefiksy(identyfikator):
    """Dwucyfrowe prefiksy kodu województwa ('35', …, '39'); dla pozostałych opcji ()."""
    return _wczytaj()[1].get(identyfikator, ())


def nieznane(identyfikatory):
    """Identyfikatory spoza opcji filtra — GET /orders odpowiada na nie 422."""
    znane = {ident for ident, _ in opcje()}
    return [i for i in identyfikatory if i not in znane]


def _prefiks_kodu():
    kod = func.coalesce(ProductionOrder.delivery_postcode, '')
    return func.substr(func.replace(func.replace(kod, '-', ''), ' ', ''), 1, 2)


def _kraj():
    return func.upper(func.trim(func.coalesce(ProductionOrder.delivery_country_code, '')))


def warunek(identyfikatory):
    """
    Warunek SQL na zamówienie z KTÓREJKOLWIEK wybranej opcji (OR). Opcje są rozłączne i razem
    obejmują każde zamówienie: Zagranica (kraj niepusty i inny niż PL), województwo (PL albo
    pusty kraj + prefiks z mapy), Bez województwa (PL albo pusty kraj + prefiks spoza mapy:
    pusty/NULL kod, śmieci, 24/69/88/89). Pusta lista albo nieznany identyfikator → ValueError
    (API sprawdza wcześniej przez nieznane() i odpowiada 422).
    """
    wybrane = list(dict.fromkeys(identyfikatory))
    zle = nieznane(wybrane)
    if zle or not wybrane:
        raise ValueError(u'Nieznany filtr województwa: {}'.format(', '.join(zle)))
    kraj, prefiks = _kraj(), _prefiks_kodu()
    w_polsce = kraj.in_(KRAJ_POLSKA)
    warunki = []
    z_mapy = sorted({p for i in wybrane for p in prefiksy(i)})
    if z_mapy:
        warunki.append(and_(w_polsce, prefiks.in_(z_mapy)))
    if ZAGRANICA in wybrane:
        warunki.append(kraj.notin_(KRAJ_POLSKA))
    if BEZ_WOJEWODZTWA in wybrane:
        wszystkie = sorted({p for ident, _ in wojewodztwa() for p in prefiksy(ident)})
        warunki.append(and_(w_polsce, prefiks.notin_(wszystkie)))
    return or_(*warunki)
```

- [ ] **Step 4: Lista i API**

`lista.py`: import `from modules.production.logistics import sposoby, wojewodztwa`; sygnatura `def pobierz(sposob=None, etap=None, q=None, zamkniete=False, woj=None):`; na końcu docstringu dopisz akapit:
```
    Runda 2 (spec 2.5): `woj` — lista identyfikatorów z wojewodztwa.opcje(); filtr SQL
    z kodu pocztowego i kraju w tym samym bloku (R3), przed order_by/limit zamkniętych.
```
i tuż przed `if zamkniete:` z `order_by(...).limit(...)` (:211):
```python
    if woj:
        zapytanie = zapytanie.filter(wojewodztwa.warunek(woj))
```
`panel_api.py`: import `from modules.production.logistics import logistics_panel_bp, sposoby, wojewodztwa`; w `orders()` po sprawdzeniu „zamknięte bez frazy”:
```python
    # (runda 2, spec 2.5) Województwa: parametr wielokrotny (?woj=a&woj=b), pusta wartość
    # = brak filtra, nieznany identyfikator = 422 (jak inne złe parametry listy).
    woj = list(dict.fromkeys(w for w in request.args.getlist('woj') if w))
    if wojewodztwa.nieznane(woj):
        return _blad(u'Nieznany filtr województwa.', 422)
```
i w wywołaniu `lista.pobierz(...)` dopisz `woj=woj or None`.

- [ ] **Step 5: Uruchom testy**

Run: `PYTEST tests/test_logistyka_wojewodztwa.py tests/test_logistyka_panel_api.py tests/test_logistyka_poprawki_panelu.py tests/test_logistyka_routimo.py`
Expected: PASS.

- [ ] **Step 6: Pełny pakiet**

Run: `docker compose -p logistyka3 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider`
Expected: 0 failed.

- [ ] **Step 7: Commit**

```bash
git add modules/production/logistics/wojewodztwa.py tests/test_logistyka_wojewodztwa.py
git commit -m "feat(production): filtr wojewodztw listy logistyki z kodu pocztowego

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- modules/production/logistics/wojewodztwa.py modules/production/logistics/services/lista.py modules/production/logistics/routers/panel_api.py tests/test_logistyka_wojewodztwa.py
```

---

### Task 4: Województwa — UI i przełączanie mapy na „Zamówienia” (skill `frontend-design`)

**REQUIRED:** `frontend-design:frontend-design` przed kodem UI. Przycisk z tej samej rodziny co „Transport bez trasy” (`.lg-filtr-trasy`: aktywny = ciemny), panel jako warstwa pod przyciskiem.

**Files:**
- Create: `modules/production/logistics/static/js/logistics-wojewodztwa.js`
- Modify: `modules/production/logistics/routers/panel_api.py` (`tab_content()` :71–75)
- Modify: `modules/production/logistics/templates/logistics/tab_content.html` (narzędzia :127–131, skrypty :644–645, `?v=` :19)
- Modify: `modules/production/logistics/static/js/logistics.js` (nagłówek :15–61, `stan.filtr` :133, `wczytaj` :285–289, `zawezonyWidok` :462, `pustyStan` :615–659, `ustawFiltrGeo` :1592, przy `mapa()` :1635, `ustawSposobFiltra` :1938, `zdejmijFiltry` :1950, `click` :2040–2058, `change` :2112–2117, `zniszcz` :2185, start :2243–2244)
- Modify: `modules/production/logistics/static/css/logistics-trasy.css` (po `.lg-filtr-trasy` :133, `@media` :2187)
- Test: `tests/test_logistyka_wojewodztwa_ui.py`

**Interfaces:**
- Consumes (Task 3): `wojewodztwa.wojewodztwa()`, `wojewodztwa.POZOSTALE`, `GET /orders?woj=…`; `window.LogisticsMap.widok()` i `.ustawWidok('zamowienia')` (zwraca false, gdy zapis punktu w toku).
- Produces: szablon — `[data-lg-woj="kontener|przycisk|etykieta|panel|wyczysc"]`, pola `input[data-lg-woj-pole][value=<identyfikator>]`; `window.LogisticsWojewodztwa = {root, wybrane(), wyczysc({cicho}), zniszcz()}`; zdarzenie `logistics:wojewodztwa` `{root, wybrane}`; w `logistics.js`: `stan.filtr.woj` (lista), `mapaNaZamowienia()`, `naWojewodztwa(e)`, `wyczyscWojewodztwa(opcje)`, akcja `data-lg-akcja="wyczysc-wojewodztwa"`.

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_wojewodztwa_ui.py`:
```python
# -*- coding: utf-8 -*-
"""Runda 2 (spec 2.4, 2.5), interfejs: panel województw i przełączanie mapy przy filtrach."""
import os
import re

from modules.production.logistics import wojewodztwa
from tests.logistyka_fixtures import BASE, app, client  # noqa: F401

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'modules', 'production', 'logistics')


def _plik(*sciezka):
    return open(os.path.join(LOG, *sciezka), encoding='utf-8').read()


def _funkcja(js, nazwa):
    start = js.index('function ' + nazwa + '(')
    return js[start:js.index('\n    }\n', start)]


def _wersja(html, plik):
    m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
    assert m, plik
    return m.group(1)


def test_panel_wojewodztw_w_szablonie(client):  # noqa: F811
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    panel = html[html.index('data-lg-woj="panel"'):]
    panel = panel[:panel.index('data-lg-woj="wyczysc"')]
    assert re.findall(r'data-lg-woj-pole value="([\w-]+)"', panel) == [i for i, _ in wojewodztwa.opcje()]
    assert re.findall(r'data-lg-woj-pole value="[\w-]+"><span>([^<]+)</span>', panel) == \
        [n for _, n in wojewodztwa.opcje()]
    assert 'wg kodu pocztowego, w przybliżeniu' in panel
    narzedzia = html[html.index('class="lg-narzedzia"'):html.index('data-lg="ile"')]
    assert narzedzia.index('data-lg-sposob="bez_trasy"') < narzedzia.index('data-lg-woj="przycisk"')
    assert 'aria-expanded="false"' in narzedzia and 'aria-controls="lg-woj-panel"' in narzedzia
    m = re.search(r'="([^"?]+js/logistics-wojewodztwa\.js)\?v=\w+"', html)
    assert m
    statyka = client.get(m.group(1))
    assert statyka.status_code == 200
    statyka.close()


def test_modul_wojewodztw_wysyla_zdarzenie_a_lista_filtruje():
    woj = _plik('static', 'js', 'logistics-wojewodztwa.js')
    lista = _plik('static', 'js', 'logistics.js')
    assert "new CustomEvent('logistics:wojewodztwa'" in _funkcja(woj, 'ogloszZmiane')
    assert "'Województwa (' + n + ')'" in _funkcja(woj, 'renderujPrzycisk')
    assert "e.key === 'Escape'" in woj and "'pointerdown'" in woj and "'focusout'" in woj
    assert 'localStorage' not in woj                                  # bez zapamiętywania (spec 2.5)
    assert 'window.LogisticsWojewodztwa && typeof window.LogisticsWojewodztwa.zniszcz' in woj
    assert 'delete window.LogisticsWojewodztwa' in woj
    assert "document.addEventListener('logistics:wojewodztwa', naWojewodztwa)" in lista
    assert "document.removeEventListener('logistics:wojewodztwa', naWojewodztwa)" in _funkcja(lista, 'zniszcz')
    assert "stan.filtr.woj.forEach((w) => params.append('woj', w))" in _funkcja(lista, 'wczytaj')
    assert 'stan.filtr.woj.length' in lista[lista.index('const zawezonyWidok'):][:200]
    assert "przyciskStanu('wyczysc-wojewodztwa', 'Wyczyść województwa')" in _funkcja(lista, 'pustyStan')
    zdejmij = _funkcja(lista, 'zdejmijFiltry')
    assert 'stan.filtr.woj = [];' in zdejmij and 'wyczyscWojewodztwa({ cicho: true })' in zdejmij


def test_filtry_przelaczaja_mape_a_wyszukiwarka_nie():
    """Review Focus 5: każda zmiana filtra zamówień (także zdjęcie) pokazuje na mapie zamówienia;
    wyszukiwarka i „także zamknięte” nie; nic nie wraca samo na „Trasy”."""
    js = _plik('static', 'js', 'logistics.js')
    mapa = _funkcja(js, 'mapaNaZamowienia')
    assert "m.widok() === 'trasy'" in mapa and "m.ustawWidok('zamowienia')" in mapa
    assert "ustawWidok('trasy')" not in js
    for nazwa in ('ustawSposobFiltra', 'ustawFiltrGeo', 'naWojewodztwa', 'zdejmijFiltry'):
        assert 'mapaNaZamowienia();' in _funkcja(js, nazwa), nazwa
    assert 'mapaNaZamowienia' not in _funkcja(js, 'zmianaFrazy')
    zmiana = js[js.index("root.addEventListener('change'"):]
    zmiana = zmiana[:zmiana.index('\n    });\n')]
    assert 'mapaNaZamowienia();' in zmiana[zmiana.index("t === el('etap')"):zmiana.index("t === el('geo')")]
    assert 'mapaNaZamowienia' not in zmiana[zmiana.index("t === el('zamkniete')"):zmiana.index("t === el('etap')")]
    klik = js[js.index("root.addEventListener('click'"):]
    klik = klik[:klik.index('\n    });\n')]
    for przypadek, jest in (("case 'pokaz-wszystkie':", True), ("case 'wszystkie-etapy':", True),
                            ("case 'wyczysc-wojewodztwa':", True), ("case 'szukaj-zamkniete':", False)):
        blok = klik[klik.index(przypadek):]
        assert ('mapaNaZamowienia();' in blok[:blok.index('break;')]) is jest, przypadek


def test_wersje_podbite():
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert _wersja(html, 'js/logistics.js') != '20260928a'
    assert _wersja(html, 'css/logistics-trasy.css') not in ('20260926c', '20260928a')
    assert _wersja(html, 'js/logistics-wojewodztwa.js')
    assert html.index("filename='js/logistics.js'") < html.index("filename='js/logistics-wojewodztwa.js'")
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_wojewodztwa_ui.py`
Expected: FAIL.

- [ ] **Step 3: Kontekst szablonu i szablon**

`panel_api.tab_content()`:
```python
    return render_template('logistics/tab_content.html', magazyn=geocoding.MAGAZYN,
                           carto_basemaps_key=_klucz_carto_basemaps(),
                           # Runda 2 (spec 2.5): opcje filtra województw z jednego źródła.
                           opcje_wojewodztw=wojewodztwa.wojewodztwa(),
                           opcje_pozostale=wojewodztwa.POZOSTALE)
```
W `tab_content.html` między przyciskiem `.lg-filtr-trasy` (:127–130) a `<span class="lg-ile" …>` (:131):
```html
          {# Runda 2 (spec 2.5): województwa z KODU POCZTOWEGO (te same zakresy co Region w eksporcie
               Routimo — modules/production/logistics/wojewodztwa.py). Kilka naraz, filtr serwera
               (?woj=…), bez zapamiętywania. Panel: logistics-wojewodztwa.js; filtr listy: logistics.js
               (zdarzenie logistics:wojewodztwa). #}
          <div class="lg-woj" data-lg-woj="kontener">
            <button type="button" class="lg-woj-przycisk" data-lg-woj="przycisk"
                    aria-expanded="false" aria-controls="lg-woj-panel"
                    title="Filtr województw (wg kodu pocztowego)">
              <i class="fas fa-map-location-dot" aria-hidden="true"></i><span data-lg-woj="etykieta">Województwa</span>
              <i class="fas fa-chevron-down lg-woj-strzalka" aria-hidden="true"></i>
            </button>
            <div class="lg-woj-panel" id="lg-woj-panel" data-lg-woj="panel" hidden>
              <fieldset class="lg-woj-pola">
                <legend class="lg-woj-podpowiedz">wg kodu pocztowego, w przybliżeniu</legend>
                <div class="lg-woj-lista">
                  {% for identyfikator, nazwa in opcje_wojewodztw %}
                  <label class="lg-woj-opcja"><input type="checkbox" data-lg-woj-pole value="{{ identyfikator }}"><span>{{ nazwa }}</span></label>
                  {% endfor %}
                </div>
                <div class="lg-woj-lista lg-woj-lista--inne">
                  {% for identyfikator, nazwa in opcje_pozostale %}
                  <label class="lg-woj-opcja"><input type="checkbox" data-lg-woj-pole value="{{ identyfikator }}"><span>{{ nazwa }}</span></label>
                  {% endfor %}
                </div>
              </fieldset>
              <div class="lg-woj-stopka">
                <button type="button" class="lg-przycisk lg-przycisk--cichy" data-lg-woj="wyczysc">Wyczyść</button>
              </div>
            </div>
          </div>
```
Za `<script src=… logistics-fleet.js …>` (:645):
```html
<script src="{{ url_for('logistics_panel.static', filename='js/logistics-wojewodztwa.js') }}?v=20260928a"></script>
```
Wersje: `logistics-trasy.css?v=20260928b`, `logistics.js?v=20260928b`.

- [ ] **Step 4: `logistics-wojewodztwa.js`**

```js
/**
 * Logistyka — filtr województw listy zamówień (runda 2 logistyki, spec 2.5).
 * modules/production/logistics/static/js/logistics-wojewodztwa.js
 *
 * Zwykły <script src> obok logistics.js. production-app-loader odtwarza tagi <script>
 * asynchronicznie, więc kolejność względem logistics.js nie jest gwarantowana — dlatego
 * rozmawiamy przez zdarzenie na document, nie przez wnętrze logistics.js:
 *   wysyłamy `logistics:wojewodztwa` {root, wybrane: ['podkarpackie', …]} po każdej zmianie
 *   wyboru (pole, „Wyczyść”). logistics.js ustawia wtedy filtr listy `woj`
 *   (GET /orders?woj=…&woj=…), przeładowuje listę (a z nią mapę) i przełącza mapę
 *   z „Trasy” na „Zamówienia”.
 * Publicznie: window.LogisticsWojewodztwa = {root, wybrane(), wyczysc(opcje), zniszcz()};
 *   wyczysc({cicho: true}) odznacza bez zdarzenia (logistics.js sam przeładowuje listę).
 *
 * Opcje (16 województw, „Zagranica”, „Bez województwa”) renderuje serwer
 * (modules/production/logistics/wojewodztwa.py). Wyboru nie zapamiętujemy (spec 2.5).
 * Panel zamyka Esc (fokus wraca na przycisk), klik obok i wyjście fokusem poza panel.
 */
(function () {
    'use strict';

    if (window.LogisticsWojewodztwa && typeof window.LogisticsWojewodztwa.zniszcz === 'function') {
        try { window.LogisticsWojewodztwa.zniszcz(); } catch (e) { /* stara instancja i tak idzie do kosza */ }
    }

    const root = document.getElementById('logistics-root');
    const kontener = root ? root.querySelector('[data-lg-woj="kontener"]') : null;
    if (!root || !kontener) return;

    const przycisk = kontener.querySelector('[data-lg-woj="przycisk"]');
    const etykieta = kontener.querySelector('[data-lg-woj="etykieta"]');
    const panel = kontener.querySelector('[data-lg-woj="panel"]');
    if (!przycisk || !etykieta || !panel) return;

    const sluchacze = new AbortController();   // jeden sygnał odpina wszystkie nasłuchy
    const naSluch = { signal: sluchacze.signal };
    let zniszczona = false;

    const pola = () => Array.from(panel.querySelectorAll('input[data-lg-woj-pole]'));

    function wybrane() {
        return pola().filter((p) => p.checked).map((p) => p.value);
    }

    function renderujPrzycisk() {
        const n = wybrane().length;
        etykieta.textContent = n ? 'Województwa (' + n + ')' : 'Województwa';
        przycisk.classList.toggle('is-aktywny', n > 0);
    }

    function ogloszZmiane() {
        if (zniszczona) return;
        document.dispatchEvent(new CustomEvent('logistics:wojewodztwa', {
            detail: { root: root, wybrane: wybrane() },
        }));
    }

    function otworz() {
        if (!panel.hidden) return;
        panel.hidden = false;
        przycisk.setAttribute('aria-expanded', 'true');
        const pierwsze = pola().find((p) => p.checked) || pola()[0];
        if (pierwsze) pierwsze.focus();
    }

    function zamknij(oddajFokus) {
        if (panel.hidden) return;
        panel.hidden = true;
        przycisk.setAttribute('aria-expanded', 'false');
        if (oddajFokus) przycisk.focus();
    }

    /** Odznacza wszystkie pola; bez `cicho` ogłasza zmianę (lista przeładuje się sama). */
    function wyczysc(opcje) {
        const o = opcje || {};
        let zmiana = false;
        pola().forEach((p) => {
            if (p.checked) {
                p.checked = false;
                zmiana = true;
            }
        });
        renderujPrzycisk();
        if (zmiana && !o.cicho) ogloszZmiane();
    }

    function naKlawisz(e) {
        if (e.key === 'Escape' && !panel.hidden) {
            e.preventDefault();
            zamknij(true);
        }
    }

    // Klik obok panelu (faza przechwytywania — mapa i lista zatrzymują część zdarzeń u siebie).
    function naWskaznik(e) {
        if (!panel.hidden && !kontener.contains(e.target)) zamknij(false);
    }

    function zniszcz() {
        zniszczona = true;
        sluchacze.abort();
        if (window.LogisticsWojewodztwa === api) delete window.LogisticsWojewodztwa;
    }

    const api = { root: root, wybrane: wybrane, wyczysc: wyczysc, zniszcz: zniszcz };

    przycisk.addEventListener('click', () => {
        if (panel.hidden) otworz(); else zamknij(false);
    }, naSluch);
    panel.addEventListener('change', (e) => {
        if (!e.target.matches('input[data-lg-woj-pole]')) return;
        renderujPrzycisk();
        ogloszZmiane();
    }, naSluch);
    panel.addEventListener('click', (e) => {
        if (e.target.closest('[data-lg-woj="wyczysc"]')) wyczysc();
    }, naSluch);
    // Wyjście fokusem (Tab) poza przycisk i panel zamyka panel.
    kontener.addEventListener('focusout', (e) => {
        if (e.relatedTarget && !kontener.contains(e.relatedTarget)) zamknij(false);
    }, naSluch);
    document.addEventListener('keydown', naKlawisz, naSluch);
    document.addEventListener('pointerdown', naWskaznik, { capture: true, signal: sluchacze.signal });

    window.LogisticsWojewodztwa = api;
    renderujPrzycisk();
})();
```

- [ ] **Step 5: Punkty zaczepienia w `logistics.js`**

1. Nagłówek: w linii API `GET {API}/orders?sposob=&q=&zamkniete=1` dopisz `&woj=…` (wielokrotny); w „Kontrakcie etapu 3” dopisz:
```js
 * Runda 2:
 *   `logistics:wojewodztwa` {root, wybrane} (logistics-wojewodztwa.js) — filtr `woj` listy
 *       (serwer); przy pustym stanie „Wyczyść województwa”, przy „Zdejmij filtry” pola odznaczamy
 *       przez window.LogisticsWojewodztwa.wyczysc({cicho: true}).
 *   Zmiana filtra zamówień przełącza mapę z „Trasy” na „Zamówienia” (mapaNaZamowienia).
```
2. `stan.filtr` (:133): `filtr: { sposob: '', etap: '', q: '', zamkniete: false, geo: '', woj: [] },`
3. `wczytaj` — po `if (stan.filtr.q && stan.filtr.zamkniete) params.set('zamkniete', '1');` (:289):
```js
        // Runda 2: województwa (parametr wielokrotny), jak sposób — filtr serwera.
        stan.filtr.woj.forEach((w) => params.append('woj', w));
```
4. `zawezonyWidok` (:462): `const zawezonyWidok = () => !!(stan.filtr.sposob || stan.filtr.etap || stan.filtr.q || stan.filtr.woj.length);`
5. `pustyStan` — między gałęzią `} else if (f.etap && stan.wiersze.length) {…}` a `} else if (f.q) {`:
```js
        } else if (f.woj.length) {
            // Runda 2: filtr województw (serwer) — bez tej gałęzi pusty widok twierdziłby, że nie ma
            // otwartych zamówień albo że każde ma już sposób dostawy.
            tytul = 'Brak zamówień w wybranych województwach' + (f.sposob || f.q ? ' przy tych filtrach.' : '.');
            przycisk = przyciskStanu('wyczysc-wojewodztwa', 'Wyczyść województwa');
```
6. Pod `function mapa() {…}` (:1635–1638):
```js
    /**
     * Runda 2 (spec 2.4): zmiana filtra zamówień — liczniki sposobu, „Transport bez trasy”, etap,
     * lokalizacja, województwa, także ich zdjęcie — pokazuje na mapie zamówienia: w widoku „Trasy”
     * filtr nie miałby widocznego skutku. Wyszukiwarka (i „także zamknięte”) tego nie robi, a do
     * „Trasy” nic nie wraca samo. ustawWidok może odmówić (zapis punktu w toku) — mapa zostaje,
     * filtr i tak działa na liście.
     */
    function mapaNaZamowienia() {
        const m = mapa();
        if (m && typeof m.widok === 'function' && m.widok() === 'trasy' && typeof m.ustawWidok === 'function') {
            m.ustawWidok('zamowienia');
        }
    }

    // Runda 2 (spec 2.5): filtr województw z logistics-wojewodztwa.js — zdarzenie, bo pliki
    // wykonują się w dowolnej kolejności. Filtr serwera (woj), jak sposób dostawy.
    function naWojewodztwa(e) {
        const d = e.detail || {};
        if (zniszczona || d.root !== root) return;
        stan.filtr.woj = Array.isArray(d.wybrane) ? d.wybrane.slice() : [];
        stan.dopasujMape = true;
        odznaczWszystko();
        mapaNaZamowienia();
        wczytaj('uzytkownik');
    }

    // Odznacza pola panelu województw; filtr listy ustawia wołający (`cicho` — bez zdarzenia).
    function wyczyscWojewodztwa(opcje) {
        const w = window.LogisticsWojewodztwa;
        if (w && w.root === root && typeof w.wyczysc === 'function') w.wyczysc(opcje);
    }
```
7. `ustawFiltrGeo` — po `stan.dopasujMape = true;` dopisz `mapaNaZamowienia();`. `ustawSposobFiltra` — po `stan.dopasujMape = true;` dopisz `mapaNaZamowienia();`.
8. `zdejmijFiltry` — po `stan.filtr.zamkniete = false;` dopisz `stan.filtr.woj = [];` i `wyczyscWojewodztwa({ cicho: true });`, a po `stan.dopasujMape = true;` — `mapaNaZamowienia();`.
9. Delegacja `click`: w `case 'pokaz-wszystkie':` i `case 'wszystkie-etapy':` po `stan.dopasujMape = true;` dopisz `mapaNaZamowienia();`; nowy przypadek przed `case 'zdejmij-filtry':`:
```js
            case 'wyczysc-wojewodztwa':
                // Pusty stan przy filtrze województw — zdejmujemy tylko ten filtr.
                stan.filtr.woj = [];
                wyczyscWojewodztwa({ cicho: true });
                stan.dopasujMape = true;
                mapaNaZamowienia();
                wczytaj('uzytkownik');
                break;
```
10. Delegacja `change`, gałąź `t === el('etap')` — po `stan.dopasujMape = true;` dopisz `mapaNaZamowienia();` (gałęzi `el('zamkniete')` nie ruszaj).
11. Start — obok `document.addEventListener('logistics:mapa-gotowa', naGotowaMape);`: `document.addEventListener('logistics:wojewodztwa', naWojewodztwa);`; w `zniszcz()` obok zdjęcia `logistics:mapa-gotowa`: `document.removeEventListener('logistics:wojewodztwa', naWojewodztwa);`.

- [ ] **Step 6: CSS (`logistics-trasy.css`, za regułami `.lg-filtr-trasy` :133)**

```css
/* ─── Dashboard: filtr województw (runda 2, spec 2.5) ───
   Przycisk z rodziny „Transport bez trasy” (aktywny = ciemny), panel jako warstwa pod
   przyciskiem — nad tabelą i nad mapą (Leaflet trzyma kontrolki na z-index 1000). */
.logistics-tab .lg-woj { position: relative; display: inline-flex; }
.logistics-tab .lg-woj-przycisk {
    display: inline-flex; align-items: center; gap: 7px; height: 32px; padding: 0 10px 1px;
    background: var(--il-bg-card, #fff); border: 1px solid var(--il-border, #c8cdd5);
    border-radius: var(--il-radius, 3px); box-shadow: inset 0 -2px 0 var(--il-inset-shadow, #d4d9e1);
    font-size: 13px; font-weight: 500; color: var(--il-text-secondary, #7a8291); cursor: pointer; white-space: nowrap;
}
.logistics-tab .lg-woj-przycisk:hover,
.logistics-tab .lg-woj-przycisk[aria-expanded="true"] {
    border-color: var(--il-text-secondary, #7a8291); color: var(--il-text-primary, #1a1a2e);
}
.logistics-tab .lg-woj-przycisk.is-aktywny,
.logistics-tab .lg-woj-przycisk.is-aktywny:hover {
    background: var(--il-text-primary, #1a1a2e); border-color: var(--il-text-primary, #1a1a2e);
    box-shadow: none; color: #fff;
}
.logistics-tab .lg-woj-strzalka { font-size: 10px; transition: transform 0.15s; }
.logistics-tab .lg-woj-przycisk[aria-expanded="true"] .lg-woj-strzalka { transform: rotate(180deg); }
.logistics-tab .lg-woj-panel {
    position: absolute; top: calc(100% + 4px); left: 0; z-index: 1010;
    width: 340px; max-width: calc(100vw - 32px); padding: 10px 12px 8px;
    background: var(--il-bg-card, #fff); border: 1px solid var(--il-border, #c8cdd5);
    border-radius: var(--il-radius, 3px); box-shadow: 0 8px 24px rgba(26, 26, 46, 0.14);
}
.logistics-tab .lg-woj-panel[hidden] { display: none; }
.logistics-tab .lg-woj-pola { min-width: 0; margin: 0; padding: 0; border: 0; }
.logistics-tab .lg-woj-podpowiedz {
    float: none; width: auto; margin: 0 0 6px; padding: 0; font-size: 11.5px; color: var(--il-text-muted, #9ba3b0);
}
.logistics-tab .lg-woj-lista { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.logistics-tab .lg-woj-lista--inne { margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--il-border-light, #e2e5ea); }
.logistics-tab .lg-woj-opcja {
    display: flex; align-items: center; gap: 7px; min-height: 28px; margin: 0; font-size: 13px; cursor: pointer;
}
.logistics-tab .lg-woj-opcja input {
    width: 16px; height: 16px; margin: 0; accent-color: var(--il-text-primary, #1a1a2e);
}
.logistics-tab .lg-woj-stopka { display: flex; justify-content: flex-end; margin-top: 8px; }
```
(Zapis zwarty — przy wklejaniu rozpisz deklaracje po jednej w linii, jak reszta pliku.)
W `@media (max-width: 900px)` (:2187):
```css
    .logistics-tab .lg-woj-przycisk { height: 36px; }
    .logistics-tab .lg-woj-opcja { min-height: 36px; }
    .logistics-tab .lg-woj-opcja input { width: 20px; height: 20px; }
```
Skillem `frontend-design` dopracuj wygląd; jeśli przycisk w zawiniętym pasku stoi przy prawej krawędzi, panel wyrównaj do prawej (`right: 0; left: auto`) — kontroler sprawdzi to w oględzinach 768/1024.

- [ ] **Step 7: Uruchom testy**

Run: `node --check modules/production/logistics/static/js/logistics-wojewodztwa.js && node --check modules/production/logistics/static/js/logistics.js`
Expected: bez błędów.
Run: `PYTEST tests/test_logistyka_wojewodztwa_ui.py tests/test_logistyka_wojewodztwa.py tests/test_logistyka_trasy_ui.py tests/test_logistyka_mapa_ui.py tests/test_logistyka_zakladka.py tests/test_logistyka_poprawki_panelu.py tests/test_logistyka_kafelki.py`
Expected: PASS.

- [ ] **Step 8: Pełny pakiet**

Run: `docker compose -p logistyka3 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider`
Expected: 0 failed.

- [ ] **Step 9: Commit**

```bash
git add modules/production/logistics/static/js/logistics-wojewodztwa.js tests/test_logistyka_wojewodztwa_ui.py
git commit -m "feat(production): panel wojewodztw i przelaczanie mapy na zamowienia przy filtrach

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- modules/production/logistics/static/js/logistics-wojewodztwa.js modules/production/logistics/routers/panel_api.py modules/production/logistics/templates/logistics/tab_content.html modules/production/logistics/static/js/logistics.js modules/production/logistics/static/css/logistics-trasy.css tests/test_logistyka_wojewodztwa_ui.py
```

Oględziny (kontroler, 5003): wybór 2 województw („Województwa (2)”), „Wyczyść”, Esc i klik obok, „Zagranica”/„Bez województwa”, pusty stan z „Wyczyść województwa”; na widoku „Trasy” klik w licznik, „Transport bez trasy”, etap, lokalizację, województwo → mapa „Zamówienia”; pisanie w wyszukiwarce — bez przełączenia; 1440/1024/768.

---

### Task 5: Dymek pinezki, odstęp pola wyboru, mapka trasy (skill `frontend-design`)

**REQUIRED:** `frontend-design:frontend-design` przed kodem UI. Select w dymku ma wyglądać jak select wiersza listy (Bootstrap `form-select form-select-sm`), z kolorową pinezką sposobu obok.

**Files:**
- Modify: `modules/production/logistics/static/js/logistics-map.js` (nagłówek :15–31, stałe :133, stan :197, `dymekHtml` :355–407, `podepnijDymek` :1155–1168, `onBlad` :2003, `zniszcz` :2044, api :2098–2117)
- Modify: `modules/production/logistics/static/js/logistics.js` (nagłówek, po `zmianaSelecta` :1283, `polaczZMapa` :1646)
- Modify: `modules/production/logistics/static/js/logistics-routes.js` (`zapewnijMapke` :2369–2398)
- Modify: `modules/production/logistics/static/css/logistics.css` (:519, :527, :1124–1125, :1132–1133, :2120–2133, :2625–2630)
- Modify: `modules/production/logistics/templates/logistics/tab_content.html` (`?v=` :17, :184, :185, :644)
- Test: `tests/test_logistyka_dymek_ui.py`

**Interfaces:**
- Consumes: `wyslijSposob(ids, sposob)` → odpowiedź `/orders/delivery-method` `{zmienione, przepakowanie, bledy, orders, usunieto_z_trasy}`; `nowyWynik()`, `dolacz()`, `podsumujZmiany(wynik, true)` (→ `podmienWiersze` → `przekazDoMapy` → `LogisticsMap.render`), `odswiezWiersz`, `pokazKomunikat`, `oczekujaceSelecty`, `stan.docelowe`, `stan.wysylane`.
- Produces: `window.LogisticsMap.onSposob(cb)` — `cb(id, sposob)` zwraca obietnicę kończącą się PO podmianie wiersza i pinezek (sposób: `'brak' | 'kurier_baselinker' | 'transport_woodpower' | 'odbior_osobisty'`); w dymku `select.lg-dymek-select[data-lg-mapa-sposob][data-id]`; w `logistics.js` `zmienSposobZMapy(id, sposob)`.

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_dymek_ui.py`:
```python
# -*- coding: utf-8 -*-
"""Runda 2 (spec 2.2, 2.3, 2.7): sposób dostawy w dymku pinezki, odstęp pola wyboru, kółko
na mapce trasy."""
import os
import re

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'modules', 'production', 'logistics')


def _plik(*sciezka):
    return open(os.path.join(LOG, *sciezka), encoding='utf-8').read()


def _funkcja(js, nazwa):
    start = js.index('function ' + nazwa + '(')
    return js[start:js.index('\n    }\n', start)]


def _regula_css(css, selektor):
    start = css.index(selektor + ' {')
    return css[start:css.index('}', start)]


def _wersja(html, plik):
    m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
    assert m, plik
    return m.group(1)


def _etykiety(js):
    blok = js[js.index('const ETYKIETY = {'):]
    return re.findall(r"(\w+): '([^']+)'", blok[:blok.index('};')])


def test_dymek_ma_wybor_sposobu_jak_wiersz_listy():
    mapa, lista = _plik('static', 'js', 'logistics-map.js'), _plik('static', 'js', 'logistics.js')
    dymek = _funkcja(mapa, 'dymekHtml')
    assert 'data-lg-mapa-sposob' in dymek and 'opcjeSposobu(sposob)' in dymek
    assert 'powodBlokadySposobu(z)' in dymek and 'Sposób dostawy zamówienia' in dymek
    # Te same podpisy i kolejność co select wiersza (selectSposobu: „Nie ustawiono” + SPOSOBY).
    assert _etykiety(mapa) == [('brak', 'Nie ustawiono')] + _etykiety(lista)
    assert "const NIE_USTAWIONO = 'Nie ustawiono';" in lista
    assert "['brak'].concat(SPOSOBY)" in _funkcja(mapa, 'opcjeSposobu')
    blokada = _funkcja(mapa, 'powodBlokadySposobu')
    for tekst in ('Zamówienie wydane klientowi. Sposobu dostawy nie można już zmienić.', 'Zamówienie anulowane.'):
        assert tekst in blokada and tekst in lista, tekst
    assert 'zapisywaneSposoby.has(z.id)' in blokada


def test_dymek_przerysowuje_wybor_po_kazdej_odpowiedzi():
    """Review Focus 3: odmowa w `bledy` przychodzi przy HTTP 200 — dymek zawsze od nowa z danych
    listy; select dymku nie może wyglądać dla delegacji listy jak select wiersza ani licznik."""
    mapa, lista = _plik('static', 'js', 'logistics-map.js'), _plik('static', 'js', 'logistics.js')
    dymek = _funkcja(mapa, 'dymekHtml')
    assert 'class="form-select form-select-sm lg-dymek-select"' in dymek
    assert not re.search(r'[" ]lg-sposob[" ]', dymek)
    assert 'data-lg-sposob' not in dymek and 'data-lg-akcja' not in dymek
    assert 'onSposob: onSposob' in mapa
    assert "addEventListener('change'" in _funkcja(mapa, 'podepnijDymek')
    wyslij = _funkcja(mapa, 'wyslijSposobZDymku')
    assert 'zapisywaneSposoby.add(id)' in wyslij and 'await cb(id, sposob)' in wyslij
    koniec = wyslij[wyslij.index('} finally {'):]
    assert 'zapisywaneSposoby.delete(id)' in koniec and 'odswiezDymek(id, fokus)' in koniec
    assert 'fetch(' not in wyslij and 'wyslij(' not in wyslij        # zapis tylko przez listę
    assert 'm.getPopup().update()' in _funkcja(mapa, 'odswiezDymek')
    assert 'm.onSposob(zmienSposobZMapy)' in _funkcja(lista, 'polaczZMapa')
    zmien = _funkcja(lista, 'zmienSposobZMapy')
    assert 'wyslijSposob([id], sposob)' in zmien and 'podsumujZmiany(wynik, true)' in zmien
    assert "pokazKomunikat('blad', 'Nie zmieniono sposobu dostawy zamówienia '" in zmien
    assert 'clearTimeout(oczekujaceSelecty.get(id))' in zmien


def test_pole_wyboru_ma_odstep_od_krawedzi():
    css = _plik('static', 'css', 'logistics.css')
    assert 'padding-left: 14px !important' in _regula_css(css, '.logistics-tab .lg-k-zaznacz')
    stan = _regula_css(css, '.logistics-tab .lg-tabela th.lg-k-stan,\n.logistics-tab .lg-tabela td.lg-k-stan')
    assert 'padding-right: 14px' in stan
    for prog, px in (('(max-width: 860px)', 12), ('(max-width: 760px)', 9)):
        blok = css[css.index('@container lg-tabela ' + prog):]
        blok = blok[:blok.index('\n}\n')]
        assert '.logistics-tab .lg-k-zaznacz { padding-left: %dpx !important; }' % px in blok, prog
        assert 'td.lg-k-stan { padding-right: %dpx; }' % px in blok, prog
    assert 'padding: 2px 14px 4px 66px;' in _regula_css(css, '.logistics-tab .lg-pozycje')


def test_mapka_trasy_przybliza_kolkiem_od_razu():
    trasy = _plik('static', 'js', 'logistics-routes.js')
    assert 'scrollWheelZoom: true' in _funkcja(trasy, 'zapewnijMapke')
    for fraza in ('scrollWheelZoom: false', 'scrollWheelZoom.enable', 'scrollWheelZoom.disable'):
        assert fraza not in trasy, fraza


def test_wersje_podbite():
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert _wersja(html, 'css/logistics.css') != '20260925i'
    assert _wersja(html, 'js/logistics-map.js') != '20260926b'
    assert _wersja(html, 'js/logistics.js') not in ('20260928a', '20260928b')
    assert _wersja(html, 'js/logistics-routes.js') not in ('20260928b', '20260928c')
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_dymek_ui.py`
Expected: FAIL.

- [ ] **Step 3: `logistics-map.js` — select w dymku i most `onSposob`**

Nagłówek — pod linią `window.LogisticsMap.onBlad(cb) …` (:27–28):
```js
 * Runda 2 (spec 2.2):
 *   window.LogisticsMap.onSposob(cb)                     cb(id, sposob) → Promise — wybór sposobu
 *                                                        w dymku; zapis robi logistics.js (ta sama
 *                                                        droga co select w wierszu listy)
```
Stała — pod `const PASEK_OK_MS = 5000;` (:133):
```js
    // Strzałki na zamkniętym <select> w Windows zmieniają wartość od razu — wysyłamy tę, na
    // której logistyk się zatrzymał (jak ZWLOKA_SELECTA_MS w logistics.js).
    const ZWLOKA_SPOSOBU_MS = 350;
```
Stan — pod `const sluchaczeBledow = [];` (:197):
```js
    const sluchaczeSposobu = [];         // onSposob (runda 2): zapis sposobu z dymku robi lista
    const zapisywaneSposoby = new Set(); // id zamówień, dla których leci zmiana sposobu z dymku
    const timerySposobu = new Map();     // id → zwłoka wyboru w dymku (osobno dla każdego zamówienia)
```
Nad `function dymekHtml(z)` (:355):
```js
    // Kolejność i podpisy jak w wierszu listy: „Nie ustawiono” (wysyłane jako 'brak'), potem SPOSOBY.
    function opcjeSposobu(wybrany) {
        return ['brak'].concat(SPOSOBY).map((s) => '<option value="' + s + '"' +
            (s === wybrany ? ' selected' : '') + '>' + esc(ETYKIETY[s]) + '</option>').join('');
    }

    // Te same blokady co select w wierszu (logistics.js, wierszHtml) — serwer i tak by odmówił.
    function powodBlokadySposobu(z) {
        if (z.wydane) return 'Zamówienie wydane klientowi. Sposobu dostawy nie można już zmienić.';
        if (z.etap && z.etap.status === 'anulowane') return 'Zamówienie anulowane.';
        if (zapisywaneSposoby.has(z.id)) return 'Zapisywanie…';
        return '';
    }
```
W `dymekHtml` przed `return` dodaj:
```js
        // Runda 2 (spec 2.2): wybór sposobu dostawy — te same opcje, podpisy i blokady co select
        // w wierszu listy; zapis robi lista (onSposob). Klasa lg-dymek-select, NIE lg-sposob,
        // i atrybut data-lg-mapa-sposob, nie data-lg-sposob: delegacja listy na #logistics-root
        // wzięłaby je za select wiersza albo za licznik filtra.
        const blokada = powodBlokadySposobu(z);
        const wybor = '<label class="lg-dymek-wybor">' +
            '<span class="lg-pin lg-pin--' + sposob + '" aria-hidden="true"></span>' +
            '<select class="form-select form-select-sm lg-dymek-select" data-lg-mapa-sposob data-id="' + esc(z.id) + '"' +
                ' aria-label="Sposób dostawy zamówienia ' + esc(z.numer) + '"' +
                (blokada ? ' disabled title="' + esc(blokada) + '"' : '') + '>' + opcjeSposobu(sposob) + '</select>' +
            '</label>';
```
a w zwracanym HTML: z `lg-dymek-gora` usuń `<span class="lg-dymek-sposob">…</span>` (zostaje sam numer) i wstaw `wybor +` między blok adresu a `'<dl class="lg-dymek-dane">'`:
```js
            (adres ? '<div class="lg-dymek-adres">' + adres + '</div>' : '') +
            wybor +
            '<dl class="lg-dymek-dane">' +
```
W `podepnijDymek` (:1155–1168), za nasłuchem `click`:
```js
        // Runda 2: wybór sposobu dostawy w dymku (Leaflet nie zatrzymuje `change`).
        el.addEventListener('change', (e) => {
            const s = e.target.closest('select[data-lg-mapa-sposob]');
            if (s && !s.disabled) naZmianeSposobuWDymku(Number(s.getAttribute('data-id')), s.value);
        });
```
Za `podepnijDymek` dodaj:
```js
    // ── Sposób dostawy z dymku (runda 2, spec 2.2) ──────────────────────────

    function naZmianeSposobuWDymku(id, sposob) {
        clearTimeout(timerySposobu.get(id));
        timerySposobu.set(id, setTimeout(() => {
            timerySposobu.delete(id);
            wyslijSposobZDymku(id, sposob);
        }, ZWLOKA_SPOSOBU_MS));
    }

    /**
     * Zapis przez listę: pierwszy słuchacz onSposob (logistics.js) wysyła POST tą samą drogą co
     * select w wierszu i kończy obietnicę PO podmianie wiersza i pinezek. Na czas zapisu select
     * w dymku nieaktywny; potem dymek zawsze od nowa z bieżących danych — po odmowie (także
     * w `bledy` przy HTTP 200: aktualizujZnacznik nie przerysuje dymku, gdy sposób się nie
     * zmienił) i po błędzie połączenia select wraca do wartości z serwera.
     */
    async function wyslijSposobZDymku(id, sposob) {
        const z = zamowienia.get(id);
        const cb = sluchaczeSposobu[0];
        if (zniszczona || !z || !cb || zapisywaneSposoby.has(id) || sposob === kluczSposobu(z.sposob)) {
            odswiezDymek(id, false);
            return;
        }
        const fokus = fokusWDymku(id);
        zapisywaneSposoby.add(id);
        odswiezDymek(id, false);
        try {
            await cb(id, sposob);
        } catch (e) {
            console.error('[LogisticsMap] onSposob:', e);
        } finally {
            zapisywaneSposoby.delete(id);
            if (!zniszczona) odswiezDymek(id, fokus);
        }
    }

    function fokusWDymku(id) {
        const m = znaczniki.get(id);
        const el = m && m.isPopupOpen() ? m.getPopup().getElement() : null;
        return !!(el && el.contains(document.activeElement));
    }

    // Dymek od nowa z bieżących danych (popup.update() woła dymekHtml). `fokus` — wybór wraca pod klawiaturę.
    function odswiezDymek(id, fokus) {
        const m = znaczniki.get(id);
        if (!m || !m.isPopupOpen()) return;
        m.getPopup().update();
        if (!fokus) return;
        const el = m.getPopup().getElement();
        const s = el && el.querySelector('select[data-lg-mapa-sposob]');
        if (s && !s.disabled) s.focus({ preventScroll: true });
    }
```
Pod `function onBlad(cb) {…}` (:2003–2009):
```js
    function onSposob(cb) {
        if (typeof cb === 'function') sluchaczeSposobu.push(cb);
        return () => {
            const i = sluchaczeSposobu.indexOf(cb);
            if (i !== -1) sluchaczeSposobu.splice(i, 1);
        };
    }
```
W `zniszcz()` przy czyszczeniu słuchaczy: `timerySposobu.forEach((t) => clearTimeout(t));`, `timerySposobu.clear();`, `sluchaczeSposobu.length = 0;`, `zapisywaneSposoby.clear();`. W `api` dopisz `onSposob: onSposob,` (obok `onBlad`).

- [ ] **Step 4: `logistics.js` — ścieżka zapisu z dymku**

W nagłówku, w sekcji „Runda 2”, dopisz: ` *   window.LogisticsMap.onSposob(zmienSposobZMapy) — wybór sposobu w dymku pinezki (ta sama droga co select wiersza).`
Za `zmianaSelecta` (:1283):
```js
    /**
     * Runda 2 (spec 2.2): wybór sposobu w dymku pinezki (logistics-map.js, onSposob) — ta sama
     * droga co select w wierszu: POST /orders/delivery-method (wyslijSposob), podsumujZmiany
     * (komunikaty, także odmowy z `bledy`), podmienWiersze → przekazDoMapy (wiersz, liczniki,
     * kolor pinezki). Obietnica kończy się PO podmianie — mapa przerysowuje wtedy dymek.
     */
    async function zmienSposobZMapy(id, sposob) {
        const w = znajdz(id);
        if (zniszczona || !w || stan.wysylane.has(id)) return;
        // Oczekująca zmiana z selecta tego wiersza (zwłoka) ustępuje wyborowi z dymku.
        clearTimeout(oczekujaceSelecty.get(id));
        oczekujaceSelecty.delete(id);
        stan.docelowe.delete(id);
        if (sposob === (w.sposob || 'brak')) {
            odswiezWiersz(id, false);
            return;
        }
        try {
            const dane = await wyslijSposob([id], sposob);
            if (zniszczona) return;
            const wynik = nowyWynik();
            dolacz(wynik, dane);
            podsumujZmiany(wynik, true);
        } catch (e) {
            if (zniszczona) return;
            odswiezWiersz(id, false);
            pokazKomunikat('blad', 'Nie zmieniono sposobu dostawy zamówienia ' + w.numer + '. ' + e.message);
        }
    }
```
W `polaczZMapa` pod `if (typeof m.onBlad === 'function') m.onBlad(naBladMapy);`:
```js
        if (typeof m.onSposob === 'function') m.onSposob(zmienSposobZMapy);
```

- [ ] **Step 5: CSS (`logistics.css`)**

1. :519 →
```css
/* (runda 2, spec 2.3) Pole wyboru ok. 14 px od lewej krawędzi ramki (było 6 px); szerokość
   +8 px, żeby pole i trójkąt rozwinięcia miały tyle miejsca co dotąd. */
.logistics-tab .lg-k-zaznacz { width: 60px; padding-left: 14px !important; padding-right: 0 !important; }
```
2. Za `.logistics-tab .lg-k-stan { width: 1%; }` (:527):
```css
/* (runda 2, spec 2.3) Ostatnia kolumna tyle samo od prawej krawędzi. Specyficzność (0,3,1) —
   wyżej niż ogólne .lg-tabela th/td (0,2,1), także w progach niżej. */
.logistics-tab .lg-tabela th.lg-k-stan,
.logistics-tab .lg-tabela td.lg-k-stan { padding-right: 14px; }
```
3. W `@container lg-tabela (max-width: 860px)` za regułą `th, td { padding-left: 7px; padding-right: 7px; }` (:1124–1125):
```css
    .logistics-tab .lg-k-zaznacz { padding-left: 12px !important; }
    .logistics-tab .lg-tabela th.lg-k-stan,
    .logistics-tab .lg-tabela td.lg-k-stan { padding-right: 12px; }
```
4. W `@container lg-tabela (max-width: 760px)` za regułą z 5 px (:1132–1133):
```css
    .logistics-tab .lg-k-zaznacz { padding-left: 9px !important; }
    .logistics-tab .lg-tabela th.lg-k-stan,
    .logistics-tab .lg-tabela td.lg-k-stan { padding-right: 9px; }
```
5. `.logistics-tab .lg-pozycje` (:2625–2630): `padding: 2px 14px 4px 66px;` z komentarzem `/* (runda 2) Wcięcie pod kolumną „Zamówienie” po poszerzeniu pierwszej kolumny do 60 px; z prawej jak ostatnia kolumna. */`.
6. Reguły `.lg-dymek-sposob` i `.lg-dymek-sposob .lg-pin` (:2120–2133) zastąp:
```css
/* Runda 2 (spec 2.2): sposób dostawy w dymku — ten sam wybór co w wierszu listy. */
.logistics-tab .lg-dymek-wybor { display: flex; align-items: center; gap: 8px; margin: 8px 0 0; }
.logistics-tab .lg-dymek-wybor .lg-pin { flex: none; margin-top: -2px; }
.logistics-tab .lg-dymek-select {
    flex: 1 1 auto; min-width: 0; height: 30px; padding-top: 2px; padding-bottom: 2px; font-size: 12.5px;
    border-color: var(--il-border, #c8cdd5); border-radius: var(--il-radius, 3px);
}
.logistics-tab .lg-dymek-select:disabled { cursor: progress; }
```

- [ ] **Step 6: Mapka trasy (`logistics-routes.js`, `zapewnijMapke`)**

W opcjach `L.map(mapkaEl, {…})` zamień komentarz i `scrollWheelZoom: false,` na:
```js
            // (runda 2, spec 2.7) Kółko myszy przybliża od razu, jak na mapie Dashboardu — bez
            // aktywacji kliknięciem. Świadomy koszt: przewijając edytor z kursorem nad mapką,
            // przybliża się mapka zamiast strony.
            scrollWheelZoom: true,
```
i usuń dwie linie `mapka.on('click', … scrollWheelZoom.enable …)` oraz `mapka.on('mouseout', … scrollWheelZoom.disable …)`.

- [ ] **Step 7: Wersje**

`tab_content.html`: `logistics.css?v=20260928a` (:17), `data-skrypt-mapy … logistics-map.js?v=20260928a` (:184), `data-skrypt-trasy … logistics-routes.js?v=20260928d` (:185), `logistics.js?v=20260928c` (:644).

- [ ] **Step 8: Uruchom testy**

Run: `node --check modules/production/logistics/static/js/logistics-map.js && node --check modules/production/logistics/static/js/logistics.js && node --check modules/production/logistics/static/js/logistics-routes.js`
Expected: bez błędów.
Run: `PYTEST tests/test_logistyka_dymek_ui.py tests/test_logistyka_mapa_ui.py tests/test_logistyka_kafelki.py tests/test_logistyka_trasy_ui.py tests/test_logistyka_poprawki_panelu.py tests/test_logistyka_zakladka.py tests/test_logistyka_wojewodztwa_ui.py tests/test_logistyka_kierowcy_ui.py`
Expected: PASS.

- [ ] **Step 9: Pełny pakiet**

Run: `docker compose -p logistyka3 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider`
Expected: 0 failed.

- [ ] **Step 10: Commit**

```bash
git add tests/test_logistyka_dymek_ui.py
git commit -m "feat(production): sposob dostawy w dymku pinezki, odstep pola wyboru i kolko na mapce trasy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- modules/production/logistics/static/js/logistics-map.js modules/production/logistics/static/js/logistics.js modules/production/logistics/static/js/logistics-routes.js modules/production/logistics/static/css/logistics.css modules/production/logistics/templates/logistics/tab_content.html tests/test_logistyka_dymek_ui.py
```

Oględziny (kontroler, 5003): zmiana sposobu z dymku (kolor pinezki, wiersz, liczniki), odmowa (spakowane → „Nie ustawiono”; zamówienie na trasie zatwierdzonej) — dymek wraca do wartości z serwera, komunikat jak z listy; select nieaktywny w trakcie (pomiar zdarzeń, nie animacji); odstęp pola wyboru i ostatniej kolumny, rozwinięte pozycje pod „Zamówieniem” (1440/1280/1024/768); kółko nad mapką trasy przybliża bez klikania.

---

### Task 6: Dashboard produkcji — logistyka poza pipeline'em (skill `frontend-design`)

**REQUIRED:** `frontend-design:frontend-design` przed kodem UI; styl karty stanowisk (`il-*`, `--il-*`, krój JetBrains Mono dla liczb).

**Files:**
- Modify: `modules/production/templates/components/dashboard-tab-content.html` („8 stanowisk” :122, komentarz i viewBox :139–145, bramka :273–282, pasek za `.il-rail-wrap` :304)
- Modify: `modules/production/static/js/modules/dashboard-module.js` (`rysujSzyneProcesu` :495–534)
- Modify: `modules/production/static/css/production-panel.css` (:2670, :2679–2696, :2756–2758)
- Modify: `modules/production/templates/panel/dashboard.html` (:13, :345)
- Modify: `tests/test_dashboard_krawedzie.py` (`test_grid_czyta_sie_w_kolejnosci_drogi_produktu` :188–202, `test_wysokosc_wiersza_zgadza_sie_w_trzech_miejscach` :285–305, `test_logistyka_nie_udaje_stanowiska_na_hali` :318–334), `tests/test_logistyka_sprzatanie.py` (`test_bramka_dashboardu_liczy_brak_sposobu`)
- Test: `tests/test_dashboard_logistyka_pasek.py`

**Interfaces:**
- Consumes: `dashboard_stats.logistics.pending_count` (bez zmian w `dashboard_api.py`), link `{{ url_for('production.production_main.dashboard') }}?tab=logistics`.
- Produces: `div.il-logistyka[data-lg-pasek="logistyka"]` (klasa `il-logistyka--spokoj` przy 0), `strong#logistics-pending` zawsze w DOM; szyna z 7 węzłami (`viewBox="0 0 54 343"`).

- [ ] **Step 1: Testy (failing)**

`tests/test_dashboard_logistyka_pasek.py`:
```python
# -*- coding: utf-8 -*-
"""Runda 2 logistyki (spec 2.1): logistyka poza pipeline'em dashboardu produkcji — pasek pod
listą stanowisk zamiast bramki na szynie. Testy tekstowe jak tests/test_dashboard_krawedzie.py;
sam pasek renderujemy Jinją (fragment między znacznikami), bez całego dashboardu."""
import os
import re

import pytest
from jinja2 import Environment

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROD = os.path.join(KORZEN, 'modules', 'production')
SZABLON = os.path.join(PROD, 'templates', 'components', 'dashboard-tab-content.html')
PANEL_HTML = os.path.join(PROD, 'templates', 'panel', 'dashboard.html')
DASHBOARD_JS = os.path.join(PROD, 'static', 'js', 'modules', 'dashboard-module.js')
PANEL_CSS = os.path.join(PROD, 'static', 'css', 'production-panel.css')


def _plik(sciezka):
    with open(sciezka, encoding='utf-8') as f:
        return f.read()


def _pasek():
    html = _plik(SZABLON)
    start = html.index("{# ─── LOGISTYKA: pasek pod pipeline'em")
    return html[start:html.index('{# ─── /LOGISTYKA ─── #}', start)]


@pytest.mark.parametrize('n, spokoj', [(0, True), (12, False)])
def test_pasek_pokazuje_liczbe_albo_spokoj(n, spokoj):
    html = Environment(autoescape=True).from_string(_pasek()).render(
        dashboard_stats={'logistics': {'pending_count': n}},
        url_for=lambda endpoint, **k: '/production/')
    assert ('il-logistyka--spokoj' in html) is spokoj
    assert 'id="logistics-pending">%d<' % n in html               # id zostaje w obu stanach
    assert 'bez sposobu dostawy' in html and 'wszystkie zamówienia mają sposób dostawy' in html
    assert 'href="/production/?tab=logistics"' in html and 'Otwórz Logistykę' in html


def test_pasek_pod_pipelineem_w_tej_samej_karcie():
    html = _plik(SZABLON)
    assert 'data-station="logistics"' not in html and 'il-station--gate' not in html
    pasek = _pasek()
    karta = html[html.index('class="dashboard-card stations-card"'):html.index('{# ═══ RIGHT STACK ═══ #}')]
    assert pasek in karta
    assert karta.index('data-station="packaging"') < karta.index(pasek)
    assert '<span class="il-cat-count">7 stanowisk</span>' in html
    for czego_nie_ma in ('-bar-fill', '-tablet-badge', 'station_crew', 'today-m3', 'data-station='):
        assert czego_nie_ma not in pasek, czego_nie_ma


def test_szyna_bez_wezla_logistyki():
    js = _plik(DASHBOARD_JS)
    szyna = js[js.index('rysujSzyneProcesu() {'):js.index('uruchomPrzeplyw() {')]
    kody = re.findall(r"'(\w+)'", re.search(r"const kody = \[([^\]]*)\]", szyna).group(1))
    assert kody == ['cutting', 'assembly', 'gluing', 'formatting', 'edges', 'painting', 'packaging']
    assert 'logistics' not in szyna and '#6366f1' not in szyna and 'Y(7)' not in szyna
    assert 'Y(PAK)' in szyna


def test_css_bez_bramki_i_ze_stanem_spokoju():
    css = _plik(PANEL_CSS)
    assert '.il-rail-gate' not in css and '.il-station[data-station="logistics"]' not in css
    for selektor in ('.il-logistyka {', '.il-logistyka--spokoj', '.il-logistyka-otworz'):
        assert selektor in css, selektor


def test_wersje_zasobow_dashboardu_podbite():
    html = _plik(PANEL_HTML)
    m = re.search(r"filename='js/modules/dashboard-module\.js'\) \}\}\?v=(\w+)", html)
    assert m and m.group(1) != '20260410'
    assert re.search(r"filename='css/production-panel\.css'\) \}\}\?v=\w+", html)
```

W `tests/test_dashboard_krawedzie.py`:
- `test_grid_czyta_sie_w_kolejnosci_drogi_produktu`: w docstringu zamień „na końcu logistyka i pakowanie” na „na końcu pakowanie; logistyki na szynie nie ma (runda 2 logistyki) — jest równoległa, pasek pod listą stanowisk”, a oczekiwaną listę na `['sawmill', 'cutting', 'assembly', 'gluing', 'formatting', 'edges', 'painting', 'packaging']`.
- `test_wysokosc_wiersza_zgadza_sie_w_trzech_miejscach`: w docstringu „`0 0 54 392` = osiem wierszy po 49” → „`0 0 54 343` = siedem wierszy po 49 (od rundy 2 logistyki bez wiersza logistyki; tyle samo `.il-rail-spine` w CSS)”; asercje:
```python
    assert 'viewBox="0 0 54 343"' in html, 'szablon: viewBox szyny'
    assert 'height: 343px;' in css.split('.il-rail-spine {')[1].split('}')[0], 'CSS: wysokość szyny'
    assert 'const WYSOKOSC_WIERSZA = 49;' in js, 'JS: stała wysokości wiersza'
```
- `test_logistyka_nie_udaje_stanowiska_na_hali` — zastąp treść:
```python
def test_logistyka_nie_udaje_stanowiska_na_hali():
    """
    Logistyka liczy zamówienia bez sposobu dostawy: nikt się na niej nie loguje, nie ma tabletu
    ani przerobu w m³. Od rundy 2 logistyki nie stoi nawet na szynie — pasek pod listą stanowisk
    mówi wyłącznie, ile czeka na decyzję, i prowadzi do zakładki.
    """
    html = _plik(SZABLON)

    assert 'data-station="logistics"' not in html and 'il-station--gate' not in html
    blok = html.split('data-lg-pasek="logistyka"')[1].split('</div>')[0]
    assert 'id="logistics-pending"' in blok
    assert 'bez sposobu dostawy' in blok
    for czego_nie_ma in ('-bar-fill', '-tablet-badge', 'station_crew', 'today-m3'):
        assert czego_nie_ma not in blok, czego_nie_ma
```
W `tests/test_logistyka_sprzatanie.py` zastąp `test_bramka_dashboardu_liczy_brak_sposobu`:
```python
def test_pasek_logistyki_dashboardu_liczy_brak_sposobu():
    html = _plik('modules', 'production', 'templates', 'components', 'dashboard-tab-content.html')
    blok = html.split('data-lg-pasek="logistyka"')[1].split('</div>')[0]
    assert 'id="logistics-pending"' in blok
    assert 'bez sposobu dostawy' in blok
    assert '?tab=logistics' in blok
```

- [ ] **Step 2: Uruchom — mają paść**

Run: `PYTEST tests/test_dashboard_logistyka_pasek.py tests/test_dashboard_krawedzie.py tests/test_logistyka_sprzatanie.py`
Expected: FAIL.

- [ ] **Step 3: Szablon**

`:122` → `<span class="il-cat-count">7 stanowisk</span>`. Komentarz :139–143 — „Wysokość 320 = osiem wierszy po 40 px” → „Wysokość 343 = siedem wierszy po 49 px (od rundy 2 logistyki bez wiersza logistyki)”; `:145` → `<svg class="il-rail-spine" viewBox="0 0 54 343" aria-hidden="true"></svg>`. Usuń cały blok `{# LOGISTYKA — równoległa … #}` + `<div class="il-station il-station--gate" data-station="logistics">…</div>` (:273–282 z pustą linią pod nim). Między `        </div>` zamykającym `.il-rail-wrap` (:304) a `      </div>` zamykającym `.il-stations-grid` wstaw:
```html

        {# ─── LOGISTYKA: pasek pod pipeline'em (runda 2 logistyki, spec 2.1) ───
           Logistyka jest równoległa do produkcji — nie stanowisko na szynie. Liczba z
           lista_logistyki.liczba_bez_sposobu() (dashboard_api.py); id „logistics-pending”
           zostaje. Oba teksty są w DOM, stan przełącza klasa (CSS: .il-logistyka--spokoj). #}
        {% set lg_n = dashboard_stats.logistics.pending_count|default(0) %}
        <div class="il-logistyka{{ ' il-logistyka--spokoj' if not lg_n else '' }}" data-lg-pasek="logistyka">
          <i class="fas fa-truck il-logistyka-ikona" aria-hidden="true"></i>
          <p class="il-logistyka-tekst">
            <span class="il-logistyka-nazwa">Logistyka:</span>
            <span class="il-logistyka-liczba"><strong class="il-logistyka-n" id="logistics-pending">{{ lg_n }}</strong> bez sposobu dostawy</span>
            <span class="il-logistyka-spokoj-tekst">wszystkie zamówienia mają sposób dostawy</span>
          </p>
          <a href="{{ url_for('production.production_main.dashboard') }}?tab=logistics" class="il-logistyka-otworz">Otwórz Logistykę<i class="fas fa-arrow-right" aria-hidden="true"></i></a>
        </div>
        {# ─── /LOGISTYKA ─── #}
```

- [ ] **Step 4: Szyna (`dashboard-module.js`, `rysujSzyneProcesu`)**

Zastąp `kody` i `barwy` (:495–503):
```js
        // Kody w kolejności wierszy — węzeł bierze barwę swojego stanowiska. Logistyki tu nie ma
        // (runda 2 logistyki): jest równoległa do produkcji, jej licznik to pasek pod listą.
        const kody = ['cutting', 'assembly', 'gluing', 'formatting',
                      'edges', 'painting', 'packaging'];
        const barwy = {
            cutting: 'var(--il-station-cut)', assembly: 'var(--il-station-asm)',
            gluing: 'var(--il-station-glu)', formatting: 'var(--il-station-fmt)',
            edges: 'var(--il-station-fin)', painting: 'var(--il-station-cmp)',
            packaging: 'var(--il-station-pak)',
        };
        // Pakowanie to ostatni wiersz — na nim kończą się linia bazowa i łuk obejścia.
        const PAK = kody.length - 1;
```
`lukDlugi` (:512): `` const lukDlugi = `M${X},${Y(2)} C${L},${Y(2) + 51} ${L},${Y(PAK) - 51} ${X},${Y(PAK)}`; ``; linia bazowa (:521): `` linia(`M${X},${Y(2)} V${Y(PAK)}`), ``; skoki (:531–532) — zostaw `` skok(`M${X},${Y(5)} V${Y(6)}`) `` zmieniony na `` skok(`M${X},${Y(5)} V${Y(PAK)}`), `` i usuń linię `` skok(`M${X},${Y(6)} V${Y(7)}`), ``.

- [ ] **Step 5: CSS (`production-panel.css`)**

`.il-rail-spine` (:2670): `height: 343px;`. Usuń blok bramki (:2679–2696, komentarz „Logistyka: bramka decyzji…” i reguły `.il-rail-gate*`) oraz regułę barwy (:2756–2758: komentarz „Logistyka nie ma paska postępu…” i `.il-station[data-station="logistics"] { --st: #6366f1; }`). W miejscu bramki:
```css
/* ─── Logistyka: pasek pod pipeline'em (runda 2 logistyki, spec 2.1) ───
   Logistyka jest RÓWNOLEGŁA do produkcji — nie stanowisko na szynie. Pod listą stanowisk, w tej
   samej karcie: liczba otwartych zamówień bez sposobu dostawy i przejście do zakładki. Zero =
   pasek zostaje, wyciszony. Oba teksty są w DOM (#logistics-pending istnieje zawsze), stan
   przełącza klasa --spokoj. */
.il-logistyka {
  display: flex; align-items: center; gap: 10px; margin-top: 10px; padding: 8px 10px 8px 12px;
  background: #fffaf2; border: 1px solid #f1dcc0; border-left: 3px solid var(--il-status-warn);
  border-radius: var(--il-radius);
}
.il-logistyka-ikona { flex: none; font-size: 14px; color: var(--il-status-warn); }
.il-logistyka-tekst { flex: 1; min-width: 0; margin: 0; font-size: 13px; color: var(--il-text-primary); }
.il-logistyka-nazwa { font-weight: 600; margin-right: 4px; }
.il-logistyka-n { font-family: 'JetBrains Mono', monospace; font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; }
.il-logistyka-spokoj-tekst { color: var(--il-text-secondary); }
.il-logistyka-otworz {
  flex: none; display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px;
  background: var(--il-bg-card); border: 1px solid var(--il-border); border-radius: var(--il-radius);
  font-size: 12.5px; font-weight: 600; color: var(--il-text-primary); text-decoration: none; white-space: nowrap;
}
.il-logistyka-otworz:hover { border-color: var(--il-text-secondary); color: var(--il-text-primary); }
.il-logistyka--spokoj { background: var(--il-bg-card); border-color: var(--il-border-light); border-left-color: var(--il-border); }
.il-logistyka--spokoj .il-logistyka-ikona { color: var(--il-text-muted); }
.il-logistyka--spokoj .il-logistyka-liczba,
.il-logistyka:not(.il-logistyka--spokoj) .il-logistyka-spokoj-tekst { display: none; }
```

- [ ] **Step 6: Wersje (`panel/dashboard.html`)**

:13 → `…filename='css/production-panel.css') }}?v=20260928a">`; :345 → `…dashboard-module.js') }}?v=20260928a`.

- [ ] **Step 7: Uruchom testy**

Run: `node --check modules/production/static/js/modules/dashboard-module.js`
Expected: bez błędów.
Run: `PYTEST tests/test_dashboard_logistyka_pasek.py tests/test_dashboard_krawedzie.py tests/test_logistyka_sprzatanie.py tests/test_logistyka_panel_api.py tests/test_sawmill_dashboard_tile.py tests/test_katalog_stanowisk_krawedzie.py`
Expected: PASS.

- [ ] **Step 8: Pełny pakiet**

Run: `docker compose -p logistyka3 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider`
Expected: 0 failed.

- [ ] **Step 9: Commit**

```bash
git add tests/test_dashboard_logistyka_pasek.py
git commit -m "feat(production): logistyka pod pipelineem dashboardu produkcji zamiast bramki na szynie

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- modules/production/templates/components/dashboard-tab-content.html modules/production/static/js/modules/dashboard-module.js modules/production/static/css/production-panel.css modules/production/templates/panel/dashboard.html tests/test_dashboard_logistyka_pasek.py tests/test_dashboard_krawedzie.py tests/test_logistyka_sprzatanie.py
```

Oględziny (kontroler, 5003): szyna cięcie…lakiernia → pakowanie bez węzła logistyki, kropki trafiają w węzły, pasek pod listą (liczba > 0 i stan zero — np. po ustawieniu sposobu wszystkim), „Otwórz Logistykę” prowadzi do zakładki; 1440/1280/1024/768.

---

## Po zadaniach (kontroler, nie implementer)

1. Odśwież kod podglądu 5003 (przekazanie, sekcja 0: `git archive` → `tar` → `docker restart logistyka3-prod`), sprawdź `/login` = 200 i `[Migrations]` w `docker logs logistyka3-prod` (1 wykonana: `2026-09-28-logistyka-kierowcy.sql`); drugi przebieg pliku ręcznie na bazie `logistyka3_prod` (MySQL) bez błędu.
2. MySQL filtra województw na 5003: `GET /production/api/logistics/orders?woj=<każda z 18 opcji>` — suma liczb = liczba bez filtra (rozłączne opcje) i zgodność próbki z `PostcodeToStateMapper.get_state_from_postcode`.
3. Oględziny wszystkich 7 punktów spec (listy „Oględziny” przy zadaniach 2, 4, 5, 6 + kierowcy w edytorze trasy) we wbudowanej przeglądarce; zdarzenia `<dialog>` sprawdzaj pomiarem, nie efektem (karta w tle nie ma klatek animacji).
4. Adwersaryjny przegląd CAŁEJ gałęzi (odłożony z rundy 4.1) — nacisk na Review Focus, regresje tabletów (API mobilne) i eksport Routimo; potem aktualizacja przekazania (sekcje 0, 4, 5, 6: po wdrożeniu logistyk dodaje kierowców we Flocie przed układaniem tras z kierowcą).
