# Logistyka równoległa — Etap 3: trasy, flota, Routimo — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Logistyk układa zamówienia z transportem własnym w trasy (zakres dat, pojazd z floty, kierowca z pracowników produkcji, uporządkowane przystanki, przebieg po drogach z km i czasem), zatwierdza je, eksportuje do Routimo i odhacza jako wykonane; tablet pakowania pokazuje nazwę trasy.

**Architecture:** Tabele `prod_vehicles`, `prod_routes`, `prod_route_stops` w podpakiecie `modules/production/logistics/`. Serwisy: `fleet.py` (pojazdy, kierowcy), `routes.py` (trasy, zajętość zasobów, przystanki, statusy Robocza → Zatwierdzona → Wykonana), `routing.py` (OpenRouteService z fallbackiem na linie proste), `routimo.py` (wspólny generator Excela Routimo, z którego korzysta też stary eksport w raportach). Cykl życia z etapu 1 (`delivery.py`) dostaje regułę „transport własny zamyka dostarczony przystanek” i blokady zmian na trasach; API mobilne wypełnia `transport.trip_*`.

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, MySQL 8.4 / SQLite (testy), `requests`, `openpyxl`, pytest, Leaflet (vendor z etapu 2), vanilla JS (HTML5 drag & drop).

**Spec:** `C:\Users\Grafik\Documents\woodpower-crm\docs\superpowers\specs\2026-09-24-logistyka-rownolegla-trasy-design.md` — sekcje 2 (pkt 9–11), 5.4, 6.2, 6.5, 8, 9–13 (plik poza gitem).

**Poprzednie etapy (ukończone, mogą być NIEWDROŻONE; kod na gałęziach `claude/logistyka-etap-1-dostawy-22cf12` → `claude/logistyka-etap-2-mapa`, każda odbita od poprzedniej — etap 3 budujemy na nowej gałęzi `claude/logistyka-etap-3-trasy` odbitej od gałęzi etapu 2; Konrad nie merguje etapów do `main`, więc nie proponuj merge'a ani pusha na `main` bez jego polecenia; jeśli gałąź etapu 2 nazywa się inaczej, sprawdź `git branch -r | grep logistyka` i zapytaj Konrada):** `docs/superpowers/plans/2026-09-24-logistyka-etap-1-sposob-dostawy.md`, `docs/superpowers/plans/2026-09-24-logistyka-etap-2-mapa.md` (ścieżki względem `C:\Users\Grafik\Documents\woodpower-crm\`).

## Kontekst (dla sesji, która nie widziała rozmowy projektowej)

**Logistyka równoległa** (zatwierdzona 24.09.2026 przez Konrada, właściciela CRM). Etap 1: sposób dostawy
na zamówieniu (`prod_orders.override_delivery_method`: NULL = „Nie ustawiono”, `kurier_baselinker`,
`transport_woodpower`, `odbior_osobisty`), zakładka „Logistyka” w panelu produkcji, blokada pakowania bez
sposobu, zapis do Base. w tle, obiekt `transport` w API mobilnym. Etap 2: współrzędne zamówień
(`prod_order_geo`) i mapa na dashboardzie zakładki. **Ten etap** dodaje trasy transportu własnego i flotę.

**Co poprzednie etapy zostawiły** (stan gałęzi `claude/logistyka-etap-2-mapa` z 25.09.2026, commit `1c9fa686`;
sprawdź `git log --oneline -- modules/production/logistics`). Etap 2 wyszedł poza swój plan na życzenie
Konrada — **ten opis jest ważniejszy niż plany etapów 1–2**:

*Backend*
- `modules/production/logistics/__init__.py` — blueprint `logistics_panel_bp` (`'logistics_panel'`, prefiks
  `/production/api/logistics`), na końcu import routerów (`cron_api`, `panel_api`).
- `models.py` — `LogisticsLog` (akcje: `sposob_dostawy`, `wydane`, `przepakowanie`, `trasa_dodane`,
  `trasa_usuniete`, `trasa_status`, `adres` — **trasowe już są w ENUM**, migracja ich nie dodaje), `OrderGeo`
  (bez relacji na `ProductionOrder` — punkty zawsze przez `geocoding.geo_zamowien(ids)`).
- `sposoby.py` — `KURIER`, `TRANSPORT`, `ODBIOR`, **`BRAK = 'brak'`** (cofnięcie do „Nie ustawiono”), `normalizuj`,
  `etykieta(sposob, nazwa_trasy=None)`, `transport_payload(order, trasa=None)` (czyta `trasa.name`,
  `trasa.date_from`, `trasa.vehicle.name`), `podpowiedz(order)`.
- `services/delivery.py` — `LogistykaBlad(komunikat, status)`, `aktywne_produkty`, `wszystkie_spakowane`,
  `zapisz_log(order, akcja, stara, nowa, user_id, note, route_id, teraz)`, `podbij_pozycje(order, teraz)`,
  `zamkniecie_wyliczone(order)` (gałąź transportu własnego zwraca `False` — **ten etap ją wypełnia**),
  `przelicz_zamkniecie`, `przelicz_otwarte`, `po_spakowaniu`, `wydaj_klientowi`,
  `ustaw_sposob_dostawy(order, sposob, user_id=None, teraz=None)` → `{'zmieniono', 'przepakowanie'}` w **trzech**
  miejscach zwrotu: wczesny (`stary == nowy`), `_cofnij_sposob(order, stary, user_id, teraz)` (dla `sposoby.BRAK`,
  odrzucane przy spakowanym towarze) i główny; **`zmien_adres(order, adres, kod, miasto, user_id=None, teraz=None)`**
  → `bool` (poprawka adresu z listy; znacznik `bl_address_pending`, log `adres`; odrzuca wydane, anulowane,
  zamknięte i z utworzoną przesyłką).
- `services/dzierzawa.py` — `wiersz`, `przejmij`, `odnow`, `zwolnij`, `zapisz(klucz, wartosc)`.
- `services/bl_sync.py` — dopychacz w tle (metoda, status **i adres** do Base.), `CZAS_DZIERZAWY_S = 420` (geokoder: 300), furtka
  `oznacz_wyslane/oznacz_dostarczone` (niewołana — tak zostaje).
- `services/geocoding.py` — `MAGAZYN`, `geo_zamowien(ids) -> {order_id: OrderGeo}`, `_odleglosc_km(a, b)`
  (przybliżenie równoprostokątne, a/b = `(lat, lng)`), geokoder w tle, `postep()`, `bez_lokalizacji()`.
- `adresy.py` — `extract_house_and_apartment_number`, `clean_street_name` (Routimo 1:1),
  `adres_do_geokodowania` (tylko dla geokodera — usuwa „lok 5” itp.).
- `services/lista.py` — `serializuj(order, geo=None)` (klucze m.in. `id`, `numer`, `klient`, `miasto`, `kod`,
  `adres`, `sposob`, `etap`, `termin`, `m3`, `spakowane`, `zamkniete`, `base_czeka`, `przepakowanie`,
  **`pozycje`** (rozwijany wiersz), `geo`); `pobierz(sposob, etap, q, zamkniete)` — **wszystkie filtry muszą
  trafić do zapytania PRZED `order_by/limit`** (uwaga „R3” w docstringu: `filter()` po `limit()` rzuca w SQLAlchemy
  < 2.0); `warunek_bez_sposobu()`, `liczniki()`.
- `routers/panel_api.py` — `guard`, `_user_id()`, `_blad(komunikat, status)`, `_zamowienie_albo_404(id)`,
  `_klucz_carto_basemaps()`; trasy: `GET /tab-content` (przekazuje `magazyn`, `carto_basemaps_key`),
  `GET /orders` (+ `bez_lokalizacji`, `geokoder_dziala`, `geokoder_postep`), `POST /orders/delivery-method`
  (akceptuje też `sposob: "brak"`), `POST /orders/<id>/handed-over`, **`PUT /orders/<id>/address`**,
  `GET|POST /geocode`, `PUT /orders/<id>/geo`, `POST /orders/<id>/geo/reset`. `lista.serializuj` jest wołane
  w **pięciu** miejscach tego pliku (`delivery_method`, `handed_over`, `order_address`, `order_geo`,
  `order_geo_reset`).
- `routers/cron_api.py` — `try/except` z logiem i 500; uruchamia dopychacz i geokoder w tle.
- Migracje: `2026-09-25-logistyka-sposob-dostawy.sql`, `2026-09-26-logistyka-geolokalizacja.sql`,
  `2026-09-26-logistyka-zmiana-adresu.sql`.
- `config/core.json`: `CARTO_BASEMAPS_KEY` (kafelki CARTO; klucz ograniczony do `crm.woodpower.pl` — lokalnie
  kafelki CARTO dają 403, to normalne).

*Frontend*
- `templates/logistics/tab_content.html` (~330 linii): nagłówek `.lg-naglowek` z paskiem podzakładek
  `.lg-podzakladki` (dziś **jeden** przycisk „Dashboard”), liczniki `.lg-liczniki` (`data-lg-sposob=...`),
  baner, układ `.lg-uklad > .lg-uklad-siatka` (lista `.lg-lista` + uchwyt/pastylka proporcji + panel mapy
  `.lg-mapa-panel`); w nagłówku mapy **puste miejsce na przełącznik widoków** `.lg-mapa-widoki`
  (`data-lg-mapa="widoki"`); okno poprawki adresu jako `<dialog class="lg-dialog">` — **wzór dla nowych okien**.
  Skrypty: Leaflet → klastry → `logistics-map.js` ładuje **po kolei** inline loader z atrybutów
  `data-skrypt-*` na `#logistics-map` (skrypty wstawiane przez `executeInlineScripts` są asynchroniczne);
  `logistics.js` jako zwykły `<script src>` na końcu. Wszystkie adresy z parametrem `?v=` (podbijaj przy zmianie).
- `static/js/logistics-map.js` (~1600 linii) — API `window.LogisticsMap`: `render(zamowienia, {dopasuj})`,
  `highlight(id, {przewin})`, `onSelect(cb)`, `onZmiana(cb)`, `ustawNaMapie(z|id)`, `anuluj()`, `zajeta()`,
  `mapa()` (instancja Leaflet), `zniszcz()`, `root`; zdarzenie `logistics:mapa-gotowa`. Wewnątrz: `PODKLADY`
  (Voyager domyślny, Positron, OSM; klucz CARTO z `data-carto-key`, obsługa odrzuconego klucza),
  `nowaWarstwaKafelkow(podklad)`, przełącznik podkładów z miniaturkami i „Grupuj pinezki” (wybór w `localStorage`),
  pastylka proporcji lista/mapa, pasek trybu korekty pinezki. Każde ponowne wykonanie sprząta poprzednią instancję
  (`zniszcz`). **Testy etapu 2 czytają ten konkretny plik** (`tests/test_logistyka_kafelki.py`,
  `tests/test_logistyka_mapa_ui.py`) — nie wynoś z niego podkładów.
- `static/js/logistics.js` (~1970 linii) — lista: sortowanie po nagłówkach, rozwijane pozycje, kolumny
  (zaznacz, Zamówienie, Klient, **Adres** w dwóch liniach, Metoda z Base., Sposób dostawy, Etap, Termin, m³,
  akcje), filtry (fraza po numerze/kliencie/ulicy/kodzie/miejscowości, etap, lokalizacja), hurt
  (`data-lg-akcja`: `hurt-sposob`, `hurt-podpowiedzi`, `odznacz`), `pokazKomunikat(typ, tresc, opcje)`,
  dwuklik w adres = okno poprawki, integracja z mapą. Publicznie wystawia **tylko**
  `window.LogisticsTab = {odswiez, zniszcz}` — `pokazKomunikat` i reszta są prywatne w IIFE.
- `static/css/logistics.css` (~1900 linii), logo Base. `static/img/base-logo.png`.

*Testy*: `tests/logistyka_fixtures.py` (`app`, `client`, `BASE`, `SEKRET_CRONA`, `STATYKA_PRODUKCJI`,
`zamowienie(...)`, `produkt(...)`; `TABLES` z `OrderGeo`); dwa testy porównują wynik `ustaw_sposob_dostawy`
całym słownikiem: `tests/test_logistyka_delivery.py:21`, `tests/test_logistyka_poprawki_panelu.py:76`.

**Otwarte u Konrada z etapu 2 — nie ruszaj:** układ kolumn listy przy 1280 px z paskiem bocznym, pierścień
klastrów. Dlatego ten etap **nie dodaje nowej kolumny** do listy (patrz Task 8).

Jeśli coś w kodzie różni się od tego opisu — dopasuj się do kodu i odnotuj różnicę w raporcie.

**Decyzje (nie dyskutuj ich ponownie):**
1. Trasa: **nazwa** (wymagana), **data od / data do** (trasy bywają wielodniowe), **pojazd** z floty (opcjonalny),
   **kierowca** z aktywnych `prod_workers` (opcjonalny — furtka pod przyszłe stanowisko kierowcy logujące się
   tym samym profilem), **notatka**, **przystanki** z kolejnością ustalaną przeciąganiem.
2. **Flota:** nazwa, rejestracja, ładowność kg (opcjonalna), aktywny. Nigdy nie kasujemy — wyłączamy.
3. **Zajętość:** pojazd albo kierowca na innej trasie `robocza`/`zatwierdzona` w nakładającym się zakresie dat
   jest w wyborze **widoczny, ale wyszarzony z dopiskiem „(zajęty)”**; serwer odrzuca taki zapis (409).
4. **Statusy:** Robocza (pełna edycja) → **Zatwierdzona** (edycja zablokowana, **eksport do Routimo**, można cofnąć
   do roboczej) → **Wykonana** (odhacza ręcznie logistyk; okno z listą przystanków — odznaczone jako
   niedostarczone wracają do puli bez trasy; tylko do odczytu; „Przywróć trasę” w razie pomyłki).
5. Odhaczenie trasy **nie zmienia statusu w Base.** (furtka `bl_sync.oznacz_wyslane/oznacz_dostarczone` zostaje
   niewołana). Nazwa trasy **nie** trafia do Base.
6. Na trasę trafiają wyłącznie zamówienia z transportem własnym. Zmiana sposobu dostawy zamówienia z trasy
   **roboczej** sama zdejmuje je z trasy (log + komunikat „usunięto z trasy X”); z trasy **zatwierdzonej** — 409
   „najpierw cofnij zatwierdzenie”; z trasy **wykonanej** (dostarczone) — 409.
7. Podsumowanie trasy: przystanki, m³, **szacowana waga m³ × 800 kg**, km i czas jazdy; ostrzeżenie (nie blokada),
   gdy waga > ładowność pojazdu.
8. Przebieg: **OpenRouteService** `driving-car`, magazyn → przystanki → magazyn; klucz `OPENROUTESERVICE_API_KEY`
   w `config/core.json` (bez wartości domyślnej w kodzie). Brak klucza / błąd / przystanek bez współrzędnych /
   > 48 przystanków → linie proste, odległość w linii prostej, czas nieznany, dopisek „przebieg przybliżony”.
9. Tablet: `transport.trip_name` = nazwa trasy (roboczej lub zatwierdzonej), `trip_date` = data od,
   `vehicle_name`; etykieta produktu „Dostawa:” = nazwa trasy. Appka już to obsługuje (plan appki vc38).
10. Dashboard: przełącznik widoków mapy **„Zamówienia | Trasy”**; widok Trasy = aktywne trasy, każda w innym
    kolorze, numerowane przystanki, przebieg, legenda; klik → edytor trasy.
11. Interfejs ze skillem `frontend-design:frontend-design`; w UI „Base.”, nie „BaseLinker”.

**Pamięć projektu:** `C:\Users\Grafik\.claude\projects\C--Users-Grafik-Documents-woodpower-crm\memory\`
(`project_logistyka_rownolegla.md`, `feedback_zmiana_core_json_wymaga_restartu.md`, `reference_worktree_docker_testy.md`,
`feedback_commit_style.md`, `feedback_nazwa_base.md`, `project_apk_timeouty_nginx.md`).

## Global Constraints

- Komentarze w kodzie **po polsku**; w UI „Base.” zamiast „BaseLinker”.
- Commity: Conventional Commits po polsku, scope `production` (`reports` dla zmian w raportach), stopka `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Nie commitujemy `docs/superpowers/**`, `config/core.json`, `CLAUDE.local.md`, `MIGRATION_PLAN.md`.
- Gunicorn: sync worker, timeout **30 s**. Jedyne wywołanie zewnętrzne w żądaniu to ORS z `timeout=8` (jedno na zapis trasy); nic więcej zewnętrznego w żądaniu.
- Migracja: `migrations/2026-09-27-logistyka-trasy-flota.sql` (nazwa ma sortować się po migracjach etapów 1–2; przy późniejszej implementacji wolno dać datę dnia implementacji), idempotentna, bez `DELIMITER`.
- Klucz ORS tylko w `config/core.json` (`OPENROUTESERVICE_API_KEY`); zmiana `core.json` na serwerze = od razu restart (memory `feedback_zmiana_core_json_wymaga_restartu`).
- Każda zmiana widoczna na tablecie (przypisanie do trasy, zdjęcie, nazwa/daty/pojazd/status trasy) podbija `updated_at` pozycji zamówień, których dotyczy (`delivery.podbij_pozycje`).
- Każde zadanie UI (Task 8) ze skillem `frontend-design:frontend-design`.
- UI rozbudowuje to, co zbudował etap 2 (patrz Kontekst): te same klasy `lg-*`, okna `<dialog class="lg-dialog">`,
  komunikaty tym samym mechanizmem co lista (`pokazKomunikat`, wystawiony przez `window.LogisticsTab.komunikat` —
  Task 8), parametry `?v=` podbijane przy każdej zmianie pliku statycznego.
  Testy UI etapu 2 (`tests/test_logistyka_mapa_ui.py`, `tests/test_logistyka_kafelki.py`,
  `tests/test_logistyka_poprawki_panelu.py`, `tests/test_logistyka_zakladka.py`) muszą zostać zielone.
- Nowy kod JS w **nowych plikach** (`logistics.js` i `logistics-map.js` mają już po ~2000/1600 linii) — w starych
  tylko punkty zaczepienia.

## Środowisko pracy

```bash
cd /c/Users/Grafik/Documents/woodpower-crm
git fetch origin
git worktree add ../woodpower-crm-logistyka-3 -b claude/logistyka-etap-3-trasy origin/claude/logistyka-etap-2-mapa
cd ../woodpower-crm-logistyka-3
docker compose -p logistyka3 run --rm --no-deps app pytest tests/<plik>.py -v   # dalej: PYTEST <ścieżki>
```
Nie przełączaj gałęzi w głównym checkoucie (pracują tam inne sesje).

**Na macOS** (etap 3 może być realizowany na Macu Konrada):
- repo: `~/Documents/woodpower-crm` — każdą ścieżkę `C:\Users\Grafik\Documents\woodpower-crm\...` z tego planu
  czytaj względem niego; worktree: `cd ~/Documents/woodpower-crm && git fetch origin && git worktree add
  ../woodpower-crm-logistyka-3 -b claude/logistyka-etap-3-trasy origin/claude/logistyka-etap-2-mapa`;
- ten plan i spec leżą w `docs/superpowers/` (poza gitem) — Konrad kopiuje je ręcznie z Windowsa; jeśli ich nie ma
  pod `~/Documents/woodpower-crm/docs/superpowers/`, poproś o nie, zanim zaczniesz;
- pamięć projektu z Windowsa (`C:\Users\Grafik\.claude\...\memory\`) na Macu nie istnieje — cały potrzebny
  kontekst jest w sekcji „Kontekst” tego planu;
- porty z `.env` Maca: aplikacja 5002, MySQL 3308 (patrz CLAUDE.md); lokalna baza Maca nie ma jeszcze migracji
  etapów 1–2 — oględziny w przeglądarce wymagają ich wykonania na **kopii** bazy (Task 9 Step 2), nie na bazie
  roboczej, jeśli równolegle pracuje tam inna sesja; `python3` zamiast `python` w poleceniach spoza Dockera.

## Review Focus

1. **Granice zakresów dat** — trasa 1–3.10 i druga 3–5.10 z tym samym pojazdem kolidują (wspólny dzień); 4–5.10 nie. Test: `test_zajetosc_na_granicy_dat` (Task 3).
2. **Zmiana sposobu dostawy zamówienia, które leży na trasie** — robocza: samo zdjęcie z trasy; zatwierdzona: 409; wykonana: 409. Testy: `test_zmiana_sposobu_zdejmuje_z_roboczej`, `test_zmiana_sposobu_na_zatwierdzonej_to_409`, `test_zmiana_sposobu_dostarczonego_to_409` (Task 4).
3. **Odhaczenie z niedostarczonym przystankiem** — zamówienie wraca do puli (otwarte, bez trasy), tablet traci nazwę trasy, `updated_at` podbite. Test: `test_niedostarczony_wraca_do_puli` (Task 3) + `test_tablet_traci_trase_po_zdjeciu` (Task 4).
4. **ORS niedostępny / brak klucza / przystanek bez współrzędnych** — trasa zapisuje się, przebieg przybliżony. Testy: `test_brak_klucza_to_linie_proste`, `test_blad_ors_to_linie_proste`, `test_przystanek_bez_wspolrzednych` (Task 5).
5. **Dwa zamówienia tej samej trasy w jednym żądaniu dodania, duplikaty id, zamówienie już na innej trasie** — bez błędu unikalności z bazy, czytelne komunikaty per zamówienie. Test: `test_dodanie_duplikatow_i_zajetych` (Task 3).
6. **Cofnięcie do „Nie ustawiono” (etap 2) zamówienia z trasy** — robocza: zdjęcie z trasy; zatwierdzona/wykonana: 409. Testy: `test_cofniecie_zdejmuje_z_roboczej`, `test_cofniecie_na_zatwierdzonej_to_409` (Task 4).
7. **Poprawka adresu (etap 2) zamówienia z trasy zatwierdzonej** — 409 „cofnij zatwierdzenie” (eksport do Routimo miałby stary adres); na roboczej adres się zmienia, zamówienie zostaje na trasie. Testy: `test_zmiana_adresu_na_zatwierdzonej_to_409`, `test_zmiana_adresu_na_roboczej_zostaje_na_trasie` (Task 4).

---

## Mapa plików

**Nowe:** `migrations/2026-09-27-logistyka-trasy-flota.sql`, `modules/production/logistics/services/fleet.py`, `modules/production/logistics/services/routes.py`, `modules/production/logistics/services/routing.py`, `modules/production/logistics/services/routimo.py`, `modules/production/logistics/routers/trasy_api.py`, `modules/production/logistics/static/js/logistics-routes.js`, `modules/production/logistics/static/js/logistics-fleet.js`, `modules/production/logistics/static/css/logistics-trasy.css`, testy `tests/test_logistyka_trasy_*.py`.

**Modyfikowane:** `modules/production/logistics/models.py`, `modules/production/logistics/__init__.py`, `modules/production/logistics/services/delivery.py`, `modules/production/logistics/services/lista.py`, `modules/production/services/mobile_api_service.py`, `modules/production/services/label_print_service.py`, `modules/reports/routers.py` (`generate_routimo_excel` na wspólnym generatorze), szablon/JS/CSS zakładki, `tests/logistyka_fixtures.py`, `tests/test_logistyka_delivery.py` (etap 1 — nowy klucz w wyniku), `CLAUDE.md`.

---

### Task 1: Tabele floty i tras

**Files:**
- Modify: `modules/production/logistics/models.py`
- Create: `migrations/2026-09-27-logistyka-trasy-flota.sql`
- Modify: `tests/logistyka_fixtures.py` (tabele w `TABLES`, fabryki `pojazd`, `kierowca`)
- Test: `tests/test_logistyka_trasy_schemat.py`

**Interfaces:**
- Produces: `STATUSY_TRASY = ('robocza', 'zatwierdzona', 'wykonana')`; modele `Vehicle` (`prod_vehicles`), `Route` (`prod_routes`, relacje `vehicle`, `driver` → `ProductionWorker`, `stops` uporządkowane po `position`, cascade delete-orphan), `RouteStop` (`prod_route_stops`, `order_id` UNIQUE, relacja `route`). Fabryki testowe `pojazd(name='Iveco', capacity_kg=None, is_active=True)`, `kierowca(imie='Jan', nazwisko='Kowalski')`.

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_trasy_schemat.py`:
```python
# -*- coding: utf-8 -*-
import os
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.production.logistics.models import Route, RouteStop, Vehicle
from tests.logistyka_fixtures import app, kierowca, pojazd, zamowienie  # noqa: F401

MIGRACJA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', '2026-09-27-logistyka-trasy-flota.sql')


def test_trasa_z_przystankami_w_kolejnosci(app):
    with app.app_context():
        v, k = pojazd(), kierowca()
        trasa = Route(name='Kraków', date_from=date(2026, 10, 1), date_to=date(2026, 10, 2),
                      vehicle_id=v.id, driver_worker_id=k.id)
        db.session.add(trasa)
        db.session.flush()
        a, b = zamowienie(), zamowienie()
        db.session.add_all([RouteStop(route_id=trasa.id, order_id=b.id, position=2),
                            RouteStop(route_id=trasa.id, order_id=a.id, position=1)])
        db.session.commit()
        assert trasa.status == 'robocza'
        assert [s.order_id for s in trasa.stops] == [a.id, b.id]
        assert trasa.vehicle.name == v.name and trasa.driver.first_name == 'Jan'


def test_zamowienie_na_jednej_trasie(app):
    with app.app_context():
        o = zamowienie()
        t1 = Route(name='A', date_from=date(2026, 10, 1), date_to=date(2026, 10, 1))
        t2 = Route(name='B', date_from=date(2026, 10, 1), date_to=date(2026, 10, 1))
        db.session.add_all([t1, t2])
        db.session.flush()
        db.session.add_all([RouteStop(route_id=t1.id, order_id=o.id, position=1),
                            RouteStop(route_id=t2.id, order_id=o.id, position=1)])
        with pytest.raises(IntegrityError):
            db.session.commit()


def test_migracja_tras():
    sql = open(MIGRACJA, encoding='utf-8').read()
    for tabela in ('prod_vehicles', 'prod_routes', 'prod_route_stops'):
        assert 'CREATE TABLE IF NOT EXISTS {}'.format(tabela) in sql
    assert 'LONGTEXT' in sql and 'DELIMITER' not in sql
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_trasy_schemat.py`
Expected: FAIL (brak modeli i fabryk).

- [ ] **Step 3: Modele**

Dopisz do `modules/production/logistics/models.py` (importy: `Boolean`, `Date`, `Numeric`, `Text` z `sqlalchemy`, `relationship` z `sqlalchemy.orm`, `LONGTEXT` z `sqlalchemy.dialects.mysql`):
```python
STATUSY_TRASY = ('robocza', 'zatwierdzona', 'wykonana')


class Vehicle(db.Model):
    """Pojazd floty. Nigdy nie kasujemy — wyłączamy (is_active=False)."""
    __tablename__ = 'prod_vehicles'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    registration = Column(String(20))
    capacity_kg = Column(Integer)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, default=get_local_now, nullable=False)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)
    deactivated_at = Column(DateTime)


class Route(db.Model):
    """Trasa transportu własnego: Robocza → Zatwierdzona → Wykonana."""
    __tablename__ = 'prod_routes'

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    date_from = Column(Date, nullable=False, index=True)
    date_to = Column(Date, nullable=False, index=True)
    status = Column(Enum(*STATUSY_TRASY, name='route_status'), nullable=False,
                    default='robocza', index=True)
    vehicle_id = Column(Integer, ForeignKey('prod_vehicles.id', ondelete='SET NULL'), index=True)
    driver_worker_id = Column(Integer, ForeignKey('prod_workers.id', ondelete='SET NULL'), index=True)
    notes = Column(Text)
    approved_at = Column(DateTime)
    approved_by = Column(Integer)
    completed_at = Column(DateTime)
    completed_by = Column(Integer)
    created_at = Column(DateTime, default=get_local_now, nullable=False)
    created_by = Column(Integer)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)
    # Cache przebiegu z ORS; przeliczany, gdy zmieni się geometry_hash (kolejność + współrzędne).
    geometry_json = Column(Text().with_variant(LONGTEXT(), 'mysql'))
    distance_km = Column(Numeric(8, 1))
    duration_min = Column(Integer)
    geometry_hash = Column(String(40))
    geometry_approx = Column(Boolean, nullable=False, default=False)

    vehicle = relationship('Vehicle')
    driver = relationship('ProductionWorker')
    stops = relationship('RouteStop', back_populates='route', order_by='RouteStop.position',
                         cascade='all, delete-orphan')


class RouteStop(db.Model):
    """Przystanek = zamówienie na trasie. Zamówienie jest na co najwyżej jednej trasie."""
    __tablename__ = 'prod_route_stops'

    id = Column(Integer, primary_key=True)
    route_id = Column(Integer, ForeignKey('prod_routes.id', ondelete='CASCADE'),
                      nullable=False, index=True)
    order_id = Column(Integer, ForeignKey('prod_orders.id', ondelete='CASCADE'),
                      nullable=False, unique=True)
    position = Column(Integer, nullable=False)

    route = relationship('Route', back_populates='stops')
```

- [ ] **Step 4: Migracja**

`migrations/2026-09-27-logistyka-trasy-flota.sql`:
```sql
-- Logistyka równoległa, etap 3: flota, trasy, przystanki. Idempotentna.

CREATE TABLE IF NOT EXISTS prod_vehicles (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    registration VARCHAR(20) NULL,
    capacity_kg INT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NULL,
    deactivated_at DATETIME NULL,
    KEY ix_prod_vehicles_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS prod_routes (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    status ENUM('robocza','zatwierdzona','wykonana') NOT NULL DEFAULT 'robocza',
    vehicle_id INT NULL,
    driver_worker_id INT NULL,
    notes TEXT NULL,
    approved_at DATETIME NULL,
    approved_by INT NULL,
    completed_at DATETIME NULL,
    completed_by INT NULL,
    created_at DATETIME NOT NULL,
    created_by INT NULL,
    updated_at DATETIME NULL,
    geometry_json LONGTEXT NULL,
    distance_km DECIMAL(8,1) NULL,
    duration_min INT NULL,
    geometry_hash CHAR(40) NULL,
    geometry_approx TINYINT(1) NOT NULL DEFAULT 0,
    KEY ix_prod_routes_date_from (date_from),
    KEY ix_prod_routes_date_to (date_to),
    KEY ix_prod_routes_status (status),
    KEY ix_prod_routes_vehicle_id (vehicle_id),
    KEY ix_prod_routes_driver_worker_id (driver_worker_id),
    CONSTRAINT fk_prod_routes_vehicle FOREIGN KEY (vehicle_id)
        REFERENCES prod_vehicles (id) ON DELETE SET NULL,
    CONSTRAINT fk_prod_routes_driver FOREIGN KEY (driver_worker_id)
        REFERENCES prod_workers (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS prod_route_stops (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    route_id INT NOT NULL,
    order_id INT NOT NULL,
    position INT NOT NULL,
    UNIQUE KEY uq_prod_route_stops_order (order_id),
    KEY ix_prod_route_stops_route_id (route_id),
    CONSTRAINT fk_prod_route_stops_route FOREIGN KEY (route_id)
        REFERENCES prod_routes (id) ON DELETE CASCADE,
    CONSTRAINT fk_prod_route_stops_order FOREIGN KEY (order_id)
        REFERENCES prod_orders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

- [ ] **Step 5: Fixture**

W `tests/logistyka_fixtures.py`: import `Route, RouteStop, Vehicle` i dopisz ich tabele do `TABLES` **po** `ProductionWorker` i `ProductionOrder` (kolejność FK). Dodaj fabryki:
```python
def pojazd(name=None, capacity_kg=None, is_active=True, registration=None):
    from modules.production.logistics.models import Vehicle
    numer = next(_licznik)
    v = Vehicle(name=name or 'Pojazd %d' % numer, registration=registration or 'KR %05d' % numer,
                capacity_kg=capacity_kg, is_active=is_active)
    db.session.add(v)
    db.session.commit()
    return v


def kierowca(imie='Jan', nazwisko=None, aktywny=True):
    k = ProductionWorker(first_name=imie, last_name=nazwisko or 'Kierowca %d' % next(_licznik),
                         is_active=aktywny)
    db.session.add(k)
    db.session.commit()
    return k
```

- [ ] **Step 6: Uruchom testy**

Run: `PYTEST tests/test_logistyka_trasy_schemat.py tests/test_migration_service.py`
Expected: PASS (SQLite egzekwuje UNIQUE → `IntegrityError`).

- [ ] **Step 7: Commit**

```bash
git add modules/production/logistics/models.py migrations/2026-09-27-logistyka-trasy-flota.sql tests/logistyka_fixtures.py tests/test_logistyka_trasy_schemat.py
git commit -m "feat(production): tabele floty, tras i przystankow

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Flota i kierowcy — serwis

**Files:**
- Create: `modules/production/logistics/services/fleet.py`
- Test: `tests/test_logistyka_trasy_flota.py`

**Interfaces:**
- Consumes: `Vehicle` (Task 1), `ProductionWorker`, `LogistykaBlad`.
- Produces: `serializuj_pojazd(v) -> dict` (`id, name, registration, capacity_kg, is_active`); `lista_pojazdow(tylko_aktywne=False) -> list[dict]`; `zapisz_pojazd(dane: dict, pojazd=None) -> Vehicle` (422 przy błędach); `ustaw_aktywnosc(pojazd, aktywny: bool) -> Vehicle`; `kierowcy() -> list[dict]` (`id, nazwa`, tylko aktywni, sortowanie `sort_order`, `last_name`).

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_trasy_flota.py`:
```python
# -*- coding: utf-8 -*-
import pytest

from extensions import db
from modules.production.logistics.services import fleet
from modules.production.logistics.services.delivery import LogistykaBlad
from tests.logistyka_fixtures import app, kierowca, pojazd  # noqa: F401


def test_zapis_pojazdu_normalizuje_dane(app):
    with app.app_context():
        v = fleet.zapisz_pojazd({'name': '  Iveco Daily ', 'registration': ' rze 12345 ',
                                 'capacity_kg': '1200'})
        db.session.commit()
        assert fleet.serializuj_pojazd(v) == {'id': v.id, 'name': 'Iveco Daily',
                                              'registration': 'RZE 12345', 'capacity_kg': 1200,
                                              'is_active': True}


@pytest.mark.parametrize('dane', [
    {'name': ''}, {'name': 'x' * 101}, {'name': 'A', 'capacity_kg': '-5'},
    {'name': 'A', 'capacity_kg': 'dużo'}, {'name': 'A', 'registration': 'x' * 21},
])
def test_walidacja_pojazdu(app, dane):
    with app.app_context():
        with pytest.raises(LogistykaBlad) as e:
            fleet.zapisz_pojazd(dane)
        assert e.value.status == 422


def test_wylaczenie_nie_kasuje(app):
    with app.app_context():
        v = pojazd()
        fleet.ustaw_aktywnosc(v, False)
        db.session.commit()
        assert v.deactivated_at is not None
        assert [p['id'] for p in fleet.lista_pojazdow(tylko_aktywne=True)] == []
        assert [p['id'] for p in fleet.lista_pojazdow()] == [v.id]
        fleet.ustaw_aktywnosc(v, True)
        assert v.deactivated_at is None


def test_kierowcy_tylko_aktywni(app):
    with app.app_context():
        k = kierowca(imie='Adam', nazwisko='Nowak')
        kierowca(imie='Ex', aktywny=False)
        assert fleet.kierowcy() == [{'id': k.id, 'nazwa': 'Adam Nowak'}]
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_trasy_flota.py`
Expected: FAIL.

- [ ] **Step 3: Implementacja**

`modules/production/logistics/services/fleet.py`:
```python
# -*- coding: utf-8 -*-
"""Flota pojazdów i lista kierowców (pracownicy produkcji) — spec 8.1."""
from extensions import db
from modules.production.logistics.models import Vehicle
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.models import ProductionWorker, get_local_now

MAKS_LADOWNOSC_KG = 100000


def serializuj_pojazd(v):
    return {'id': v.id, 'name': v.name, 'registration': v.registration,
            'capacity_kg': v.capacity_kg, 'is_active': bool(v.is_active)}


def lista_pojazdow(tylko_aktywne=False):
    zapytanie = Vehicle.query
    if tylko_aktywne:
        zapytanie = zapytanie.filter(Vehicle.is_active.is_(True))
    return [serializuj_pojazd(v) for v in zapytanie.order_by(Vehicle.name).all()]


def zapisz_pojazd(dane, pojazd=None):
    nazwa = (dane.get('name') or '').strip()
    if not nazwa or len(nazwa) > 100:
        raise LogistykaBlad(u'Podaj nazwę pojazdu (do 100 znaków).', status=422)
    rejestracja = ' '.join((dane.get('registration') or '').upper().split()) or None
    if rejestracja and len(rejestracja) > 20:
        raise LogistykaBlad(u'Numer rejestracyjny może mieć najwyżej 20 znaków.', status=422)
    ladownosc = dane.get('capacity_kg')
    if ladownosc in (None, ''):
        ladownosc = None
    else:
        try:
            ladownosc = int(ladownosc)
        except (TypeError, ValueError):
            raise LogistykaBlad(u'Ładowność podaj w pełnych kilogramach.', status=422)
        if not 0 < ladownosc <= MAKS_LADOWNOSC_KG:
            raise LogistykaBlad(u'Ładowność musi być dodatnia.', status=422)
    if pojazd is None:
        pojazd = Vehicle(is_active=True)
        db.session.add(pojazd)
    pojazd.name, pojazd.registration, pojazd.capacity_kg = nazwa, rejestracja, ladownosc
    db.session.flush()
    return pojazd


def ustaw_aktywnosc(pojazd, aktywny):
    pojazd.is_active = bool(aktywny)
    pojazd.deactivated_at = None if aktywny else get_local_now()
    return pojazd


def kierowcy():
    pracownicy = (ProductionWorker.query.filter(ProductionWorker.is_active.is_(True))
                  .order_by(ProductionWorker.sort_order, ProductionWorker.last_name).all())
    return [{'id': p.id, 'nazwa': u'{} {}'.format(p.first_name, p.last_name).strip()}
            for p in pracownicy]
```

- [ ] **Step 4: Uruchom testy**

Run: `PYTEST tests/test_logistyka_trasy_flota.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/production/logistics/services/fleet.py tests/test_logistyka_trasy_flota.py
git commit -m "feat(production): serwis floty pojazdow i listy kierowcow

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Trasy — zajętość, przystanki, statusy

**Files:**
- Create: `modules/production/logistics/services/routes.py`
- Test: `tests/test_logistyka_trasy_serwis.py`

**Interfaces:**
- Consumes: `Route`, `RouteStop`, `Vehicle` (Task 1), `fleet.serializuj_pojazd`, `fleet.kierowcy` (Task 2), `delivery.LogistykaBlad`, `delivery.zapisz_log`, `delivery.podbij_pozycje`, `delivery.przelicz_zamkniecie` (etap 1), `sposoby.TRANSPORT`, `sposoby.normalizuj`.
- Produces (moduł `modules.production.logistics.services.routes`):
  - `AKTYWNE = ('robocza', 'zatwierdzona')`, `WAGA_KG_NA_M3 = 800`,
  - `zajetosc(date_from, date_to, pomin_route_id=None) -> {'pojazdy': {vehicle_id: nazwa_trasy}, 'kierowcy': {worker_id: nazwa_trasy}}`,
  - `dostepnosc(date_from, date_to, pomin_route_id=None) -> {'pojazdy': [pojazd + {'zajety', 'trasa'}], 'kierowcy': [kierowca + {'zajety', 'trasa'}]}`,
  - `utworz(dane, user_id=None) -> Route`, `edytuj(route, dane, user_id=None) -> Route` (`dane`: `name`, `date_from`, `date_to` (ISO), `vehicle_id`, `driver_worker_id`, `notes`),
  - `przystanek_zamowienia(order_id) -> RouteStop | None`, `trasy_zamowien(order_ids) -> {order_id: Route}`, `mapa_tras_aktywnych() -> {order_id: Route}`, `trasa_dla_tabletu(order_id) -> Route | None` (cache w `flask.g` na żądanie),
  - `dodaj_przystanki(route, order_ids, user_id=None) -> {'dodane': [id], 'bledy': [{'order_id', 'komunikat'}]}`,
  - `usun_przystanek(route, order_id, user_id=None, note=None, wymagaj_roboczej=True) -> ProductionOrder`,
  - `zmien_kolejnosc(route, order_ids) -> None`,
  - `zatwierdz(route, user_id=None)`, `cofnij_do_roboczej(route, user_id=None)`, `wykonaj(route, dostarczone_ids=None, user_id=None) -> {'dostarczone': [id], 'niedostarczone': [id]}`, `przywroc(route, user_id=None)`, `usun(route, user_id=None)`,
  - `zamowienia_trasy(route) -> list[ProductionOrder]` (w kolejności przystanków),
  - `podsumowanie(route, zamowienia, punkty) -> dict` (`przystanki, m3, waga_kg, km, minuty, przyblizony, bez_lokalizacji, przekroczona_ladownosc`),
  - `serializuj_trase(route, zamowienia=None, punkty=None) -> dict` (bez przystanków; przystanki składa API).
- Wszystkie funkcje zmieniające **nie commitują**.

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_trasy_serwis.py`:
```python
# -*- coding: utf-8 -*-
from datetime import date, datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog, RouteStop
from modules.production.logistics.services import routes
from modules.production.logistics.services.delivery import LogistykaBlad
from tests.logistyka_fixtures import app, kierowca, pojazd, zamowienie  # noqa: F401


def _trasa(od='2026-10-01', do=None, **dane):
    dane.setdefault('name', 'Trasa %s' % od)
    trasa = routes.utworz(dict(dane, date_from=od, date_to=do or od))
    db.session.commit()
    return trasa


def _transport(**kolumny):
    return zamowienie(sposob=s.TRANSPORT, **kolumny)


def test_utworzenie_i_walidacja(app):
    with app.app_context():
        t = _trasa(name='  Kraków + Tarnów ', od='2026-10-01', do='2026-10-02')
        assert (t.name, t.status, t.date_to) == ('Kraków + Tarnów', 'robocza', date(2026, 10, 2))
        for zle in ({'name': ''}, {'name': 'A', 'date_from': 'jutro'},
                    {'name': 'A', 'date_from': '2026-10-02', 'date_to': '2026-10-01'}):
            dane = dict({'date_from': '2026-10-01'}, **zle)
            with pytest.raises(LogistykaBlad) as e:
                routes.utworz(dane)
            assert e.value.status == 422


@pytest.mark.parametrize('od, do, zajety', [
    ('2026-10-03', '2026-10-05', True),   # wspólny dzień 3.10
    ('2026-09-28', '2026-10-01', True),
    ('2026-10-04', '2026-10-05', False),
    ('2026-09-28', '2026-09-30', False),
])
def test_zajetosc_na_granicy_dat(app, od, do, zajety):
    """Review Focus 1."""
    with app.app_context():
        v, k = pojazd(), kierowca()
        _trasa(od='2026-10-01', do='2026-10-03', vehicle_id=v.id, driver_worker_id=k.id)
        z = routes.zajetosc(date.fromisoformat(od), date.fromisoformat(do))
        assert (v.id in z['pojazdy']) is zajety and (k.id in z['kierowcy']) is zajety
        d = routes.dostepnosc(date.fromisoformat(od), date.fromisoformat(do))
        assert d['pojazdy'][0]['zajety'] is zajety


def test_zajety_pojazd_odrzucony_a_wykonana_trasa_nie_blokuje(app):
    with app.app_context():
        v = pojazd()
        t = _trasa(vehicle_id=v.id)
        with pytest.raises(LogistykaBlad) as e:
            routes.utworz({'name': 'Druga', 'date_from': '2026-10-01', 'vehicle_id': v.id})
        assert e.value.status == 409 and t.name in e.value.komunikat
        t.status = 'wykonana'
        db.session.commit()
        assert routes.utworz({'name': 'Druga', 'date_from': '2026-10-01', 'vehicle_id': v.id})


def test_edycja_nie_koliduje_sama_ze_soba(app):
    with app.app_context():
        v = pojazd()
        t = _trasa(vehicle_id=v.id)
        routes.edytuj(t, {'name': 'Nowa', 'date_from': '2026-10-01', 'date_to': '2026-10-02',
                          'vehicle_id': v.id})
        assert t.name == 'Nowa'


def test_wylaczony_pojazd_odrzucony(app):
    with app.app_context():
        v = pojazd(is_active=False)
        with pytest.raises(LogistykaBlad):
            routes.utworz({'name': 'A', 'date_from': '2026-10-01', 'vehicle_id': v.id})


def test_dodanie_duplikatow_i_zajetych(app):
    """Review Focus 5."""
    with app.app_context():
        t1, t2 = _trasa(name='Pierwsza'), _trasa(name='Druga')
        a, b = _transport(), _transport()
        kurier = zamowienie(sposob=s.KURIER)
        routes.dodaj_przystanki(t1, [b.id])
        wynik = routes.dodaj_przystanki(t2, [a.id, a.id, b.id, kurier.id, 999999])
        db.session.commit()
        assert wynik['dodane'] == [a.id]
        komunikaty = {x['order_id']: x['komunikat'] for x in wynik['bledy']}
        assert 'Pierwsza' in komunikaty[b.id]
        assert 'transportu własnego' in komunikaty[kurier.id]
        assert 999999 in komunikaty


def test_przystanki_numerowane_i_kolejnosc(app):
    with app.app_context():
        t = _trasa()
        a, b, c = _transport(), _transport(), _transport()
        routes.dodaj_przystanki(t, [a.id, b.id, c.id])
        routes.zmien_kolejnosc(t, [c.id, a.id, b.id])
        db.session.commit()
        assert [x.order_id for x in t.stops] == [c.id, a.id, b.id]
        routes.usun_przystanek(t, a.id)
        db.session.commit()
        assert [(x.order_id, x.position) for x in t.stops] == [(c.id, 1), (b.id, 2)]
        with pytest.raises(LogistykaBlad):
            routes.zmien_kolejnosc(t, [c.id])


def test_dodanie_podbija_pozycje_i_loguje(app):
    with app.app_context():
        t = _trasa()
        o = _transport()
        for p in o.products:
            p.updated_at = datetime(2026, 1, 1)
        db.session.commit()
        routes.dodaj_przystanki(t, [o.id])
        db.session.commit()
        assert all(p.updated_at > datetime(2026, 1, 1) for p in o.products)
        log = LogisticsLog.query.filter_by(order_id=o.id, action='trasa_dodane').one()
        assert log.route_id == t.id


def test_zatwierdzona_jest_zablokowana(app):
    with app.app_context():
        t = _trasa()
        with pytest.raises(LogistykaBlad):
            routes.zatwierdz(t)  # bez przystanków
        o = _transport()
        routes.dodaj_przystanki(t, [o.id])
        routes.zatwierdz(t)
        db.session.commit()
        assert t.status == 'zatwierdzona' and t.approved_at is not None
        for akcja in (lambda: routes.dodaj_przystanki(t, [_transport().id]),
                      lambda: routes.usun_przystanek(t, o.id),
                      lambda: routes.edytuj(t, {'name': 'X', 'date_from': '2026-10-01'})):
            with pytest.raises(LogistykaBlad) as e:
                akcja()
            assert e.value.status == 409
        routes.cofnij_do_roboczej(t)
        assert t.status == 'robocza'


def test_niedostarczony_wraca_do_puli(app):
    """Review Focus 3."""
    with app.app_context():
        t = _trasa()
        a = _transport(statusy=('spakowane',))
        b = _transport(statusy=('spakowane',))
        routes.dodaj_przystanki(t, [a.id, b.id])
        wynik = routes.wykonaj(t, dostarczone_ids=[a.id])
        db.session.commit()
        assert wynik == {'dostarczone': [a.id], 'niedostarczone': [b.id]}
        assert t.status == 'wykonana' and t.completed_at is not None
        assert a.logistics_closed_at is not None
        assert b.logistics_closed_at is None
        assert RouteStop.query.filter_by(order_id=b.id).first() is None
        notatka = LogisticsLog.query.filter_by(order_id=b.id, action='trasa_usuniete').one().note
        assert notatka == 'niedostarczone'


def test_przywrocenie_otwiera_zamowienia(app):
    with app.app_context():
        t = _trasa()
        a = _transport(statusy=('spakowane',))
        routes.dodaj_przystanki(t, [a.id])
        routes.wykonaj(t)
        db.session.commit()
        routes.przywroc(t)
        db.session.commit()
        assert t.status == 'zatwierdzona' and a.logistics_closed_at is None


def test_usuniecie_roboczej(app):
    with app.app_context():
        t = _trasa()
        a = _transport()
        routes.dodaj_przystanki(t, [a.id])
        routes.usun(t)
        db.session.commit()
        assert routes.przystanek_zamowienia(a.id) is None


def test_podsumowanie_i_ladownosc(app):
    with app.app_context():
        v = pojazd(capacity_kg=100)
        t = _trasa(vehicle_id=v.id)
        o = _transport(statusy=('spakowane', 'spakowane'))   # 2 × 0.024 m³ × 2 szt.
        routes.dodaj_przystanki(t, [o.id])
        db.session.commit()
        sumy = routes.podsumowanie(t, routes.zamowienia_trasy(t), {})
        assert sumy['przystanki'] == 1
        assert sumy['m3'] == pytest.approx(0.096)
        assert sumy['waga_kg'] == 77
        assert sumy['przekroczona_ladownosc'] is False
        assert sumy['bez_lokalizacji'] == 1


def test_mapa_tras_aktywnych(app):
    with app.app_context():
        t = _trasa()
        a = _transport()
        routes.dodaj_przystanki(t, [a.id])
        db.session.commit()
        assert routes.mapa_tras_aktywnych() == {a.id: t}
        t.status = 'wykonana'
        db.session.commit()
        assert routes.mapa_tras_aktywnych() == {}
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_trasy_serwis.py`
Expected: FAIL.

- [ ] **Step 3: Implementacja**

`modules/production/logistics/services/routes.py`:
```python
# -*- coding: utf-8 -*-
"""
Trasy transportu własnego (spec, sekcja 8.2).

Statusy: robocza (pełna edycja) → zatwierdzona (zablokowana, eksport Routimo)
→ wykonana (tylko odczyt; przywracana do zatwierdzonej). Funkcje NIE commitują.
Każda zmiana widoczna na tablecie podbija updated_at pozycji zamówień
(ETag kolejek tabletów — spec 6.5).
"""
from datetime import date

from extensions import db
from modules.production.logistics import sposoby
from modules.production.logistics.models import Route, RouteStop, Vehicle
from modules.production.logistics.services import delivery, fleet
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.models import ProductionOrder, ProductionWorker, get_local_now

AKTYWNE = ('robocza', 'zatwierdzona')
WAGA_KG_NA_M3 = 800
MAKS_NAZWA = 120


# ── Pomocnicze ─────────────────────────────────────────────────────────────

def _data(wartosc, pole):
    if isinstance(wartosc, date):
        return wartosc
    try:
        return date.fromisoformat(str(wartosc))
    except (TypeError, ValueError):
        raise LogistykaBlad(u'Pole „{}”: podaj datę RRRR-MM-DD.'.format(pole), status=422)


def _id(wartosc, pole):
    if wartosc in (None, '', 0, '0'):
        return None
    try:
        return int(wartosc)
    except (TypeError, ValueError):
        raise LogistykaBlad(u'Pole „{}”: nieprawidłowa wartość.'.format(pole), status=422)


def _wymagaj_statusu(route, *statusy):
    if route.status not in statusy:
        opis = {'robocza': u'robocza', 'zatwierdzona': u'zatwierdzona', 'wykonana': u'wykonana'}
        raise LogistykaBlad(u'Trasa „{}” jest {} — ta operacja nie jest dostępna.'.format(
            route.name, opis.get(route.status, route.status)))


def zamowienia_trasy(route):
    ids = [s.order_id for s in route.stops]
    if not ids:
        return []
    po_id = {o.id: o for o in ProductionOrder.query.filter(ProductionOrder.id.in_(ids)).all()}
    return [po_id[i] for i in ids if i in po_id]


def _podbij_trase(route, teraz):
    for order in zamowienia_trasy(route):
        delivery.podbij_pozycje(order, teraz)


def _log_statusu(route, stary, nowy, user_id, teraz):
    for order in zamowienia_trasy(route):
        delivery.zapisz_log(order, 'trasa_status', stary, nowy, user_id=user_id,
                            route_id=route.id, teraz=teraz)


# ── Zajętość zasobów ──────────────────────────────────────────────────────

def zajetosc(date_from, date_to, pomin_route_id=None):
    zapytanie = Route.query.filter(Route.status.in_(AKTYWNE),
                                   Route.date_from <= date_to, Route.date_to >= date_from)
    if pomin_route_id:
        zapytanie = zapytanie.filter(Route.id != pomin_route_id)
    pojazdy, kierowcy = {}, {}
    for trasa in zapytanie.order_by(Route.date_from).all():
        if trasa.vehicle_id:
            pojazdy.setdefault(trasa.vehicle_id, trasa.name)
        if trasa.driver_worker_id:
            kierowcy.setdefault(trasa.driver_worker_id, trasa.name)
    return {'pojazdy': pojazdy, 'kierowcy': kierowcy}


def dostepnosc(date_from, date_to, pomin_route_id=None):
    z = zajetosc(date_from, date_to, pomin_route_id)
    return {
        'pojazdy': [dict(p, zajety=p['id'] in z['pojazdy'], trasa=z['pojazdy'].get(p['id']))
                    for p in fleet.lista_pojazdow(tylko_aktywne=True)],
        'kierowcy': [dict(k, zajety=k['id'] in z['kierowcy'], trasa=z['kierowcy'].get(k['id']))
                     for k in fleet.kierowcy()],
    }


def _sprawdz_zasoby(od, do, vehicle_id, driver_id, pomin_route_id=None):
    if vehicle_id:
        # FOR UPDATE na wierszu pojazdu serializuje dwa równoległe zapisy tras (MySQL);
        # SQLite go ignoruje, testy jadą sekwencyjnie.
        pojazd = Vehicle.query.with_for_update().filter_by(id=vehicle_id).first()
        if pojazd is None:
            raise LogistykaBlad(u'Nie ma takiego pojazdu.', status=422)
        if not pojazd.is_active:
            raise LogistykaBlad(u'Pojazd „{}” jest wyłączony z floty.'.format(pojazd.name), status=422)
    if driver_id:
        kierowca = ProductionWorker.query.get(driver_id)
        if kierowca is None or not kierowca.is_active:
            raise LogistykaBlad(u'Nie ma takiego aktywnego kierowcy.', status=422)
    z = zajetosc(od, do, pomin_route_id)
    if vehicle_id and vehicle_id in z['pojazdy']:
        raise LogistykaBlad(u'Pojazd jest zajęty na trasie „{}” w tych dniach.'.format(
            z['pojazdy'][vehicle_id]))
    if driver_id and driver_id in z['kierowcy']:
        raise LogistykaBlad(u'Kierowca jest zajęty na trasie „{}” w tych dniach.'.format(
            z['kierowcy'][driver_id]))


def _dane_trasy(dane):
    nazwa = (dane.get('name') or '').strip()
    if not nazwa or len(nazwa) > MAKS_NAZWA:
        raise LogistykaBlad(u'Podaj nazwę trasy (do {} znaków).'.format(MAKS_NAZWA), status=422)
    od = _data(dane.get('date_from'), u'data od')
    do = _data(dane.get('date_to') or dane.get('date_from'), u'data do')
    if do < od:
        raise LogistykaBlad(u'Data „do” jest wcześniejsza niż „od”.', status=422)
    notatka = (dane.get('notes') or '').strip() or None
    return (nazwa, od, do, _id(dane.get('vehicle_id'), u'pojazd'),
            _id(dane.get('driver_worker_id'), u'kierowca'), notatka)


# ── Tworzenie i edycja ────────────────────────────────────────────────────

def utworz(dane, user_id=None):
    nazwa, od, do, pojazd_id, kierowca_id, notatka = _dane_trasy(dane)
    _sprawdz_zasoby(od, do, pojazd_id, kierowca_id)
    teraz = get_local_now()
    trasa = Route(name=nazwa, date_from=od, date_to=do, vehicle_id=pojazd_id,
                  driver_worker_id=kierowca_id, notes=notatka, status='robocza',
                  created_at=teraz, created_by=user_id, updated_at=teraz, geometry_approx=False)
    db.session.add(trasa)
    db.session.flush()
    return trasa


def edytuj(route, dane, user_id=None):
    _wymagaj_statusu(route, 'robocza')
    nazwa, od, do, pojazd_id, kierowca_id, notatka = _dane_trasy(dane)
    _sprawdz_zasoby(od, do, pojazd_id, kierowca_id, pomin_route_id=route.id)
    route.name, route.date_from, route.date_to = nazwa, od, do
    route.vehicle_id, route.driver_worker_id, route.notes = pojazd_id, kierowca_id, notatka
    db.session.flush()
    db.session.expire(route, ['vehicle', 'driver'])
    _podbij_trase(route, get_local_now())
    return route


# ── Odczyty dla innych modułów ────────────────────────────────────────────

def przystanek_zamowienia(order_id):
    return RouteStop.query.filter_by(order_id=order_id).first()


def trasy_zamowien(order_ids):
    if not order_ids:
        return {}
    wiersze = (db.session.query(RouteStop.order_id, Route)
               .join(Route, RouteStop.route_id == Route.id)
               .filter(RouteStop.order_id.in_(list(order_ids))).all())
    return {order_id: trasa for order_id, trasa in wiersze}


def mapa_tras_aktywnych():
    wiersze = (db.session.query(RouteStop.order_id, Route)
               .join(Route, RouteStop.route_id == Route.id)
               .filter(Route.status.in_(AKTYWNE)).all())
    return {order_id: trasa for order_id, trasa in wiersze}


def trasa_dla_tabletu(order_id):
    """Trasa (robocza/zatwierdzona) zamówienia; jedno zapytanie na żądanie HTTP (cache w g)."""
    from flask import g, has_request_context
    if has_request_context():
        mapa = getattr(g, '_logistyka_trasy_aktywne', None)
        if mapa is None:
            mapa = g._logistyka_trasy_aktywne = mapa_tras_aktywnych()
    else:
        mapa = mapa_tras_aktywnych()
    return mapa.get(order_id)


# ── Przystanki ────────────────────────────────────────────────────────────

def _przenumeruj(route):
    db.session.flush()
    db.session.expire(route, ['stops'])
    for pozycja, przystanek in enumerate(route.stops, start=1):
        przystanek.position = pozycja


def dodaj_przystanki(route, order_ids, user_id=None):
    _wymagaj_statusu(route, 'robocza')
    teraz = get_local_now()
    unikalne = list(dict.fromkeys(int(i) for i in order_ids))
    zamowienia = {o.id: o for o in
                  ProductionOrder.query.filter(ProductionOrder.id.in_(unikalne)).all()}
    pozycja = max([s.position for s in route.stops] or [0])
    dodane, bledy = [], []
    for order_id in unikalne:
        order = zamowienia.get(order_id)
        if order is None:
            bledy.append({'order_id': order_id, 'komunikat': u'Nie ma takiego zamówienia.'})
            continue
        numer = order.internal_order_number
        if sposoby.normalizuj(order.override_delivery_method) != sposoby.TRANSPORT:
            bledy.append({'order_id': order_id, 'komunikat':
                          u'Zamówienie {} nie ma ustawionego transportu własnego.'.format(numer)})
            continue
        if order.logistics_closed_at is not None:
            bledy.append({'order_id': order_id, 'komunikat':
                          u'Zamówienie {} jest zamknięte w logistyce.'.format(numer)})
            continue
        inny = przystanek_zamowienia(order_id)
        if inny is not None:
            bledy.append({'order_id': order_id, 'komunikat':
                          u'Zamówienie {} jest już na trasie „{}”.'.format(numer, inny.route.name)})
            continue
        pozycja += 1
        db.session.add(RouteStop(route_id=route.id, order_id=order_id, position=pozycja))
        db.session.flush()
        delivery.zapisz_log(order, 'trasa_dodane', None, route.name[:64], user_id=user_id,
                            route_id=route.id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
        dodane.append(order_id)
    db.session.expire(route, ['stops'])
    return {'dodane': dodane, 'bledy': bledy}


def usun_przystanek(route, order_id, user_id=None, note=None, wymagaj_roboczej=True):
    if wymagaj_roboczej:
        _wymagaj_statusu(route, 'robocza')
    przystanek = RouteStop.query.filter_by(route_id=route.id, order_id=order_id).first()
    if przystanek is None:
        raise LogistykaBlad(u'Tego zamówienia nie ma na trasie „{}”.'.format(route.name), status=404)
    order = ProductionOrder.query.get(order_id)
    db.session.delete(przystanek)
    _przenumeruj(route)
    teraz = get_local_now()
    delivery.zapisz_log(order, 'trasa_usuniete', route.name[:64], None, user_id=user_id,
                        note=note, route_id=route.id, teraz=teraz)
    delivery.podbij_pozycje(order, teraz)
    return order


def zmien_kolejnosc(route, order_ids):
    _wymagaj_statusu(route, 'robocza')
    obecne = {s.order_id: s for s in route.stops}
    nowe = [int(i) for i in order_ids]
    if len(nowe) != len(obecne) or set(nowe) != set(obecne):
        raise LogistykaBlad(u'Kolejność musi zawierać dokładnie przystanki tej trasy.', status=422)
    for pozycja, order_id in enumerate(nowe, start=1):
        obecne[order_id].position = pozycja
    db.session.flush()
    db.session.expire(route, ['stops'])


# ── Statusy ───────────────────────────────────────────────────────────────

def zatwierdz(route, user_id=None):
    _wymagaj_statusu(route, 'robocza')
    if not route.stops:
        raise LogistykaBlad(u'Trasa bez przystanków nie może być zatwierdzona.', status=422)
    teraz = get_local_now()
    route.status, route.approved_at, route.approved_by = 'zatwierdzona', teraz, user_id
    _log_statusu(route, 'robocza', 'zatwierdzona', user_id, teraz)
    _podbij_trase(route, teraz)


def cofnij_do_roboczej(route, user_id=None):
    _wymagaj_statusu(route, 'zatwierdzona')
    teraz = get_local_now()
    route.status, route.approved_at, route.approved_by = 'robocza', None, None
    _log_statusu(route, 'zatwierdzona', 'robocza', user_id, teraz)
    _podbij_trase(route, teraz)


def wykonaj(route, dostarczone_ids=None, user_id=None):
    _wymagaj_statusu(route, *AKTYWNE)
    na_trasie = [s.order_id for s in route.stops]
    if not na_trasie:
        raise LogistykaBlad(u'Trasa nie ma przystanków.', status=422)
    dostarczone = set(int(i) for i in (na_trasie if dostarczone_ids is None else dostarczone_ids))
    if not dostarczone <= set(na_trasie):
        raise LogistykaBlad(u'Część zamówień nie należy do tej trasy.', status=422)
    niedostarczone = [i for i in na_trasie if i not in dostarczone]
    for order_id in niedostarczone:
        usun_przystanek(route, order_id, user_id=user_id, note=u'niedostarczone',
                        wymagaj_roboczej=False)
    teraz = get_local_now()
    stary = route.status
    route.status, route.completed_at, route.completed_by = 'wykonana', teraz, user_id
    db.session.flush()
    for order in zamowienia_trasy(route):
        delivery.zapisz_log(order, 'trasa_status', stary, 'wykonana', user_id=user_id,
                            route_id=route.id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
        delivery.przelicz_zamkniecie(order, teraz)
    return {'dostarczone': [i for i in na_trasie if i in dostarczone],
            'niedostarczone': niedostarczone}


def przywroc(route, user_id=None):
    _wymagaj_statusu(route, 'wykonana')
    _sprawdz_zasoby(route.date_from, route.date_to, route.vehicle_id, route.driver_worker_id,
                    pomin_route_id=route.id)
    teraz = get_local_now()
    route.status, route.completed_at, route.completed_by = 'zatwierdzona', None, None
    db.session.flush()
    for order in zamowienia_trasy(route):
        delivery.zapisz_log(order, 'trasa_status', 'wykonana', 'zatwierdzona', user_id=user_id,
                            route_id=route.id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
        delivery.przelicz_zamkniecie(order, teraz)


def usun(route, user_id=None):
    _wymagaj_statusu(route, 'robocza')
    for order_id in [s.order_id for s in route.stops]:
        usun_przystanek(route, order_id, user_id=user_id, note=u'usunięcie trasy')
    db.session.delete(route)
    db.session.flush()


# ── Podsumowanie i serializacja ───────────────────────────────────────────

def podsumowanie(route, zamowienia, punkty):
    m3 = sum(float(p.volume_m3 or 0) * (p.quantity or 1)
             for o in zamowienia for p in delivery.aktywne_produkty(o))
    waga = int(round(m3 * WAGA_KG_NA_M3))
    ladownosc = route.vehicle.capacity_kg if route.vehicle is not None else None
    return {
        'przystanki': len(zamowienia),
        'm3': round(m3, 4),
        'waga_kg': waga,
        'km': float(route.distance_km) if route.distance_km is not None else None,
        'minuty': route.duration_min,
        'przyblizony': bool(route.geometry_approx),
        'bez_lokalizacji': sum(1 for o in zamowienia
                               if punkty.get(o.id) is None or punkty[o.id].lat is None),
        'przekroczona_ladownosc': bool(ladownosc) and waga > ladownosc,
    }


def serializuj_trase(route, zamowienia=None, punkty=None):
    kierowca = route.driver
    dane = {
        'id': route.id,
        'nazwa': route.name,
        'date_from': route.date_from.isoformat(),
        'date_to': route.date_to.isoformat(),
        'status': route.status,
        'pojazd': fleet.serializuj_pojazd(route.vehicle) if route.vehicle is not None else None,
        'kierowca': ({'id': kierowca.id, 'nazwa': u'{} {}'.format(kierowca.first_name,
                                                                   kierowca.last_name).strip()}
                     if kierowca is not None else None),
        'notatka': route.notes,
        'zatwierdzona': route.approved_at.isoformat() if route.approved_at else None,
        'wykonana': route.completed_at.isoformat() if route.completed_at else None,
    }
    if zamowienia is not None:
        dane['podsumowanie'] = podsumowanie(route, zamowienia, punkty or {})
    return dane
```

- [ ] **Step 4: Uruchom testy**

Run: `PYTEST tests/test_logistyka_trasy_serwis.py`
Expected: PASS. `test_niedostarczony_wraca_do_puli` wymaga Task 4 (reguła zamknięcia transportu) — jeśli pada tylko na `a.logistics_closed_at`, oznacz go `@pytest.mark.xfail(reason='Task 4', strict=True)` i zdejmij znacznik w Task 4. To samo dla `test_przywrocenie_otwiera_zamowienia`.

- [ ] **Step 5: Commit**

```bash
git add modules/production/logistics/services/routes.py tests/test_logistyka_trasy_serwis.py
git commit -m "feat(production): trasy transportu wlasnego - zajetosc zasobow, przystanki i statusy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Trasy w cyklu życia, liście i na tablecie

**Files:**
- Modify: `modules/production/logistics/services/delivery.py` (`zamkniecie_wyliczone`, `ustaw_sposob_dostawy`, `zmien_adres`)
- Modify: `modules/production/logistics/services/lista.py` (klucz `trasa`, filtr `bez_trasy`)
- Modify: `modules/production/logistics/routers/panel_api.py` (pięć wywołań `lista.serializuj`, `usunieto_z_trasy` w odpowiedzi hurtu)
- Modify: `modules/production/services/mobile_api_service.py` (`serialize_order`)
- Modify: `modules/production/services/label_print_service.py` (`_format_delivery_label`)
- Modify: `tests/test_logistyka_delivery.py:21`, `tests/test_logistyka_poprawki_panelu.py:76` (nowy klucz w wyniku `ustaw_sposob_dostawy`)
- Test: `tests/test_logistyka_trasy_integracja.py`

**Interfaces:**
- Consumes: `routes.przystanek_zamowienia`, `routes.usun_przystanek`, `routes.trasa_dla_tabletu`, `routes.trasy_zamowien` (Task 3).
- Produces:
  - `delivery.zamkniecie_wyliczone(order)`: transport własny → `True`, gdy zamówienie ma przystanek na trasie `wykonana`.
  - `delivery.ustaw_sposob_dostawy(...)` zwraca **we wszystkich trzech miejscach** `{'zmieniono', 'przepakowanie', 'usunieto_z_trasy': str|None}`; zmiana zdejmująca z trasy (na kuriera/odbiór **albo cofnięcie `sposoby.BRAK`**): trasa robocza → zdjęcie; zatwierdzona → 409; wykonana → 409 dla każdej zmiany.
  - `delivery.zmien_adres(...)`: 409, gdy zamówienie leży na trasie zatwierdzonej; na roboczej adres się zmienia, przystanek zostaje (przebieg przeliczy się sam, gdy geokoder da nowy punkt — zmienia się `geometry_hash`).
  - `lista.serializuj(order, geo=None, trasa=None)` dostaje `'trasa': None | {'id', 'nazwa', 'status'}`; `pobierz(..., sposob='bez_trasy')` = transport własny bez trasy.
  - API mobilne: `transport.trip_name/trip_date/vehicle_name` z trasy aktywnej; etykieta „Dostawa:” = nazwa trasy.

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_trasy_integracja.py`:
```python
# -*- coding: utf-8 -*-
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import delivery, routes
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.services.label_print_service import _format_delivery_label
from modules.production.services.mobile_api_service import serialize_order
from tests.logistyka_fixtures import BASE, app, client, pojazd, zamowienie  # noqa: F401


def _na_trasie(status='robocza', statusy=('spakowane',)):
    v = pojazd(name='Iveco KR 1')
    trasa = routes.utworz({'name': 'Kraków + Tarnów', 'date_from': '2026-10-01',
                           'vehicle_id': v.id})
    order = zamowienie(sposob=s.TRANSPORT, statusy=statusy)
    routes.dodaj_przystanki(trasa, [order.id])
    if status in ('zatwierdzona', 'wykonana'):
        routes.zatwierdz(trasa)
    if status == 'wykonana':
        routes.wykonaj(trasa)
    db.session.commit()
    return trasa, order


def test_zmiana_sposobu_zdejmuje_z_roboczej(app):
    """Review Focus 2."""
    with app.app_context():
        trasa, order = _na_trasie('robocza')
        wynik = delivery.ustaw_sposob_dostawy(order, s.ODBIOR)
        db.session.commit()
        assert wynik['usunieto_z_trasy'] == 'Kraków + Tarnów'
        assert routes.przystanek_zamowienia(order.id) is None


def test_zmiana_sposobu_na_zatwierdzonej_to_409(app):
    with app.app_context():
        _trasa, order = _na_trasie('zatwierdzona')
        with pytest.raises(LogistykaBlad) as e:
            delivery.ustaw_sposob_dostawy(order, s.KURIER)
        assert e.value.status == 409 and 'cofnij' in e.value.komunikat


def test_zmiana_sposobu_dostarczonego_to_409(app):
    with app.app_context():
        _trasa, order = _na_trasie('wykonana')
        assert order.logistics_closed_at is not None
        with pytest.raises(LogistykaBlad):
            delivery.ustaw_sposob_dostawy(order, s.ODBIOR)


def test_tablet_widzi_trase_i_etykieta_tez(app):
    with app.app_context():
        trasa, order = _na_trasie('robocza', statusy=('czeka_na_pakowanie',))
        with app.test_request_context():
            dane = serialize_order(order.products[0], station_code='packaging')
        assert dane['transport'] == {'mode': 'wlasny', 'trip_name': 'Kraków + Tarnów',
                                     'trip_date': '2026-10-01', 'vehicle_name': 'Iveco KR 1',
                                     'repack_required': False}
        assert _format_delivery_label(order.products[0]) == 'Krakow + Tarnow' or \
            _format_delivery_label(order.products[0]).startswith('Krak')


def test_tablet_traci_trase_po_zdjeciu(app):
    """Review Focus 3."""
    with app.app_context():
        trasa, order = _na_trasie('robocza', statusy=('czeka_na_pakowanie',))
        przed = order.products[0].updated_at
        routes.usun_przystanek(trasa, order.id)
        db.session.commit()
        with app.test_request_context():
            dane = serialize_order(order.products[0], station_code='packaging')
        assert dane['transport']['trip_name'] is None
        assert order.products[0].updated_at >= przed


def test_lista_pokazuje_trase_i_filtr_bez_trasy(client, app):
    with app.app_context():
        trasa, order = _na_trasie('robocza', statusy=('czeka_na_wyciecie',))
        wolne = zamowienie(sposob=s.TRANSPORT)
        tid, wolne_id = trasa.id, wolne.id
    wiersze = {o['id']: o for o in client.get(BASE + '/orders').get_json()['orders']}
    assert wiersze[order.id]['trasa'] == {'id': tid, 'nazwa': 'Kraków + Tarnów', 'status': 'robocza'}
    bez = client.get(BASE + '/orders?sposob=bez_trasy').get_json()['orders']
    assert [o['id'] for o in bez] == [wolne_id]


def test_cofniecie_zdejmuje_z_roboczej(app):
    """Review Focus 6 — „Nie ustawiono” (sposoby.BRAK) z etapu 2."""
    with app.app_context():
        _trasa, order = _na_trasie('robocza', statusy=('czeka_na_wyciecie',))
        wynik = delivery.ustaw_sposob_dostawy(order, s.BRAK)
        db.session.commit()
        assert wynik['usunieto_z_trasy'] == 'Kraków + Tarnów'
        assert order.override_delivery_method is None
        assert routes.przystanek_zamowienia(order.id) is None


def test_cofniecie_na_zatwierdzonej_to_409(app):
    with app.app_context():
        _trasa, order = _na_trasie('zatwierdzona', statusy=('czeka_na_wyciecie',))
        with pytest.raises(LogistykaBlad) as e:
            delivery.ustaw_sposob_dostawy(order, s.BRAK)
        assert e.value.status == 409 and 'cofnij' in e.value.komunikat


def test_zmiana_adresu_na_zatwierdzonej_to_409(app):
    """Review Focus 7."""
    with app.app_context():
        _trasa, order = _na_trasie('zatwierdzona', statusy=('czeka_na_wyciecie',))
        with pytest.raises(LogistykaBlad) as e:
            delivery.zmien_adres(order, 'Nowa 1', '30-001', 'Kraków')
        assert e.value.status == 409 and 'cofnij' in e.value.komunikat


def test_zmiana_adresu_na_roboczej_zostaje_na_trasie(app):
    with app.app_context():
        _trasa, order = _na_trasie('robocza', statusy=('czeka_na_wyciecie',))
        assert delivery.zmien_adres(order, 'Nowa 1', '30-001', 'Kraków') is True
        db.session.commit()
        assert routes.przystanek_zamowienia(order.id) is not None


def test_niezmieniony_sposob_ma_pelny_slownik(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER)
        assert delivery.ustaw_sposob_dostawy(order, s.KURIER) == {
            'zmieniono': False, 'przepakowanie': False, 'usunieto_z_trasy': None}
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_trasy_integracja.py`
Expected: FAIL.

- [ ] **Step 3: `delivery.py`**

1. W `zamkniecie_wyliczone` zastąp końcowe `return False` gałęzi transportu własnego na:
```python
    # Transport własny: koniec cyklu = przystanek na trasie wykonanej (etap 3).
    from modules.production.logistics.services import routes
    przystanek = routes.przystanek_zamowienia(order.id)
    return przystanek is not None and przystanek.route.status == 'wykonana'
```
2. Dopisz pomocnika (nad `ustaw_sposob_dostawy`):
```python
def _przystanek_do_zmiany(order, zdejmuje, opis):
    """
    (etap 3) Przystanek zamówienia i blokady zmian na trasach. Trasa wykonana —
    zamówienie dostarczone, żadnych zmian. Zatwierdzona — zmiana, która zdejmuje
    zamówienie z trasy albo zmienia adres (`zdejmuje=True`), wymaga cofnięcia
    zatwierdzenia (eksport do Routimo mógł już pójść). Zwraca przystanek albo None.
    """
    from modules.production.logistics.services import routes
    przystanek = routes.przystanek_zamowienia(order.id)
    if przystanek is None:
        return None
    trasa = przystanek.route
    if trasa.status == 'wykonana':
        raise LogistykaBlad(u'Zamówienie {} zostało dostarczone trasą „{}”.'.format(
            order.internal_order_number, trasa.name))
    if trasa.status == 'zatwierdzona' and zdejmuje:
        raise LogistykaBlad(u'Zamówienie {} jest na zatwierdzonej trasie „{}” — najpierw cofnij '
                            u'jej zatwierdzenie, potem {}.'.format(order.internal_order_number,
                                                                   trasa.name, opis))
    return przystanek


def _zdejmij_z_trasy(przystanek, order, user_id):
    from modules.production.logistics.services import routes
    nazwa = przystanek.route.name
    routes.usun_przystanek(przystanek.route, order.id, user_id=user_id,
                           note=u'zmiana sposobu dostawy')
    return nazwa
```
3. W `ustaw_sposob_dostawy`:
   - wczesny zwrot `if stary == nowy:` → `return {'zmieniono': False, 'przepakowanie': False, 'usunieto_z_trasy': None}`;
   - zaraz **po** tym zwrocie (przed `teraz = ...`):
```python
    zdejmuje = nowy != sposoby.TRANSPORT   # kurier, odbiór i cofnięcie (nowy=None) zdejmują z trasy
    przystanek = _przystanek_do_zmiany(order, zdejmuje, u'zmień sposób dostawy')
```
   - w gałęzi `if cofniecie:` — po istniejącym sprawdzeniu spakowanego towaru, zamiast samego
     `return _cofnij_sposob(...)`:
```python
        usunieto = _zdejmij_z_trasy(przystanek, order, user_id) if przystanek is not None else None
        wynik = _cofnij_sposob(order, stary, user_id, teraz)
        wynik['usunieto_z_trasy'] = usunieto
        return wynik
```
   - w ścieżce głównej, przed końcowym `podbij_pozycje(order, teraz)`:
```python
    usunieto_z_trasy = None
    if przystanek is not None and zdejmuje:
        usunieto_z_trasy = _zdejmij_z_trasy(przystanek, order, user_id)
```
     i zwróć `{'zmieniono': True, 'przepakowanie': przepakowanie, 'usunieto_z_trasy': usunieto_z_trasy}`.
4. W `zmien_adres`, po istniejących odmowach (wydane, anulowane, zamknięte, przesyłka), przed porównaniem `stary = tuple(...)`:
```python
    # Etap 3: na trasie zatwierdzonej adres zmieniamy dopiero po cofnięciu zatwierdzenia.
    _przystanek_do_zmiany(order, True, u'popraw adres')
```
5. W `tests/test_logistyka_delivery.py:21` i `tests/test_logistyka_poprawki_panelu.py:76` asercję
   `wynik == {'zmieniono': True, 'przepakowanie': False}` zmień na
   `wynik == {'zmieniono': True, 'przepakowanie': False, 'usunieto_z_trasy': None}`. Jeśli inne testy porównują
   ten wynik całym słownikiem (`git grep -n "'przepakowanie': False}" tests`), popraw je tak samo.
6. W `routers/panel_api.py` (`delivery_method`) zbieraj `usunieto_z_trasy` z wyników
   (`if wynik.get('usunieto_z_trasy'): usunieto.append({'order_id': order.id, 'trasa': wynik['usunieto_z_trasy']})`)
   i dopisz do odpowiedzi `'usunieto_z_trasy': usunieto` (UI pokaże „Usunięto z trasy X”).

- [ ] **Step 4: Lista**

W `services/lista.py`:
- import `from modules.production.logistics.services import routes` (bez cyklu: `routes` nie importuje `lista`);
- `serializuj(order, geo=None, trasa=None)` z kluczem
  `'trasa': {'id': trasa.id, 'nazwa': trasa.name, 'status': trasa.status} if trasa is not None else None`;
- w `pobierz(...)` filtr `bez_trasy` **w bloku filtrów, przed `if zamkniete: ... limit(...)`** (uwaga R3 w docstringu):
```python
    elif sposob == 'bez_trasy':
        zapytanie = zapytanie.filter(ProductionOrder.override_delivery_method == sposoby.TRANSPORT)
```
  (gałąź między `if sposob == 'brak'` a `elif sposoby.normalizuj(sposob)`), a po wczytaniu:
```python
    zamowienia = zapytanie.all()
    ids = [o.id for o in zamowienia]
    punkty = geocoding.geo_zamowien(ids)
    trasy = routes.trasy_zamowien(ids)
    wiersze = [serializuj(o, punkty.get(o.id), trasy.get(o.id)) for o in zamowienia]
    if sposob == 'bez_trasy':
        wiersze = [w for w in wiersze if w['trasa'] is None]
```
W `routers/panel_api.py` każde z pięciu wywołań `lista.serializuj(...)` (`delivery_method`, `handed_over`,
`order_address`, `order_geo`, `order_geo_reset`) dostaje trasę: `trasy = routes.trasy_zamowien(ids)` i
`lista.serializuj(o, punkty.get(o.id), trasy.get(o.id))` (dla pojedynczego zamówienia `trasy_zamowien([order_id])`).

- [ ] **Step 5: Tablet i etykieta**

`mobile_api_service.serialize_order` — zamiast `transport = sposoby.transport_payload(item.order)`:
```python
    trasa = None
    if item.order is not None and sposoby.normalizuj(item.order.override_delivery_method) == sposoby.TRANSPORT:
        from modules.production.logistics.services.routes import trasa_dla_tabletu
        trasa = trasa_dla_tabletu(item.order.id)
    transport = sposoby.transport_payload(item.order, trasa)
```
`label_print_service._format_delivery_label`:
```python
    from modules.production.logistics import sposoby
    from modules.production.logistics.services.routes import trasa_dla_tabletu
    order = item.order if item.order else None
    sposob = order.override_delivery_method if order else None
    trasa = trasa_dla_tabletu(order.id) if order is not None else None
    return _normalize_text(sposoby.etykieta(sposob, nazwa_trasy=trasa.name if trasa else None))
```
Zestaw pól API się nie zmienia (`trip_*` istniały od etapu 1), więc **nie** podbijaj `KSZTALT_ODPOWIEDZI_KOLEJKI`; świeżość zapewnia `podbij_pozycje`.
Uwaga: jeśli `_normalize_text` zdejmuje polskie znaki, asercja etykiety w teście jest już na to przygotowana (sprawdza prefiks).

- [ ] **Step 6: Uruchom testy**

Run: `PYTEST tests/test_logistyka_trasy_integracja.py tests/test_logistyka_trasy_serwis.py tests/test_logistyka_delivery.py tests/test_logistyka_poprawki_panelu.py tests/test_logistyka_mobile.py tests/test_logistyka_panel_api.py tests/test_logistyka_geo_api.py`
Expected: PASS (zdejmij `xfail` z Task 3, jeśli był).

- [ ] **Step 7: Commit**

```bash
git add modules/production tests/
git commit -m "feat(production): trasy zamykaja cykl transportu wlasnego i trafiaja na tablet pakowania

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Przebieg trasy — OpenRouteService z fallbackiem

**Files:**
- Create: `modules/production/logistics/services/routing.py`
- Test: `tests/test_logistyka_trasy_routing.py`

**Interfaces:**
- Consumes: `Route` (Task 1), `routes.zamowienia_trasy` (Task 3), `geocoding.MAGAZYN`, `geocoding.geo_zamowien` (etap 2).
- Produces: `ORS_URL`, `TIMEOUT_S = 8`, `MAKS_PRZYSTANKOW = 48`; `klucz_ors() -> str|None` (z `current_app.config['OPENROUTESERVICE_API_KEY']`); `skrot_przebiegu(punkty) -> str`; `odleglosc_km(a, b) -> float` (**ta sama funkcja co w geokoderze** — patrz Step 3); `przelicz(route, punkty_zamowien: dict[int, OrderGeo], http_post=requests.post, wymus=False) -> bool` (True = geometria zmieniona); `przebieg(route) -> dict|None` (GeoJSON geometrii z cache). Geometria: `{'type': 'LineString', 'coordinates': [[lng, lat], ...]}`.

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_trasy_routing.py`:
```python
# -*- coding: utf-8 -*-
import json

import pytest
import requests

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import OrderGeo
from modules.production.logistics.services import geocoding, routes, routing
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

ORS_ODP = {'type': 'FeatureCollection', 'features': [{
    'geometry': {'type': 'LineString', 'coordinates': [[22.25, 49.84], [19.94, 50.06], [22.25, 49.84]]},
    'properties': {'summary': {'distance': 412345.6, 'duration': 18000.0}}}]}


class Odp(object):
    def __init__(self, dane, status=200):
        self.dane, self.status_code = dane, status

    def json(self):
        return self.dane

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakePost(object):
    def __init__(self, odp=None, wyjatek=None):
        self.odp, self.wyjatek, self.wywolania = odp, wyjatek, []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.wywolania.append((url, json, headers, timeout))
        if self.wyjatek:
            raise self.wyjatek
        return self.odp


def _trasa_z_punktem(app, z_punktem=True):
    trasa = routes.utworz({'name': 'T', 'date_from': '2026-10-01'})
    order = zamowienie(sposob=s.TRANSPORT)
    routes.dodaj_przystanki(trasa, [order.id])
    if z_punktem:
        db.session.add(OrderGeo(order_id=order.id, lat=50.06, lng=19.94, source='gugik',
                                quality='dokladna', address_hash='x' * 40))
    db.session.commit()
    return trasa, geocoding.geo_zamowien([order.id])


def test_ors_liczy_przebieg_magazyn_przystanki_magazyn(app):
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    with app.app_context():
        trasa, punkty = _trasa_z_punktem(app)
        http = FakePost(Odp(ORS_ODP))
        assert routing.przelicz(trasa, punkty, http_post=http) is True
        url, cialo, naglowki, timeout = http.wywolania[0]
        m = geocoding.MAGAZYN
        assert cialo['coordinates'] == [[m['lng'], m['lat']], [19.94, 50.06], [m['lng'], m['lat']]]
        assert naglowki['Authorization'] == 'klucz' and timeout == routing.TIMEOUT_S
        assert (float(trasa.distance_km), trasa.duration_min, trasa.geometry_approx) == (412.3, 300, False)
        assert routing.przebieg(trasa)['type'] == 'LineString'
        # Ten sam układ — bez ponownego zapytania.
        assert routing.przelicz(trasa, punkty, http_post=http) is False
        assert len(http.wywolania) == 1


def test_brak_klucza_to_linie_proste(app):
    """Review Focus 4."""
    app.config.pop('OPENROUTESERVICE_API_KEY', None)
    with app.app_context():
        trasa, punkty = _trasa_z_punktem(app)
        http = FakePost(Odp(ORS_ODP))
        routing.przelicz(trasa, punkty, http_post=http)
        assert http.wywolania == []
        assert trasa.geometry_approx is True and trasa.duration_min is None
        assert float(trasa.distance_km) == pytest.approx(
            2 * routing.odleglosc_km((49.840438, 22.254053), (50.06, 19.94)), abs=0.1)


def test_blad_ors_to_linie_proste(app):
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    with app.app_context():
        trasa, punkty = _trasa_z_punktem(app)
        routing.przelicz(trasa, punkty, http_post=FakePost(wyjatek=requests.Timeout('x')))
        assert trasa.geometry_approx is True


def test_przystanek_bez_wspolrzednych(app):
    app.config['OPENROUTESERVICE_API_KEY'] = 'klucz'
    with app.app_context():
        trasa, punkty = _trasa_z_punktem(app, z_punktem=False)
        http = FakePost(Odp(ORS_ODP))
        routing.przelicz(trasa, punkty, http_post=http)
        assert http.wywolania == [] and trasa.geometry_approx is True


def test_pusta_trasa_czysci_przebieg(app):
    with app.app_context():
        trasa = routes.utworz({'name': 'Pusta', 'date_from': '2026-10-01'})
        trasa.geometry_json, trasa.distance_km = json.dumps({'type': 'LineString'}), 10
        routing.przelicz(trasa, {}, http_post=FakePost())
        assert trasa.geometry_json is None and trasa.distance_km is None
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_trasy_routing.py`
Expected: FAIL.

- [ ] **Step 3: Implementacja**

Najpierw w `modules/production/logistics/services/geocoding.py` zmień nazwę `_odleglosc_km` na publiczną
`odleglosc_km` (to samo ciało — przybliżenie równoprostokątne, na skalę kraju wystarcza) i zostaw pod nią alias
`_odleglosc_km = odleglosc_km` (używa jej geokoder i testy etapu 2). Routing jej nie kopiuje.

`modules/production/logistics/services/routing.py`:
```python
# -*- coding: utf-8 -*-
"""
Przebieg trasy po drogach — OpenRouteService (spec 8.2).

Magazyn → przystanki w kolejności → magazyn. Klucz OPENROUTESERVICE_API_KEY
z config/core.json (bez wartości domyślnej). Brak klucza, błąd, przystanek
bez współrzędnych albo za dużo punktów → linie proste, odległość w linii
prostej, czas nieznany, geometry_approx = True. Jedno zapytanie z timeoutem
8 s na zapis trasy (limit gunicorna 30 s).
"""
import hashlib
import json

import requests
from flask import current_app

from modules.logging import get_structured_logger
from modules.production.logistics.services import routes
from modules.production.logistics.services.geocoding import MAGAZYN, odleglosc_km  # noqa: F401

logger = get_structured_logger('production.logistics.routing')

ORS_URL = 'https://api.openrouteservice.org/v2/directions/driving-car/geojson'
TIMEOUT_S = 8
MAKS_PRZYSTANKOW = 48  # ORS: do 50 punktów, dwa zajmuje magazyn


def klucz_ors():
    klucz = current_app.config.get('OPENROUTESERVICE_API_KEY')
    return klucz.strip() if isinstance(klucz, str) and klucz.strip() else None


def skrot_przebiegu(punkty):
    tekst = json.dumps([[round(p[0], 6), round(p[1], 6)] for p in punkty])
    return hashlib.sha1(tekst.encode('utf-8')).hexdigest()


def _punkty(route, punkty_zamowien):
    """[(lat, lng)] magazyn → przystanki z współrzędnymi → magazyn, oraz czy któregoś brakuje."""
    magazyn = (MAGAZYN['lat'], MAGAZYN['lng'])
    srodek, braki = [], False
    for order in routes.zamowienia_trasy(route):
        punkt = punkty_zamowien.get(order.id)
        if punkt is None or punkt.lat is None:
            braki = True
            continue
        srodek.append((float(punkt.lat), float(punkt.lng)))
    return [magazyn] + srodek + [magazyn], braki, len(srodek)


def _linie_proste(route, punkty):
    route.geometry_json = json.dumps({'type': 'LineString',
                                      'coordinates': [[p[1], p[0]] for p in punkty]})
    route.distance_km = round(sum(odleglosc_km(a, b) for a, b in zip(punkty, punkty[1:])), 1)
    route.duration_min = None
    route.geometry_approx = True


def przelicz(route, punkty_zamowien, http_post=requests.post, wymus=False):
    punkty, braki, liczba = _punkty(route, punkty_zamowien)
    skrot = skrot_przebiegu(punkty) + ('-braki' if braki else '')
    skrot = hashlib.sha1(skrot.encode('utf-8')).hexdigest()
    if not wymus and route.geometry_hash == skrot:
        return False
    route.geometry_hash = skrot
    if liczba == 0:
        route.geometry_json = route.distance_km = route.duration_min = None
        route.geometry_approx = braki
        return True
    klucz = klucz_ors()
    if klucz and not braki and liczba <= MAKS_PRZYSTANKOW:
        try:
            odp = http_post(ORS_URL, json={'coordinates': [[p[1], p[0]] for p in punkty]},
                            headers={'Authorization': klucz, 'Content-Type': 'application/json'},
                            timeout=TIMEOUT_S)
            odp.raise_for_status()
            cecha = odp.json()['features'][0]
            podsumowanie = cecha['properties']['summary']
            route.geometry_json = json.dumps(cecha['geometry'])
            route.distance_km = round(float(podsumowanie['distance']) / 1000.0, 1)
            route.duration_min = int(round(float(podsumowanie['duration']) / 60.0))
            route.geometry_approx = False
            return True
        except Exception as e:
            logger.warning("ORS nie policzyl przebiegu - linie proste", extra={
                'route_id': route.id, 'error': str(e)})
    _linie_proste(route, punkty)
    return True


def przebieg(route):
    return json.loads(route.geometry_json) if route.geometry_json else None
```

- [ ] **Step 4: Uruchom testy**

Run: `PYTEST tests/test_logistyka_trasy_routing.py`
Expected: PASS. (`duration 18000 s` → 300 min; `412345.6 m` → 412.3 km.)

- [ ] **Step 5: Commit**

```bash
git add modules/production/logistics/services/routing.py tests/test_logistyka_trasy_routing.py
git commit -m "feat(production): przebieg trasy z OpenRouteService z fallbackiem na linie proste

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: API tras, floty i dostępności

**Files:**
- Create: `modules/production/logistics/routers/trasy_api.py`
- Modify: `modules/production/logistics/__init__.py` (import routera)
- Test: `tests/test_logistyka_trasy_api.py`

**Interfaces:**
- Consumes: `fleet.*`, `routes.*`, `routing.przelicz`, `routing.przebieg`, `geocoding.geo_zamowien`, `lista.serializuj`, `panel_api.guard`, `panel_api._user_id`, `panel_api._blad`.
- Produces (prefiks `/production/api/logistics`, wszystko za `guard`; odmowy `LogistykaBlad` → `{'success': False, 'error': komunikat}` ze statusem błędu):
  - `GET /vehicles?aktywne=1` → `{'success', 'vehicles': [...]}`; `POST /vehicles` → 201 `{'vehicle'}`; `PUT /vehicles/<id>` → `{'vehicle'}`; `POST /vehicles/<id>/active` body `{'active': bool}` → `{'vehicle'}`.
  - `GET /drivers` → `{'drivers': [{'id', 'nazwa'}]}`.
  - `GET /availability?date_from=&date_to=&route_id=` → `routes.dostepnosc(...)`.
  - `GET /routes?status=&od=&do=` → `{'routes': [serializuj_trase + podsumowanie]}` (sortowanie: status aktywne najpierw, potem `date_from`).
  - `POST /routes` → 201 `{'route': szczegoly}`; `GET /routes/<id>` → `{'route': szczegoly}`; `PUT /routes/<id>`; `DELETE /routes/<id>`.
  - `szczegoly` = `serializuj_trase(route, zamowienia, punkty)` + `'przystanki': [{'pozycja', 'zamowienie': lista.serializuj(o, punkt, route)}]` + `'przebieg': routing.przebieg(route)`; **przed** złożeniem `routing.przelicz(route, punkty)` (bez `wymus`), a gdy zwróci `True` — `commit`.
  - `POST /routes/<id>/stops` body `{'order_ids': [...]}` → `{'dodane', 'bledy', 'route': szczegoly}`; `DELETE /routes/<id>/stops/<order_id>`; `PUT /routes/<id>/stops/order` body `{'order_ids': [...]}`.
  - `POST /routes/<id>/approve`, `/revert`, `/complete` (body `{'delivered_order_ids': [...]}`, brak = wszystkie), `/restore` → `{'route': szczegoly}` (+ `wynik` dla `complete`).
  - `GET /routes/map` → `{'routes': [{'id', 'nazwa', 'status', 'date_from', 'date_to', 'przebieg', 'przyblizony', 'przystanki': [{'pozycja', 'order_id', 'numer', 'klient', 'lat', 'lng'}]}]}` dla tras aktywnych.
  - `GET /routes/<id>/routimo` → plik `.xlsx` (Task 7; tu trasa zwraca 501 do czasu Task 7 — **nie** twórz jej w tym zadaniu).

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_trasy_api.py`:
```python
# -*- coding: utf-8 -*-
import pytest

from modules.production.logistics import sposoby as s
from tests.logistyka_fixtures import BASE, app, client, kierowca, pojazd, zamowienie  # noqa: F401


@pytest.fixture(autouse=True)
def bez_ors(app):
    app.config.pop('OPENROUTESERVICE_API_KEY', None)


def _nowa(client, **dane):
    dane.setdefault('name', 'Kraków')
    dane.setdefault('date_from', '2026-10-01')
    return client.post(BASE + '/routes', json=dane)


def test_flota_crud(client):
    r = client.post(BASE + '/vehicles', json={'name': 'Iveco', 'capacity_kg': 1500})
    assert r.status_code == 201
    vid = r.get_json()['vehicle']['id']
    assert client.put(BASE + '/vehicles/%d' % vid, json={'name': 'Iveco Daily'}).status_code == 200
    assert client.post(BASE + '/vehicles/%d/active' % vid, json={'active': False}).get_json()['vehicle']['is_active'] is False
    assert client.get(BASE + '/vehicles?aktywne=1').get_json()['vehicles'] == []
    assert client.post(BASE + '/vehicles', json={'name': ''}).status_code == 422


def test_dostepnosc_i_konflikt(client, app):
    with app.app_context():
        vid = pojazd().id
    assert _nowa(client, vehicle_id=vid).status_code == 201
    d = client.get(BASE + '/availability?date_from=2026-10-01&date_to=2026-10-01').get_json()
    assert d['pojazdy'][0]['zajety'] is True and d['pojazdy'][0]['trasa'] == 'Kraków'
    r = _nowa(client, name='Druga', vehicle_id=vid)
    assert r.status_code == 409 and 'Kraków' in r.get_json()['error']


def test_pelny_cykl_trasy(client, app):
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
        b = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
    rid = _nowa(client).get_json()['route']['id']
    r = client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a, b]})
    assert r.get_json()['dodane'] == [a, b]
    trasa = r.get_json()['route']
    assert [p['zamowienie']['id'] for p in trasa['przystanki']] == [a, b]
    assert trasa['podsumowanie']['przystanki'] == 2
    assert client.put(BASE + '/routes/%d/stops/order' % rid, json={'order_ids': [b, a]}).status_code == 200
    assert client.post(BASE + '/routes/%d/approve' % rid).get_json()['route']['status'] == 'zatwierdzona'
    assert client.delete(BASE + '/routes/%d/stops/%d' % (rid, a)).status_code == 409
    r = client.post(BASE + '/routes/%d/complete' % rid, json={'delivered_order_ids': [b]})
    assert r.get_json()['wynik'] == {'dostarczone': [b], 'niedostarczone': [a]}
    assert client.post(BASE + '/routes/%d/restore' % rid).get_json()['route']['status'] == 'zatwierdzona'


def test_mapa_tras_aktywnych(client, app):
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT).id
    rid = _nowa(client).get_json()['route']['id']
    client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a]})
    mapa = client.get(BASE + '/routes/map').get_json()['routes']
    assert mapa[0]['id'] == rid and mapa[0]['przystanki'][0]['order_id'] == a


def test_kierowcy(client, app):
    with app.app_context():
        kierowca(imie='Adam', nazwisko='Nowak')
    assert client.get(BASE + '/drivers').get_json()['drivers'][0]['nazwa'] == 'Adam Nowak'


def test_usuniecie_roboczej_i_404(client):
    rid = _nowa(client).get_json()['route']['id']
    assert client.delete(BASE + '/routes/%d' % rid).status_code == 200
    assert client.get(BASE + '/routes/%d' % rid).status_code == 404
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_trasy_api.py`
Expected: FAIL (404).

- [ ] **Step 3: Implementacja**

`modules/production/logistics/routers/trasy_api.py`:
```python
# -*- coding: utf-8 -*-
"""API tras, floty i dostępności — /production/api/logistics/* (etap 3)."""
from datetime import date

from flask import jsonify, request

from extensions import db
from modules.production.logistics import logistics_panel_bp
from modules.production.logistics.models import Route, Vehicle
from modules.production.logistics.routers.panel_api import _blad, _user_id, guard
from modules.production.logistics.services import fleet, geocoding, lista, routes, routing
from modules.production.logistics.services.delivery import LogistykaBlad

KOLEJNOSC_STATUSOW = {'robocza': 0, 'zatwierdzona': 1, 'wykonana': 2}


def _odmowa(e):
    db.session.rollback()
    return _blad(e.komunikat, e.status)


def _szczegoly(route):
    zamowienia = routes.zamowienia_trasy(route)
    punkty = geocoding.geo_zamowien([o.id for o in zamowienia])
    if routing.przelicz(route, punkty):
        db.session.commit()
    dane = routes.serializuj_trase(route, zamowienia, punkty)
    dane['przystanki'] = [{'pozycja': i, 'zamowienie': lista.serializuj(o, punkty.get(o.id), route)}
                          for i, o in enumerate(zamowienia, start=1)]
    dane['przebieg'] = routing.przebieg(route)
    return dane


def _trasa_albo_none(route_id):
    return Route.query.get(route_id)


# ── Flota ────────────────────────────────────────────────────────────────

@logistics_panel_bp.route('/vehicles', methods=['GET'])
@guard
def vehicles():
    return jsonify({'success': True,
                    'vehicles': fleet.lista_pojazdow(tylko_aktywne=request.args.get('aktywne') == '1')})


@logistics_panel_bp.route('/vehicles', methods=['POST'])
@guard
def vehicle_create():
    try:
        pojazd = fleet.zapisz_pojazd(request.get_json(silent=True) or {})
    except LogistykaBlad as e:
        return _odmowa(e)
    db.session.commit()
    return jsonify({'success': True, 'vehicle': fleet.serializuj_pojazd(pojazd)}), 201


@logistics_panel_bp.route('/vehicles/<int:vehicle_id>', methods=['PUT'])
@guard
def vehicle_update(vehicle_id):
    pojazd = Vehicle.query.get(vehicle_id)
    if pojazd is None:
        return _blad(u'Nie ma takiego pojazdu.', 404)
    dane = dict(fleet.serializuj_pojazd(pojazd), **(request.get_json(silent=True) or {}))
    try:
        fleet.zapisz_pojazd(dane, pojazd)
    except LogistykaBlad as e:
        return _odmowa(e)
    db.session.commit()
    return jsonify({'success': True, 'vehicle': fleet.serializuj_pojazd(pojazd)})


@logistics_panel_bp.route('/vehicles/<int:vehicle_id>/active', methods=['POST'])
@guard
def vehicle_active(vehicle_id):
    pojazd = Vehicle.query.get(vehicle_id)
    if pojazd is None:
        return _blad(u'Nie ma takiego pojazdu.', 404)
    fleet.ustaw_aktywnosc(pojazd, bool((request.get_json(silent=True) or {}).get('active')))
    db.session.commit()
    return jsonify({'success': True, 'vehicle': fleet.serializuj_pojazd(pojazd)})


@logistics_panel_bp.route('/drivers', methods=['GET'])
@guard
def drivers():
    return jsonify({'success': True, 'drivers': fleet.kierowcy()})


@logistics_panel_bp.route('/availability', methods=['GET'])
@guard
def availability():
    try:
        od = date.fromisoformat(request.args.get('date_from', ''))
        do = date.fromisoformat(request.args.get('date_to') or request.args.get('date_from', ''))
    except ValueError:
        return _blad(u'Podaj daty RRRR-MM-DD.', 422)
    route_id = request.args.get('route_id', type=int)
    return jsonify(dict(routes.dostepnosc(od, do, route_id), success=True))


# ── Trasy ────────────────────────────────────────────────────────────────

@logistics_panel_bp.route('/routes', methods=['GET'])
@guard
def routes_list():
    zapytanie = Route.query
    if request.args.get('status'):
        zapytanie = zapytanie.filter(Route.status == request.args['status'])
    if request.args.get('od'):
        zapytanie = zapytanie.filter(Route.date_to >= request.args['od'])
    if request.args.get('do'):
        zapytanie = zapytanie.filter(Route.date_from <= request.args['do'])
    trasy = sorted(zapytanie.all(), key=lambda r: (KOLEJNOSC_STATUSOW[r.status], r.date_from, r.id))
    wynik = []
    for trasa in trasy:
        zamowienia = routes.zamowienia_trasy(trasa)
        wynik.append(routes.serializuj_trase(
            trasa, zamowienia, geocoding.geo_zamowien([o.id for o in zamowienia])))
    return jsonify({'success': True, 'routes': wynik})


@logistics_panel_bp.route('/routes', methods=['POST'])
@guard
def route_create():
    try:
        trasa = routes.utworz(request.get_json(silent=True) or {}, user_id=_user_id())
    except LogistykaBlad as e:
        return _odmowa(e)
    db.session.commit()
    return jsonify({'success': True, 'route': _szczegoly(trasa)}), 201


@logistics_panel_bp.route('/routes/map', methods=['GET'])
@guard
def routes_map():
    wynik = []
    for trasa in Route.query.filter(Route.status.in_(routes.AKTYWNE)).order_by(Route.date_from).all():
        zamowienia = routes.zamowienia_trasy(trasa)
        punkty = geocoding.geo_zamowien([o.id for o in zamowienia])
        if routing.przelicz(trasa, punkty):
            db.session.commit()
        wynik.append({
            'id': trasa.id, 'nazwa': trasa.name, 'status': trasa.status,
            'date_from': trasa.date_from.isoformat(), 'date_to': trasa.date_to.isoformat(),
            'przebieg': routing.przebieg(trasa), 'przyblizony': bool(trasa.geometry_approx),
            'przystanki': [{'pozycja': i, 'order_id': o.id, 'numer': o.internal_order_number,
                            'klient': o.client_name,
                            'lat': float(punkty[o.id].lat) if punkty.get(o.id) and punkty[o.id].lat is not None else None,
                            'lng': float(punkty[o.id].lng) if punkty.get(o.id) and punkty[o.id].lng is not None else None}
                           for i, o in enumerate(zamowienia, start=1)],
        })
    return jsonify({'success': True, 'routes': wynik})


@logistics_panel_bp.route('/routes/<int:route_id>', methods=['GET'])
@guard
def route_get(route_id):
    trasa = _trasa_albo_none(route_id)
    if trasa is None:
        return _blad(u'Nie ma takiej trasy.', 404)
    return jsonify({'success': True, 'route': _szczegoly(trasa)})


def _akcja(route_id, funkcja):
    trasa = _trasa_albo_none(route_id)
    if trasa is None:
        return _blad(u'Nie ma takiej trasy.', 404)
    try:
        wynik = funkcja(trasa)
    except LogistykaBlad as e:
        return _odmowa(e)
    db.session.commit()
    odpowiedz = {'success': True, 'route': _szczegoly(trasa)}
    if isinstance(wynik, dict):
        odpowiedz.update(wynik if 'dodane' in wynik else {'wynik': wynik})
    return jsonify(odpowiedz)


@logistics_panel_bp.route('/routes/<int:route_id>', methods=['PUT'])
@guard
def route_update(route_id):
    dane = request.get_json(silent=True) or {}
    return _akcja(route_id, lambda t: routes.edytuj(t, dane, user_id=_user_id()) and None)


@logistics_panel_bp.route('/routes/<int:route_id>', methods=['DELETE'])
@guard
def route_delete(route_id):
    trasa = _trasa_albo_none(route_id)
    if trasa is None:
        return _blad(u'Nie ma takiej trasy.', 404)
    try:
        routes.usun(trasa, user_id=_user_id())
    except LogistykaBlad as e:
        return _odmowa(e)
    db.session.commit()
    return jsonify({'success': True})


@logistics_panel_bp.route('/routes/<int:route_id>/stops', methods=['POST'])
@guard
def route_stops_add(route_id):
    ids = (request.get_json(silent=True) or {}).get('order_ids') or []
    if not isinstance(ids, list) or not ids:
        return _blad(u'Podaj zamówienia do dodania.', 422)
    return _akcja(route_id, lambda t: routes.dodaj_przystanki(t, ids, user_id=_user_id()))


@logistics_panel_bp.route('/routes/<int:route_id>/stops/<int:order_id>', methods=['DELETE'])
@guard
def route_stop_remove(route_id, order_id):
    return _akcja(route_id, lambda t: routes.usun_przystanek(t, order_id, user_id=_user_id()) and None)


@logistics_panel_bp.route('/routes/<int:route_id>/stops/order', methods=['PUT'])
@guard
def route_stops_order(route_id):
    ids = (request.get_json(silent=True) or {}).get('order_ids') or []
    return _akcja(route_id, lambda t: routes.zmien_kolejnosc(t, ids))


@logistics_panel_bp.route('/routes/<int:route_id>/approve', methods=['POST'])
@guard
def route_approve(route_id):
    return _akcja(route_id, lambda t: routes.zatwierdz(t, user_id=_user_id()))


@logistics_panel_bp.route('/routes/<int:route_id>/revert', methods=['POST'])
@guard
def route_revert(route_id):
    return _akcja(route_id, lambda t: routes.cofnij_do_roboczej(t, user_id=_user_id()))


@logistics_panel_bp.route('/routes/<int:route_id>/complete', methods=['POST'])
@guard
def route_complete(route_id):
    ids = (request.get_json(silent=True) or {}).get('delivered_order_ids')
    return _akcja(route_id, lambda t: routes.wykonaj(t, ids, user_id=_user_id()))


@logistics_panel_bp.route('/routes/<int:route_id>/restore', methods=['POST'])
@guard
def route_restore(route_id):
    return _akcja(route_id, lambda t: routes.przywroc(t, user_id=_user_id()))
```
W `modules/production/logistics/__init__.py` ostatni import:
```python
from modules.production.logistics.routers import cron_api, panel_api, trasy_api  # noqa: E402,F401
```
Uwaga na `_akcja`: `routes.wykonaj` zwraca `{'dostarczone', 'niedostarczone'}` → trafia do `wynik`; `dodaj_przystanki` zwraca `{'dodane', 'bledy'}` → trafia na górny poziom odpowiedzi. `lista.serializuj(o, punkt, route)` — trzeci argument to trasa (Task 4).

- [ ] **Step 4: Uruchom testy**

Run: `PYTEST tests/test_logistyka_trasy_api.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/production/logistics tests/test_logistyka_trasy_api.py
git commit -m "feat(production): API tras, floty, kierowcow i dostepnosci zasobow

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Wspólny generator Routimo i eksport trasy

**Files:**
- Create: `modules/production/logistics/services/routimo.py`
- Modify: `modules/reports/routers.py` (`generate_routimo_excel`, ok. `:3057-3257`)
- Modify: `modules/production/logistics/routers/trasy_api.py` (`GET /routes/<id>/routimo`)
- Test: `tests/test_logistyka_routimo.py`

**Interfaces:**
- Consumes: `adresy.extract_house_and_apartment_number` (etap 2), `routes.zamowienia_trasy`, `delivery.aktywne_produkty`, `geocoding.geo_zamowien`, `PostcodeToStateMapper.get_state_from_postcode(postcode)` (`modules/reports/utils.py:124`).
- Produces: `routimo.NAGLOWKI` (37 nazw kolumn — dokładna kopia listy `headers` z `generate_routimo_excel`), `routimo.SZEROKOSCI` (kopia `column_widths`), `routimo.KOLUMNA_KOMENTARZA = 33`, `routimo.zbuduj_excel(wiersze: list[list]) -> bytes` (całe formatowanie ze starej funkcji: arkusze `Sheet1` + pusty `Sheet2`, styl nagłówka, szerokości, wysokość wiersza 1 = 43, zawijanie i wysokość wiersza dla komentarza wieloliniowego), `routimo.wiersze_trasy(route) -> list[list]`, `routimo.nazwa_pliku(route) -> str`. `modules/reports/routers.generate_routimo_excel(grouped_orders)` buduje wiersze jak dotąd i woła `zbuduj_excel`.

- [ ] **Step 1: Test charakteryzujący stary eksport (MA PRZEJŚĆ przed refaktorem)**

`tests/test_logistyka_routimo.py` (pierwsza część):
```python
# -*- coding: utf-8 -*-
import io
from types import SimpleNamespace as NS

import openpyxl

from modules.reports.routers import generate_routimo_excel

GRUPA = [{
    'records': [NS(raw_product_name='Blat dębowy 200x60x4', quantity=2),
                NS(raw_product_name='Parapet 100x30x3', quantity=1)],
    'baselinker_order_id': 12345, 'internal_order_number': '26/00042',
    'customer_name': 'Jan Kowalski', 'delivery_address': 'ul. Floriańska 10/5',
    'delivery_postcode': '31-021', 'delivery_city': 'Kraków', 'delivery_state': 'małopolskie',
    'phone': '600100200', 'email': 'jan@example.com', 'delivery_cost': 123.0,
    'payment_method': 'Przelew', 'order_amount_net': 2000.0, 'total_quantity': 3,
    'total_volume': 0.1, 'total_value_net': 2000.0, 'current_status': 'x',
}]


def _arkusz(tresc):
    return openpyxl.load_workbook(io.BytesIO(tresc)).active


def test_stary_eksport_routimo_bez_zmian():
    """Charakterystyka: przechodzi PRZED i PO wydzieleniu generatora."""
    ark = _arkusz(generate_routimo_excel(GRUPA))
    naglowki = [c.value for c in ark[1]]
    assert len(naglowki) == 37 and naglowki[0] == 'Nazwa' and naglowki[-1] == 'Dodatkowe 2'
    wiersz = [c.value for c in ark[2]]
    assert wiersz[:10] == ['Jan Kowalski', 'Jan Kowalski', 12345, '26/00042', 100.0,
                           'Floriańska', '10', '5', '31-021', 'Kraków']
    assert wiersz[26] == 80.0            # waga = 0.1 m³ × 800
    assert wiersz[32] == 'Blat dębowy 200x60x4 x2\nParapet 100x30x3 x1'
    assert wiersz[33] == '12345, 26/00042'
    assert ark.column_dimensions['A'].width == 40.0
    assert ark.row_dimensions[1].height == 43.0
    assert ark[1][0].font.bold and ark[2][32].alignment.wrap_text
    assert ark.parent.sheetnames == ['Sheet1', 'Sheet2']
```

- [ ] **Step 2: Uruchom — ma PRZEJŚĆ na starym kodzie**

Run: `PYTEST tests/test_logistyka_routimo.py::test_stary_eksport_routimo_bez_zmian`
Expected: PASS. Jeśli któraś wartość się różni — popraw **test** do faktycznego zachowania (to charakterystyka), nie kod. Commit samego testu:
```bash
git add tests/test_logistyka_routimo.py
git commit -m "test(reports): charakterystyka eksportu Routimo przed wydzieleniem generatora

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 3: Testy nowego eksportu (failing)**

Dopisz do `tests/test_logistyka_routimo.py`:
```python
from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import OrderGeo
from modules.production.logistics.services import routes, routimo
from tests.logistyka_fixtures import BASE, app, client, pojazd, zamowienie  # noqa: F401,E402


def test_wspolny_generator_to_te_same_naglowki():
    assert len(routimo.NAGLOWKI) == 37
    ark = _arkusz(routimo.zbuduj_excel([['x'] * 37]))
    assert [c.value for c in ark[1]] == routimo.NAGLOWKI


def _zatwierdzona(app):
    v = pojazd(name='Iveco KR 1')
    trasa = routes.utworz({'name': 'Kraków + Tarnów', 'date_from': '2026-10-01', 'vehicle_id': v.id})
    a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    a.delivery_address, a.delivery_postcode, a.client_phone = 'Floriańska 10/5', '31-021', '600'
    b = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    db.session.add(OrderGeo(order_id=a.id, lat=50.062726, lng=19.93962, source='gugik',
                            quality='dokladna', address_hash='x' * 40))
    routes.dodaj_przystanki(trasa, [b.id, a.id])
    routes.zatwierdz(trasa)
    db.session.commit()
    return trasa, a, b


def test_wiersze_trasy_w_kolejnosci_przystankow(app):
    with app.app_context():
        trasa, a, b = _zatwierdzona(app)
        wiersze = routimo.wiersze_trasy(trasa)
        assert [w[2] for w in wiersze] == [b.baselinker_order_id, a.baselinker_order_id]
        w = wiersze[1]
        assert (w[5], w[6], w[7], w[8]) == ('Floriańska', '10', '5', '31-021')
        assert w[20] == '2026-10-01' and w[22] == 'Iveco KR 1'
        assert (w[30], w[31]) == (50.062726, 19.93962)
        assert w[11] == 'małopolskie'
        assert wiersze[0][30] == ''       # bez współrzędnych — puste


def test_eksport_tylko_dla_zatwierdzonej(client, app):
    with app.app_context():
        trasa, _a, _b = _zatwierdzona(app)
        rid = trasa.id
        robocza = routes.utworz({'name': 'R', 'date_from': '2026-11-01'})
        db.session.commit()
        rid_roboczej = robocza.id
    r = client.get(BASE + '/routes/%d/routimo' % rid)
    assert r.status_code == 200
    assert r.headers['Content-Type'].startswith(
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    assert 'routimo_' in r.headers['Content-Disposition']
    assert client.get(BASE + '/routes/%d/routimo' % rid_roboczej).status_code == 409
```

- [ ] **Step 4: Uruchom — nowe testy mają paść**

Run: `PYTEST tests/test_logistyka_routimo.py`
Expected: FAIL tylko nowych testów.

- [ ] **Step 5: Wydzielenie generatora**

1. Utwórz `modules/production/logistics/services/routimo.py` (formatowanie przepisane z `generate_routimo_excel` — przed zapisem porównaj z aktualnym kodem funkcji; jeśli coś się różni, np. ktoś dołożył styl, weź wersję z kodu; test charakteryzujący z Step 1 pilnuje wyniku):
```python
# -*- coding: utf-8 -*-
"""
Eksport do Routimo — wspólny generator Excela (spec 8.4).

Formatowanie przeniesione 1:1 z modules/reports/routers.generate_routimo_excel;
raporty budują swoje wiersze i wołają zbuduj_excel(), trasy logistyki —
wiersze_trasy(). Kolumny: 37, kolejność jak w NAGLOWKI.
"""
import io
import re

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from modules.production.logistics.adresy import extract_house_and_apartment_number
from modules.production.logistics.services import delivery, geocoding, routes

WAGA_KG_NA_M3 = 800
KOLUMNA_KOMENTARZA = 33  # AG — wieloliniowa lista produktów

NAGLOWKI = [
    'Nazwa', 'Klient', 'Nazwa przesyłki', 'Numer wew.', 'Koszty kuriera netto', 'Ulica',
    'Numer domu', 'Numer mieszkania', 'Kod pocztowy', 'Miasto', 'Kraj', 'Region',
    'Numer telefonu', 'Email', 'Email klienta', 'Nip klienta', 'Początek okna czasowego',
    'Koniec okna czasowego', 'Okno czasowe', 'Czas na wykonanie zadania',
    'Oczekiwana data realizacji', 'Harmonogram', 'Pojazd', 'Typy pojazdów',
    'Liczba przesyłek', 'Wielkość przesyłki', 'Waga przesyłki', 'Wartość przesyłki',
    'Forma płatności', 'Waluta', 'Szerokość geograficzna', 'Długość geograficzna',
    'Komentarz', 'Komentarz 2', 'Uwagi', 'Dodatkowe 1', 'Dodatkowe 2',
]

SZEROKOSCI = {
    'A': 40.0, 'B': 31.81, 'C': 17.0, 'D': 13.0, 'E': 13.0, 'F': 32.0, 'G': 9.0, 'H': 9.0,
    'I': 14.0, 'J': 25.0, 'K': 12.0, 'L': 20.0, 'M': 15.0, 'N': 25.0, 'O': 38.0, 'P': 15.0,
    'Q': 20.0, 'R': 20.0, 'S': 15.0, 'T': 25.0, 'U': 20.0, 'V': 15.0, 'W': 15.0, 'X': 20.0,
    'Y': 15.0, 'Z': 18.0, 'AA': 15.0, 'AB': 18.0, 'AC': 20.0, 'AD': 10.0, 'AE': 20.0,
    'AF': 20.0, 'AG': 70.0, 'AH': 20.0, 'AI': 25.0, 'AJ': 15.0, 'AK': 15.0,
}


def zbuduj_excel(wiersze):
    """Lista wierszy (każdy = 37 wartości w kolejności NAGLOWKI) → bytes pliku .xlsx."""
    skoroszyt = openpyxl.Workbook()
    arkusz = skoroszyt.active
    arkusz.title = 'Sheet1'
    skoroszyt.create_sheet('Sheet2')  # pusty drugi arkusz, jak we wzorcu Routimo

    wypelnienie = PatternFill(start_color='F3F3F3', end_color='EFEFEF', fill_type='solid')
    czcionka = Font(bold=True, underline='single')
    wyrownanie = Alignment(horizontal='left', vertical='center', wrap_text=True)
    linia = Side(border_style='thin', color='000000')
    obramowanie = Border(left=linia, right=linia, top=linia, bottom=linia)
    for kolumna, naglowek in enumerate(NAGLOWKI, 1):
        komorka = arkusz.cell(row=1, column=kolumna, value=naglowek)
        komorka.fill, komorka.font = wypelnienie, czcionka
        komorka.alignment, komorka.border = wyrownanie, obramowanie
    for litera, szerokosc in SZEROKOSCI.items():
        arkusz.column_dimensions[litera].width = szerokosc
    arkusz.row_dimensions[1].height = 43.0

    for nr_wiersza, wiersz in enumerate(wiersze, 2):
        for kolumna, wartosc in enumerate(wiersz, 1):
            komorka = arkusz.cell(row=nr_wiersza, column=kolumna, value=wartosc)
            if kolumna == KOLUMNA_KOMENTARZA:
                komorka.alignment = Alignment(horizontal='left', vertical='top', wrap_text=True)
        komentarz = wiersz[KOLUMNA_KOMENTARZA - 1] if len(wiersz) >= KOLUMNA_KOMENTARZA else None
        if komentarz and '\n' in str(komentarz):
            linie = str(komentarz).count('\n') + 1
            arkusz.row_dimensions[nr_wiersza].height = max(15 * linie, 15)

    bufor = io.BytesIO()
    skoroszyt.save(bufor)
    return bufor.getvalue()
```
2. W `modules/reports/routers.py` w `generate_routimo_excel` zostaw część budującą `row_data` dla każdego zamówienia, zbieraj je do listy `wiersze` i na końcu `return zbuduj_excel(wiersze)` (import `from modules.production.logistics.services.routimo import zbuduj_excel` na górze pliku). Usuń przeniesione formatowanie. Log `reports_logger.info("Wygenerowano Excel dla Routimo…")` zostaje w raportach.
3. Dopisz w `routimo.py`:
```python
def _produkty(order):
    return '\n'.join(u'{} x{}'.format(p.original_product_name, p.quantity or 1)
                     for p in delivery.aktywne_produkty(order))


def wiersze_trasy(route):
    from modules.reports.utils import PostcodeToStateMapper
    zamowienia = routes.zamowienia_trasy(route)
    punkty = geocoding.geo_zamowien([o.id for o in zamowienia])
    pojazd = route.vehicle.name if route.vehicle is not None else ''
    wiersze = []
    for order in zamowienia:
        aktywne = delivery.aktywne_produkty(order)
        dom, mieszkanie, ulica = extract_house_and_apartment_number(order.delivery_address or '')
        m3 = sum(float(p.volume_m3 or 0) * (p.quantity or 1) for p in aktywne)
        wartosc = sum(float(p.total_value_net or 0) for p in aktywne)
        punkt = punkty.get(order.id)
        kraj = (order.delivery_country_code or 'PL').upper()
        wiersze.append([
            order.client_name or '', order.client_name or '', order.baselinker_order_id,
            order.internal_order_number or '', '', ulica, dom, mieszkanie,
            order.delivery_postcode or '', order.delivery_city or '',
            'Polska' if kraj == 'PL' else kraj,
            PostcodeToStateMapper.get_state_from_postcode(order.delivery_postcode or '') or '',
            order.client_phone or '', '', order.client_email or '', '', '', '', '', '',
            route.date_from.isoformat(), '', pojazd, '',
            sum(int(p.quantity or 0) for p in aktywne), round(m3, 3),
            round(m3 * WAGA_KG_NA_M3, 2), round(wartosc, 2), '', 'PLN',
            float(punkt.lat) if punkt is not None and punkt.lat is not None else '',
            float(punkt.lng) if punkt is not None and punkt.lng is not None else '',
            _produkty(order),
            u'{}, {}'.format(order.baselinker_order_id or '', order.internal_order_number or '').strip(', '),
            '', '', '',
        ])
    return wiersze


def nazwa_pliku(route):
    slug = re.sub(r'[^a-z0-9]+', '-', route.name.lower()).strip('-') or 'trasa'
    return 'routimo_{}_{}.xlsx'.format(slug, route.date_from.isoformat())
```
   (Jeśli `PostcodeToStateMapper.get_state_from_postcode` zwraca nazwę w innej formie niż `'małopolskie'`, dostosuj asercję testu do faktycznej wartości.)
4. W `routers/trasy_api.py`:
```python
import io
from flask import send_file
from modules.production.logistics.services import routimo


@logistics_panel_bp.route('/routes/<int:route_id>/routimo', methods=['GET'])
@guard
def route_routimo(route_id):
    trasa = Route.query.get(route_id)
    if trasa is None:
        return _blad(u'Nie ma takiej trasy.', 404)
    if trasa.status not in ('zatwierdzona', 'wykonana'):
        return _blad(u'Eksport do Routimo jest dostępny po zatwierdzeniu trasy.', 409)
    tresc = routimo.zbuduj_excel(routimo.wiersze_trasy(trasa))
    return send_file(io.BytesIO(tresc), as_attachment=True,
                     download_name=routimo.nazwa_pliku(trasa),
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
```
   (Flask < 2.2 używa `attachment_filename` zamiast `download_name` — sprawdź wersję w `requirements.txt` i dobierz.)

- [ ] **Step 6: Uruchom testy**

Run: `PYTEST tests/test_logistyka_routimo.py` oraz `PYTEST tests/ -k "routimo or reports"`
Expected: PASS — **także** `test_stary_eksport_routimo_bez_zmian`.

- [ ] **Step 7: Commit**

```bash
git add modules/production/logistics modules/reports/routers.py tests/test_logistyka_routimo.py
git commit -m "feat(production): eksport trasy do Routimo na wspolnym generatorze z raportami

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Interfejs — Trasy, Flota, widok tras na mapie (skill `frontend-design`)

**REQUIRED:** Przed napisaniem HTML/CSS/JS wywołaj skill `frontend-design:frontend-design`. To **rozbudowa**
interfejsu z etapu 2, nie nowy projekt: te same klasy `lg-*`, zmienne `--il-*`, przyciski `lg-przycisk`
(`lg-przycisk--glowny`), okna `<dialog class="lg-dialog">` (wzór: okno poprawki adresu w `tab_content.html`),
komunikaty przez `pokazKomunikat` z `logistics.js`. Teksty po polsku, „Base.”. Przeczytaj najpierw sekcję
„Frontend” w Kontekście tego planu i obecne pliki zakładki.

**Files:**
- Modify: `modules/production/logistics/templates/logistics/tab_content.html` (podzakładki, panele widoków, przełącznik mapy, okna, ładowanie skryptów, `<link>` nowego CSS)
- Modify: `modules/production/logistics/static/js/logistics-map.js` (**tylko** nowe metody API i warstwa tras)
- Modify: `modules/production/logistics/static/js/logistics.js` (**tylko** punkty zaczepienia: plakietka trasy w komórce sposobu, filtr „Transport bez trasy”, akcja hurtowa, komunikat `usunieto_z_trasy`, przełączanie podzakładek)
- Create: `modules/production/logistics/static/js/logistics-routes.js` (podzakładka Trasy + edytor + mapka), `modules/production/logistics/static/js/logistics-fleet.js` (podzakładka Flota), `modules/production/logistics/static/css/logistics-trasy.css`
- Test: `tests/test_logistyka_trasy_ui.py`

**Interfaces:**
- Consumes: całe API z Task 6–7 oraz `/orders` (klucz `trasa`, filtr `sposob=bez_trasy`, `usunieto_z_trasy` w odpowiedzi hurtu).
- Produces:
  - podzakładki: przyciski w `.lg-podzakladki` z `data-lg-widok="dashboard|routes|fleet"`, panele `data-logistics-view="dashboard|routes|fleet"`; obecna treść Dashboardu (liczniki, baner, `.lg-uklad`) trafia **w całości** do panelu `dashboard`;
  - `window.LogisticsMap` rozszerzone o: `ustawWidok('zamowienia'|'trasy')`, `renderTrasy(trasy)` (dane z `GET /routes/map`), `onWyborTrasy(cb)` (`cb(route_id)`), `nowaWarstwaPodkladu()` (nowa `L.TileLayer` dla aktualnie wybranego podkładu — z tym samym kluczem CARTO i tą samą obsługą odrzuconego klucza co mapa Dashboardu; dla mapki edytora trasy);
  - `window.LogisticsTab` rozszerzone o `komunikat(typ, tresc, opcje)` (opakowanie prywatnego `pokazKomunikat`) i `pokazWidok(widok, opcje)` (przełączenie podzakładki, np. `pokazWidok('routes', {route_id})`); `odswiez()` już jest — nowe pliki korzystają wyłącznie z tych metod, nie z wnętrza `logistics.js`;
  - `window.LogisticsRoutes` (`otworz(route_id)`, `zniszcz()`), `window.LogisticsFleet` (`zniszcz()`) — sprzątanie przy ponownym wstawieniu fragmentu, jak `LogisticsTab`/`LogisticsMap`.

**Wymagania funkcjonalne (spec 8.1–8.2, 7.2):**
1. **Podzakładki** Dashboard | Trasy | Flota w istniejącym `.lg-podzakladki` (role `tab`, `aria-selected`), przełączanie bez przeładowania, ostatnia zapamiętana w `localStorage` (w `try/catch`). Mapa Dashboardu po powrocie na podzakładkę musi się przerysować (jej `ResizeObserver` to łapie — sprawdź).
2. **Dashboard — mapa:** w pustym `.lg-mapa-widoki` przełącznik **„Zamówienia | Trasy”**. Widok Trasy (`GET /routes/map`, pobierane przy wejściu w widok i po każdej zmianie trasy): pinezki zamówień ukryte (warstwa klastrów zdjęta z mapy, nie zniszczona), każda aktywna trasa w innym kolorze (paleta ≥ 8 barw odróżnialnych od kolorów sposobów dostawy z legendy), polilinia przebiegu (przerywana, gdy `przyblizony`), numerowane znaczniki przystanków, magazyn; legenda mapy przełącza się na listę tras (nazwa, daty, status); klik w trasę/pozycję legendy → `onWyborTrasy` → podzakładka Trasy z otwartą trasą. Przełącznik podkładów, „Grupuj pinezki” i pastylka proporcji działają w obu widokach (grupowanie dotyczy tylko zamówień).
3. **Dashboard — lista (bez nowej kolumny** — układ kolumn przy 1280 px czeka na decyzję Konrada**):** dla transportu własnego pod selectem sposobu plakietka trasy („Kraków + Tarnów · robocza”, klik → edytor trasy) albo „bez trasy”; filtr **„Transport bez trasy”** (`sposob=bez_trasy`) jako dodatkowy przełącznik przy licznikach albo w narzędziach listy; akcja hurtowa **„Dodaj do trasy…”** (`data-lg-akcja="hurt-trasa"`) w pasku hurtu obok `hurt-sposob` → okno z wyborem trasy roboczej (`GET /routes?status=robocza`) albo „+ Nowa trasa” (nazwa + daty) → `POST /routes/<id>/stops`, wynik (`dodane`, `bledy` z numerami) przez `pokazKomunikat`; po zmianie sposobu dostawy komunikat „Usunięto z trasy X” z `usunieto_z_trasy`.
4. **Trasy — lista (lewa kolumna):** sekcje Robocze / Zatwierdzone / Wykonane (wykonane zwinięte, z filtrem dat), w każdej trasy po dacie; wiersz: nazwa, daty, pojazd, kierowca, liczba przystanków, waga, ikona ostrzeżenia przy przekroczonej ładowności. Przycisk „+ Nowa trasa”.
5. **Trasy — edytor (prawa kolumna):**
   - formularz: nazwa, data od, data do, pojazd (select), kierowca (select), notatka. Selecty z `GET /availability?date_from&date_to&route_id` — zajęte **widoczne, wyszarzone (`disabled`), z dopiskiem „(zajęty — nazwa trasy)”**; odświeżenie przy każdej zmianie dat;
   - przystanki: lista z numerami, **przeciąganie** (HTML5 drag & drop + przyciski ↑/↓ dla klawiatury) → `PUT /routes/<id>/stops/order`; przy każdym: numer, klient, adres (jak kolumna Adres listy: kod + miasto, ulica pod spodem), m³, ikona braku lokalizacji, „Usuń z trasy”;
   - „Do dodania”: zamówienia `sposob=bez_trasy` (z wyszukiwarką — ta sama fraza co lista: numer, klient, ulica, kod, miejscowość), „Dodaj” pojedynczo i dla zaznaczonych;
   - **mapka trasy**: osobna instancja Leaflet w edytorze z podkładem z `window.LogisticsMap.nowaWarstwaPodkladu()` (gdy mapy Dashboardu jeszcze nie ma — z OSM, bez klucza), przebieg i numerowane przystanki, magazyn; niszczona przy zamknięciu edytora i w `LogisticsRoutes.zniszcz()`;
   - podsumowanie: przystanki, m³, waga (kg), km, czas (h:mm), „przebieg przybliżony” gdy `przyblizony`, ostrzeżenie „Przekroczona ładowność pojazdu (X kg > Y kg)”, „N przystanków bez lokalizacji”;
   - akcje wg statusu: Robocza — „Zapisz”, „Zatwierdź”, „Usuń trasę” (potwierdzenie); Zatwierdzona — **„Eksport do Routimo”** (`GET /routes/<id>/routimo`, pobranie pliku), „Cofnij do roboczej”, „Odhacz jako wykonaną”; Wykonana — tylko odczyt, „Eksport do Routimo”, „Przywróć trasę”;
   - **„Odhacz jako wykonaną”**: `<dialog class="lg-dialog">` z listą przystanków, wszystkie zaznaczone jako dostarczone; odznaczone opisane „wróci do puli bez trasy”; potwierdzenie → `POST /routes/<id>/complete`;
   - błędy 409/422 z API (`error`) przy formularzu albo w oknie.
6. **Flota:** tabela (nazwa, rejestracja, ładowność, status), „+ Dodaj pojazd”, edycja w `<dialog class="lg-dialog">`, „Wyłącz/Włącz” (bez kasowania); wyłączone wyszarzone na końcu listy.
7. **Ładowanie skryptów:** `logistics-routes.js` potrzebuje Leafleta — dopisz go do istniejącego inline loadera jako kolejny krok po `logistics-map.js` (nowy atrybut `data-skrypt-trasy` na `#logistics-map`, ładowany „zawsze”, jak mapa). `logistics-fleet.js` — zwykły `<script src>` obok `logistics.js`. Nowy `<link>` do `logistics-trasy.css` obok `logistics.css`. Wszystko z nowymi `?v=`.
8. Brak jakiejkolwiek biblioteki z CDN; żadnych nowych zależności (drag & drop natywny).

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_trasy_ui.py`:
```python
# -*- coding: utf-8 -*-
import os

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'modules', 'production', 'logistics')


def _plik(*sciezka):
    return open(os.path.join(LOG, *sciezka), encoding='utf-8').read()


def _js():
    katalog = os.path.join(LOG, 'static', 'js')
    return ''.join(open(os.path.join(katalog, f), encoding='utf-8').read()
                   for f in os.listdir(katalog) if f.endswith('.js'))


def test_podzakladki_i_widoki():
    html = _plik('templates', 'logistics', 'tab_content.html')
    for widok in ('dashboard', 'routes', 'fleet'):
        assert 'data-logistics-view="{}"'.format(widok) in html
        assert 'data-lg-widok="{}"'.format(widok) in html
    assert 'data-skrypt-trasy=' in html
    assert 'js/logistics-fleet.js' in html and 'css/logistics-trasy.css' in html
    for cdn in ('unpkg.com', 'cdn.jsdelivr', 'cdnjs'):
        assert cdn not in html


def test_mapa_ma_widok_tras_i_fabryke_podkladu():
    mapa = _plik('static', 'js', 'logistics-map.js')
    for fraza in ('ustawWidok', 'renderTrasy', 'onWyborTrasy', 'nowaWarstwaPodkladu'):
        assert fraza in mapa, fraza


def test_js_uzywa_api_tras_i_floty():
    js = _js()
    for fraza in ('/routes/map', '/availability', '/stops/order', '/approve', '/revert',
                  '/complete', '/restore', '/routimo', '/vehicles', '/drivers',
                  'bez_trasy', 'hurt-trasa', 'usunieto_z_trasy', 'dragstart', '(zajęty',
                  'window.LogisticsRoutes', 'window.LogisticsFleet', 'komunikat:', 'pokazWidok'):
        assert fraza in js, fraza
    assert 'BaseLinker' not in js and 'unpkg.com' not in js
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_trasy_ui.py`
Expected: FAIL.

- [ ] **Step 3: Implementacja ze skillem `frontend-design`**

Wywołaj `frontend-design:frontend-design`, przekaż wymagania 1–8, kontrakt API (Interfaces Task 6–7), sekcję
„Frontend” z Kontekstu i obecne pliki zakładki. Zasady techniczne:
- w `logistics-map.js` nowa warstwa tras to osobna `L.LayerGroup`; `ustawWidok` zdejmuje/zakłada warstwę pinezek
  i warstwę tras, nie przebudowuje mapy; `nowaWarstwaPodkladu()` korzysta z istniejącego
  `nowaWarstwaKafelkow(aktywnyPodklad)` (bez kopiowania `PODKLADY`); `zniszcz()` sprząta też warstwę tras;
- każdy tekst z API escapowany (`esc()` albo `textContent`); `fetch` z `credentials: 'same-origin'`;
- po każdej mutacji trasy edytor odświeża się z odpowiedzi (`route`), mapa Dashboardu w widoku Trasy pobiera
  `GET /routes/map` ponownie, a lista Dashboardu odświeża się przy powrocie na podzakładkę;
- pobranie Routimo przez `<a href download>` albo `window.location = url`.

- [ ] **Step 4: Uruchom testy**

Run: `PYTEST tests/test_logistyka_trasy_ui.py tests/test_logistyka_mapa_ui.py tests/test_logistyka_kafelki.py tests/test_logistyka_poprawki_panelu.py tests/test_logistyka_zakladka.py`
Expected: PASS. Testy etapu 2 mają zostać zielone **bez zmian w ich asercjach**; jeśli któryś sprawdza, że pasek
podzakładek ma jeden przycisk, zmień go na sprawdzenie obecności przycisku „Dashboard” i odnotuj w raporcie.

- [ ] **Step 5: Oględziny**

W przeglądarce (Browser pane) na lokalnej kopii danych (po Task 9 Step 2): utworzenie trasy, zajęty pojazd
wyszarzony, dodanie przystanków z listy („Dodaj do trasy…”) i z edytora, przeciąganie, zatwierdzenie, eksport
Routimo (otwórz plik), odhaczenie z jednym niedostarczonym, przywrócenie, flota, przełącznik „Zamówienia | Trasy”
na mapie, powrót Trasy → Dashboard (mapa bez białych pól); 1440/1280/1024/768 px. Kafelki CARTO lokalnie dają 403
(klucz ograniczony do domeny) — oglądaj na podkładzie OSM. Zrzuty do raportu.

- [ ] **Step 6: Commit**

```bash
git add modules/production/logistics tests/test_logistyka_trasy_ui.py
git commit -m "feat(production): zakladki Trasy i Flota oraz widok tras na mapie Logistyki

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Dokumentacja, konfiguracja, weryfikacja, przegląd

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: CLAUDE.md**

W „Deployment → Ważne”, w punkcie o pozostałych sekretach w `config/core.json`, dopisz:
```markdown
  `OPENROUTESERVICE_API_KEY` (przebieg tras logistyki po drogach, km i czas; bez niego trasy rysują się liniami
  prostymi z dopiskiem „przebieg przybliżony” — nic się nie psuje),
```
W sekcji „External Integrations” dopisz: `- OpenRouteService (przebieg tras transportu własnego, klucz OPENROUTESERVICE_API_KEY)`.

- [ ] **Step 2: Migracja na MySQL (osobna baza ze zrzutem)**

```bash
cd /c/Users/Grafik/Documents/woodpower-crm-logistyka-3
docker compose -p woodpower-crm exec -T db sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" > /tmp/zrzut.sql && mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "DROP DATABASE IF EXISTS logistyka_test; CREATE DATABASE logistyka_test" && mysql -uroot -p"$MYSQL_ROOT_PASSWORD" logistyka_test < /tmp/zrzut.sql'
for i in 1 2; do docker compose -p woodpower-crm exec -T db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" logistyka_test' < migrations/2026-09-27-logistyka-trasy-flota.sql; done
docker compose -p woodpower-crm exec -T db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" logistyka_test -e "SHOW CREATE TABLE prod_routes\G; SHOW CREATE TABLE prod_route_stops\G; DROP DATABASE logistyka_test"'
```
Expected: oba przebiegi bez błędu (jeśli baza nie ma migracji etapów 1–2, zaaplikuj je wcześniej do `logistyka_test`).

- [ ] **Step 3: Próba ORS na żywo (opcjonalna, tylko z kluczem od Konrada, publiczne punkty)**

```bash
docker compose -p logistyka3 run --rm --no-deps -e ORS=<klucz> app python -c "
import os, requests
r = requests.post('https://api.openrouteservice.org/v2/directions/driving-car/geojson',
    json={'coordinates': [[22.254053, 49.840438], [19.9396, 50.0627], [22.254053, 49.840438]]},
    headers={'Authorization': os.environ['ORS']}, timeout=8)
print(r.status_code, r.json()['features'][0]['properties']['summary'])"
```
Expected: 200 i `distance` ≈ 350–450 km. Klucza nie zapisuj w repo ani w logach.

- [ ] **Step 4: Pełny pakiet**

Run: `docker compose -p logistyka3 run --rm --no-deps app pytest tests/ -q` i `... bash -c "cd integrations/blog_seo && python -m pytest -q"`
Expected: zielone.

- [ ] **Step 5: Przegląd gałęzi**

`superpowers:requesting-code-review` na całej gałęzi; nacisk na Review Focus, regresje tabletów (API mobilne, etykiety) i eksport Routimo w raportach.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: klucz OpenRouteService dla tras logistyki

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Lista kontrolna wdrożenia (do raportu, NIE wykonywać bez zgody Konrada)**

1. Konrad zakłada darmowe konto na openrouteservice.org i generuje klucz (limit 2000 tras/dobę).
2. Na serwerze: `OPENROUTESERVICE_API_KEY` w `config/core.json` i **od razu** `sudo /usr/bin/supervisorctl restart crm_woodpower` (zapis i restart razem — incydent 24.09 z rozjechanym `SECRET_KEY`).
3. Gałąź `claude/logistyka-etap-3-trasy` wypchnięta na origin (bez merge'a do `main`); o wdrożeniu decyduje Konrad, zawsze po appce 1.7.0 na tabletach.
4. Logistyk dodaje pojazdy we Flocie, tworzy pierwszą trasę, sprawdza eksport Routimo w Routimo.
5. Na tablecie pakowania sprawdzenie plakietki z nazwą trasy.
