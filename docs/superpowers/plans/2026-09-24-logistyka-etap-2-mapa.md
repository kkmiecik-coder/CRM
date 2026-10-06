# Logistyka równoległa — Etap 2: geokodowanie i mapa — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Każde otwarte zamówienie logistyki dostaje współrzędne (liczone na serwerze, zapisane w bazie, z ręczną korektą), a dashboard zakładki „Logistyka” pokazuje je na mapie obok listy.

**Architecture:** Nowa tabela `prod_order_geo` (1:1 z `prod_orders`) i moduł `logistics/services/geocoding.py`: GUGiK UUG (oficjalne punkty adresowe PRG) → Nominatim → przybliżenie do miejscowości → „nie znaleziono”. Geokoder działa wyłącznie w wątku w tle z dzierżawą `logistyka_geo_dzierzawa` (jeden na serwer — Nominatim pozwala na 1 zapytanie/s), uruchamiany cronem logistyki co godzinę i przyciskiem „Zlokalizuj teraz”. Mapa to Leaflet 1.9.4 + Leaflet.markercluster 1.5.3 skopiowane do repo.

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, MySQL 8.4 / SQLite (testy), `requests`, pytest, Leaflet (vendor), vanilla JS.

**Spec:** `C:\Users\Grafik\Documents\woodpower-crm\docs\superpowers\specs\2026-09-24-logistyka-rownolegla-trasy-design.md` — sekcje 5.3, 7, 8.3, 9–13 (plik poza gitem).

**Poprzedni etap (ukończony, NIEWDROŻONY):** plan `C:\Users\Grafik\Documents\woodpower-crm\docs\superpowers\plans\2026-09-24-logistyka-etap-1-sposob-dostawy.md`, kod na gałęzi `claude/logistyka-etap-1-dostawy-22cf12` (origin). Konrad **nie merguje** etapów do `main` — etap 2 budujemy na nowej gałęzi `claude/logistyka-etap-2-mapa` odbitej od gałęzi etapu 1. Nie proponuj merge'a do `main` ani pusha na `main` bez jego wyraźnego polecenia (push na `main` = deploy na produkcję).

**Odstępstwa etapu 1 od jego planu (wprowadzone po przeglądach — trzymaj się ich w geokoderze):** dzierżawa `bl_sync.CZAS_DZIERZAWY_S = 300` (nie 90), ostrzeżenie o zawieszonej dzierżawie (`_ostrzez_o_zawieszonej_dzierzawie`), zwalnianie dzierżawy w `finally` także po błędzie, błąd sieci przerywa przebieg. **Wzorcem dla `geocoding.lokalizuj/uruchom_w_tle` jest aktualny kod `bl_sync.dopychaj/uruchom_w_tle` na gałęzi, nie kod z planu etapu 1.** `lista.serializuj(order)` ma dziś jeden argument; `routers/cron_api.py` owija pracę w `try/except` z logiem i odpowiedzią 500 — dopisując geokoder, zachowaj ten układ.

## Kontekst (dla sesji, która nie widziała rozmowy projektowej)

**Logistyka równoległa** (zatwierdzona 24.09.2026 przez Konrada, właściciela CRM): sposób dostawy jest
atrybutem zamówienia (`prod_orders.override_delivery_method`: NULL = „Nie ustawiono”, `kurier_baselinker`,
`transport_woodpower`, `odbior_osobisty`), ustawianym przez logistyka w zakładce „Logistyka” panelu
produkcji; pakowanie bez niego jest zablokowane. Etap 1 to zbudował. Ten etap dokłada **mapę** z
geolokalizacją każdego otwartego zamówienia; etap 3 dołoży trasy transportu własnego i flotę
(plan `docs/superpowers/plans/2026-09-24-logistyka-etap-3-trasy-flota.md`).

**Co etap 1 zostawił w kodzie (sprawdź, zanim zaczniesz — `git log --oneline -- modules/production/logistics`):**
- podpakiet `modules/production/logistics/` z blueprintem `logistics_panel_bp` (nazwa `'logistics_panel'`)
  pod `/production/api/logistics`, `guard` w `routers/panel_api.py` (dostęp jak Trakownia),
- `sposoby.py` (stałe `KURIER`, `TRANSPORT`, `ODBIOR`, `normalizuj`, `etykieta`, …),
- `services/delivery.py` (`LogistykaBlad(komunikat, status)`, `aktywne_produkty`, cykl życia),
- `services/dzierzawa.py` (`wiersz(klucz)`, `przejmij(klucz, czas_s, teraz=None)`, `odnow(...)`, `zwolnij(...)`,
  `ZERO`) — **użyj go dla geokodera**,
- `services/bl_sync.py` (wzór wątku w tle: `uruchom_w_tle(app)`),
- `services/lista.py` (`serializuj(order)`, `pobierz(...)`, `liczniki()`),
- `routers/cron_api.py` (`POST /cron` → przelicza cykl i uruchamia dopychacz Base.),
- `templates/logistics/tab_content.html`, `static/js/logistics.js`, `static/css/logistics.css` (lista),
- `tests/logistyka_fixtures.py` (`app`, `client`, `BASE`, `SEKRET_CRONA`, `zamowienie(...)`, `produkt(...)`).
Jeśli którakolwiek nazwa się różni — dopasuj się do kodu, nie do tego opisu, i odnotuj różnicę w raporcie.

**Decyzje (nie dyskutuj ich ponownie):**
1. Geokodowanie **na serwerze**, wyniki w bazie (dziś strona logistyki liczy w przeglądarce, samo miasto+kod,
   cache w localStorage — to znika).
2. Kolejność: **GUGiK UUG** → **Nominatim** → przybliżenie (miejscowość/kod) → „nie znaleziono” (lista do ręcznego
   ustawienia). Ręczna korekta (przeciągnięcie pinezki, „ustaw tutaj”) nigdy nie jest nadpisywana automatem;
   zmiana adresu w Base. po korekcie daje tylko ikonę „adres zmieniony”.
3. Wyzwalanie: **cron co godzinę** (istniejący cron logistyki) albo przycisk **„Zlokalizuj teraz”**.
4. Do usług zewnętrznych wysyłamy **wyłącznie adres** — bez nazwiska, firmy, telefonu, e-maila.
5. Magazyn: **Bachórz 14N** (49.840438, 22.254053) — znacznik na mapie, w etapie 3 start i koniec tras.
6. Widoki mapy: w etapie 2 tylko „Zamówienia”; przełącznik „Zamówienia | Trasy” dochodzi w etapie 3.
7. Kolory pinezek: szary = nie ustawiono, niebieski = kurier, zielony = transport własny, fioletowy = odbiór
   osobisty; przybliżone rysowane inaczej (np. przerywana obwódka); klastry przy wielu blisko siebie.
8. Interfejs ze skillem `frontend-design:frontend-design`; teksty „Base.”, nie „BaseLinker”.

**Zmierzone 24.09.2026 (zapytania z kontenera `app`, publiczne adresy) — podstawa parsera:**
| Zapytanie do GUGiK | Wynik |
|---|---|
| `Kraków, Floriańska 10` | 2 trafienia: Floriańska 10 (31-021, accuracy 1), Ariańska 10 (31-505, 0.67) |
| `Kraków, Floriańska 10/5` i `Kraków, ul. Floriańska 10/5` | **0** — numer mieszkania psuje zapytanie |
| `Kraków, Floriańska 10 m. 5` | trafia w **numer 5** (zły budynek) — numer mieszkania trzeba usunąć |
| `36-068 Bachórz 14N` | **0** — rejestr ma dla 14N kod 36-065; kodu NIE dajemy do zapytania |
| `Bachórz, Bachórz 14N` | **0**; `Bachórz 14N` → dokładny punkt (x 22.25405, y 49.84043) |
| `Rzeszów, al. Tadeusza Rejtana 16C` | 1 trafienie, accuracy 0.90, number `16c` (małe litery!) |
| `Rzeszów, Rejtana 16C` | to samo, accuracy 0.68 |
| `Dynów` | `type: "city"`, punkt miejscowości |
| `Kraków, Floriańska` | `type: "street"` |

Odpowiedź GUGiK: `{"type": "address"|"city"|"street", "returned objects": N, "results": {"1": {"city",
"street", "number", "code", "accuracy": "1", "x": "<lng>", "y": "<lat>", ...}, ...}}` (przy `srid=4326`
x = długość, y = szerokość; `results` = `null`, gdy brak). Nominatim (`/search?format=jsonv2&street=…&city=…
&postalcode=…&countrycodes=pl&limit=1`, nagłówek `User-Agent`) zwraca listę z `lat`, `lon` (tekst) i
`place_rank` (30 = budynek, 26–27 = ulica, mniej = miejscowość/obszar). `requests` w kontenerze ma poprawne
certyfikaty (MSYS-owy Python na Windows NIE — testy ręczne rób z kontenera).

**Pamięć projektu:** `C:\Users\Grafik\.claude\projects\C--Users-Grafik-Documents-woodpower-crm\memory\`
(`project_logistyka_rownolegla.md`, `feedback_vendor_cdn.md`, `reference_worktree_docker_testy.md`,
`feedback_commit_style.md`, `feedback_nazwa_base.md`, `project_apk_timeouty_nginx.md`).

## Global Constraints

- Komentarze w kodzie **po polsku**; w UI „Base.” zamiast „BaseLinker”.
- Commity: Conventional Commits po polsku, scope `production` (albo `reports` dla zmian w module raportów), stopka `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Nie commitujemy `docs/superpowers/**`, `config/core.json`, `CLAUDE.local.md`, `MIGRATION_PLAN.md` (repo publiczne).
- **Żadnej długiej pracy w żądaniu HTTP** — gunicorn `-w 4`, sync worker, timeout **30 s**. Geokodowanie wyłącznie w wątku w tle z dzierżawą `logistyka_geo_dzierzawa`.
- Nominatim: najwyżej **1 zapytanie / 1,1 s** na serwer, `User-Agent: WoodPowerCRM/1.0 (+https://crm.woodpower.pl)`, `Accept-Language: pl`. GUGiK: odstęp 0,2 s.
- Do usług zewnętrznych wyłącznie adres (ulica, numer, miejscowość, kod, kraj).
- Migracja: `migrations/2026-09-26-logistyka-geolokalizacja.sql` (jeśli implementujesz później, możesz dać datę dnia implementacji — nazwa musi sortować się po `2026-09-25-logistyka-sposob-dostawy.sql`), idempotentna, bez `DELIMITER`.
- Leaflet i wtyczka klastrów **w repo** (`modules/production/static/vendor/`), nie z CDN (Safari ITP — memory `feedback_vendor_cdn`). Kafelki: CARTO `light_all` (jak stara strona logistyki).
- Każde zadanie UI (Task 7) ze skillem `frontend-design:frontend-design`.

## Środowisko pracy

Jak w etapie 1 — **nie przełączaj gałęzi w głównym checkoucie** (pracują tam inne sesje):
```bash
cd /c/Users/Grafik/Documents/woodpower-crm
git fetch origin
git worktree add ../woodpower-crm-logistyka-2 -b claude/logistyka-etap-2-mapa origin/claude/logistyka-etap-1-dostawy-22cf12
cd ../woodpower-crm-logistyka-2
docker compose -p logistyka2 run --rm --no-deps app pytest tests/<plik>.py -v   # dalej: PYTEST <ścieżki>
```

## Review Focus

1. **Adres z numerem mieszkania albo kodem pocztowym w polu adresu** („Floriańska 10/5”, „10 m. 5”, „36-068 Bachórz 14N”) — pinezka ma trafić w budynek, nie w pusty wynik ani w sąsiedni numer. Testy: `test_zapytanie_bez_mieszkania_i_kodu`, `test_mieszkanie_m_nie_trafia_w_zly_numer` (Task 3).
2. **Awaria GUGiK/Nominatim (timeout, 5xx)** — zamówienie nie może dostać „nie znaleziono” ani spalić prób; wraca w kolejnym przebiegu. Test: `test_awaria_uslug_nie_zuzywa_prob` (Task 4).
3. **Logistyk przeciągnął pinezkę, potem Base. zmienił adres** — punkt ręczny zostaje, pojawia się ikona „adres zmieniony”, automat go nie rusza. Test: `test_reczny_punkt_przezywa_zmiane_adresu` (Task 4).
4. **Dwa workery i klik „Zlokalizuj teraz” w trakcie crona** — jeden geokoder na serwer, Nominatim ≤ 1/s. Test: `test_drugi_geokoder_nie_startuje` (Task 4).
5. **Odbiór osobisty bez adresu / puste pola** — bez zapytań do usług, bez nieskończonych prób, zamówienie w „bez lokalizacji”. Test: `test_zamowienie_bez_adresu_bez_zapytan` (Task 4).

---

## Mapa plików

**Nowe:** `migrations/2026-09-26-logistyka-geolokalizacja.sql`, `modules/production/logistics/adresy.py`, `modules/production/logistics/services/geocoding.py`, `modules/production/static/vendor/leaflet/**`, `modules/production/static/vendor/leaflet-markercluster/**`, testy `tests/test_logistyka_adresy.py`, `tests/test_logistyka_geocoding.py`, `tests/test_logistyka_geo_runner.py`, `tests/test_logistyka_geo_api.py`, `tests/test_logistyka_mapa_ui.py`.

**Modyfikowane:** `modules/production/logistics/models.py` (+`OrderGeo`), `modules/reports/routers.py` (import funkcji adresowych z nowego miejsca), `modules/production/logistics/services/lista.py`, `modules/production/logistics/routers/panel_api.py`, `modules/production/logistics/routers/cron_api.py`, `modules/production/logistics/templates/logistics/tab_content.html`, `modules/production/logistics/static/js/logistics.js` (+ ewentualnie nowy `logistics-map.js`), `modules/production/logistics/static/css/logistics.css`, `tests/logistyka_fixtures.py`, `CLAUDE.md`.

---

### Task 1: Tabela `prod_order_geo`

**Files:**
- Modify: `modules/production/logistics/models.py`
- Create: `migrations/2026-09-26-logistyka-geolokalizacja.sql`
- Modify: `tests/logistyka_fixtures.py` (tabela w `TABLES`)
- Test: `tests/test_logistyka_geo_schemat.py`

**Interfaces:**
- Produces: model `OrderGeo` (`order_id` PK/FK, `lat`, `lng` `Numeric(9,6)`, `source` ∈ {`gugik`, `nominatim`, `reczna`, NULL}, `quality` ∈ {`dokladna`, `przyblizona`, `nie_znaleziono`}, `address_hash` `String(40)`, `address_changed_after_manual` bool, `attempts` int, `updated_at`). **Bez relacji/backrefów** na `ProductionOrder` — wszędzie jawne zapytania `OrderGeo.query.filter(OrderGeo.order_id.in_(...))` (backref konfigurowany leniwie psuł importy w testach).

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_geo_schemat.py`:
```python
# -*- coding: utf-8 -*-
import os

from extensions import db
from modules.production.logistics.models import OrderGeo
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

MIGRACJA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', '2026-09-26-logistyka-geolokalizacja.sql')


def test_geo_zamowienia_zapisuje_sie(app):
    with app.app_context():
        order = zamowienie()
        db.session.add(OrderGeo(order_id=order.id, lat=50.062726, lng=19.93962,
                                source='gugik', quality='dokladna', address_hash='a' * 40))
        db.session.commit()
        geo = OrderGeo.query.get(order.id)
        assert float(geo.lat) == 50.062726 and geo.attempts == 0
        assert geo.address_changed_after_manual is False


def test_migracja_geo():
    sql = open(MIGRACJA, encoding='utf-8').read()
    assert 'CREATE TABLE IF NOT EXISTS prod_order_geo' in sql
    assert 'logistyka_geo_dzierzawa' in sql
    assert 'DELIMITER' not in sql
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_geo_schemat.py`
Expected: FAIL — `ImportError: cannot import name 'OrderGeo'`.

- [ ] **Step 3: Model i migracja**

Do `modules/production/logistics/models.py` dopisz (importy uzupełnij o `Boolean`, `Numeric`):
```python
class OrderGeo(db.Model):
    """Współrzędne adresu dostawy zamówienia (etap 2). Jeden wiersz na zamówienie."""
    __tablename__ = 'prod_order_geo'

    order_id = Column(Integer, ForeignKey('prod_orders.id', ondelete='CASCADE'), primary_key=True)
    lat = Column(Numeric(9, 6))
    lng = Column(Numeric(9, 6))
    source = Column(Enum('gugik', 'nominatim', 'reczna', name='order_geo_source'))
    quality = Column(Enum('dokladna', 'przyblizona', 'nie_znaleziono', name='order_geo_quality'),
                     nullable=False)
    # SHA-1 znormalizowanego adresu, z którego liczono — zmiana adresu w Base. = inny skrót.
    address_hash = Column(String(40), nullable=False)
    # Punkt ręczny, a adres w Base. zmienił się później — ikona „adres zmieniony”.
    address_changed_after_manual = Column(Boolean, nullable=False, default=False)
    # Nieudane próby automatu dla TEGO adresu; po MAKS_PROB automat odpuszcza.
    attempts = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)
```
W `tests/logistyka_fixtures.py` dodaj `OrderGeo` do importu z `modules.production.logistics.models` i do krotki w `TABLES`.

`migrations/2026-09-26-logistyka-geolokalizacja.sql`:
```sql
-- Logistyka równoległa, etap 2: współrzędne adresów dostawy.
-- Idempotentna (runner wykonuje katalog przy każdym deployu).

CREATE TABLE IF NOT EXISTS prod_order_geo (
    order_id INT NOT NULL PRIMARY KEY,
    lat DECIMAL(9,6) NULL,
    lng DECIMAL(9,6) NULL,
    source ENUM('gugik','nominatim','reczna') NULL,
    quality ENUM('dokladna','przyblizona','nie_znaleziono') NOT NULL,
    address_hash CHAR(40) NOT NULL,
    address_changed_after_manual TINYINT(1) NOT NULL DEFAULT 0,
    attempts INT NOT NULL DEFAULT 0,
    updated_at DATETIME NULL,
    CONSTRAINT fk_prod_order_geo_order FOREIGN KEY (order_id)
        REFERENCES prod_orders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dzierżawa „jeden geokoder na serwer” (Nominatim: 1 zapytanie/s).
INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type, created_at, updated_at)
VALUES ('logistyka_geo_dzierzawa', '1970-01-01T00:00:00',
        'Logistyka: dzierzawa geokodera (waznosc ISO)', 'string', NOW(), NOW());
```

- [ ] **Step 4: Uruchom testy**

Run: `PYTEST tests/test_logistyka_geo_schemat.py tests/test_migration_service.py tests/test_logistyka_schemat.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/production/logistics/models.py migrations/2026-09-26-logistyka-geolokalizacja.sql tests/logistyka_fixtures.py tests/test_logistyka_geo_schemat.py
git commit -m "feat(production): tabela wspolrzednych adresow dostawy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `adresy.py` — rozbicie adresu (przeniesione z raportów)

**Files:**
- Create: `modules/production/logistics/adresy.py`
- Modify: `modules/reports/routers.py` (funkcje `extract_house_and_apartment_number` i `clean_street_name`, ok. `:3372-3537`)
- Test: `tests/test_logistyka_adresy.py`

**Interfaces:**
- Produces: `modules.production.logistics.adresy.extract_house_and_apartment_number(address) -> (house, apartment, clean_street)` i `clean_street_name(street) -> str` — **logika 1:1** z `modules/reports/routers.py` (eksport Routimo), plus nowa `usun_kod_pocztowy(tekst) -> str`. `modules/reports/routers.py` importuje obie funkcje z nowego miejsca pod tymi samymi nazwami (stary eksport Routimo działa bez zmian).

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_adresy.py`:
```python
# -*- coding: utf-8 -*-
import pytest

from modules.production.logistics import adresy


@pytest.mark.parametrize('adres, oczekiwane', [
    ('ul. Floriańska 10/5', ('10', '5', 'Floriańska')),
    ('Floriańska 10 m. 5', ('10', '5', 'Floriańska')),
    ('al. Tadeusza Rejtana 16C', ('16C', '', 'al. Tadeusza Rejtana')),
    ('Bachórz 14N', ('14N', '', 'Bachórz')),
    ('12/3 Długa', ('12', '3', 'Długa')),
    ('Rynek', ('', '', 'Rynek')),
    ('', ('', '', '')),
])
def test_rozbicie_adresu(adres, oczekiwane):
    assert adresy.extract_house_and_apartment_number(adres) == oczekiwane


def test_raporty_uzywaja_tej_samej_funkcji():
    from modules.reports import routers
    assert routers.extract_house_and_apartment_number is adresy.extract_house_and_apartment_number
    assert routers.clean_street_name is adresy.clean_street_name


@pytest.mark.parametrize('tekst, oczekiwane', [
    ('36-068 Bachórz 14N', 'Bachórz 14N'),
    ('Floriańska 10, 31-021', 'Floriańska 10'),
    ('Floriańska 10', 'Floriańska 10'),
])
def test_usun_kod_pocztowy(tekst, oczekiwane):
    assert adresy.usun_kod_pocztowy(tekst) == oczekiwane
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_adresy.py`
Expected: FAIL — brak modułu.

- [ ] **Step 3: Przeniesienie**

1. Utwórz `modules/production/logistics/adresy.py` z nagłówkiem:
```python
# -*- coding: utf-8 -*-
"""
Rozbijanie adresu dostawy na ulicę, numer domu i numer mieszkania.

Funkcje przeniesione 1:1 z modules/reports/routers.py (eksport Routimo), żeby
geokoder logistyki i eksport Routimo dzieliły jedną logikę. Raporty importują
je stąd pod starymi nazwami.
"""
import re

_KOD_POCZTOWY = re.compile(r'\b\d{2}-\d{3}\b')


def usun_kod_pocztowy(tekst):
    """„36-068 Bachórz 14N” → „Bachórz 14N”. GUGiK z kodem w zapytaniu potrafi nic nie znaleźć."""
    bez = _KOD_POCZTOWY.sub('', tekst or '')
    return re.sub(r'\s+', ' ', bez).strip(' ,')
```
2. **Przenieś** (wytnij z `modules/reports/routers.py`, wklej do `adresy.py` bez zmian w logice) całe funkcje `extract_house_and_apartment_number` i `clean_street_name` (w `routers.py` zaczynają się ok. `:3372` i `:3494`; zlokalizuj je `grep -n "def extract_house_and_apartment_number\|def clean_street_name" modules/reports/routers.py`). Zachowaj ich docstringi.
3. W `modules/reports/routers.py`, w bloku importów na górze pliku, dopisz:
```python
# Rozbijanie adresu żyje w logistyce (wspólne z geokoderem) — tu pod starymi nazwami.
from modules.production.logistics.adresy import (  # noqa: F401
    clean_street_name, extract_house_and_apartment_number,
)
```
Jeśli wynik któregoś przypadku z testu różni się od oczekiwanego, **nie zmieniaj logiki** — popraw oczekiwanie w teście do faktycznego zachowania starej funkcji (to jest przeniesienie, nie poprawka) i odnotuj różnicę w raporcie.

- [ ] **Step 4: Uruchom testy**

Run: `PYTEST tests/test_logistyka_adresy.py` oraz `PYTEST tests/ -k "routimo or reports"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/production/logistics/adresy.py modules/reports/routers.py tests/test_logistyka_adresy.py
git commit -m "refactor(reports): rozbijanie adresu przeniesione do logistyki, wspolne z geokoderem

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Geokoder adresu (GUGiK → Nominatim → przybliżenie)

**Files:**
- Create: `modules/production/logistics/services/geocoding.py` (część „adres → punkt”)
- Test: `tests/test_logistyka_geocoding.py`

**Interfaces:**
- Consumes: `adresy.extract_house_and_apartment_number`, `adresy.usun_kod_pocztowy` (Task 2).
- Produces (moduł `modules.production.logistics.services.geocoding`): stałe `MAGAZYN = {'lat': 49.840438, 'lng': 22.254053, 'nazwa': 'WoodPower — Bachórz 14N'}`, `GUGIK_URL`, `NOMINATIM_URL`, `USER_AGENT`, `ODSTEP_NOMINATIM_S = 1.1`, `ODSTEP_GUGIK_S = 0.2`, `MIN_DOKLADNOSC_GUGIK = 0.6`; `Wynik = namedtuple('Wynik', 'lat lng source quality')`; `class BladUslugi(Exception)`; `zapytania_gugik(adres, miasto) -> (list[str], numer: str)`; `wybierz_trafienie(odpowiedz: dict, numer: str, kod: str|None) -> dict|None`; `geokoduj_adres(adres, miasto, kod, kraj, http_get=requests.get, spij=time.sleep) -> Wynik` (rzuca `BladUslugi`, gdy nic nie znaleziono, a któraś usługa padła).

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_geocoding.py`:
```python
# -*- coding: utf-8 -*-
"""Odpowiedzi usług to kopie zapytań wykonanych 24.09.2026 (patrz „Zmierzone” w planie)."""
import pytest
import requests

from modules.production.logistics.services import geocoding as g

FLORIANSKA = {'type': 'address', 'returned objects': 2, 'results': {
    '1': {'city': 'Kraków', 'street': 'Floriańska', 'number': '10', 'code': '31-021',
          'accuracy': '1', 'x': '19.9396202491515', 'y': '50.0627258466159'},
    '2': {'city': 'Kraków', 'street': 'Ariańska', 'number': '10', 'code': '31-505',
          'accuracy': '0.666667', 'x': '19.9542258649548', 'y': '50.0665202'}}}
BACHORZ = {'type': 'address', 'returned objects': 1, 'results': {
    '1': {'city': 'Bachórz', 'street': None, 'number': '14N', 'code': '36-065',
          'accuracy': '1', 'x': '22.2540527461363', 'y': '49.8404376841563'}}}
REJTANA = {'type': 'address', 'returned objects': 1, 'results': {
    '1': {'city': 'Rzeszów', 'street': 'Tadeusza Rejtana', 'number': '16c', 'code': '35-310',
          'accuracy': '0.678571', 'x': '22.01588', 'y': '50.03016'}}}
PUSTO = {'type': 'address', 'returned objects': 0, 'results': None}
MIASTO = {'type': 'city', 'returned objects': 1, 'results': {
    '1': {'city': 'Dynów', 'accuracy': '1', 'x': '22.23386', 'y': '49.81479'}}}


class Odp(object):
    def __init__(self, dane, status=200):
        self.dane, self.status_code = dane, status

    def json(self):
        return self.dane

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakeHttp(object):
    """Odpowiada według (usługa, klucz) — klucz: adres dla GUGiK, krotka parametrów dla Nominatim."""

    def __init__(self, gugik=None, nominatim=None, awaria=()):
        self.gugik, self.nominatim, self.awaria = gugik or {}, nominatim or [], set(awaria)
        self.wywolania = []

    def __call__(self, url, params=None, timeout=None, headers=None):
        self.wywolania.append((url, dict(params or {}), dict(headers or {})))
        usluga = 'gugik' if url == g.GUGIK_URL else 'nominatim'
        if usluga in self.awaria:
            raise requests.ConnectionError('awaria testowa')
        if usluga == 'gugik':
            return Odp(self.gugik.get(params['address'], PUSTO))
        return Odp(self.nominatim.pop(0) if self.nominatim else [])


def _bez_spania(_):
    pass


def test_zapytanie_bez_mieszkania_i_kodu():
    assert g.zapytania_gugik('ul. Floriańska 10/5', 'Kraków') == (['Kraków, Floriańska 10'], '10')
    assert g.zapytania_gugik('36-068 Bachórz 14N', 'Bachórz') == (['Bachórz 14N'], '14N')
    assert g.zapytania_gugik('Rynek', 'Kraków') == ([], '')


def test_wybor_trafienia_po_kodzie_i_numerze():
    assert g.wybierz_trafienie(FLORIANSKA, '10', '31-021')['street'] == 'Floriańska'
    assert g.wybierz_trafienie(FLORIANSKA, '10', None)['street'] == 'Floriańska'  # max accuracy
    assert g.wybierz_trafienie(BACHORZ, '14N', '36-068')['number'] == '14N'  # kod inny, numer pewny
    assert g.wybierz_trafienie(REJTANA, '16C', '35-310')['number'] == '16c'  # wielkość liter
    assert g.wybierz_trafienie(FLORIANSKA, '12', None) is None  # zły numer
    assert g.wybierz_trafienie(MIASTO, '10', None) is None  # nie adres


def test_mieszkanie_m_nie_trafia_w_zly_numer():
    http = FakeHttp(gugik={'Kraków, Floriańska 10': FLORIANSKA})
    wynik = g.geokoduj_adres('Floriańska 10 m. 5', 'Kraków', '31-021', 'PL', http, _bez_spania)
    assert wynik == g.Wynik(50.0627258466159, 19.9396202491515, 'gugik', 'dokladna')


def test_wies_bez_ulic():
    http = FakeHttp(gugik={'Bachórz 14N': BACHORZ})
    wynik = g.geokoduj_adres('Bachórz 14N', 'Bachórz', '36-068', 'PL', http, _bez_spania)
    assert (wynik.source, wynik.quality) == ('gugik', 'dokladna')


def test_nominatim_gdy_gugik_nic_nie_zna_i_tylko_adres_do_uslug():
    http = FakeHttp(nominatim=[[{'lat': '50.1', 'lon': '19.9', 'place_rank': 30}]])
    wynik = g.geokoduj_adres('Nowa 5', 'Kraków', '30-001', 'PL', http, _bez_spania)
    assert wynik == g.Wynik(50.1, 19.9, 'nominatim', 'dokladna')
    url, params, naglowki = http.wywolania[-1]
    assert url == g.NOMINATIM_URL
    assert params['street'] == 'Nowa 5' and params['city'] == 'Kraków'
    assert naglowki['User-Agent'] == g.USER_AGENT


def test_nominatim_na_poziomie_ulicy_to_przyblizenie():
    http = FakeHttp(nominatim=[[{'lat': '50.1', 'lon': '19.9', 'place_rank': 26}]])
    assert g.geokoduj_adres('Nowa 5', 'Kraków', None, 'PL', http, _bez_spania).quality == 'przyblizona'


def test_przyblizenie_do_miejscowosci():
    http = FakeHttp(gugik={'Dynów': MIASTO}, nominatim=[[]])
    wynik = g.geokoduj_adres('Nieistniejąca 1', 'Dynów', None, 'PL', http, _bez_spania)
    assert wynik == g.Wynik(49.81479, 22.23386, 'gugik', 'przyblizona')


def test_zagranica_bez_gugik():
    http = FakeHttp(nominatim=[[{'lat': '52.5', 'lon': '13.4', 'place_rank': 30}]])
    wynik = g.geokoduj_adres('Unter den Linden 1', 'Berlin', '10117', 'DE', http, _bez_spania)
    assert wynik.source == 'nominatim'
    assert all(u == g.NOMINATIM_URL for u, _, _ in http.wywolania)
    assert http.wywolania[0][1]['countrycodes'] == 'de'


def test_nic_nie_znaleziono():
    http = FakeHttp(nominatim=[[], []])
    assert g.geokoduj_adres('Nowa 5', 'Xyz', None, 'PL', http, _bez_spania).quality == 'nie_znaleziono'


def test_awaria_uslug_to_blad_a_nie_nie_znaleziono():
    http = FakeHttp(awaria={'gugik', 'nominatim'})
    with pytest.raises(g.BladUslugi):
        g.geokoduj_adres('Floriańska 10', 'Kraków', None, 'PL', http, _bez_spania)


def test_odstep_przed_nominatim():
    przerwy = []
    http = FakeHttp(nominatim=[[{'lat': '50.1', 'lon': '19.9', 'place_rank': 30}]])
    g.geokoduj_adres('Nowa 5', 'Kraków', None, 'PL', http, przerwy.append)
    assert g.ODSTEP_NOMINATIM_S in przerwy
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_geocoding.py`
Expected: FAIL — brak modułu.

- [ ] **Step 3: Implementacja (część „adres → punkt”)**

`modules/production/logistics/services/geocoding.py`:
```python
# -*- coding: utf-8 -*-
"""
Geokodowanie adresów dostawy (spec, sekcja 7.1).

Kolejność: GUGiK UUG (oficjalne punkty adresowe PRG, tylko PL) → Nominatim →
przybliżenie do miejscowości → „nie znaleziono”. Do usług wysyłamy WYŁĄCZNIE
adres. Pułapki zmierzone 24.09.2026: kod pocztowy albo numer mieszkania
w zapytaniu GUGiK daje 0 trafień albo zły budynek; „Bachórz, Bachórz 14N”
nic nie znajduje, a „Bachórz 14N” trafia.

Ten moduł woła usługi wyłącznie z wątku w tle (timeout gunicorna 30 s).
"""
import time
from collections import namedtuple

import requests

from modules.logging import get_structured_logger
from modules.production.logistics.adresy import (
    extract_house_and_apartment_number, usun_kod_pocztowy,
)

logger = get_structured_logger('production.logistics.geocoding')

MAGAZYN = {'lat': 49.840438, 'lng': 22.254053, 'nazwa': u'WoodPower — Bachórz 14N'}
GUGIK_URL = 'https://services.gugik.gov.pl/uug/'
NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
USER_AGENT = 'WoodPowerCRM/1.0 (+https://crm.woodpower.pl)'
TIMEOUT_S = 10
ODSTEP_NOMINATIM_S = 1.1
ODSTEP_GUGIK_S = 0.2
MIN_DOKLADNOSC_GUGIK = 0.6
# place_rank Nominatim: 30 = budynek, 28–29 = adres/obiekt, 26–27 = ulica, niżej obszar.
MIN_RANGA_DOKLADNA = 28

Wynik = namedtuple('Wynik', 'lat lng source quality')
NIE_ZNALEZIONO = Wynik(None, None, None, 'nie_znaleziono')


class BladUslugi(Exception):
    """Usługa nie odpowiedziała — to nie jest „nie znaleziono”, nie zużywa próby."""


def _naglowki():
    return {'User-Agent': USER_AGENT, 'Accept-Language': 'pl'}


def zapytania_gugik(adres, miasto):
    """Kandydaci zapytań do GUGiK (bez kodu i bez numeru mieszkania) oraz numer domu."""
    numer, _mieszkanie, ulica = extract_house_and_apartment_number(usun_kod_pocztowy(adres))
    if not numer:
        return [], ''
    miasto = (miasto or '').strip()
    ulica = (ulica or '').strip()
    if not ulica or ulica.lower() == miasto.lower():
        # Miejscowość bez ulic: „Bachórz 14N”. Powtórzenie nazwy psuje wynik.
        return [u'{} {}'.format(miasto or ulica, numer)], numer
    if miasto:
        return [u'{}, {} {}'.format(miasto, ulica, numer)], numer
    return [u'{} {}'.format(ulica, numer)], numer


def _dokladnosc(trafienie):
    try:
        return float(trafienie.get('accuracy') or 0)
    except (TypeError, ValueError):
        return 0.0


def wybierz_trafienie(odpowiedz, numer, kod):
    """Trafienie z tym samym numerem: najpierw zgodny kod pocztowy, potem najwyższa dokładność."""
    if not odpowiedz or odpowiedz.get('type') != 'address':
        return None
    trafienia = list((odpowiedz.get('results') or {}).values())
    pasujace = [t for t in trafienia if (t.get('number') or '').lower() == (numer or '').lower()]
    if kod:
        z_kodem = [t for t in pasujace if t.get('code') == kod]
        if z_kodem:
            return z_kodem[0]
    pewne = [t for t in pasujace if _dokladnosc(t) >= MIN_DOKLADNOSC_GUGIK]
    return max(pewne, key=_dokladnosc) if pewne else None


def _gugik(zapytanie, http_get):
    odp = http_get(GUGIK_URL, params={'request': 'GetAddress', 'address': zapytanie, 'srid': '4326'},
                   timeout=TIMEOUT_S, headers=_naglowki())
    odp.raise_for_status()
    return odp.json() or {}


def _nominatim(parametry, http_get):
    """(lat, lng, dokładny) albo None."""
    params = {k: v for k, v in parametry.items() if v}
    params.update({'format': 'jsonv2', 'limit': 1})
    odp = http_get(NOMINATIM_URL, params=params, timeout=TIMEOUT_S, headers=_naglowki())
    odp.raise_for_status()
    dane = odp.json() or []
    if not dane:
        return None
    return (float(dane[0]['lat']), float(dane[0]['lon']),
            int(dane[0].get('place_rank') or 0) >= MIN_RANGA_DOKLADNA)


def geokoduj_adres(adres, miasto, kod, kraj, http_get=requests.get, spij=time.sleep):
    kraj = (kraj or 'PL').upper()
    miasto = (miasto or '').strip()
    kod = (kod or '').strip() or None
    awaria = False

    # 1. GUGiK — dokładny punkt adresowy (tylko Polska).
    if kraj == 'PL':
        kandydaci, numer = zapytania_gugik(adres, miasto)
        for zapytanie in kandydaci:
            spij(ODSTEP_GUGIK_S)
            try:
                trafienie = wybierz_trafienie(_gugik(zapytanie, http_get), numer, kod)
            except Exception as e:
                awaria = True
                logger.warning("GUGiK nie odpowiedzial", extra={'error': str(e)})
                continue
            if trafienie:
                return Wynik(float(trafienie['y']), float(trafienie['x']), 'gugik', 'dokladna')

    # 2. Nominatim — adres strukturalny.
    numer, _mieszkanie, ulica = extract_house_and_apartment_number(usun_kod_pocztowy(adres))
    ulica_z_numerem = (u'{} {}'.format(ulica, numer) if numer else (ulica or '')).strip()
    if ulica_z_numerem:
        spij(ODSTEP_NOMINATIM_S)
        try:
            punkt = _nominatim({'street': ulica_z_numerem, 'city': miasto, 'postalcode': kod,
                                'countrycodes': kraj.lower()}, http_get)
        except Exception as e:
            awaria, punkt = True, None
            logger.warning("Nominatim nie odpowiedzial", extra={'error': str(e)})
        if punkt:
            return Wynik(punkt[0], punkt[1], 'nominatim',
                         'dokladna' if punkt[2] else 'przyblizona')

    # 3. Przybliżenie do miejscowości.
    if kraj == 'PL' and miasto:
        spij(ODSTEP_GUGIK_S)
        try:
            odp = _gugik(miasto, http_get)
            if odp.get('type') == 'city' and odp.get('results'):
                pierwszy = list(odp['results'].values())[0]
                return Wynik(float(pierwszy['y']), float(pierwszy['x']), 'gugik', 'przyblizona')
        except Exception as e:
            awaria = True
            logger.warning("GUGiK (miejscowosc) nie odpowiedzial", extra={'error': str(e)})
    if miasto or kod:
        spij(ODSTEP_NOMINATIM_S)
        try:
            punkt = _nominatim({'city': miasto, 'postalcode': kod,
                                'countrycodes': kraj.lower()}, http_get)
        except Exception as e:
            awaria, punkt = True, None
            logger.warning("Nominatim (miejscowosc) nie odpowiedzial", extra={'error': str(e)})
        if punkt:
            return Wynik(punkt[0], punkt[1], 'nominatim', 'przyblizona')

    if awaria:
        raise BladUslugi(u'Usługa geokodowania nie odpowiedziała')
    return NIE_ZNALEZIONO
```

- [ ] **Step 4: Uruchom testy**

Run: `PYTEST tests/test_logistyka_geocoding.py`
Expected: PASS. Uwaga na `test_przyblizenie_do_miejscowosci`: „Nieistniejąca 1” → GUGiK dla „Dynów, Nieistniejąca 1” zwraca PUSTO, Nominatim (adres) `[]`, GUGiK „Dynów” → MIASTO.

- [ ] **Step 5: Commit**

```bash
git add modules/production/logistics/services/geocoding.py tests/test_logistyka_geocoding.py
git commit -m "feat(production): geokoder adresu dostawy GUGiK, Nominatim i przyblizenie

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Geokoder zamówień — zapis, dzierżawa, wątek w tle, ręczna korekta

**Files:**
- Modify: `modules/production/logistics/services/geocoding.py` (część „zamówienia”)
- Test: `tests/test_logistyka_geo_runner.py`

**Interfaces:**
- Consumes: `OrderGeo` (Task 1), `geokoduj_adres`, `Wynik`, `BladUslugi` (Task 3), `dzierzawa.przejmij/odnow/zwolnij/wiersz` (etap 1), `delivery.LogistykaBlad` (etap 1).
- Produces: `KLUCZ_DZIERZAWY = 'logistyka_geo_dzierzawa'`, `CZAS_DZIERZAWY_S = 300` (jak `bl_sync` po przeglądzie etapu 1), `MAKS_PROB = 3`; `skrot_adresu(order) -> str`; `geo_zamowien(order_ids) -> dict[int, OrderGeo]`; `oznacz_zmienione_reczne() -> int`; `do_zlokalizowania(limit=None) -> list[ProductionOrder]`; `zlokalizuj_zamowienie(order, http_get=requests.get, spij=time.sleep) -> OrderGeo`; `lokalizuj(limit=None, http_get=requests.get, spij=time.sleep) -> dict` (`{'zamowienia', 'dokladne', 'przyblizone', 'nie_znaleziono', 'bledy', 'dzierzawa'}`); `geokoder_dziala(teraz=None) -> bool`; `uruchom_w_tle(app) -> bool`; `ustaw_recznie(order, lat, lng) -> OrderGeo` (422 przy złych współrzędnych); `resetuj(order) -> None`; `bez_lokalizacji() -> int`.

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_geo_runner.py`:
```python
# -*- coding: utf-8 -*-
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics.models import OrderGeo
from modules.production.logistics.services import delivery, dzierzawa
from modules.production.logistics.services import geocoding as g
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401
from tests.test_logistyka_geocoding import BACHORZ, FLORIANSKA, FakeHttp


def _bez_spania(_):
    pass


def test_lokalizuje_otwarte_i_zapisuje(app):
    with app.app_context():
        order = zamowienie(miasto='Kraków')
        order.delivery_address, order.delivery_postcode = 'Floriańska 10', '31-021'
        db.session.commit()
        http = FakeHttp(gugik={'Kraków, Floriańska 10': FLORIANSKA})
        wynik = g.lokalizuj(http_get=http, spij=_bez_spania)
        assert wynik['dokladne'] == 1 and wynik['dzierzawa'] is True
        geo = OrderGeo.query.get(order.id)
        assert (geo.source, geo.quality) == ('gugik', 'dokladna')
        assert geo.address_hash == g.skrot_adresu(order)


def test_zamkniete_nie_sa_lokalizowane(app):
    with app.app_context():
        zamowienie(logistics_closed_at=datetime(2026, 9, 1))
        assert g.do_zlokalizowania() == []


def test_nie_znaleziono_zuzywa_proby_do_limitu(app):
    with app.app_context():
        order = zamowienie(miasto='Xyz')
        order.delivery_address = 'Nowa 5'
        db.session.commit()
        for _ in range(g.MAKS_PROB):
            g.zlokalizuj_zamowienie(order, FakeHttp(nominatim=[[], []]), _bez_spania)
            db.session.commit()
        assert OrderGeo.query.get(order.id).attempts == g.MAKS_PROB
        assert g.do_zlokalizowania() == []


def test_awaria_uslug_nie_zuzywa_prob(app):
    """Review Focus 2."""
    with app.app_context():
        order = zamowienie(miasto='Kraków')
        order.delivery_address = 'Floriańska 10'
        db.session.commit()
        wynik = g.lokalizuj(http_get=FakeHttp(awaria={'gugik', 'nominatim'}), spij=_bez_spania)
        assert wynik['bledy'] == 1
        assert OrderGeo.query.get(order.id) is None
        assert g.do_zlokalizowania() == [order]


def test_zmiana_adresu_lokalizuje_od_nowa(app):
    with app.app_context():
        order = zamowienie(miasto='Bachórz')
        order.delivery_address = 'Bachórz 14N'
        db.session.commit()
        g.zlokalizuj_zamowienie(order, FakeHttp(gugik={'Bachórz 14N': BACHORZ}), _bez_spania)
        db.session.commit()
        assert g.do_zlokalizowania() == []
        order.delivery_address = 'Bachórz 15'
        db.session.commit()
        assert g.do_zlokalizowania() == [order]


def test_reczny_punkt_przezywa_zmiane_adresu(app):
    """Review Focus 3."""
    with app.app_context():
        order = zamowienie()
        g.ustaw_recznie(order, 50.05, 19.95)
        db.session.commit()
        order.delivery_address = 'Inna 1'
        db.session.commit()
        assert g.do_zlokalizowania() == []
        assert g.oznacz_zmienione_reczne() == 1
        geo = OrderGeo.query.get(order.id)
        assert (float(geo.lat), geo.source) == (50.05, 'reczna')
        assert geo.address_changed_after_manual is True


@pytest.mark.parametrize('lat, lng', [(None, 19.9), (91, 19.9), (50, 181), ('x', 1)])
def test_reczny_punkt_walidacja(app, lat, lng):
    with app.app_context():
        with pytest.raises(delivery.LogistykaBlad) as e:
            g.ustaw_recznie(zamowienie(), lat, lng)
        assert e.value.status == 422


def test_reset_oddaje_zamowienie_automatowi(app):
    with app.app_context():
        order = zamowienie()
        g.ustaw_recznie(order, 50.05, 19.95)
        db.session.commit()
        g.resetuj(order)
        db.session.commit()
        assert OrderGeo.query.get(order.id) is None


def test_zamowienie_bez_adresu_bez_zapytan(app):
    """Review Focus 5."""
    with app.app_context():
        order = zamowienie(delivery_method='Odbiór osobisty')
        order.delivery_address = order.delivery_city = order.delivery_postcode = None
        db.session.commit()
        http = FakeHttp()
        geo = g.zlokalizuj_zamowienie(order, http, _bez_spania)
        db.session.commit()
        assert http.wywolania == []
        assert geo.quality == 'nie_znaleziono' and geo.attempts == g.MAKS_PROB
        assert g.bez_lokalizacji() == 1


def test_drugi_geokoder_nie_startuje(app):
    """Review Focus 4."""
    with app.app_context():
        zamowienie()
        assert dzierzawa.przejmij(g.KLUCZ_DZIERZAWY, g.CZAS_DZIERZAWY_S) is not None
        wynik = g.lokalizuj(http_get=FakeHttp(), spij=_bez_spania)
        assert wynik['dzierzawa'] is False and wynik['zamowienia'] == 0
        assert g.geokoder_dziala() is True
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_geo_runner.py`
Expected: FAIL (brak funkcji).

- [ ] **Step 3: Implementacja**

Dopisz do `modules/production/logistics/services/geocoding.py` (importy uzupełnij: `hashlib`, `threading`, `datetime`, `from extensions import db`, `from modules.production.logistics.models import OrderGeo`, `from modules.production.logistics.services import dzierzawa`, `from modules.production.logistics.services.delivery import LogistykaBlad`, `from modules.production.models import ProductionOrder, get_local_now`):
```python
KLUCZ_DZIERZAWY = 'logistyka_geo_dzierzawa'
CZAS_DZIERZAWY_S = 300  # jak bl_sync.CZAS_DZIERZAWY_S (przegląd etapu 1)
MAKS_PROB = 3


def _norm(tekst):
    return ' '.join((tekst or '').lower().split())


def skrot_adresu(order):
    tekst = '|'.join(_norm(x) for x in (order.delivery_address, order.delivery_postcode,
                                         order.delivery_city, order.delivery_country_code))
    return hashlib.sha1(tekst.encode('utf-8')).hexdigest()


def _ma_adres(order):
    return any((x or '').strip() for x in (order.delivery_address, order.delivery_city,
                                            order.delivery_postcode))


def geo_zamowien(order_ids):
    if not order_ids:
        return {}
    return {geo.order_id: geo for geo in
            OrderGeo.query.filter(OrderGeo.order_id.in_(list(order_ids))).all()}


def _otwarte():
    return (ProductionOrder.query.filter(ProductionOrder.logistics_closed_at.is_(None))
            .order_by(ProductionOrder.id).all())


def oznacz_zmienione_reczne():
    """Punkt ręczny + inny adres w Base. → tylko ikona. Zwraca liczbę nowo oznaczonych."""
    otwarte = _otwarte()
    geo = geo_zamowien([o.id for o in otwarte])
    zmienione = 0
    for order in otwarte:
        punkt = geo.get(order.id)
        if (punkt is not None and punkt.source == 'reczna'
                and not punkt.address_changed_after_manual
                and punkt.address_hash != skrot_adresu(order)):
            punkt.address_changed_after_manual = True
            zmienione += 1
    return zmienione


def do_zlokalizowania(limit=None):
    otwarte = _otwarte()
    geo = geo_zamowien([o.id for o in otwarte])
    wynik = []
    for order in otwarte:
        punkt = geo.get(order.id)
        if punkt is None:
            wynik.append(order)
        elif punkt.source == 'reczna':
            continue
        elif punkt.address_hash != skrot_adresu(order):
            wynik.append(order)
        elif punkt.quality == 'nie_znaleziono' and punkt.attempts < MAKS_PROB:
            wynik.append(order)
    return wynik[:limit] if limit else wynik


def zlokalizuj_zamowienie(order, http_get=requests.get, spij=time.sleep):
    """Zapisuje wynik do sesji (bez commita). BladUslugi przechodzi wyżej."""
    skrot = skrot_adresu(order)
    punkt = OrderGeo.query.get(order.id)
    if punkt is None:
        punkt = OrderGeo(order_id=order.id, attempts=0, address_changed_after_manual=False)
        db.session.add(punkt)
    if punkt.address_hash != skrot:
        punkt.attempts = 0
    if not _ma_adres(order):
        # Brak adresu (np. odbiór osobisty) — nie pytamy usług i nie próbujemy w kółko.
        wynik = NIE_ZNALEZIONO
        punkt.attempts = MAKS_PROB
    else:
        wynik = geokoduj_adres(order.delivery_address, order.delivery_city,
                               order.delivery_postcode, order.delivery_country_code,
                               http_get=http_get, spij=spij)
        punkt.attempts = (punkt.attempts or 0) + 1 if wynik.quality == 'nie_znaleziono' else 0
    punkt.lat, punkt.lng = wynik.lat, wynik.lng
    punkt.source, punkt.quality = wynik.source, wynik.quality
    punkt.address_hash = skrot
    punkt.address_changed_after_manual = False
    return punkt


_KLUCZE_WYNIKU = {'dokladna': 'dokladne', 'przyblizona': 'przyblizone',
                  'nie_znaleziono': 'nie_znaleziono'}


def lokalizuj(limit=None, http_get=requests.get, spij=time.sleep):
    wynik = {'zamowienia': 0, 'dokladne': 0, 'przyblizone': 0, 'nie_znaleziono': 0,
             'bledy': 0, 'dzierzawa': False}
    znacznik = dzierzawa.przejmij(KLUCZ_DZIERZAWY, CZAS_DZIERZAWY_S)
    if znacznik is None:
        return wynik
    wynik['dzierzawa'] = True
    try:
        oznacz_zmienione_reczne()
        db.session.commit()
        for order in do_zlokalizowania(limit):
            try:
                punkt = zlokalizuj_zamowienie(order, http_get=http_get, spij=spij)
            except BladUslugi:
                db.session.rollback()
                wynik['bledy'] += 1
                continue
            db.session.commit()
            wynik['zamowienia'] += 1
            wynik[_KLUCZE_WYNIKU[punkt.quality]] += 1
            znacznik = dzierzawa.odnow(KLUCZ_DZIERZAWY, znacznik, CZAS_DZIERZAWY_S)
            if znacznik is None:
                break
    finally:
        if znacznik:
            dzierzawa.zwolnij(KLUCZ_DZIERZAWY, znacznik)
    logger.info("Geokodowanie zamowien zakonczone", extra=wynik)
    return wynik


def geokoder_dziala(teraz=None):
    teraz = teraz or get_local_now()
    db.session.expire_all()
    try:
        return datetime.fromisoformat(dzierzawa.wiersz(KLUCZ_DZIERZAWY).config_value) > teraz
    except ValueError:
        return False


_watek = None
_blokada_watku = threading.Lock()


def uruchom_w_tle(app):
    """Jeden wątek na proces; między procesami porządku pilnuje dzierżawa."""
    global _watek
    with _blokada_watku:
        if _watek is not None and _watek.is_alive():
            return False

        def _praca():
            with app.app_context():
                try:
                    lokalizuj()
                except Exception as e:
                    logger.error("Geokoder logistyki przerwany", extra={'error': str(e)})
                finally:
                    db.session.remove()

        _watek = threading.Thread(target=_praca, name='logistyka-geo', daemon=True)
        _watek.start()
        return True


def ustaw_recznie(order, lat, lng):
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        raise LogistykaBlad(u'Nieprawidłowe współrzędne.', status=422)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise LogistykaBlad(u'Współrzędne poza zakresem.', status=422)
    punkt = OrderGeo.query.get(order.id)
    if punkt is None:
        punkt = OrderGeo(order_id=order.id)
        db.session.add(punkt)
    punkt.lat, punkt.lng = round(lat, 6), round(lng, 6)
    punkt.source, punkt.quality = 'reczna', 'dokladna'
    punkt.address_hash = skrot_adresu(order)
    punkt.address_changed_after_manual = False
    punkt.attempts = 0
    return punkt


def resetuj(order):
    """Usuwa punkt (też ręczny) — zamówienie wraca do automatu przy najbliższym przebiegu."""
    OrderGeo.query.filter_by(order_id=order.id).delete(synchronize_session=False)


def bez_lokalizacji():
    otwarte = _otwarte()
    geo = geo_zamowien([o.id for o in otwarte])
    return sum(1 for o in otwarte
               if geo.get(o.id) is None or geo[o.id].quality == 'nie_znaleziono')
```

- [ ] **Step 4: Uruchom testy**

Run: `PYTEST tests/test_logistyka_geo_runner.py tests/test_logistyka_geocoding.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/production/logistics/services/geocoding.py tests/test_logistyka_geo_runner.py
git commit -m "feat(production): geokoder zamowien w tle z dzierzawa i reczna korekta punktu

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: API — współrzędne w liście, „Zlokalizuj teraz”, ręczna korekta, cron

**Files:**
- Modify: `modules/production/logistics/services/lista.py` (`serializuj`, `pobierz`)
- Modify: `modules/production/logistics/routers/panel_api.py`
- Modify: `modules/production/logistics/routers/cron_api.py`
- Modify: `modules/production/logistics/templates/logistics/tab_content.html` (atrybuty magazynu)
- Test: `tests/test_logistyka_geo_api.py`

**Interfaces:**
- Consumes: `geocoding.*` (Task 4).
- Produces:
  - `lista.serializuj(order, geo=None)` dostaje klucz `'geo': None | {'lat': float, 'lng': float, 'quality', 'source', 'adres_zmieniony': bool}`; `pobierz(...)` ładuje punkty jednym zapytaniem (`geocoding.geo_zamowien`). **Każde miejsce, które woła `serializuj`, musi podać `geo`** (w panel_api: odpowiedzi hurtu i wydania — pobierz `geo_zamowien(ids)`).
  - `GET /orders` → dodatkowo `'bez_lokalizacji': int`, `'geokoder_dziala': bool`.
  - `POST /geocode` → `202 {'success': True, 'uruchomiono': bool}` (wątek w tle).
  - `PUT /orders/<id>/geo` body `{'lat': float, 'lng': float}` → `200 {'success': True, 'order': serializuj}`; 422 przy złych współrzędnych; 404.
  - `POST /orders/<id>/geo/reset` → `200 {'success': True, 'order': serializuj}`.
  - `POST /cron` → dodatkowo `'geokoder_uruchomiony': bool`.
  - `tab_content.html`: korzeń dostaje `data-magazyn-lat`, `data-magazyn-lng`, `data-magazyn-nazwa` z `geocoding.MAGAZYN`.

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_geo_api.py`:
```python
# -*- coding: utf-8 -*-
import pytest

from extensions import db
from modules.production.logistics.models import OrderGeo
from modules.production.logistics.services import bl_sync, geocoding
from tests.logistyka_fixtures import BASE, SEKRET_CRONA, app, client, zamowienie  # noqa: F401


@pytest.fixture(autouse=True)
def bez_watkow(monkeypatch):
    uruchomione = []
    monkeypatch.setattr(geocoding, 'uruchom_w_tle', lambda app_: uruchomione.append('geo') or True)
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: uruchomione.append('base') or True)
    return uruchomione


def test_lista_niesie_wspolrzedne_i_licznik(client, app):
    with app.app_context():
        a = zamowienie()
        zamowienie()
        db.session.add(OrderGeo(order_id=a.id, lat=50.06, lng=19.94, source='gugik',
                                quality='dokladna', address_hash='x' * 40))
        db.session.commit()
    dane = client.get(BASE + '/orders').get_json()
    geo = {o['id']: o['geo'] for o in dane['orders']}
    assert geo[a.id] == {'lat': 50.06, 'lng': 19.94, 'quality': 'dokladna',
                         'source': 'gugik', 'adres_zmieniony': False}
    assert dane['bez_lokalizacji'] == 1
    assert dane['geokoder_dziala'] is False


def test_zlokalizuj_teraz_uruchamia_watek(client, bez_watkow):
    r = client.post(BASE + '/geocode')
    assert r.status_code == 202 and bez_watkow == ['geo']


def test_reczna_korekta_i_reset(client, app):
    with app.app_context():
        oid = zamowienie().id
    r = client.put(BASE + '/orders/%d/geo' % oid, json={'lat': 50.1, 'lng': 20.2})
    assert r.status_code == 200 and r.get_json()['order']['geo']['source'] == 'reczna'
    assert client.put(BASE + '/orders/%d/geo' % oid, json={'lat': 'x'}).status_code == 422
    assert client.put(BASE + '/orders/999999/geo', json={'lat': 1, 'lng': 1}).status_code == 404
    r = client.post(BASE + '/orders/%d/geo/reset' % oid)
    assert r.status_code == 200 and r.get_json()['order']['geo'] is None


def test_cron_uruchamia_tez_geokoder(client, bez_watkow):
    r = client.post(BASE + '/cron', headers={'X-Cron-Secret': SEKRET_CRONA})
    assert r.get_json()['geokoder_uruchomiony'] is True
    assert sorted(bez_watkow) == ['base', 'geo']


def test_zakladka_zna_magazyn(client):
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    assert 'data-magazyn-lat="49.840438"' in html
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_geo_api.py`
Expected: FAIL.

- [ ] **Step 3: Lista**

W `modules/production/logistics/services/lista.py`:
```python
from modules.production.logistics.services import geocoding


def _geo(punkt):
    if punkt is None or punkt.lat is None:
        return None
    return {'lat': float(punkt.lat), 'lng': float(punkt.lng), 'quality': punkt.quality,
            'source': punkt.source, 'adres_zmieniony': bool(punkt.address_changed_after_manual)}
```
- `serializuj(order)` → `serializuj(order, geo=None)` i w słowniku `'geo': _geo(geo),`.
- w `pobierz(...)` zamiast `[serializuj(o) for o in zapytanie.all()]`:
```python
    zamowienia = zapytanie.all()
    punkty = geocoding.geo_zamowien([o.id for o in zamowienia])
    wiersze = [serializuj(o, punkty.get(o.id)) for o in zamowienia]
```

- [ ] **Step 4: Router panelu i cron**

W `routers/panel_api.py`:
- import `from flask import current_app` i `from modules.production.logistics.services import geocoding`;
- w `orders()` do odpowiedzi dopisz `'bez_lokalizacji': geocoding.bez_lokalizacji(), 'geokoder_dziala': geocoding.geokoder_dziala(),`;
- w `delivery_method()` i `handed_over()` przekazuj punkty: `punkty = geocoding.geo_zamowien(ids)` i `lista.serializuj(o, punkty.get(o.id))`;
- nowe trasy:
```python
@logistics_panel_bp.route('/geocode', methods=['POST'])
@guard
def geocode():
    """„Zlokalizuj teraz” — tylko uruchamia wątek w tle (timeout gunicorna 30 s)."""
    uruchomiono = geocoding.uruchom_w_tle(current_app._get_current_object())
    return jsonify({'success': True, 'uruchomiono': bool(uruchomiono)}), 202


def _zamowienie_albo_404(order_id):
    return ProductionOrder.query.get(order_id)


@logistics_panel_bp.route('/orders/<int:order_id>/geo', methods=['PUT'])
@guard
def order_geo(order_id):
    order = _zamowienie_albo_404(order_id)
    if order is None:
        return _blad(u'Nie ma takiego zamówienia.', 404)
    dane = request.get_json(silent=True) or {}
    try:
        punkt = geocoding.ustaw_recznie(order, dane.get('lat'), dane.get('lng'))
    except delivery.LogistykaBlad as e:
        db.session.rollback()
        return _blad(e.komunikat, e.status)
    db.session.commit()
    return jsonify({'success': True, 'order': lista.serializuj(order, punkt)})


@logistics_panel_bp.route('/orders/<int:order_id>/geo/reset', methods=['POST'])
@guard
def order_geo_reset(order_id):
    order = _zamowienie_albo_404(order_id)
    if order is None:
        return _blad(u'Nie ma takiego zamówienia.', 404)
    geocoding.resetuj(order)
    db.session.commit()
    return jsonify({'success': True, 'order': lista.serializuj(order, None)})
```
- w `tab_content()` przekaż `magazyn=geocoding.MAGAZYN`.

W `routers/cron_api.py` po uruchomieniu dopychacza:
```python
    geokoder = geocoding.uruchom_w_tle(current_app._get_current_object())
```
i w odpowiedzi `'geokoder_uruchomiony': bool(geokoder),` (import `geocoding`).

W `tab_content.html` korzeń:
```html
<div id="logistics-root" class="logistics-tab"
     data-api="{{ url_for('logistics_panel.orders') }}"
     data-magazyn-lat="{{ magazyn.lat }}" data-magazyn-lng="{{ magazyn.lng }}"
     data-magazyn-nazwa="{{ magazyn.nazwa }}">
```
(zachowaj pozostałą treść szablonu z etapu 1).

- [ ] **Step 5: Uruchom testy**

Run: `PYTEST tests/test_logistyka_geo_api.py tests/test_logistyka_panel_api.py tests/test_logistyka_cron.py`
Expected: PASS (testy etapu 1 też, bo `geo` ma wartość domyślną).

- [ ] **Step 6: Commit**

```bash
git add modules/production/logistics tests/test_logistyka_geo_api.py
git commit -m "feat(production): API wspolrzednych zamowien, lokalizowanie na zadanie i korekta pinezki

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Leaflet i klastry w repo

**Files:**
- Create: `modules/production/static/vendor/leaflet/{leaflet.js, leaflet.css, LICENSE, images/layers.png, images/layers-2x.png, images/marker-icon.png, images/marker-icon-2x.png, images/marker-shadow.png}`
- Create: `modules/production/static/vendor/leaflet-markercluster/{leaflet.markercluster.js, MarkerCluster.css, MarkerCluster.Default.css, LICENSE}`
- Test: `tests/test_logistyka_vendor.py`

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_vendor.py`:
```python
# -*- coding: utf-8 -*-
import os

VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'modules', 'production', 'static', 'vendor')
PLIKI = ['leaflet/leaflet.js', 'leaflet/leaflet.css', 'leaflet/LICENSE',
         'leaflet/images/marker-icon.png', 'leaflet/images/marker-icon-2x.png',
         'leaflet/images/marker-shadow.png', 'leaflet/images/layers.png',
         'leaflet/images/layers-2x.png',
         'leaflet-markercluster/leaflet.markercluster.js',
         'leaflet-markercluster/MarkerCluster.css',
         'leaflet-markercluster/MarkerCluster.Default.css',
         'leaflet-markercluster/LICENSE']


def test_biblioteki_mapy_sa_w_repo():
    for plik in PLIKI:
        sciezka = os.path.join(VENDOR, *plik.split('/'))
        assert os.path.getsize(sciezka) > 0, plik
    assert '1.9.4' in open(os.path.join(VENDOR, 'leaflet', 'leaflet.js'), encoding='utf-8').read(2000)
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_vendor.py`
Expected: FAIL.

- [ ] **Step 3: Pobranie (z worktree)**

```bash
V=modules/production/static/vendor
mkdir -p $V/leaflet/images $V/leaflet-markercluster
L=https://cdn.jsdelivr.net/npm/leaflet@1.9.4
for f in dist/leaflet.js dist/leaflet.css dist/images/layers.png dist/images/layers-2x.png dist/images/marker-icon.png dist/images/marker-icon-2x.png dist/images/marker-shadow.png; do
  curl -fsSL "$L/$f" -o "$V/leaflet/${f#dist/}"; done
curl -fsSL "$L/LICENSE" -o $V/leaflet/LICENSE
M=https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3
for f in leaflet.markercluster.js MarkerCluster.css MarkerCluster.Default.css; do
  curl -fsSL "$M/dist/$f" -o "$V/leaflet-markercluster/$f"; done
curl -fsSL "$M/MIT-LICENCE.txt" -o $V/leaflet-markercluster/LICENSE
head -c 300 $V/leaflet/leaflet.js; echo; head -c 200 $V/leaflet-markercluster/leaflet.markercluster.js
```
Expected: nagłówki z „Leaflet 1.9.4” i „Leaflet.markercluster 1.5.3”. Jeśli `head` nie pokazuje wersji w pierwszych 2000 znakach `leaflet.js`, popraw test na wyszukanie `"1.9.4"` w całym pliku.

- [ ] **Step 4: Uruchom test**

Run: `PYTEST tests/test_logistyka_vendor.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/production/static/vendor/leaflet modules/production/static/vendor/leaflet-markercluster tests/test_logistyka_vendor.py
git commit -m "chore(production): Leaflet 1.9.4 i markercluster 1.5.3 w repo zamiast z CDN

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Mapa na dashboardzie Logistyki (skill `frontend-design`)

**REQUIRED:** Przed napisaniem HTML/CSS/JS wywołaj skill `frontend-design:frontend-design`. Oprawa zgodna z panelem produkcji (zmienne `--il-*` z `modules/production/static/css/production-panel.css`, JetBrains Mono w nagłówkach) i z listą z etapu 1 (`modules/production/logistics/static/css/logistics.css`). Teksty po polsku, „Base.”.

**Files:**
- Modify: `modules/production/logistics/templates/logistics/tab_content.html`
- Modify / Create: `modules/production/logistics/static/js/logistics.js` (lista) i `modules/production/logistics/static/js/logistics-map.js` (mapa), `modules/production/logistics/static/css/logistics.css`
- Test: `tests/test_logistyka_mapa_ui.py`

**Interfaces:**
- Consumes: `GET /orders` (pola `geo`, `bez_lokalizacji`, `geokoder_dziala`), `POST /geocode`, `PUT /orders/<id>/geo`, `POST /orders/<id>/geo/reset`, atrybuty `data-magazyn-*` (Task 5); pliki Leaflet (Task 6) spod `url_for('production.static', filename='vendor/leaflet/...')`.
- Produces: kontener mapy `#logistics-map`; globalny `window.LogisticsMap` z metodami `render(orders)`, `highlight(orderId)`, `onSelect(callback)` — **etap 3 doda do niego warstwę tras** (przełącznik widoków).

**Wymagania funkcjonalne (spec 7.2):**
1. Układ: lista (z etapu 1) i mapa obok siebie na szerokim ekranie (mapa przyklejona przy przewijaniu listy); poniżej ~1100 px mapa nad listą. Przy 768 px oba czytelne.
2. Kafelki CARTO `https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png`, atrybucja „© OpenStreetMap © CARTO”; widok startowy — granice Polski; po wczytaniu dopasowanie do pinezek (+ magazyn).
3. Pinezki zamówień z `geo` w kolorze sposobu dostawy: szary (nie ustawiono), niebieski (kurier), zielony (transport własny), fioletowy (odbiór osobisty) — te same kolory co znaczniki na liście. Pinezki `quality == 'przyblizona'` wyraźnie inne (przerywana obwódka) z podpowiedzią „Lokalizacja przybliżona (miejscowość)”. Ikona „adres zmieniony” gdy `adres_zmieniony`.
4. Klastry (markercluster) z liczbą; kolor klastra neutralny.
5. Magazyn: osobny, wyróżniony znacznik (np. ikona domu/fabryki), nie wchodzi do klastrów.
6. Powiązanie z listą: klik w pinezkę → podświetlenie i przewinięcie do wiersza; klik w wiersz (lub ikonę „pokaż na mapie”) → przybliżenie i otwarcie dymka. Filtry i wyszukiwarka listy działają na mapie (mapa pokazuje tylko widoczne wiersze).
7. Dymek pinezki: numer, klient, miasto, sposób dostawy, etap, termin + akcje „Popraw lokalizację” (pinezka staje się przeciągalna; po upuszczeniu potwierdzenie → `PUT /orders/<id>/geo`) i „Przywróć automat” (tylko dla ręcznych → `POST /orders/<id>/geo/reset`).
8. Licznik **„Bez lokalizacji: N”** nad mapą; klik filtruje listę do zamówień bez `geo` albo z `quality == 'nie_znaleziono'`; w takim wierszu akcja „Ustaw na mapie” → następne kliknięcie w mapę ustawia punkt (`PUT`), Esc anuluje.
9. Przycisk **„Zlokalizuj teraz”** → `POST /geocode`; komunikat „Lokalizowanie w tle…”; gdy `geokoder_dziala`, przycisk nieaktywny z animacją, a lista odświeża się co 10 s aż do końca.
10. W etapie 2 **brak** przełącznika „Zamówienia | Trasy” (dochodzi w etapie 3) — ale struktura HTML ma na niego miejsce w nagłówku mapy.
11. Leaflet ładowany wyłącznie z `modules/production/static/vendor/` (żadnego `unpkg.com`/`cdn.jsdelivr.net` w szablonie ani JS).

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_mapa_ui.py`:
```python
# -*- coding: utf-8 -*-
import os

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(KATALOG, 'modules', 'production', 'logistics')


def _plik(*sciezka):
    return open(os.path.join(*sciezka), encoding='utf-8').read()


def _js():
    katalog = os.path.join(LOG, 'static', 'js')
    return ''.join(_plik(katalog, f) for f in os.listdir(katalog) if f.endswith('.js'))


def test_szablon_laduje_leaflet_z_repo():
    html = _plik(LOG, 'templates', 'logistics', 'tab_content.html')
    assert 'vendor/leaflet/leaflet.js' in html
    assert 'vendor/leaflet-markercluster/leaflet.markercluster.js' in html
    assert 'id="logistics-map"' in html
    for cdn in ('unpkg.com', 'cdn.jsdelivr', 'cdnjs'):
        assert cdn not in html


def test_js_mapy_obsluguje_korekte_i_lokalizowanie():
    js = _js()
    for fraza in ('/geocode', '/geo/reset', "method: 'PUT'", 'basemaps.cartocdn.com',
                  'markerClusterGroup', 'window.LogisticsMap', 'bez_lokalizacji'):
        assert fraza in js, fraza
    assert 'unpkg.com' not in js and 'BaseLinker' not in js
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_mapa_ui.py`
Expected: FAIL.

- [ ] **Step 3: Implementacja ze skillem `frontend-design`**

Wywołaj `frontend-design:frontend-design`, przekaż: wymagania 1–11, kontrakt z Interfaces, pliki etapu 1 (`tab_content.html`, `logistics.js`, `logistics.css`) jako punkt wyjścia i starą implementację mapy dla odniesienia (`git show origin/main~50:modules/production/templates/logistics/logistics.html` albo historia pliku sprzed etapu 1: `git log --all --oneline -- modules/production/templates/logistics/logistics.html` → `git show <hash>:modules/production/templates/logistics/logistics.html` — interakcja lista↔mapa, `createPinIcon`, `placeMarkers`). Zasady techniczne:
- `<link>`/`<script>` Leaflet i markercluster przez `url_for('production.static', filename='vendor/...')`, przed `logistics-map.js` i `logistics.js`.
- `logistics-map.js` bez zależności od `logistics.js`; `logistics.js` woła `window.LogisticsMap.render(orders)` po każdym wczytaniu listy.
- Teksty z API escapowane przed wstawieniem do HTML dymków.
- Mapa inicjalizowana dopiero, gdy kontener jest widoczny (zakładka Bootstrap) — `map.invalidateSize()` przy pokazaniu zakładki (`shown.bs.tab` dla `#logistics-tab`).

- [ ] **Step 4: Uruchom testy**

Run: `PYTEST tests/test_logistyka_mapa_ui.py tests/test_logistyka_zakladka.py`
Expected: PASS.

- [ ] **Step 5: Oględziny**

Po Task 8 Step 2 (migracja na kopii bazy) albo przez render z test clienta: w przeglądarce (Browser pane) sprawdź pinezki, klastry, magazyn, klik pinezka↔wiersz, „Popraw lokalizację”, „Ustaw na mapie”, „Zlokalizuj teraz”, szerokości 1440/1024/768 px. Zrzuty do raportu.

- [ ] **Step 6: Commit**

```bash
git add modules/production/logistics tests/test_logistyka_mapa_ui.py
git commit -m "feat(production): mapa zamowien na dashboardzie Logistyki

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Dokumentacja, weryfikacja migracji, pełny pakiet, przegląd

**Files:**
- Modify: `CLAUDE.md` (sekcja „Zadania cykliczne (cron)” — akapit o cronie logistyki z etapu 1)

- [ ] **Step 1: CLAUDE.md**

Do akapitu o cronie logistyki dopisz zdanie:
```markdown
Od etapu 2 ten sam cron uruchamia w tle **geokoder** adresów (`logistics/services/geocoding.py`: GUGiK UUG →
Nominatim → przybliżenie; dzierżawa `logistyka_geo_dzierzawa`, Nominatim ≤ 1 zapytanie/s). Do usług idzie
wyłącznie adres. Ręczny punkt (przeciągnięta pinezka) nigdy nie jest nadpisywany automatem.
```

- [ ] **Step 2: Migracja na MySQL (osobna baza ze zrzutem, nie wspólna lokalna)**

```bash
cd /c/Users/Grafik/Documents/woodpower-crm-logistyka-2
docker compose -p woodpower-crm exec -T db sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" > /tmp/zrzut.sql && mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "DROP DATABASE IF EXISTS logistyka_test; CREATE DATABASE logistyka_test" && mysql -uroot -p"$MYSQL_ROOT_PASSWORD" logistyka_test < /tmp/zrzut.sql'
for i in 1 2; do docker compose -p woodpower-crm exec -T db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" logistyka_test' < migrations/2026-09-26-logistyka-geolokalizacja.sql; done
docker compose -p woodpower-crm exec -T db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" logistyka_test -e "SHOW CREATE TABLE prod_order_geo\G; SELECT config_key FROM prod_config WHERE config_key LIKE \"logistyka%\"; DROP DATABASE logistyka_test"'
```
Expected: oba przebiegi bez błędu, tabela i wiersz dzierżawy obecne. (Jeśli lokalna baza nie ma jeszcze migracji etapu 1, najpierw zaaplikuj `migrations/2026-09-25-logistyka-sposob-dostawy.sql` do `logistyka_test`).

- [ ] **Step 3: Próba na żywych usługach (ręczna, z kontenera, publiczne adresy)**

```bash
docker compose -p logistyka2 run --rm --no-deps app python -c "
from modules.production.logistics.services.geocoding import geokoduj_adres
for a in [('Floriańska 10/5','Kraków','31-021'),('36-068 Bachórz 14N','Bachórz','36-068'),('al. Tadeusza Rejtana 16C','Rzeszów','35-310')]:
    print(a, geokoduj_adres(a[0], a[1], a[2], 'PL'))"
```
Expected: trzy wyniki `gugik`/`dokladna` blisko: (50.0627, 19.9396), (49.8404, 22.2541), (50.0302, 22.0159).

- [ ] **Step 4: Pełny pakiet**

Run: `docker compose -p logistyka2 run --rm --no-deps app pytest tests/ -q` i `docker compose -p logistyka2 run --rm --no-deps app bash -c "cd integrations/blog_seo && python -m pytest -q"`
Expected: zielone.

- [ ] **Step 5: Przegląd gałęzi**

`superpowers:requesting-code-review` na całej gałęzi, nacisk na Review Focus z nagłówka. Popraw, powtórz testy.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: geokoder logistyki w cronie

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Lista kontrolna wdrożenia (do raportu, NIE wykonywać bez zgody Konrada)**

1. Gałąź `claude/logistyka-etap-2-mapa` wypchnięta na origin (bez merge'a do `main`). O wdrożeniu etapów decyduje Konrad — zawsze **po** instalacji appki 1.7.0 na tabletach.
2. Przy wdrożeniu: migracje etapów 1 i 2 przed restartem (robi to `deploy.sh`), wpis crontaba logistyki z etapu 1.
3. Po wdrożeniu: „Zlokalizuj teraz” w zakładce; obserwacja licznika „Bez lokalizacji” (pierwsze przejście kilkuset zamówień trwa minuty — Nominatim 1/s tylko dla adresów, których GUGiK nie zna).
4. Przejrzenie zamówień „nie znaleziono” i przybliżonych, ręczne poprawki.
