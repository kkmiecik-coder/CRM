# Logistyka etap 4, krok 4.1 — druk na dwóch drukarkach — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CRM i agent druku obsługują drugą drukarkę (`wysylka`, etykiety paczek 100×150) obok dzisiejszej (`etykiety`, 60×40), z etykietą paczki w ZPL, wydrukiem próbnym z panelu i kalibracją — gotowe pod deklarację paczek z kroku 4.2.

**Architecture:** Kolejka `prod_print_queue` dostaje kolumnę `printer`; `GET /api/print-agent/jobs` filtruje po `?printers=` (brak parametru = tylko `etykiety`, więc stary agent jest bezpieczny). Etykieta paczki to czysta funkcja `DaneEtykietyPaczki → ZPL` w nowym module `package_label.py`; kolejkowanie i wydruk próbny w nowym `print_queue_service.py`. Agent (`tools/print_agent`, sama biblioteka standardowa) czyta drukarki z sekcji `[printer:<nazwa>]`, każdą obsługuje osobną kolejką i drukuje przez TCP albo przez kolejkę wydruku Windows (RAW, `winspool.drv` przez `ctypes`).

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, MySQL 8.4 (produkcja) / SQLite (testy), pytest, Jinja2, vanilla JS, Python stdlib (agent), ZPL (emulacja Xprinter).

**Spec:** `docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md` — sekcje 5.1, 6 (6.1–6.4), 13, 14 pkt 1, 15 (pierwszy punkt).

## Global Constraints

- Kod zgodny z **Pythonem 3.9** (produkcja): bez `X | Y` w adnotacjach, bez `match`, `typing.Optional/List`.
- Komentarze i docstringi **po polsku**; teksty w UI po polsku; w UI „Base.” zamiast BaseLinker.
- Etykieta paczki: **tylko ASCII**, odbiorca zanonimizowany (dwa pierwsze słowa, 3 znaki + `***`), **zero danych adresowych** (ulica, kod, miejscowość), treść w marginesie ≥ 3 mm (24 punkty), dół treści ≤ 1130.
- Stary agent (bez `?printers=`) dostaje **wyłącznie** zadania `etykiety`.
- Agent: **tylko biblioteka standardowa** (urllib, socket, configparser, ctypes), stara sekcja `[printer]` działa dalej jako `etykiety`.
- Migracja: nazwa `2026-09-30-druk-dwie-drukarki.sql`, idempotentna, `ALTER` osłonięte `information_schema` + `PREPARE/EXECUTE`, bez `DELIMITER`.
- Etykiety produktów 60×40 (`label_print_service.generate_label_zpl`, `_enqueue_labels`) — **bez zmian w zachowaniu**; ich zadania dostają `printer = 'etykiety'` z domyślnej kolumny.
- Testy WYŁĄCZNIE z katalogu worktree: `docker compose -p logistyka4 run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider`; **nigdy** `docker compose exec` (testuje główny checkout); nie twórz `config/core.json` w worktree.
- Commity: Conventional Commits po polsku **bez polskich znaków w temacie** (jak `fix(production): odmowa przy utworzonej przesylce`), stopka `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Bez pushu do `main` (push = deploy); push gałęzi tylko na polecenie Konrada.

## Review Focus

1. **Stary agent na nowym serwerze** (brak `?printers=`) nie może dostać etykiety 100×150 — test `test_stary_agent_bez_parametru_dostaje_tylko_etykiety` (Task 2).
2. **Nowy agent na starym serwerze** (zadania bez pola `printer`) nie może wydrukować etykiet produktów na drukarce paczek ani kręcić się w kółko po te same zadania — testy `test_stary_serwer_bez_pola_printer` i `test_cudza_pelna_porcja_nie_zapetla_oprozniania` (Task 6).
3. **Martwa drukarka paczek z pełną kolejką** nie może zagłodzić drukarki etykiet (osobna kolejka na drukarkę) — test `test_martwa_drukarka_paczek_nie_wstrzymuje_etykiet` (Task 6).
4. **Dane z bazy „z życia”** (polskie znaki, `^`/`~`, pusty odbiorca, 6-cyfrowy numer, 40 pozycji) — ASCII, jedno `^XZ`, treść w marginesach — testy Task 3 (`test_dane_nie_wstrzykuja_komend_zpl`, `test_tresc_miesci_sie_w_marginesach`, `test_pusty_odbiorca`, `test_dlugi_numer_zamowienia_mniejsza_czcionka`).
5. **Przesunięcie z panelu poza zakresem albo śmieci** — odczyt przycięty do ±120 / 0, pola nigdy ujemne, zapis > 120 odrzucony walidacją — testy `test_wczytaj_przesuniecie`, `test_przesuniecie_nie_schodzi_ponizej_zera` (Task 3), `test_walidacja_przesuniecia` (Task 4).

## Odstępstwa od specu (świadome, do dopisania w specu w Task 7)

- 6.1: przesunięcie etykiety paczki dodajemy do **współrzędnych każdego pola** w Pythonie, nie komendą `^LH` — `^LH` nie przyjmuje wartości ujemnych, a na drukarce testowej potrzeba −8 w pionie. Działa na każdej emulacji ZPL.
- 6.2: w sekcjach drukarek TCP klucz adresu to **`ip`** (jak w dzisiejszej sekcji `[printer]`), nie `host`.
- 6.4 (dodatek): agent dostaje tryb **`python print_agent.py --kalibruj wysylka`** (TSPL `GAPDETECT`) — kalibracja jest obowiązkowym krokiem instalacji, a na hali nie będzie PowerShella ze skryptem z tej sesji.
- Poza tym krokiem (celowo): „stanowiska uprawnione do etykiet paczek: `packaging`, `verification`” (6.1) i ikona „etykiety paczek sprzed zmiany” (6.3) — dotyczą druku ze stanowisk i paczek, więc wchodzą w krok 4.2 razem z `prod_packages`. Krok 4.1 drukuje tylko z panelu (wydruk próbny).

## Środowisko

- Worktree (Git Bash): `cd /c/Users/Grafik/Documents/woodpower-crm/.claude/worktrees/logistyka-etap-4`, gałąź `claude/logistyka-etap-4` (odbita od `claude/logistyka-etap-3-trasy`).
- `PYTEST <ścieżki>` w krokach = `docker compose -p logistyka4 run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider` (pierwszy przebieg buduje obraz, ok. 80 s).
- Punkt wyjścia: `4888 passed, 3 skipped` (koniec etapu 3). Po każdym zadaniu pełny pakiet: 0 failed, passed = poprzednio + nowe.

## Mapa plików

| Plik | Rola |
|---|---|
| `migrations/2026-09-30-druk-dwie-drukarki.sql` (nowy) | kolumny `printer`, `package_id`, indeks |
| `modules/production/models.py` (`LabelPrintJob`, :917) | kolumny + stałe drukarek |
| `modules/production/routers/api/print_agent_api.py` | filtr `?printers=`, pole `printer` w odpowiedzi |
| `modules/production/services/package_label.py` (nowy) | dane etykiety paczki, anonimizacja, ZPL paczki i ZPL próbny 100×150, odczyt przesunięcia |
| `modules/production/services/print_queue_service.py` (nowy) | `zakolejkuj_zpl`, wydruk próbny obu drukarek |
| `modules/production/routers/api/config_api.py` | `POST /production/api/print-test`, klucze przesunięcia |
| `modules/production/services/config_service.py` | walidacja zakresu przesunięcia |
| `modules/production/templates/components/config-tab-content.html` | pola przesunięcia + przyciski „Wydruk próbny” |
| `modules/production/static/js/modules/config-module.js` | mapy pól, `wydrukProbny()` |
| `modules/production/templates/panel/dashboard.html` | wersja skryptu konfiguracji |
| `tools/print_agent/print_agent.py`, `config.example.ini`, `README.md` | drukarki, tryb Windows, kolejka na drukarkę, kalibracja |
| `tests/druk_fixtures.py` (nowy) | wspólna apka testowa kolejki |
| `tests/test_druk_kolejka_drukarek.py`, `tests/test_print_agent_api_drukarki.py`, `tests/test_etykieta_paczki.py`, `tests/test_druk_wydruk_probny.py`, `tests/test_druk_panel_ui.py`, `tests/test_print_agent_drukarki.py` (nowe) | testy |
| `tests/test_print_agent_sse.py` | 4 atrapy `fetch_jobs` dostają drugi argument |

---

### Task 1: Kolejka wydruku zna drukarkę (migracja + model)

**Files:**
- Create: `migrations/2026-09-30-druk-dwie-drukarki.sql`
- Modify: `modules/production/models.py` (klasa `LabelPrintJob`, ok. :917–960)
- Create: `tests/druk_fixtures.py`
- Test: `tests/test_druk_kolejka_drukarek.py`

**Interfaces:**
- Produces: `LabelPrintJob.DRUKARKA_ETYKIETY = 'etykiety'`, `LabelPrintJob.DRUKARKA_WYSYLKA = 'wysylka'`, `LabelPrintJob.DRUKARKI = ('etykiety', 'wysylka')`; kolumny `LabelPrintJob.printer: str` (domyślnie `'etykiety'`), `LabelPrintJob.package_id: Optional[int]`. Fikstury `tests.druk_fixtures.app`, `tests.druk_fixtures.nowa_apka(template_folder=None)`, `tests.druk_fixtures.zadanie(printer=None, status='pending', kod='900_1', zpl='^XA^XZ') -> LabelPrintJob`.

- [ ] **Step 0: Punkt wyjścia**

Run: `docker compose -p logistyka4 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider`
Expected: `4888 passed, 3 skipped` (zapisz liczby — to baseline kroku).

- [ ] **Step 1: Fikstury testowe**

Create `tests/druk_fixtures.py`:

```python
# -*- coding: utf-8 -*-
"""
Wspólna apka testowa kolejki wydruku (logistyka etap 4, krok 4.1).

    from tests.druk_fixtures import app, zadanie  # noqa: F401

SQLite in-memory z tabelami kolejki i konfiguracji. Import modeli kalkulatora,
klientów i wycen jest potrzebny tylko dlatego, że configure_mappers() przy
pierwszym zapytaniu konfiguruje CAŁY rejestr mapperów (User ma relacje do nich).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import LabelPrintJob, ProductionConfig
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

TABLES = [m.__table__ for m in (User, ProductionConfig, LabelPrintJob)]


def nowa_apka(template_folder=None):
    """Goła apka Flask z SQLite in-memory (jedno połączenie na cały test)."""
    app = Flask(__name__, template_folder=template_folder)
    app.secret_key = 'test-druk'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    return app


@pytest.fixture()
def app():
    app = nowa_apka()
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABLES)
        yield app
        db.session.remove()


def zadanie(printer=None, status='pending', kod='900_1', zpl='^XA^XZ'):
    """Wiersz kolejki; printer=None = bez podania drukarki (wartość domyślna kolumny)."""
    kolumny = dict(short_product_id=kod, zpl_payload=zpl, station_code='packaging',
                   requested_by_type='user', requested_by_id='1', status=status)
    if printer is not None:
        kolumny['printer'] = printer
    job = LabelPrintJob(**kolumny)
    db.session.add(job)
    db.session.commit()
    return job
```

- [ ] **Step 2: Test, który padnie**

Create `tests/test_druk_kolejka_drukarek.py`:

```python
# -*- coding: utf-8 -*-
"""Kolejka wydruku zna drukarkę (logistyka etap 4, krok 4.1, spec 5.1)."""
import os

from modules.production.models import LabelPrintJob
from tests.druk_fixtures import app, zadanie  # noqa: F401

MIGRACJA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', '2026-09-30-druk-dwie-drukarki.sql')


def test_stale_drukarek():
    assert LabelPrintJob.DRUKARKA_ETYKIETY == 'etykiety'
    assert LabelPrintJob.DRUKARKA_WYSYLKA == 'wysylka'
    assert LabelPrintJob.DRUKARKI == ('etykiety', 'wysylka')


def test_zadanie_bez_drukarki_idzie_na_etykiety(app):
    """Dzisiejszy kod etykiet produktów nie podaje drukarki — musi trafić na starą."""
    job = zadanie()
    assert LabelPrintJob.query.get(job.id).printer == 'etykiety'
    assert job.package_id is None


def test_zadanie_na_drukarke_wysylki(app):
    job = zadanie(printer='wysylka', kod='P-1')
    assert LabelPrintJob.query.get(job.id).printer == 'wysylka'


def test_migracja_drukarek():
    sql = open(MIGRACJA, encoding='utf-8').read()
    assert "ADD COLUMN printer VARCHAR(20) NOT NULL DEFAULT ''etykiety''" in sql
    assert 'ADD COLUMN package_id INT NULL' in sql
    assert 'ADD INDEX ix_prod_print_queue_printer_status (printer, status)' in sql
    # każdy z trzech ALTER-ów osłonięty warunkiem (runner wykonuje katalog przy każdym deployu)
    assert sql.count('information_schema') == 3
    assert sql.count('PREPARE krok FROM @sql') == 3
    assert 'DELIMITER' not in sql
```

- [ ] **Step 3: Uruchom — ma paść**

Run: `PYTEST tests/test_druk_kolejka_drukarek.py`
Expected: FAIL (`AttributeError: ... DRUKARKA_ETYKIETY`, `TypeError: 'printer' is an invalid keyword argument`, `FileNotFoundError` migracji).

- [ ] **Step 4: Migracja**

Create `migrations/2026-09-30-druk-dwie-drukarki.sql`:

```sql
-- Logistyka etap 4, krok 4.1 (spec 2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md, sekcja 5.1):
-- kolejka wydruku zna drukarkę. 'etykiety' = dotychczasowa drukarka 60x40 (domyślna, więc stare
-- wiersze i stary kod działają bez zmian), 'wysylka' = drukarka etykiet paczek 100x150 przy pakowaniu.
-- package_id: paczka, której dotyczy etykieta (tabela prod_packages powstaje w kroku 4.2 — klucz obcy
-- dojdzie wtedy). Indeks (printer, status): agent pyta o zadania 'pending' jednej drukarki.
-- Idempotentna: ALTER nie ma IF NOT EXISTS, więc warunek z information_schema przez
-- PREPARE/EXECUTE (bez zmiany separatora poleceń), jak w 2026-09-28-logistyka-kierowcy.sql.

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_print_queue'
               AND COLUMN_NAME = 'printer');
SET @sql = IF(@brak, 'ALTER TABLE prod_print_queue ADD COLUMN printer VARCHAR(20) NOT NULL DEFAULT ''etykiety''',
              'SELECT "printer juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_print_queue'
               AND COLUMN_NAME = 'package_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_print_queue ADD COLUMN package_id INT NULL',
              'SELECT "package_id juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_print_queue'
               AND INDEX_NAME = 'ix_prod_print_queue_printer_status');
SET @sql = IF(@brak, 'ALTER TABLE prod_print_queue ADD INDEX ix_prod_print_queue_printer_status (printer, status)',
              'SELECT "indeks drukarki juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;
```

- [ ] **Step 5: Model**

W `modules/production/models.py`, klasa `LabelPrintJob`: pod stałymi `STATUS_*` dopisz stałe drukarek, a pod `status = Column(...)` (przed `printed_at`) — kolumny. `Index` jest już importowany (linia 21).

```python
    STATUS_EXPIRED = 'expired'

    # Drukarki (logistyka etap 4, spec 5.1). Nazwy są wspólne z agentem druku
    # (sekcje [printer:<nazwa>] w jego config.ini) — zmiana tu = zmiana na hubie.
    DRUKARKA_ETYKIETY = 'etykiety'   # etykiety produktów 60x40 (dotychczasowa drukarka)
    DRUKARKA_WYSYLKA = 'wysylka'     # etykiety paczek 100x150 przy pakowaniu
    DRUKARKI = (DRUKARKA_ETYKIETY, DRUKARKA_WYSYLKA)

    __table_args__ = (
        Index('ix_prod_print_queue_printer_status', 'printer', 'status'),
    )
```

```python
    # Drukarka docelowa. Domyślna 'etykiety': kod etykiet produktów jej nie podaje,
    # a stary agent (bez ?printers=) dostaje wyłącznie te zadania.
    printer = Column(String(20), nullable=False, default='etykiety', server_default='etykiety')
    # Paczka, której dotyczy etykieta (krok 4.2 — prod_packages); NULL dla etykiet produktów.
    package_id = Column(Integer, nullable=True)
```

- [ ] **Step 6: Uruchom — ma przejść**

Run: `PYTEST tests/test_druk_kolejka_drukarek.py`
Expected: PASS (4 testy).

- [ ] **Step 7: Pełny pakiet**

Run: `docker compose -p logistyka4 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider`
Expected: 0 failed, passed = baseline + 4.

- [ ] **Step 8: Commit**

```bash
git add migrations/2026-09-30-druk-dwie-drukarki.sql modules/production/models.py tests/druk_fixtures.py tests/test_druk_kolejka_drukarek.py
git commit -m "feat(production): kolejka wydruku zna drukarke (etykiety, wysylka)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: API agenta filtruje zadania po drukarce

**Files:**
- Modify: `modules/production/routers/api/print_agent_api.py` (docstring modułu, `list_jobs` :129–163)
- Test: `tests/test_print_agent_api_drukarki.py`

**Interfaces:**
- Consumes: `LabelPrintJob.DRUKARKI`, `LabelPrintJob.printer` (Task 1), fikstury `tests.druk_fixtures`.
- Produces: `GET /api/print-agent/jobs?limit=N&printers=a,b` — brak parametru = `('etykiety',)`, parametr pusty albo same nieznane nazwy = pusta lista; każde zadanie w odpowiedzi ma pole `printer`. Funkcja `print_agent_api._drukarki_z_zapytania(surowe: Optional[str]) -> tuple`.

- [ ] **Step 1: Test, który padnie**

Create `tests/test_print_agent_api_drukarki.py`:

```python
# -*- coding: utf-8 -*-
"""GET /api/print-agent/jobs z filtrem drukarek (logistyka etap 4, krok 4.1, spec 6.1)."""
import pytest

from modules.production.models import LabelPrintJob
from modules.production.routers.api import print_agent_api
from tests.druk_fixtures import app, zadanie  # noqa: F401

TOKEN = 'token-agenta-testowy'
NAGLOWKI = {'Authorization': 'Bearer ' + TOKEN}


@pytest.fixture()
def client(app, monkeypatch):
    monkeypatch.setattr(print_agent_api, '_get_agent_token', lambda: TOKEN)
    app.register_blueprint(print_agent_api.print_agent_bp, url_prefix='/api/print-agent')
    return app.test_client()


def _jobs(client, zapytanie=''):
    resp = client.get('/api/print-agent/jobs' + zapytanie, headers=NAGLOWKI)
    assert resp.status_code == 200
    return resp.get_json()['jobs']


def test_stary_agent_bez_parametru_dostaje_tylko_etykiety(client):
    """Agent sprzed etapu 4 nie wysyła ?printers= — etykieta 100x150 wysłana na
    drukarkę 60x40 zmarnowałaby etykiety i zadanie."""
    a = zadanie()
    zadanie(printer='wysylka', kod='P-1')
    jobs = _jobs(client)
    assert [j['id'] for j in jobs] == [a.id]
    assert jobs[0]['printer'] == 'etykiety'


def test_agent_drukarki_wysylki_dostaje_tylko_swoje(client):
    zadanie()
    b = zadanie(printer='wysylka', kod='P-1')
    jobs = _jobs(client, '?printers=wysylka')
    assert [j['id'] for j in jobs] == [b.id]
    assert jobs[0]['printer'] == 'wysylka'


def test_lista_drukarek_w_kolejnosci_fifo(client):
    a = zadanie()
    b = zadanie(printer='wysylka', kod='P-1')
    c = zadanie(kod='900_2')
    assert [j['id'] for j in _jobs(client, '?printers=etykiety,wysylka')] == [a.id, b.id, c.id]


@pytest.mark.parametrize('zapytanie', ['?printers=', '?printers=nieznana', '?printers=%20,%20'])
def test_nieznane_albo_puste_drukarki_nie_dostaja_niczego(client, zapytanie):
    zadanie()
    zadanie(printer='wysylka', kod='P-1')
    assert _jobs(client, zapytanie) == []


def test_wielkosc_liter_i_spacje_w_parametrze(client):
    b = zadanie(printer='wysylka', kod='P-1')
    assert [j['id'] for j in _jobs(client, '?printers=%20WYSYLKA%20')] == [b.id]


def test_limit_liczy_po_filtrze(client):
    for i in range(3):
        zadanie(printer='wysylka', kod='P-%d' % i)
    zadanie()
    assert len(_jobs(client, '?printers=wysylka&limit=2')) == 2


def test_tylko_oczekujace(client):
    zadanie(printer='wysylka', kod='P-1', status='printed')
    assert _jobs(client, '?printers=wysylka') == []


def test_nieudany_wydruk_paczki_nie_rusza_pozycji(client):
    """Zadanie bez product_id (etykieta paczki, wydruk próbny) po błędzie drukarki
    ma status failed, a cofanie licznika etykiet produktów je pomija."""
    b = zadanie(printer='wysylka', kod='P-1')
    resp = client.post('/api/print-agent/ack', headers=NAGLOWKI,
                       json={'results': [{'id': b.id, 'success': False, 'error': 'brak papieru'}]})
    assert resp.status_code == 200 and resp.get_json()['updated'] == 1
    job = LabelPrintJob.query.get(b.id)
    assert job.status == 'failed' and job.error_message == 'brak papieru'
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_print_agent_api_drukarki.py`
Expected: FAIL — bez parametru wraca też zadanie `wysylka`, brak klucza `printer` w odpowiedzi.

- [ ] **Step 3: Implementacja**

W `print_agent_api.py` w docstringu modułu zmień linię o `GET /api/print-agent/jobs?limit=10` na:

```
woła GET /api/print-agent/jobs?limit=10&printers=<drukarka>, drukuje lokalnie ZPL z pola
zpl_payload, potem POST /api/print-agent/ack z listą wyników. Każda drukarka ma własną
kolejkę (etap 4 logistyki: 'etykiety' 60x40 i 'wysylka' 100x150); agent sprzed etapu 4
nie podaje parametru i dostaje wyłącznie 'etykiety'. Polling został
```

Nad `@print_agent_bp.route('/jobs', ...)` dodaj:

```python
def _drukarki_z_zapytania(surowe):
    """`?printers=etykiety,wysylka` → krotka znanych nazw w kolejności podania.

    Brak parametru = tylko dotychczasowa drukarka: agent sprzed etapu 4 nie zna
    parametru, a etykieta 100x150 wysłana na drukarkę 60x40 to zmarnowane etykiety.
    Parametr podany, ale pusty albo z samymi nieznanymi nazwami = nic (agent z
    literówką w config.ini nie może przejąć cudzej kolejki).
    """
    if surowe is None:
        return (LabelPrintJob.DRUKARKA_ETYKIETY,)
    nazwy = []
    for nazwa in str(surowe).split(','):
        nazwa = nazwa.strip().lower()
        if nazwa in LabelPrintJob.DRUKARKI and nazwa not in nazwy:
            nazwy.append(nazwa)
    return tuple(nazwy)
```

W `list_jobs` zamień docstring i zapytanie:

```python
def list_jobs():
    """
    GET /api/print-agent/jobs?limit=10&printers=etykiety,wysylka
    Zwraca pending zadania ZPL wskazanych drukarek (FIFO). Bez `printers` —
    tylko 'etykiety' (zgodność ze starym agentem). Przy okazji oznacza zadania
    starsze niż 1h jako expired.
    """
    _expire_stale_pending()

    try:
        limit = max(1, min(int(request.args.get('limit', 10)), 50))
    except (TypeError, ValueError):
        limit = 10

    drukarki = _drukarki_z_zapytania(request.args.get('printers'))
    if not drukarki:
        return jsonify({'jobs': [], 'count': 0}), 200

    jobs = (LabelPrintJob.query
            .filter(LabelPrintJob.status == 'pending',
                    LabelPrintJob.printer.in_(drukarki))
            # id jako drugi klucz: zadania z tej samej milisekundy wychodzą w kolejności wstawienia
            .order_by(LabelPrintJob.requested_at.asc(), LabelPrintJob.id.asc())
            .limit(limit)
            .all())

    return jsonify({
        'jobs': [
            {
                'id': j.id,
                'printer': j.printer,
                'short_product_id': j.short_product_id,
                'baselinker_order_id': j.baselinker_order_id,
                'station_code': j.station_code,
                'zpl_payload': j.zpl_payload,
                'requested_at': j.requested_at.isoformat() if j.requested_at else None,
            }
            for j in jobs
        ],
        'count': len(jobs),
    }), 200
```

- [ ] **Step 4: Uruchom — ma przejść (razem z dotychczasowymi testami API agenta)**

Run: `PYTEST tests/test_print_agent_api_drukarki.py tests/test_print_agent_api_realtime.py`
Expected: PASS.

- [ ] **Step 5: Pełny pakiet** — jak w Task 1 Step 7 (passed = poprzednio + 10).

- [ ] **Step 6: Commit**

```bash
git add modules/production/routers/api/print_agent_api.py tests/test_print_agent_api_drukarki.py
git commit -m "feat(production): agent druku pobiera zadania swojej drukarki

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Etykieta paczki 100×150 (ZPL) i przesunięcie z konfiguracji

**Files:**
- Create: `modules/production/services/package_label.py`
- Test: `tests/test_etykieta_paczki.py`

**Interfaces:**
- Consumes: `label_print_service._tekst_pola_zpl(tekst, maks) -> str` (istniejąca: polskie litery → ASCII, `^`/`~` → spacja, typografia → ASCII, jedna linia, ucinanie z `...`), `ProductionConfig`.
- Produces (używa Task 4 i krok 4.2):
  - `@dataclass PozycjaEtykiety(gatunek: str, technologia: str, klasa: str, dlugosc_cm: float, szerokosc_cm: float, grubosc_cm: float, ilosc: int, wykonczenie: Optional[str] = None)`
  - `@dataclass DaneEtykietyPaczki(numer_zamowienia: str, kod_paczki: str, rodzaj: str, numer: int, z_ilu: int, sposob: str, odbiorca: Optional[str], pozycje: List[PozycjaEtykiety] = [], typ_palety: Optional[str] = None, dlugosc_cm: Optional[int] = None, szerokosc_cm: Optional[int] = None, m3: float = 0.0, spakowano: Optional[date] = None, base_id: Optional[int] = None, zamowienie_klienta: Optional[str] = None)` — `rodzaj` ∈ {`'paczka'`, `'paleta'`}, `typ_palety` ∈ {`'eur'`, `'niestandardowa'`, None}, `sposob` = gotowy tekst pasa (np. `'KURIER'`, `'TRASA: Rzeszow 07.10'`).
  - `anonimizuj_odbiorce(nazwa: Optional[str]) -> str`
  - `opis_rodzaju(dane: DaneEtykietyPaczki) -> str`
  - `generate_package_label_zpl(dane: DaneEtykietyPaczki, przesuniecie: Tuple[int, int] = (0, 0)) -> str`
  - `generate_test_label_zpl(przesuniecie: Tuple[int, int] = (0, 0)) -> str`
  - `wczytaj_przesuniecie() -> Tuple[int, int]` oraz stałe `KLUCZ_PRZESUNIECIA_X = 'PACKAGE_LABEL_OFFSET_X_DOTS'`, `KLUCZ_PRZESUNIECIA_Y = 'PACKAGE_LABEL_OFFSET_Y_DOTS'`, `MAKS_PRZESUNIECIA = 120`, `SZEROKOSC = 800`, `WYSOKOSC = 1200`, `MARGINES = 24`, `MAKS_WIERSZY = 14`, `WAGA_KG_NA_M3 = 800`.

- [ ] **Step 1: Test, który padnie**

Create `tests/test_etykieta_paczki.py`:

```python
# -*- coding: utf-8 -*-
"""Etykieta paczki 100x150 (logistyka etap 4, krok 4.1, spec 6.3)."""
import re
from datetime import date

import pytest

from extensions import db
from modules.production.models import ProductionConfig
from modules.production.services import package_label as pl
from modules.production.services.package_label import DaneEtykietyPaczki, PozycjaEtykiety
from tests.druk_fixtures import app  # noqa: F401


def _pozycja(**zmiany):
    dane = dict(gatunek='dąb', technologia='lity', klasa='A/B', dlugosc_cm=97,
                szerokosc_cm=29, grubosc_cm=4, ilosc=5)
    dane.update(zmiany)
    return PozycjaEtykiety(**dane)


def _dane(**zmiany):
    dane = dict(numer_zamowienia='1450', kod_paczki='P-12345', rodzaj='paleta',
                typ_palety='eur', numer=1, z_ilu=1, sposob='TRANSPORT WOODPOWER',
                odbiorca='Dariusz Kowalczyk', pozycje=[_pozycja()], m3=0.373,
                spakowano=date(2026, 9, 25), base_id=49915386, zamowienie_klienta='2149/2026')
    dane.update(zmiany)
    return DaneEtykietyPaczki(**dane)


def _x(zpl):
    return [int(v) for v in re.findall(r'\^FO(-?\d+),', zpl)]


def _y(zpl):
    return [int(v) for v in re.findall(r'\^FO-?\d+,(-?\d+)', zpl)]


@pytest.mark.parametrize('nazwa, wynik', [
    ('Dariusz Kowalczyk', 'Dar*** Kow***'),
    ('Łucja Żak', 'Luc*** Zak'),
    ('Jan Maria Rokita', 'Jan Mar***'),
    ('  STOLBUD   Sp. z o.o. ', 'STO*** Sp.'),
    ('', ''),
    (None, ''),
])
def test_anonimizacja_odbiorcy(nazwa, wynik):
    assert pl.anonimizuj_odbiorce(nazwa) == wynik


def test_bez_pelnej_nazwy_i_tylko_ascii():
    zpl = pl.generate_package_label_zpl(_dane(odbiorca='Łukasz Źdźbło-Wiśniewski',
                                              sposob='TRASA: Łódź – Śląsk „wt”'))
    assert 'Luk***' in zpl and 'Lukasz' not in zpl and 'Zdzblo' not in zpl
    assert all(ord(z) < 128 for z in zpl)


def test_pusty_odbiorca():
    zpl = pl.generate_package_label_zpl(_dane(odbiorca=None))
    assert '^FDODBIORCA^FS' in zpl


def test_rozmiar_i_kod_qr():
    zpl = pl.generate_package_label_zpl(_dane())
    assert zpl.startswith('^XA') and zpl.rstrip().endswith('^XZ')
    assert '^PW800' in zpl and '^LL1200' in zpl
    assert '^BQN,2,11^FDLA,P-12345^FS' in zpl


def test_rodzaj_i_numer_paczki():
    assert 'PALETA EUR 120x80' in pl.generate_package_label_zpl(_dane())
    zpl = pl.generate_package_label_zpl(_dane(rodzaj='paczka', typ_palety=None, numer=2, z_ilu=3))
    assert '^FR^FDPACZKA^FS' in zpl and '^FR^FD2 / 3^FS' in zpl and '^FDPACZKA^FS' in zpl
    zpl = pl.generate_package_label_zpl(_dane(typ_palety='niestandardowa', dlugosc_cm=150,
                                              szerokosc_cm=100))
    assert 'PALETA 150x100' in zpl


def test_waga_i_podsumowanie():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja(ilosc=5), _pozycja(ilosc=3)],
                                              m3=0.373))
    assert 'Waga szac.: ~298 kg' in zpl
    assert '2 poz. / 8 szt. / 0,373 m3' in zpl
    assert 'Spakowano: 25.09.2026' in zpl


def test_wiersz_pozycji():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja(
        dlugosc_cm=101.5, szerokosc_cm=29.0, grubosc_cm=4, wykonczenie='olejowane')]))
    assert '^FD1. Dab lity A/B 101.5x29x4 cm, olejowane^FS' in zpl
    assert '^FD5 szt.^FS' in zpl


def test_surowe_bez_dopisku():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja(wykonczenie='surowe')]))
    assert 'surowe' not in zpl


def test_14_pozycji_miesci_sie_cala_lista():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja() for _ in range(14)]))
    assert '14. Dab' in zpl and 'pozycji (' not in zpl


def test_15_pozycji_ucina_do_13_i_dopisuje_reszte():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja(ilosc=1) for _ in range(15)]))
    assert '13. Dab' in zpl and '14. Dab' not in zpl
    assert '+ 2 pozycji (2 szt.) - pelna lista w CRM' in zpl


def test_tresc_miesci_sie_w_marginesach():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja() for _ in range(40)]))
    assert min(_x(zpl)) >= pl.MARGINES
    assert min(_y(zpl)) >= pl.MARGINES
    assert max(_y(zpl)) <= 1108          # stopka startuje na 1108 i kończy się przed 1130


def test_dane_nie_wstrzykuja_komend_zpl():
    zpl = pl.generate_package_label_zpl(_dane(sposob='TRASA: ^XZ~JA', zamowienie_klienta='12^FS',
                                              odbiorca='^Jan ~Nowak', numer_zamowienia='14~50'))
    assert zpl.count('^XZ') == 1 and '~' not in zpl


def test_dlugi_numer_zamowienia_mniejsza_czcionka():
    assert '^A0N,140,120^FD1450^FS' in pl.generate_package_label_zpl(_dane())
    assert '^A0N,110,90^FD123456^FS' in pl.generate_package_label_zpl(_dane(numer_zamowienia='123456'))


def test_przesuniecie_przesuwa_wszystkie_pola():
    zero = pl.generate_package_label_zpl(_dane())
    przes = pl.generate_package_label_zpl(_dane(), przesuniecie=(8, -8))
    assert [x + 8 for x in _x(zero)] == _x(przes)
    assert [y - 8 for y in _y(zero)] == _y(przes)


def test_przesuniecie_nie_schodzi_ponizej_zera():
    zpl = pl.generate_package_label_zpl(_dane(), przesuniecie=(-120, -120))
    assert min(_x(zpl)) >= 0 and min(_y(zpl)) >= 0


def test_etykieta_probna():
    zpl = pl.generate_test_label_zpl((0, -8))
    assert '^FO24,16^GB752,1152,4^FS' in zpl          # ramka 3 mm, przesunięta o 1 mm w górę
    assert 'WYDRUK PROBNY' in zpl and 'X=0, Y=-8' in zpl
    assert all(ord(z) < 128 for z in zpl) and zpl.count('^XZ') == 1


@pytest.mark.parametrize('x, y, oczekiwane', [
    (None, None, (0, 0)),
    ('8', '-8', (8, -8)),
    ('abc', '', (0, 0)),
    ('500', '-500', (120, -120)),
])
def test_wczytaj_przesuniecie(app, x, y, oczekiwane):
    for klucz, wartosc in ((pl.KLUCZ_PRZESUNIECIA_X, x), (pl.KLUCZ_PRZESUNIECIA_Y, y)):
        if wartosc is not None:
            db.session.add(ProductionConfig(config_key=klucz, config_value=wartosc,
                                            config_type='integer'))
    db.session.commit()
    assert pl.wczytaj_przesuniecie() == oczekiwane
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_etykieta_paczki.py`
Expected: FAIL — `ModuleNotFoundError: modules.production.services.package_label`.

- [ ] **Step 3: Implementacja**

Create `modules/production/services/package_label.py`:

```python
# -*- coding: utf-8 -*-
"""
Etykieta paczki 100x150 mm dla drukarki `wysylka` (logistyka etap 4, spec sekcja 6.3).

Czyste funkcje: dostają gotowe dane (DaneEtykietyPaczki) i zwracają ZPL. Z bazy
czytamy tylko przesunięcie z panelu. Dane paczki zbiera w kroku 4.2 serwis paczek.

Zasady druku (ustalone z Konradem 30.09 na wzorach z zamówienia 1450):
- tylko ASCII: emulacja ZPL drukarek Xprinter nie ma polskich znaków (z
  „ĄĆĘŁŃÓŚŹŻ” wyszło tylko Ó), więc litery zamieniamy jak na etykietach
  produktów, a resztę spoza ASCII usuwamy;
- odbiorca zanonimizowany i ZERO danych adresowych — pełne dane są w CRM pod
  kodem paczki;
- treść w marginesie 3 mm i nad y=1130: po kalibracji drukarka i tak zostawia
  kilka milimetrów luzu, a resztę wyrównuje przesunięcie z panelu.
"""
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple

from modules.production.models import ProductionConfig
from modules.production.services.label_print_service import _tekst_pola_zpl

SZEROKOSC = 800          # 100 mm przy 203 dpi (8 punktów na mm)
WYSOKOSC = 1200          # 150 mm
MARGINES = 24            # 3 mm
MAKS_WIERSZY = 14        # pozycji na etykiecie; przy większej liczbie 13 + „+ N pozycji”
MAKS_OPISU = 40          # znaków opisu pozycji — dalej wchodziłby na kolumnę ilości (x=600)
# Ta sama gęstość co w podsumowaniu tras (logistics/services/routes.py, WAGA_KG_NA_M3).
# Kopia, a nie import: routes ciągnie za sobą modele logistyki, a ten moduł ma zostać lekki.
WAGA_KG_NA_M3 = 800

KLUCZ_PRZESUNIECIA_X = 'PACKAGE_LABEL_OFFSET_X_DOTS'
KLUCZ_PRZESUNIECIA_Y = 'PACKAGE_LABEL_OFFSET_Y_DOTS'
MAKS_PRZESUNIECIA = 120  # 15 mm — większe przesunięcie to źle założona rolka, nie kalibracja


@dataclass
class PozycjaEtykiety:
    gatunek: str
    technologia: str
    klasa: str
    dlugosc_cm: float
    szerokosc_cm: float
    grubosc_cm: float
    ilosc: int
    wykonczenie: Optional[str] = None      # None albo 'surowe' = nie dopisujemy


@dataclass
class DaneEtykietyPaczki:
    numer_zamowienia: str
    kod_paczki: str                        # 'P-<id>' — treść QR
    rodzaj: str                            # 'paczka' | 'paleta'
    numer: int                             # 1..z_ilu
    z_ilu: int
    sposob: str                            # gotowy tekst pasa, np. 'KURIER', 'TRASA: Rzeszow 07.10'
    odbiorca: Optional[str]                # pełna nazwa — anonimizuje generator
    pozycje: List[PozycjaEtykiety] = field(default_factory=list)
    typ_palety: Optional[str] = None       # 'eur' | 'niestandardowa'
    dlugosc_cm: Optional[int] = None       # wymiar palety niestandardowej
    szerokosc_cm: Optional[int] = None
    m3: float = 0.0
    spakowano: Optional[date] = None
    base_id: Optional[int] = None
    zamowienie_klienta: Optional[str] = None


def _ascii(tekst, maks):
    """Tekst pola ZPL: bez komend (^, ~), jedna linia, polskie litery zamienione,
    reszta spoza ASCII usunięta."""
    czysty = _tekst_pola_zpl(tekst or '', maks)
    return unicodedata.normalize('NFKD', czysty).encode('ascii', 'ignore').decode('ascii')


def anonimizuj_odbiorce(nazwa):
    """„Dariusz Kowalczyk” → „Dar*** Kow***”: dwa pierwsze słowa, z każdego 3 znaki."""
    slowa = _ascii(nazwa, 200).split()[:2]
    return ' '.join(s[:3] + ('***' if len(s) > 3 else '') for s in slowa)


def _wymiar(wartosc):
    liczba = float(wartosc or 0)
    return str(int(liczba)) if liczba == int(liczba) else '%.1f' % liczba


def opis_rodzaju(dane):
    if dane.rodzaj == 'paleta':
        if dane.typ_palety == 'eur':
            return 'PALETA EUR 120x80'
        if dane.dlugosc_cm and dane.szerokosc_cm:
            return 'PALETA %dx%d' % (int(dane.dlugosc_cm), int(dane.szerokosc_cm))
        return 'PALETA'
    return 'PACZKA'


def _wiersz_pozycji(numer, pozycja):
    opis = '%d. %s %s %s %sx%sx%s cm' % (
        numer, (pozycja.gatunek or '').capitalize(), pozycja.technologia or '',
        pozycja.klasa or '', _wymiar(pozycja.dlugosc_cm), _wymiar(pozycja.szerokosc_cm),
        _wymiar(pozycja.grubosc_cm))
    if pozycja.wykonczenie and pozycja.wykonczenie.strip().lower() != 'surowe':
        opis += ', ' + pozycja.wykonczenie.strip()
    return _ascii(opis, MAKS_OPISU)


class _Zpl:
    """Składa etykietę 100x150; każde pole dostaje przesunięcie z panelu (bez ^LH,
    bo ^LH nie przyjmuje wartości ujemnych). Współrzędne nigdy nie schodzą poniżej 0."""

    def __init__(self, przesuniecie):
        self.dx, self.dy = przesuniecie
        self.linie = ['^XA', '^CI0', '^PW%d' % SZEROKOSC, '^LL%d' % WYSOKOSC, '^LH0,0']

    def pole(self, x, y, tresc):
        self.linie.append('^FO%d,%d%s' % (max(0, x + self.dx), max(0, y + self.dy), tresc))

    def gotowe(self):
        return '\n'.join(self.linie + ['^XZ']) + '\n'


def generate_package_label_zpl(dane, przesuniecie=(0, 0)):
    """ZPL etykiety paczki. Układ zatwierdzony na wzorze 30.09 (spec 6.3)."""
    z = _Zpl(przesuniecie)
    numer = _ascii(dane.numer_zamowienia, 8)
    czcionka_numeru = '^A0N,140,120' if len(numer) <= 5 else '^A0N,110,90'

    # 1. Nagłówek: numer zamówienia + czarny kafel rodzaju i numeru paczki
    z.pole(32, 24, '^A0N,28,28^FDZAMOWIENIE^FS')
    z.pole(32, 54, '%s^FD%s^FS' % (czcionka_numeru, numer))
    z.pole(440, 24, '^GB328,166,166^FS')
    z.pole(440, 40, '^FB328,1,0,C^A0N,52,52^FR^FD%s^FS'
           % ('PALETA' if dane.rodzaj == 'paleta' else 'PACZKA'))
    z.pole(440, 100, '^FB328,1,0,C^A0N,84,84^FR^FD%d / %d^FS' % (int(dane.numer), int(dane.z_ilu)))

    # 2. Pas sposobu dostawy (biały na czarnym)
    z.pole(32, 204, '^GB736,72,72^FS')
    z.pole(32, 216, '^FB736,1,0,C^A0N,52,52^FR^FD%s^FS' % _ascii(dane.sposob, 26))

    # 3. Odbiorca — tylko zanonimizowana nazwa, bez żadnych danych adresowych
    z.pole(32, 292, '^A0N,26,26^FDODBIORCA^FS')
    z.pole(32, 322, '^A0N,46,44^FD%s^FS' % anonimizuj_odbiorce(dane.odbiorca))
    z.pole(32, 378, '^GB736,3,3^FS')

    # 4. QR i opis paczki
    kod = _ascii(dane.kod_paczki, 20)
    m3 = float(dane.m3 or 0)
    sztuk = sum(int(p.ilosc or 0) for p in dane.pozycje)
    z.pole(24, 390, '^BQN,2,11^FDLA,%s^FS' % kod)
    z.pole(330, 406, '^A0N,56,52^FD%s^FS' % kod)
    z.pole(330, 472, '^A0N,36,34^FD%s^FS' % opis_rodzaju(dane))
    z.pole(330, 516, '^A0N,32,30^FDWaga szac.: ~%d kg^FS' % round(m3 * WAGA_KG_NA_M3))
    z.pole(330, 556, '^A0N,32,30^FD%d poz. / %d szt. / %s m3^FS'
           % (len(dane.pozycje), sztuk, ('%.3f' % m3).replace('.', ',')))
    if dane.spakowano:
        z.pole(330, 596, '^A0N,28,28^FDSpakowano: %s^FS' % dane.spakowano.strftime('%d.%m.%Y'))
    z.pole(32, 640, '^GB736,3,3^FS')

    # 5. Zawartość całego zamówienia
    z.pole(32, 652, '^A0N,28,28^FDZAWARTOSC ZAMOWIENIA^FS')
    widoczne = (dane.pozycje if len(dane.pozycje) <= MAKS_WIERSZY
                else dane.pozycje[:MAKS_WIERSZY - 1])
    y = 690
    for numer_wiersza, pozycja in enumerate(widoczne, 1):
        z.pole(32, y, '^A0N,27,25^FD%s^FS' % _wiersz_pozycji(numer_wiersza, pozycja))
        z.pole(600, y, '^FB168,1,0,R^A0N,27,25^FD%d szt.^FS' % int(pozycja.ilosc or 0))
        y += 28
    reszta = dane.pozycje[len(widoczne):]
    if reszta:
        z.pole(32, y, '^A0N,27,25^FD+ %d pozycji (%d szt.) - pelna lista w CRM^FS'
               % (len(reszta), sum(int(p.ilosc or 0) for p in reszta)))

    # 6. Stopka
    z.pole(32, 1100, '^GB736,2,2^FS')
    z.pole(32, 1108, '^A0N,22,22^FDBase.: %s   Zam. klienta: %s   WoodPower^FS'
           % (dane.base_id or '-', _ascii(dane.zamowienie_klienta or '-', 20)))
    return z.gotowe()


def generate_test_label_zpl(przesuniecie=(0, 0)):
    """Etykieta próbna drukarki paczek: ramka 3 mm od krawędzi, bieżące przesunięcie, QR.
    Po kalibracji i dobrym przesunięciu ramka ma równy odstęp od wszystkich krawędzi."""
    z = _Zpl(przesuniecie)
    z.pole(MARGINES, MARGINES, '^GB%d,%d,4^FS' % (SZEROKOSC - 2 * MARGINES, WYSOKOSC - 2 * MARGINES))
    z.pole(60, 80, '^A0N,64,60^FDWYDRUK PROBNY^FS')
    z.pole(60, 160, '^A0N,36,34^FDDrukarka paczek 100x150^FS')
    z.pole(60, 230, '^A0N,30,28^FDRamka: 3 mm od kazdej krawedzi.^FS')
    z.pole(60, 270, '^A0N,30,28^FDNierowno? Popraw przesuniecie w panelu^FS')
    z.pole(60, 310, '^A0N,30,28^FD(8 punktow = 1 mm) i drukuj ponownie.^FS')
    z.pole(60, 370, '^A0N,30,28^FDPrzesuniecie teraz: X=%d, Y=%d^FS' % przesuniecie)
    z.pole(60, 440, '^BQN,2,11^FDLA,P-TEST^FS')
    z.pole(60, 1100, '^A0N,28,28^FDDol tresci (y=1100)^FS')
    return z.gotowe()


def _przesuniecie_z_tekstu(surowe):
    try:
        wartosc = int(str(surowe).strip())
    except (TypeError, ValueError):
        return 0
    return max(-MAKS_PRZESUNIECIA, min(MAKS_PRZESUNIECIA, wartosc))


def wczytaj_przesuniecie():
    """(dx, dy) w punktach z prod_config. Brak klucza albo śmieci = 0, poza zakresem =
    przycięte do ±MAKS_PRZESUNIECIA (panel waliduje zapis, ale ręczna zmiana w bazie
    nie może zepsuć druku)."""
    wiersze = {
        c.config_key: c.config_value
        for c in ProductionConfig.query.filter(
            ProductionConfig.config_key.in_((KLUCZ_PRZESUNIECIA_X, KLUCZ_PRZESUNIECIA_Y))).all()
    }
    return (_przesuniecie_z_tekstu(wiersze.get(KLUCZ_PRZESUNIECIA_X)),
            _przesuniecie_z_tekstu(wiersze.get(KLUCZ_PRZESUNIECIA_Y)))
```

- [ ] **Step 4: Uruchom — ma przejść**

Run: `PYTEST tests/test_etykieta_paczki.py`
Expected: PASS. Jeśli `test_bez_pelnej_nazwy_i_tylko_ascii` pada na znaku spoza ASCII — sprawdź, że każde pole z danymi przechodzi przez `_ascii` (albo `anonimizuj_odbiorce`/`opis_rodzaju`/`_wiersz_pozycji`), nie przez gołe `%s`.

- [ ] **Step 5: Pełny pakiet**, potem **Commit**

```bash
git add modules/production/services/package_label.py tests/test_etykieta_paczki.py
git commit -m "feat(production): etykieta paczki 100x150 w ZPL z anonimizacja odbiorcy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Kolejkowanie ZPL i wydruk próbny (serwis + endpoint + klucze konfiguracji)

**Files:**
- Create: `modules/production/services/print_queue_service.py`
- Modify: `modules/production/routers/api/config_api.py` (słownik `EXPECTED` ok. :244–253, `allowed_config_keys` ok. :515–520, nowy endpoint na końcu pliku)
- Modify: `modules/production/services/config_service.py` (`_validate_config_value`, :377)
- Test: `tests/test_druk_wydruk_probny.py`

**Interfaces:**
- Consumes: `LabelPrintJob.DRUKARKI/DRUKARKA_*` (Task 1), `package_label.generate_test_label_zpl`, `package_label.wczytaj_przesuniecie` (Task 3), `label_print_service._load_config()` (klucze `offset_lt`, `offset_ls`), `realtime_service.publish_print_signal(n)`.
- Produces (krok 4.2 użyje `zakolejkuj_zpl` do etykiet paczek):
  - `class NieznanaDrukarka(ValueError)`
  - `NAZWY_DRUKAREK = {'etykiety': 'drukarka etykiet (60x40)', 'wysylka': 'drukarka paczek (100x150)'}`
  - `zakolejkuj_zpl(drukarka: str, zpl: str, kod: str, stanowisko: str, aktor: dict, baselinker_order_id: Optional[int] = None, package_id: Optional[int] = None) -> LabelPrintJob` — dodaje i `flush()`, **nie commituje**.
  - `zpl_probny(drukarka: str) -> str`
  - `wydruk_probny(drukarka: str, aktor: dict) -> LabelPrintJob` — commit + sygnał dla agenta.
  - `POST /production/api/print-test` `{"printer": "etykiety"|"wysylka"}` → 200 `{success, job_id, message}` / 400 `{success: false, error}`; tylko admin.
  - Klucze `prod_config`: `PACKAGE_LABEL_OFFSET_X_DOTS`, `PACKAGE_LABEL_OFFSET_Y_DOTS` (grupa `printer`, integer, domyślnie 0, zakres −120…120).

- [ ] **Step 1: Test, który padnie**

Create `tests/test_druk_wydruk_probny.py`:

```python
# -*- coding: utf-8 -*-
"""Kolejkowanie ZPL i wydruk próbny (logistyka etap 4, krok 4.1, spec 6.1)."""
import pytest
from flask_login import LoginManager, UserMixin

from extensions import db
from modules.production.models import LabelPrintJob, ProductionConfig
from modules.production.services import print_queue_service as pqs
from modules.production.services.config_service import get_config_service
from tests.druk_fixtures import app  # noqa: F401


class _Uzytkownik(UserMixin):
    def __init__(self, uid, role):
        self.id = uid
        self.role = role


UZYTKOWNICY = {'1': _Uzytkownik('1', 'admin'), '2': _Uzytkownik('2', 'user')}


@pytest.fixture()
def sygnaly(monkeypatch):
    wyslane = []
    monkeypatch.setattr(pqs.realtime_service, 'publish_print_signal',
                        lambda n: wyslane.append(n) or True)
    return wyslane


@pytest.fixture()
def panel(app, sygnaly):
    menedzer = LoginManager()
    menedzer.init_app(app)
    menedzer.user_loader(lambda uid: UZYTKOWNICY.get(uid))
    from modules.production.routers.api import api_bp
    app.register_blueprint(api_bp, url_prefix='/production/api')
    return app.test_client()


def _zaloguj(klient, uid):
    with klient.session_transaction() as sesja:
        sesja['_user_id'] = uid
        sesja['_fresh'] = True


def test_zakolejkuj_zpl_zapisuje_drukarke_i_nie_commituje(app):
    job = pqs.zakolejkuj_zpl('wysylka', '^XA^XZ', 'P-7', 'packaging',
                             {'type': 'device', 'id': 3}, baselinker_order_id=99, package_id=7)
    assert job.id is not None                      # flush nadał id
    db.session.rollback()                          # bez commita zadanie znika
    assert LabelPrintJob.query.count() == 0


def test_zakolejkuj_zpl_pola(app):
    job = pqs.zakolejkuj_zpl('wysylka', '^XA^XZ', 'P-7', 'packaging',
                             {'type': 'device', 'id': 3}, package_id=7)
    db.session.commit()
    j = LabelPrintJob.query.get(job.id)
    assert (j.printer, j.short_product_id, j.package_id, j.status,
            j.requested_by_type, j.requested_by_id) == ('wysylka', 'P-7', 7, 'pending', 'device', '3')


@pytest.mark.parametrize('drukarka', ['laserowa', '', None, 'WYSYLKA'])
def test_zakolejkuj_zpl_odrzuca_nieznana_drukarke(app, drukarka):
    with pytest.raises(pqs.NieznanaDrukarka):
        pqs.zakolejkuj_zpl(drukarka, '^XA^XZ', 'X', 'panel', {'type': 'user', 'id': 1})


def test_wydruk_probny_drukarki_paczek(app, sygnaly):
    job = pqs.wydruk_probny('wysylka', {'type': 'user', 'id': 1})
    j = LabelPrintJob.query.get(job.id)
    assert (j.printer, j.short_product_id, j.station_code) == ('wysylka', 'TEST-wysylka', 'panel')
    assert '^PW800' in j.zpl_payload and 'WYDRUK PROBNY' in j.zpl_payload
    assert sygnaly == [1]                          # agent obudzony po commicie


def test_wydruk_probny_bierze_zapisane_przesuniecie(app, sygnaly):
    db.session.add(ProductionConfig(config_key='PACKAGE_LABEL_OFFSET_Y_DOTS', config_value='-8',
                                    config_type='integer'))
    db.session.commit()
    job = pqs.wydruk_probny('wysylka', {'type': 'user', 'id': 1})
    assert '^FO24,16^GB752,1152,4^FS' in job.zpl_payload


def test_wydruk_probny_etykiet_z_przesunieciami_etykiet_produktow(app, sygnaly):
    db.session.add_all([
        ProductionConfig(config_key='LABEL_PRINTER_OFFSET_LT', config_value='-10', config_type='integer'),
        ProductionConfig(config_key='LABEL_PRINTER_OFFSET_LS', config_value='100', config_type='integer'),
    ])
    db.session.commit()
    job = pqs.wydruk_probny('etykiety', {'type': 'user', 'id': 1})
    assert job.printer == 'etykiety'
    assert '^PW480' in job.zpl_payload and '^LT-10' in job.zpl_payload
    assert '^FO100,0^GB480,320,4^FS' in job.zpl_payload


def test_wydruk_probny_wymaga_admina(panel):
    assert panel.post('/production/api/print-test', json={'printer': 'wysylka'}).status_code == 401
    _zaloguj(panel, '2')
    assert panel.post('/production/api/print-test', json={'printer': 'wysylka'}).status_code == 403
    assert LabelPrintJob.query.count() == 0


def test_wydruk_probny_z_panelu(panel):
    _zaloguj(panel, '1')
    resp = panel.post('/production/api/print-test', json={'printer': 'wysylka'})
    assert resp.status_code == 200
    dane = resp.get_json()
    assert dane['success'] is True and 'drukarka paczek' in dane['message']
    job = LabelPrintJob.query.get(dane['job_id'])
    assert job.printer == 'wysylka' and job.requested_by_id == '1'


@pytest.mark.parametrize('cialo', [{}, {'printer': 'laserowa'}, {'printer': None}, {'printer': ['wysylka']}])
def test_wydruk_probny_nieznana_drukarka(panel, cialo):
    _zaloguj(panel, '1')
    resp = panel.post('/production/api/print-test', json=cialo)
    assert resp.status_code == 400
    assert resp.get_json()['success'] is False and 'drukark' in resp.get_json()['error'].lower()
    assert LabelPrintJob.query.count() == 0


@pytest.mark.parametrize('klucz', ['PACKAGE_LABEL_OFFSET_X_DOTS', 'PACKAGE_LABEL_OFFSET_Y_DOTS'])
def test_walidacja_przesuniecia(app, klucz):
    serwis = get_config_service()
    assert serwis.validate_config_batch({klucz: -8})['invalid'] == []
    assert serwis.validate_config_batch({klucz: 120})['invalid'] == []
    assert serwis.validate_config_batch({klucz: 121})['invalid'] != []
    assert serwis.validate_config_batch({klucz: -121})['invalid'] != []


def test_panel_zapisuje_przesuniecie(panel):
    _zaloguj(panel, '1')
    resp = panel.post('/production/api/update-configs',
                      json={'configs': {'PACKAGE_LABEL_OFFSET_Y_DOTS': -8}})
    assert resp.status_code == 200 and resp.get_json()['success'] is True
    wiersz = ProductionConfig.query.filter_by(config_key='PACKAGE_LABEL_OFFSET_Y_DOTS').one()
    assert wiersz.config_value == '-8'
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_druk_wydruk_probny.py`
Expected: FAIL — `ModuleNotFoundError: print_queue_service`; endpoint 404; walidacja przepuszcza 121; `update-configs` odrzuca klucz („Niepozwolone klucze konfiguracji”).

- [ ] **Step 3: Serwis**

Create `modules/production/services/print_queue_service.py`:

```python
# -*- coding: utf-8 -*-
"""
Kolejka wydruku dla obu drukarek (logistyka etap 4, spec 6.1).

`zakolejkuj_zpl` wkłada gotowy ZPL do prod_print_queue z nazwą drukarki — krok 4.2
użyje go do etykiet paczek. `wydruk_probny` służy do ustawienia drukarki z panelu
(Konfiguracja → Drukarka etykiet). Druk robi agent na komputerze hali; CRM tylko
kolejkuje i budzi agenta sygnałem.
"""
from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import LabelPrintJob
from modules.production.services import package_label, realtime_service
from modules.production.services.label_print_service import _load_config

logger = get_structured_logger('production.print_queue')

NAZWY_DRUKAREK = {
    LabelPrintJob.DRUKARKA_ETYKIETY: 'drukarka etykiet (60x40)',
    LabelPrintJob.DRUKARKA_WYSYLKA: 'drukarka paczek (100x150)',
}


class NieznanaDrukarka(ValueError):
    """Nazwa drukarki spoza LabelPrintJob.DRUKARKI."""


def _sprawdz_drukarke(drukarka):
    if not isinstance(drukarka, str) or drukarka not in LabelPrintJob.DRUKARKI:
        raise NieznanaDrukarka('Nieznana drukarka: %r' % (drukarka,))


def zakolejkuj_zpl(drukarka, zpl, kod, stanowisko, aktor,
                   baselinker_order_id=None, package_id=None):
    """Jedno zadanie ZPL w kolejce agenta. Flush (żeby było id), bez commita —
    commituje wywołujący razem ze swoją zmianą, a po commicie woła
    realtime_service.publish_print_signal (inaczej agent obudzi się przed
    zakończeniem transakcji i wróci z pustymi rękami)."""
    _sprawdz_drukarke(drukarka)
    job = LabelPrintJob(
        printer=drukarka,
        short_product_id=str(kod)[:20],
        package_id=package_id,
        baselinker_order_id=baselinker_order_id,
        zpl_payload=zpl,
        station_code=str(stanowisko)[:50],
        requested_by_type=str(aktor.get('type') or 'user')[:20],
        requested_by_id=str(aktor.get('id') if aktor.get('id') is not None else '0')[:100],
        status=LabelPrintJob.STATUS_PENDING,
    )
    db.session.add(job)
    db.session.flush()
    return job


def _zpl_probny_etykiet(offset_lt, offset_ls):
    """Etykieta próbna 60x40 z tymi samymi przesunięciami co etykieta produktu
    (label_print_service.generate_label_zpl): ^LT w pionie, offset_ls dodawany do x."""
    x = offset_ls
    return (
        '^XA\n^PW480\n^LL320\n^LT%d\n^LS0\n^CI0\n' % offset_lt
        + '^FO%d,0^GB480,320,4^FS\n' % x
        + '^FO%d,40^A0N,40,40^FDWYDRUK PROBNY^FS\n' % (x + 20)
        + '^FO%d,100^A0N,26,26^FDDrukarka etykiet 60x40^FS\n' % (x + 20)
        + '^FO%d,140^A0N,22,22^FDLT=%d LS=%d^FS\n' % (x + 20, offset_lt, offset_ls)
        + '^FO%d,190^BQN,2,4^FDLA,TEST^FS\n' % (x + 20)
        + '^XZ\n'
    )


def zpl_probny(drukarka):
    _sprawdz_drukarke(drukarka)
    if drukarka == LabelPrintJob.DRUKARKA_WYSYLKA:
        return package_label.generate_test_label_zpl(package_label.wczytaj_przesuniecie())
    cfg = _load_config()
    return _zpl_probny_etykiet(cfg['offset_lt'], cfg['offset_ls'])


def wydruk_probny(drukarka, aktor):
    """Etykieta próbna w kolejce wskazanej drukarki. Bierze ZAPISANE przesunięcia —
    niezapisane zmiany w panelu nie mają wpływu (panel o tym ostrzega)."""
    zpl = zpl_probny(drukarka)
    job = zakolejkuj_zpl(drukarka, zpl, 'TEST-' + drukarka, 'panel', aktor)
    db.session.commit()
    # Sygnał dopiero po commicie — patrz komentarz w label_print_service._enqueue_labels.
    realtime_service.publish_print_signal(1)
    logger.info('Wydruk próbny w kolejce', extra={'printer': drukarka, 'job_id': job.id})
    return job
```

- [ ] **Step 4: Walidacja zakresu**

W `config_service.py`, `_validate_config_value`, dopisz gałąź przed `elif key.endswith('_IPS') ...`:

```python
        elif key.startswith('PACKAGE_LABEL_OFFSET_') and config_type == 'integer':
            # Przesunięcie etykiety paczki (logistyka etap 4) — powyżej 15 mm to źle
            # założona rolka, a nie kalibracja; generator i tak przycina do ±120.
            przesuniecie = int(value)
            if not (-120 <= przesuniecie <= 120):
                raise ConfigError("Przesunięcie etykiety paczki musi być między -120 a 120 punktów "
                                  "(8 punktów = 1 mm)")
```

- [ ] **Step 5: Klucze i endpoint w `config_api.py`**

W `EXPECTED`, pod `'LABEL_PRINTER_AGENT_TOKEN': ...`:

```python
            # Drukarka paczek 100x150 (logistyka etap 4) — przesunięcie w punktach, 8 = 1 mm
            'PACKAGE_LABEL_OFFSET_X_DOTS':   ('printer',     0,                          'integer'),
            'PACKAGE_LABEL_OFFSET_Y_DOTS':   ('printer',     0,                          'integer'),
```

W `allowed_config_keys`, pod `'LABEL_PRINTER_USE_AGENT', 'LABEL_PRINTER_AGENT_TOKEN',`:

```python
            # Drukarka paczek — bez tego pola w UI istnieją, ale zapis wraca błędem.
            'PACKAGE_LABEL_OFFSET_X_DOTS', 'PACKAGE_LABEL_OFFSET_Y_DOTS',
```

Na końcu pliku (sprawdź, że `request`, `jsonify` i `current_user` są już importowane na górze — są używane przez `/update-configs`):

```python
@api_bp.route('/print-test', methods=['POST'])
@admin_required
def api_print_test():
    """
    POST /production/api/print-test  {"printer": "etykiety" | "wysylka"}

    Wydruk próbny z panelu Konfiguracja → Drukarka etykiet. Wkłada jedno zadanie do
    kolejki agenta druku — samą etykietę drukuje agent na komputerze hali.
    """
    from ...services import print_queue_service

    dane = request.get_json(silent=True) or {}
    drukarka = dane.get('printer')
    try:
        job = print_queue_service.wydruk_probny(
            drukarka, {'type': 'user', 'id': current_user.id})
    except print_queue_service.NieznanaDrukarka:
        return jsonify({
            'success': False,
            'error': 'Nieznana drukarka — wybierz drukarkę etykiet albo drukarkę paczek.',
        }), 400
    return jsonify({
        'success': True,
        'job_id': job.id,
        'message': 'Wydruk próbny w kolejce: %s. Etykieta wyjdzie, gdy agent druku pobierze zadanie.'
                   % print_queue_service.NAZWY_DRUKAREK[drukarka],
    }), 200
```

- [ ] **Step 6: Uruchom — ma przejść**

Run: `PYTEST tests/test_druk_wydruk_probny.py tests/test_config_service_set.py`
Expected: PASS. Jeśli `test_panel_zapisuje_przesuniecie` pada na `updated_by` (id użytkownika `'1'` jako tekst), sprawdź komunikat — SQLite przyjmuje tekst w kolumnie INTEGER, więc to nie powinno wystąpić; nie zmieniaj `update_multiple_configs`.

- [ ] **Step 7: Pełny pakiet**, potem **Commit**

```bash
git add modules/production/services/print_queue_service.py modules/production/routers/api/config_api.py modules/production/services/config_service.py tests/test_druk_wydruk_probny.py
git commit -m "feat(production): wydruk probny obu drukarek i przesuniecie etykiety paczki

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Panel Konfiguracja — przesunięcie drukarki paczek i przyciski „Wydruk próbny”

**Files:**
- Modify: `modules/production/templates/components/config-tab-content.html` (karta drukarki; nowe pozycje po `<!-- LABEL_PRINTER_AGENT_TOKEN -->`, przed zamknięciem `config-card-body`, ok. :1121)
- Modify: `modules/production/static/js/modules/config-module.js` (`defaultValues` :27, mapa pól :214–249, `updateFormField` :648–684, mapa odwrotna :780–812, metoda + funkcja globalna)
- Modify: `modules/production/templates/panel/dashboard.html:350` (wersja skryptu)
- Test: `tests/test_druk_panel_ui.py`

**Interfaces:**
- Consumes: `POST /production/api/print-test` i klucze `PACKAGE_LABEL_OFFSET_X_DOTS/Y_DOTS` (Task 4).
- Produces: pola `#package_label_offset_x`, `#package_label_offset_y`; `ConfigModule.wydrukProbny(drukarka)`; `window.wydrukProbny(drukarka)`.

Styl: dokładnie istniejący wzór `config-item` z tej karty (ikona, tytuł, `default-badge`, opis, meta, input + `config-reset-btn`) — bez nowego wyglądu. Przyciski „Wydruk próbny” w klasach `btn btn-outline-primary btn-sm` (jak inne przyciski akcji w panelu), z ikoną `fas fa-print`.

- [ ] **Step 1: Test, który padnie**

Create `tests/test_druk_panel_ui.py`:

```python
# -*- coding: utf-8 -*-
"""Panel Konfiguracja: drukarka paczek (logistyka etap 4, krok 4.1). Testy tekstu źródła —
repo nie ma runnera JS, a szablon renderuje się tylko w pełnej apce."""
import os

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SZABLON = os.path.join(KORZEN, 'modules', 'production', 'templates', 'components', 'config-tab-content.html')
SKRYPT = os.path.join(KORZEN, 'modules', 'production', 'static', 'js', 'modules', 'config-module.js')
PANEL = os.path.join(KORZEN, 'modules', 'production', 'templates', 'panel', 'dashboard.html')
POLA = (('PACKAGE_LABEL_OFFSET_X_DOTS', 'package_label_offset_x'),
        ('PACKAGE_LABEL_OFFSET_Y_DOTS', 'package_label_offset_y'))


def _czytaj(sciezka):
    with open(sciezka, encoding='utf-8') as plik:
        return plik.read()


def test_pola_przesuniecia_w_szablonie():
    html = _czytaj(SZABLON)
    for klucz, pole in POLA:
        assert 'id="%s"' % pole in html
        assert "configChanged('%s', parseInt(this.value))" % klucz in html
        assert "resetToDefault('%s')" % klucz in html
        assert 'config_groups.printer.%s.value|default(0)' % klucz in html
    assert html.count('min="-120" max="120"') >= 2


def test_przyciski_wydruku_probnego():
    html = _czytaj(SZABLON)
    assert "wydrukProbny('etykiety')" in html and "wydrukProbny('wysylka')" in html


def test_skrypt_zna_pola_i_wydruk():
    js = _czytaj(SKRYPT)
    for klucz, pole in POLA:
        assert "'%s': 0" % klucz in js                     # defaultValues
        assert "'%s': '%s'" % (pole, klucz) in js          # odczyt wartości z formularza
        assert js.count("'%s': '%s'" % (klucz, pole)) == 2  # updateFormField + mapa odwrotna
    assert "fetch('/production/api/print-test'" in js
    assert 'async wydrukProbny(drukarka)' in js
    assert 'window.wydrukProbny = function' in js


def test_nowa_wersja_skryptu_konfiguracji():
    assert "js/modules/config-module.js') }}?v=20260930" in _czytaj(PANEL)
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_druk_panel_ui.py`
Expected: FAIL (brak pól i funkcji).

- [ ] **Step 3: Szablon**

W `config-tab-content.html`, po bloku `<!-- LABEL_PRINTER_AGENT_TOKEN -->` (po jego zamykającym `</div>` pozycji `config-item`, przed zamknięciem `config-card-body` karty drukarki) wstaw:

```html
                <!-- PACKAGE_LABEL_OFFSET_X_DOTS (logistyka etap 4) -->
                <div class="config-item">
                    <div class="config-item-row">
                        <div class="config-item-main">
                            <div class="config-item-header">
                                <div class="config-item-icon">
                                    <i class="fas fa-arrows-alt-h"></i>
                                </div>
                                <div class="config-item-info">
                                    <h5 class="config-item-title">Drukarka paczek: przesunięcie poziome <span class="default-badge">domyślnie: 0</span></h5>
                                    <p class="config-item-description">Przesuwa całą etykietę paczki 100×150 w punktach (8 punktów = 1 mm). Dodatnie w prawo, ujemne w lewo. Zakres od −120 do 120.</p>
                                </div>
                            </div>
                            <div class="config-item-meta">
                                <div class="config-item-meta-item">
                                    <i class="fas fa-user"></i>
                                    <span>Ostatnio: {{ config_groups.printer.PACKAGE_LABEL_OFFSET_X_DOTS.updated_by|default('System') }}</span>
                                </div>
                                <div class="config-item-meta-item">
                                    <i class="fas fa-clock"></i>
                                    <span>{{ config_groups.printer.PACKAGE_LABEL_OFFSET_X_DOTS.updated_at|default('---') }}</span>
                                </div>
                            </div>
                        </div>
                        <div class="config-item-controls">
                            <div class="config-control-wrapper">
                                <div class="config-control">
                                    <input type="number" class="form-control" id="package_label_offset_x"
                                           value="{{ config_groups.printer.PACKAGE_LABEL_OFFSET_X_DOTS.value|default(0) }}"
                                           min="-120" max="120"
                                           oninput="configChanged('PACKAGE_LABEL_OFFSET_X_DOTS', parseInt(this.value))">
                                </div>
                                <button class="config-reset-btn" onclick="resetToDefault('PACKAGE_LABEL_OFFSET_X_DOTS')" title="Przywróć domyślne">
                                    <i class="fas fa-undo"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- PACKAGE_LABEL_OFFSET_Y_DOTS (logistyka etap 4) -->
                <div class="config-item">
                    <div class="config-item-row">
                        <div class="config-item-main">
                            <div class="config-item-header">
                                <div class="config-item-icon">
                                    <i class="fas fa-arrows-alt-v"></i>
                                </div>
                                <div class="config-item-info">
                                    <h5 class="config-item-title">Drukarka paczek: przesunięcie pionowe <span class="default-badge">domyślnie: 0</span></h5>
                                    <p class="config-item-description">Dodatnie w dół, ujemne w górę (8 punktów = 1 mm). Zakres od −120 do 120. Najpierw skalibruj drukarkę (agent druku: <code>--kalibruj wysylka</code>).</p>
                                </div>
                            </div>
                            <div class="config-item-meta">
                                <div class="config-item-meta-item">
                                    <i class="fas fa-user"></i>
                                    <span>Ostatnio: {{ config_groups.printer.PACKAGE_LABEL_OFFSET_Y_DOTS.updated_by|default('System') }}</span>
                                </div>
                                <div class="config-item-meta-item">
                                    <i class="fas fa-clock"></i>
                                    <span>{{ config_groups.printer.PACKAGE_LABEL_OFFSET_Y_DOTS.updated_at|default('---') }}</span>
                                </div>
                            </div>
                        </div>
                        <div class="config-item-controls">
                            <div class="config-control-wrapper">
                                <div class="config-control">
                                    <input type="number" class="form-control" id="package_label_offset_y"
                                           value="{{ config_groups.printer.PACKAGE_LABEL_OFFSET_Y_DOTS.value|default(0) }}"
                                           min="-120" max="120"
                                           oninput="configChanged('PACKAGE_LABEL_OFFSET_Y_DOTS', parseInt(this.value))">
                                </div>
                                <button class="config-reset-btn" onclick="resetToDefault('PACKAGE_LABEL_OFFSET_Y_DOTS')" title="Przywróć domyślne">
                                    <i class="fas fa-undo"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Wydruk próbny (logistyka etap 4) -->
                <div class="config-item">
                    <div class="config-item-row">
                        <div class="config-item-main">
                            <div class="config-item-header">
                                <div class="config-item-icon">
                                    <i class="fas fa-print"></i>
                                </div>
                                <div class="config-item-info">
                                    <h5 class="config-item-title">Wydruk próbny</h5>
                                    <p class="config-item-description">Wysyła etykietę testową do kolejki agenta druku. Na drukarce paczek ramka powinna mieć ok. 3 mm od każdej krawędzi; jeśli nie, popraw przesunięcie, zapisz zmiany i drukuj ponownie.</p>
                                </div>
                            </div>
                        </div>
                        <div class="config-item-controls">
                            <div class="config-control-wrapper">
                                <button type="button" class="btn btn-outline-primary btn-sm" onclick="wydrukProbny('etykiety')">
                                    <i class="fas fa-print me-1"></i>Drukarka etykiet (60×40)
                                </button>
                                <button type="button" class="btn btn-outline-primary btn-sm" onclick="wydrukProbny('wysylka')">
                                    <i class="fas fa-print me-1"></i>Drukarka paczek (100×150)
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
```

- [ ] **Step 4: Skrypt**

W `config-module.js`:

1. `this.defaultValues` — dopisz przed `'DAILY_REPORT_RECIPIENTS': ''` (z przecinkiem po poprzednim wpisie):
```js
            // Drukarka paczek (logistyka etap 4) — zgodne z EXPECTED w config_api.py
            'PACKAGE_LABEL_OFFSET_X_DOTS': 0,
            'PACKAGE_LABEL_OFFSET_Y_DOTS': 0,
```
2. Mapa pól w odczycie wartości (obok `'label_printer_agent_token': 'LABEL_PRINTER_AGENT_TOKEN'`, pamiętaj o przecinku):
```js
                'package_label_offset_x': 'PACKAGE_LABEL_OFFSET_X_DOTS',
                'package_label_offset_y': 'PACKAGE_LABEL_OFFSET_Y_DOTS',
```
3. W `updateFormField` i w mapie odwrotnej (obie mają `'LABEL_PRINTER_AGENT_TOKEN': 'label_printer_agent_token',`) dopisz pod tym wpisem:
```js
            'PACKAGE_LABEL_OFFSET_X_DOTS': 'package_label_offset_x',
            'PACKAGE_LABEL_OFFSET_Y_DOTS': 'package_label_offset_y',
```
4. Metoda klasy — wstaw przed sekcją `// CACHE MANAGEMENT`:
```js
    /**
     * Wydruk próbny na drukarce etykiet albo paczek (logistyka etap 4).
     * Serwer bierze ZAPISANE przesunięcia, więc przy niezapisanej zmianie ostrzegamy.
     */
    async wydrukProbny(drukarka) {
        const niezapisane = Object.keys(this.pendingChanges || {})
            .some(klucz => klucz.startsWith('PACKAGE_LABEL_OFFSET_') || klucz.startsWith('LABEL_PRINTER_OFFSET_'));
        if (niezapisane) {
            this.showToast('Masz niezapisane przesunięcie — wydruk próbny użyje zapisanych wartości.', 'info');
        }
        try {
            const response = await fetch('/production/api/print-test', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({ printer: drukarka })
            });
            const result = await response.json();
            if (!response.ok || !result.success) {
                throw new Error(result.error || `HTTP ${response.status}`);
            }
            this.showToast(result.message, 'success');
        } catch (error) {
            console.error('[ConfigModule] Wydruk próbny:', error);
            this.showToast(`Wydruk próbny nie poszedł: ${error.message}`, 'error');
        }
    }

```
5. Funkcja globalna — pod `window.clearCache = ...`:
```js
window.wydrukProbny = function (drukarka) {
    if (window.configModule) {
        window.configModule.wydrukProbny(drukarka);
    }
};
```

W `templates/panel/dashboard.html:350` zmień `config-module.js') }}?v=20260410` na `config-module.js') }}?v=20260930`.

- [ ] **Step 5: Uruchom — ma przejść**

Run: `PYTEST tests/test_druk_panel_ui.py`
Expected: PASS.

- [ ] **Step 6: Pełny pakiet**, potem **Commit**

```bash
git add modules/production/templates/components/config-tab-content.html modules/production/static/js/modules/config-module.js modules/production/templates/panel/dashboard.html tests/test_druk_panel_ui.py
git commit -m "feat(production): przesuniecie drukarki paczek i wydruk probny w panelu

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Agent druku — dwie drukarki, kolejka Windows, kalibracja

**Files:**
- Modify: `tools/print_agent/print_agent.py`
- Modify: `tools/print_agent/config.example.ini`, `tools/print_agent/README.md`
- Modify: `tests/test_print_agent_sse.py` (4 atrapy `fetch_jobs`: linie ok. :221, :247, :274, :293)
- Test: `tests/test_print_agent_drukarki.py`

**Interfaces:**
- Consumes: `GET /api/print-agent/jobs?limit=N&printers=<nazwa>` z polem `printer` w zadaniach (Task 2).
- Produces:
  - `wczytaj_drukarki(cp: ConfigParser) -> Dict[str, dict]` — drukarka TCP: `{'nazwa', 'type': 'tcp', 'ip', 'port', 'timeout'}`, Windows: `{'nazwa', 'type': 'windows', 'name', 'timeout'}`; błąd konfiguracji = `ValueError`.
  - `load_config(path)` zwraca `'printers'` zamiast `printer_ip/printer_port/printer_timeout`.
  - `fetch_jobs(cfg, drukarka: str)`, `send_to_printer(drukarka: dict, zpl: str)`, `wyslij_surowe(drukarka: dict, dane: bytes)`, `query_printer_status(drukarka)`, `log_printer_status(drukarka)`, `kalibruj(cfg, nazwa)`, `_drukarki(cfg)`, `_winspool()`.
  - CLI: `python print_agent.py --kalibruj [nazwa]` (domyślnie `wysylka`), `--drukarka` pyta każdą drukarkę TCP.

- [ ] **Step 1: Test, który padnie**

Create `tests/test_print_agent_drukarki.py`:

```python
# -*- coding: utf-8 -*-
"""Agent druku na dwie drukarki (logistyka etap 4, krok 4.1, spec 6.2)."""
import configparser
import importlib.util
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
AGENT_DIR = os.path.join(REPO_ROOT, 'tools', 'print_agent')

_spec = importlib.util.spec_from_file_location('print_agent_drukarki', os.path.join(AGENT_DIR, 'print_agent.py'))
print_agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(print_agent)

TCP = {'nazwa': 'etykiety', 'type': 'tcp', 'ip': '127.0.0.1', 'port': 9100, 'timeout': 1}
WIN = {'nazwa': 'wysylka', 'type': 'windows', 'name': 'Xprinter XP-410B', 'timeout': 1}


def _cp(tekst):
    cp = configparser.ConfigParser()
    cp.read_string(tekst)
    return cp


def _cfg(**drukarki):
    return {'jobs_limit': 10, 'request_timeout': 5, 'printers': drukarki}


def _zadanie(i, drukarka=None):
    z = {'id': i, 'short_product_id': 'X', 'zpl_payload': '^XA%d^XZ' % i, 'requested_at': None}
    if drukarka:
        z['printer'] = drukarka
    return z


# --- konfiguracja ---

def test_stara_sekcja_printer_to_etykiety():
    d = print_agent.wczytaj_drukarki(_cp('[printer]\nip = 10.0.0.5\nport = 9100\nsend_timeout_seconds = 7\n'))
    assert d == {'etykiety': {'nazwa': 'etykiety', 'type': 'tcp', 'ip': '10.0.0.5',
                              'port': 9100, 'timeout': 7}}


def test_dwie_drukarki_tcp_i_windows():
    d = print_agent.wczytaj_drukarki(_cp(
        '[printer:etykiety]\nip = 10.0.0.5\n'
        '[printer:wysylka]\ntype = windows\nname = Xprinter XP-410B\n'))
    assert d['etykiety'] == {'nazwa': 'etykiety', 'type': 'tcp', 'ip': '10.0.0.5', 'port': 9100, 'timeout': 15}
    assert d['wysylka'] == {'nazwa': 'wysylka', 'type': 'windows', 'name': 'Xprinter XP-410B', 'timeout': 15}


def test_nowa_sekcja_wygrywa_ze_stara():
    d = print_agent.wczytaj_drukarki(_cp('[printer]\nip = 1.1.1.1\n[printer:etykiety]\nip = 2.2.2.2\n'))
    assert d['etykiety']['ip'] == '2.2.2.2'


@pytest.mark.parametrize('tekst', [
    '[crm]\nurl = x\n',                                     # brak drukarek
    '[printer:wysylka]\ntype = usb\nname = X\n',            # nieznany typ
    '[printer:wysylka]\ntype = windows\n',                  # brak nazwy kolejki
    '[printer:wysylka]\ntype = tcp\n',                      # brak ip
    '[printer:wysylka]\ntype = windows\nname =   \n',       # pusta nazwa kolejki
    '[printer:]\nip = 1.1.1.1\n',                           # brak nazwy drukarki
    '[printer:etykiety]\nip = 1.1.1.1\nport = abc\n',       # port nie jest liczbą
])
def test_bledna_konfiguracja_drukarek(tekst):
    with pytest.raises(ValueError):
        print_agent.wczytaj_drukarki(_cp(tekst))


def test_wzor_konfiguracji_jest_poprawny():
    cfg = print_agent.load_config(os.path.join(AGENT_DIR, 'config.example.ini'))
    assert set(cfg['printers']) == {'etykiety'}
    assert 'printer_ip' not in cfg


def test_zapytanie_o_zadania_podaje_drukarke(monkeypatch):
    adresy = []
    monkeypatch.setattr(print_agent, 'crm_request',
                        lambda metoda, url, token, **k: (adresy.append(url), {'jobs': []})[1])
    print_agent.fetch_jobs({'crm_url': 'https://crm', 'jobs_limit': 10, 'token': 't',
                            'request_timeout': 5}, 'wysylka')
    assert adresy == ['https://crm/api/print-agent/jobs?limit=10&printers=wysylka']


# --- kierowanie zadań ---

def test_kazda_drukarka_pobiera_swoja_kolejke(monkeypatch):
    kolejki = {'etykiety': [_zadanie(1, 'etykiety')], 'wysylka': [_zadanie(2, 'wysylka')]}
    pobrania, wyslane = [], []
    monkeypatch.setattr(print_agent, 'fetch_jobs',
                        lambda c, n: (pobrania.append(n), {'jobs': kolejki[n]})[1])
    monkeypatch.setattr(print_agent, 'send_to_printer', lambda d, z: wyslane.append((d['nazwa'], z)))
    monkeypatch.setattr(print_agent, 'ack_jobs', lambda c, r: {'updated': len(r)})
    assert print_agent.run_once(_cfg(etykiety=TCP, wysylka=WIN)) is True
    assert pobrania == ['etykiety', 'wysylka']
    assert wyslane == [('etykiety', '^XA1^XZ'), ('wysylka', '^XA2^XZ')]


def test_martwa_drukarka_paczek_nie_wstrzymuje_etykiet(monkeypatch):
    """Pełna kolejka martwej drukarki paczek nie może zasłonić etykiet produktów."""
    kolejki = {'wysylka': [_zadanie(i, 'wysylka') for i in range(10)],
               'etykiety': [_zadanie(100, 'etykiety')]}
    wyslane, potwierdzone = [], []

    def druk(d, z):
        if d['nazwa'] == 'wysylka':
            raise OSError('drukarka paczek nie odpowiada')
        wyslane.append(z)

    monkeypatch.setattr(print_agent, 'fetch_jobs', lambda c, n: {'jobs': kolejki[n]})
    monkeypatch.setattr(print_agent, 'send_to_printer', druk)
    monkeypatch.setattr(print_agent, 'log_printer_status', lambda d: None)
    monkeypatch.setattr(print_agent, 'ack_jobs', lambda c, r: (potwierdzone.extend(r), {'updated': len(r)})[1])
    stan = {}
    print_agent.run_once(_cfg(wysylka=WIN, etykiety=TCP), stan=stan)
    assert wyslane == ['^XA100^XZ']
    assert [r['id'] for r in potwierdzone if not r['success']] == [0], 'jedna próba na martwej drukarce'
    assert stan.get('drukarka_padla') is True


def test_stary_serwer_bez_pola_printer(monkeypatch):
    """Serwer sprzed etapu 4 ignoruje ?printers= i nie podaje drukarki: każde zadanie
    to etykieta produktu — drukarka paczek nie może jej wydrukować ani potwierdzić."""
    wyslane, potwierdzone = [], []
    monkeypatch.setattr(print_agent, 'fetch_jobs', lambda c, n: {'jobs': [_zadanie(5)]})
    monkeypatch.setattr(print_agent, 'send_to_printer', lambda d, z: wyslane.append(d['nazwa']))
    monkeypatch.setattr(print_agent, 'ack_jobs', lambda c, r: (potwierdzone.extend(r), {'updated': len(r)})[1])
    print_agent.run_once(_cfg(etykiety=TCP, wysylka=WIN))
    assert wyslane == ['etykiety']
    assert [r['id'] for r in potwierdzone] == [5]


def test_cudza_pelna_porcja_nie_zapetla_oprozniania(monkeypatch):
    pobrania = []
    monkeypatch.setattr(print_agent, 'fetch_jobs',
                        lambda c, n: (pobrania.append(n), {'jobs': [_zadanie(i) for i in range(10)]})[1])
    monkeypatch.setattr(print_agent, 'send_to_printer', lambda d, z: None)
    monkeypatch.setattr(print_agent, 'ack_jobs', lambda c, r: {'updated': len(r)})
    print_agent.run_once(_cfg(wysylka=WIN))
    assert pobrania == ['wysylka'], 'porcja z samymi cudzymi zadaniami kończy cykl drukarki'


def test_nieznana_drukarka_w_konfiguracji_bez_pola_printers():
    """Słownik bez 'printers' (starsze wywołania, testy SSE) = jedna drukarka TCP 'etykiety'."""
    d = print_agent._drukarki({'printer_ip': '10.0.0.9', 'printer_port': 9100, 'printer_timeout': 3})
    assert d == {'etykiety': {'nazwa': 'etykiety', 'type': 'tcp', 'ip': '10.0.0.9', 'port': 9100, 'timeout': 3}}


# --- kolejka Windows ---

class _FakeWinspool:
    def __init__(self, otworz=True, zapisz_ile=None):
        self.otworz = otworz
        self.zapisz_ile = zapisz_ile
        self.wywolania = []
        self.dane = None

    def OpenPrinterW(self, nazwa, uchwyt, _domyslne):
        self.wywolania.append(('open', nazwa))
        if not self.otworz:
            return 0
        uchwyt._obj.value = 42
        return 1

    def StartDocPrinterW(self, uchwyt, poziom, info):
        self.wywolania.append(('doc', info._obj.pDatatype))
        return 7

    def StartPagePrinter(self, uchwyt):
        self.wywolania.append(('page',))
        return 1

    def WritePrinter(self, uchwyt, bufor, dlugosc, zapisane):
        self.dane = bufor.raw[:dlugosc]
        zapisane._obj.value = dlugosc if self.zapisz_ile is None else self.zapisz_ile
        self.wywolania.append(('write', dlugosc))
        return 1

    def EndPagePrinter(self, uchwyt):
        self.wywolania.append(('endpage',))
        return 1

    def EndDocPrinter(self, uchwyt):
        self.wywolania.append(('enddoc',))
        return 1

    def ClosePrinter(self, uchwyt):
        self.wywolania.append(('close',))
        return 1


def test_windows_wysyla_surowe_bajty(monkeypatch):
    fake = _FakeWinspool()
    monkeypatch.setattr(print_agent, '_winspool', lambda: fake)
    print_agent.send_to_printer(WIN, '^XA^XZ')
    assert fake.dane == b'^XA^XZ'
    assert fake.wywolania == [('open', 'Xprinter XP-410B'), ('doc', 'RAW'), ('page',), ('write', 6),
                              ('endpage',), ('enddoc',), ('close',)]


def test_windows_brak_kolejki_to_blad_drukarki(monkeypatch):
    fake = _FakeWinspool(otworz=False)
    monkeypatch.setattr(print_agent, '_winspool', lambda: fake)
    with pytest.raises(OSError) as blad:
        print_agent.send_to_printer(WIN, '^XA^XZ')
    assert 'Xprinter XP-410B' in str(blad.value)
    assert ('close',) not in fake.wywolania


def test_windows_niepelny_zapis_to_blad_i_zamyka_kolejke(monkeypatch):
    fake = _FakeWinspool(zapisz_ile=2)
    monkeypatch.setattr(print_agent, '_winspool', lambda: fake)
    with pytest.raises(OSError):
        print_agent.send_to_printer(WIN, '^XA^XZ')
    assert fake.wywolania[-2:] == [('enddoc',), ('close',)]


def test_windows_bez_zapytan_o_stan():
    wyniki = print_agent.query_printer_status(WIN)
    assert len(wyniki) == 1 and 'Windows' in wyniki[0][2]


# --- kalibracja ---

def test_kalibracja_wysyla_gapdetect(monkeypatch):
    wyslane = []
    monkeypatch.setattr(print_agent, 'wyslij_surowe', lambda d, b: wyslane.append((d['nazwa'], b)))
    print_agent.kalibruj(_cfg(wysylka=WIN), 'wysylka')
    assert wyslane == [('wysylka', b'GAPDETECT\r\n')]


def test_kalibracja_nieznanej_drukarki():
    with pytest.raises(ValueError):
        print_agent.kalibruj(_cfg(wysylka=WIN), 'etykiety')
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_print_agent_drukarki.py`
Expected: FAIL — `AttributeError: ... has no attribute 'wczytaj_drukarki'` itd.

- [ ] **Step 3: Importy i drukarki w konfiguracji**

W `print_agent.py`: do importów dopisz `import ctypes` (obok `import configparser`) i zmień `from urllib.parse import urlsplit` na `from urllib.parse import quote, urlsplit`. W docstringu modułu zamień zdanie „Print agent — drukuje zadania ZPL z kolejki CRM na drukarce w LAN.” na „Print agent — drukuje zadania ZPL z kolejki CRM na drukarkach w LAN albo podpiętych do tego komputera (kolejka wydruku Windows).”, a w linii „Uwaga: stdlib only (…)” dopisz `ctypes` do listy.

Nad `# === Config ===` wstaw:

```python
# === Drukarki ===
# Nazwy są wspólne z CRM (kolumna prod_print_queue.printer, logistyka etap 4):
# 'etykiety' = etykiety produktów 60x40, 'wysylka' = etykiety paczek 100x150.
DRUKARKA_DOMYSLNA = 'etykiety'
TYPY_POLACZENIA = ('tcp', 'windows')
PREFIKS_SEKCJI_DRUKARKI = 'printer:'


def _drukarka_z_sekcji(cp, sekcja, nazwa):
    typ = cp.get(sekcja, 'type', fallback='tcp').strip().lower()
    if typ not in TYPY_POLACZENIA:
        raise ValueError(f"[{sekcja}] type = {typ!r} — dozwolone: {', '.join(TYPY_POLACZENIA)}")
    try:
        drukarka = {'nazwa': nazwa, 'type': typ}
        if typ == 'tcp':
            drukarka['ip'] = cp.get(sekcja, 'ip').strip()
            drukarka['port'] = cp.getint(sekcja, 'port', fallback=9100)
        else:
            drukarka['name'] = cp.get(sekcja, 'name').strip()
        drukarka['timeout'] = cp.getint(sekcja, 'send_timeout_seconds', fallback=15)
    except configparser.Error as e:
        raise ValueError(f"[{sekcja}] {e}") from e
    if not (drukarka.get('ip') or drukarka.get('name')):
        raise ValueError(f"[{sekcja}] pusty adres drukarki (ip albo name)")
    return drukarka


def wczytaj_drukarki(cp):
    """Drukarki z config.ini: sekcje [printer:<nazwa>]. Stara sekcja [printer]
    (config.ini sprzed etapu 4 stoi na hubie i nikt go nie podmieni przy
    aktualizacji) działa dalej jako drukarka 'etykiety'."""
    drukarki = {}
    for sekcja in cp.sections():
        if not sekcja.startswith(PREFIKS_SEKCJI_DRUKARKI):
            continue
        nazwa = sekcja[len(PREFIKS_SEKCJI_DRUKARKI):].strip()
        if not nazwa:
            raise ValueError(f"[{sekcja}] brak nazwy drukarki po 'printer:'")
        drukarki[nazwa] = _drukarka_z_sekcji(cp, sekcja, nazwa)
    if DRUKARKA_DOMYSLNA not in drukarki and cp.has_section('printer'):
        drukarki[DRUKARKA_DOMYSLNA] = _drukarka_z_sekcji(cp, 'printer', DRUKARKA_DOMYSLNA)
    if not drukarki:
        raise ValueError("Brak drukarek w config.ini — dodaj sekcję [printer:etykiety] "
                         "albo [printer:wysylka] (wzór w config.example.ini)")
    return drukarki


def _drukarki(cfg):
    """Drukarki z konfiguracji. Słownik bez 'printers' (starsze wywołania i testy)
    to jedna drukarka TCP 'etykiety' z dawnych kluczy printer_*."""
    if cfg.get('printers'):
        return cfg['printers']
    return {DRUKARKA_DOMYSLNA: {'nazwa': DRUKARKA_DOMYSLNA, 'type': 'tcp', 'ip': cfg['printer_ip'],
                                'port': cfg.get('printer_port', 9100),
                                'timeout': cfg.get('printer_timeout', 15)}}


def _opis_drukarki(drukarka):
    if drukarka['type'] == 'windows':
        return f"kolejka Windows „{drukarka['name']}”"
    return f"{drukarka['ip']}:{drukarka['port']}"
```

W `load_config` usuń trzy linie `'printer_ip': ...`, `'printer_port': ...`, `'printer_timeout': ...` i w ich miejsce wstaw:

```python
        'printers': wczytaj_drukarki(cp),
```

- [ ] **Step 4: Pobieranie zadań i druk**

Zamień `fetch_jobs`:

```python
def fetch_jobs(cfg, drukarka):
    """Zadania jednej drukarki. Każda drukarka ma własną kolejkę (FIFO), więc
    martwa drukarka paczek z pełną kolejką nie zasłania zadań drukarki etykiet."""
    url = (f"{cfg['crm_url']}/api/print-agent/jobs?limit={cfg['jobs_limit']}"
           f"&printers={quote(drukarka)}")
    return crm_request('GET', url, cfg['token'], timeout=cfg['request_timeout'])
```

Zamień blok `# === Printer (TCP) ===` + `send_to_printer` na:

```python
# === Printer (TCP albo kolejka Windows) ===
def wyslij_surowe(drukarka, dane):
    """Surowe bajty (ZPL/TSPL) do drukarki. Każdy błąd to OSError — pętla druku
    traktuje obie drogi tak samo."""
    if drukarka['type'] == 'windows':
        _drukuj_przez_windows(drukarka['name'], dane)
        return
    with socket.create_connection((drukarka['ip'], drukarka['port']),
                                  timeout=drukarka['timeout']) as sock:
        sock.sendall(dane)


def send_to_printer(drukarka, zpl):
    wyslij_surowe(drukarka, zpl.encode('utf-8'))


class _DocInfo1(ctypes.Structure):
    """DOC_INFO_1W z winspool.h (napisy UTF-16)."""
    _fields_ = [('pDocName', ctypes.c_wchar_p),
                ('pOutputFile', ctypes.c_wchar_p),
                ('pDatatype', ctypes.c_wchar_p)]


def _winspool():
    """Bufor wydruku Windows. Osobna funkcja, żeby testy (Linux) mogły go podmienić."""
    return ctypes.WinDLL('winspool.drv', use_last_error=True)


def _ostatni_blad():
    return getattr(ctypes, 'get_last_error', lambda: 0)()


def _drukuj_przez_windows(nazwa, dane):
    """Surowe bajty do kolejki wydruku Windows z typem danych RAW — sterownik ich nie
    przerabia, drukarka dostaje ZPL jak po sieci. Tak drukuje drukarka podpięta przez
    USB (sprawdzone 30.09.2026 na Xprinter XP-410B)."""
    ws = _winspool()
    uchwyt = ctypes.c_void_p()
    if not ws.OpenPrinterW(nazwa, ctypes.byref(uchwyt), None):
        raise OSError(f"Nie mogę otworzyć kolejki Windows „{nazwa}” (błąd {_ostatni_blad()}) — "
                      "sprawdź nazwę w Ustawienia → Drukarki")
    try:
        info = _DocInfo1('WoodPower CRM', None, 'RAW')
        if not ws.StartDocPrinterW(uchwyt, 1, ctypes.byref(info)):
            raise OSError(f"Kolejka „{nazwa}” nie przyjęła dokumentu (błąd {_ostatni_blad()})")
        try:
            ws.StartPagePrinter(uchwyt)
            bufor = ctypes.create_string_buffer(dane, len(dane))
            zapisane = ctypes.c_uint32(0)
            if (not ws.WritePrinter(uchwyt, bufor, len(dane), ctypes.byref(zapisane))
                    or zapisane.value != len(dane)):
                raise OSError(f"Kolejka „{nazwa}” przyjęła {zapisane.value} z {len(dane)} bajtów "
                              f"(błąd {_ostatni_blad()})")
            ws.EndPagePrinter(uchwyt)
        finally:
            ws.EndDocPrinter(uchwyt)
    finally:
        ws.ClosePrinter(uchwyt)
```

W `query_printer_status(cfg)` zmień sygnaturę na `query_printer_status(drukarka)`, na początku funkcji dodaj:

```python
    if drukarka['type'] == 'windows':
        return [('-', 'kolejka Windows',
                 'zapytań o stan nie wysyłamy przez kolejkę Windows — sprawdź drukarkę '
                 'w Ustawienia → Drukarki (papier, pokrywa, zasilanie)')]
```

a w `socket.create_connection((cfg['printer_ip'], cfg['printer_port']), ...)` użyj `(drukarka['ip'], drukarka['port'])`.

Zamień `log_printer_status`:

```python
def log_printer_status(drukarka):
    """Wypytuje drukarkę i wypisuje odpowiedzi do konsoli oraz logu błędów."""
    warn(f"Pytam drukarkę {drukarka['nazwa']} ({_opis_drukarki(drukarka)}) o stan...")
    linie = []
    for komenda, opis, odpowiedz in query_printer_status(drukarka):
        info(f"  {komenda} ({opis}): {odpowiedz}")
        linie.append(f"{komenda}={odpowiedz}")
    err_logger.error(f"Stan drukarki {drukarka['nazwa']} po nieudanym wydruku: " + " | ".join(linie))
```

W `print_banner` zamień linię `info(f"Drukarka:       {cfg['printer_ip']}:{cfg['printer_port']}")` na:

```python
    for nazwa, drukarka in _drukarki(cfg).items():
        info(f"Drukarka {nazwa + ':':<9}  {_opis_drukarki(drukarka)}")
```

- [ ] **Step 5: Pętla — osobna kolejka na drukarkę**

Zamień `run_once` (zachowaj cały dotychczasowy docstring, dopisując na końcu akapit poniżej) i `_process_one_batch`:

```python
def run_once(cfg, signal_at=None, stan=None):
    """<dotychczasowy docstring bez zmian>

    Od etapu 4 logistyki każda drukarka ma własną kolejkę i opróżniamy je po kolei —
    martwa drukarka paczek z pełną kolejką nie zasłania etykiet produktów. Błąd
    komunikacji z CRM przerywa cały cykl (dotyczy wszystkich drukarek naraz).
    """
    for nazwa, drukarka in _drukarki(cfg).items():
        if not _oproznij_drukarke(cfg, nazwa, drukarka, signal_at, stan):
            return False
    return True


def _oproznij_drukarke(cfg, nazwa, drukarka, signal_at=None, stan=None):
    for _ in range(_MAX_BATCHES_PER_CYCLE):
        wynik = _process_one_batch(cfg, nazwa, drukarka, signal_at, stan=stan)
        if wynik != 'more':
            return wynik == 'ok'
        # Pełna porcja = w kolejce może czekać więcej. Dociągamy od razu,
        # zamiast czekać na następny sygnał albo na zapasowy polling.
    warn(f"[{nazwa}] Przerwano opróżnianie kolejki po {_MAX_BATCHES_PER_CYCLE} porcjach — "
         "reszta pójdzie następnym cyklem")
    return True


def _process_one_batch(cfg, nazwa, drukarka, signal_at=None, stan=None):
    """Jedna porcja zadań jednej drukarki. Zwraca 'ok' | 'more' (porcja była pełna) | 'error'."""
    try:
        data = fetch_jobs(cfg, nazwa)
    except HTTPError as e:
        if e.code == 401:
            log_error("401 Unauthorized z CRM — sprawdź token w panelu. Czekam 60s.")
            time.sleep(60)
            return 'error'
        log_error(f"CRM HTTP {e.code}: {e.reason}", exc=e)
        return 'error'
    except (URLError, TimeoutError, OSError) as e:
        log_error(f"Błąd sieci do CRM: {e}", exc=e)
        return 'error'

    jobs = data.get('jobs', [])
    if not jobs:
        return 'ok'  # cisza w logach przy braku zadań

    info(f"[{nazwa}] Pobrano {len(jobs)} zadań → drukuję...")
    results = []
    drukarka_padla = False
    cudze = 0
    for j in jobs:
        # Serwer sprzed etapu 4 ignoruje ?printers= i nie podaje drukarki — wtedy
        # każde zadanie to etykieta produktu. Cudzych zadań nie drukujemy ani nie
        # potwierdzamy: zostają `pending` dla właściwej drukarki.
        if (j.get('printer') or DRUKARKA_DOMYSLNA) != nazwa:
            cudze += 1
            continue
        timing = _describe_timing(signal_at, j.get('requested_at'))
        if drukarka_padla:
            # Nie dobijamy się do martwej drukarki resztą porcji — każda próba
            # to kolejne `send_timeout_seconds` blokady, a efekt i tak ten sam.
            # Te zadania zostawiamy w kolejce (bez ACK), więc pozostaną `pending`
            # i wyjadą, gdy drukarka wróci.
            continue
        try:
            send_to_printer(drukarka, j['zpl_payload'])
            ok(f"  ✓ [{nazwa}] id={j['id']} short={j['short_product_id']}{timing}")
            results.append({'id': j['id'], 'success': True})
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            err(f"  ✗ [{nazwa}] id={j['id']} short={j['short_product_id']}{timing} ({e})")
            log_error(f"Drukowanie [{nazwa}] id={j['id']} nieudane{timing}: {e}", exc=e)
            results.append({'id': j['id'], 'success': False, 'error': str(e)[:200]})
            drukarka_padla = True
            # Raz na porcję pytamy drukarkę, co jej dolega — sam komunikat
            # gniazda („timed out") nie odróżnia braku etykiet od wyłączonego
            # zasilania, a operator przy maszynie potrzebuje właśnie tego.
            log_printer_status(drukarka)

    if not results:
        return 'ok'   # same cudze zadania — nic do potwierdzenia

    try:
        resp = ack_jobs(cfg, results)
        success_count = sum(1 for r in results if r['success'])
        ok(f"[{nazwa}] ACK: {success_count}/{len(results)} OK (server updated={resp.get('updated', '?')})")
    except (URLError, HTTPError, TimeoutError, OSError) as e:
        log_error(f"Nie udało się wysłać ACK: {e}", exc=e)
        return 'error'

    # <tu zostaje bez zmian dotychczasowy długi komentarz „Po resztę wracamy TYLKO wtedy…”>
    if success_count < len(results):
        warn(f"[{nazwa}] Drukarka nie przyjęła części etykiet — przerywam opróżnianie kolejki")
        if stan is not None:
            stan['drukarka_padla'] = True
        return 'ok'
    if cudze:
        return 'ok'   # porcja z cudzymi zadaniami — kolejna przyniosłaby te same
    return 'more' if len(jobs) >= cfg['jobs_limit'] else 'ok'
```

- [ ] **Step 6: Kalibracja i tryby wiersza poleceń**

Zamień `printer_status_mode` i blok `if __name__ == '__main__':` na:

```python
def printer_status_mode():
    """`python print_agent.py --drukarka` — pyta drukarki o stan i kończy.

    Do odpalenia w drugim oknie, bez zatrzymywania agenta: pytania idą osobnym
    połączeniem i nie mieszają się z kolejką wydruków.
    """
    cfg = load_config(os.path.join(SCRIPT_DIR, 'config.ini'))
    for nazwa, drukarka in _drukarki(cfg).items():
        print(f"{C.BOLD}{C.CYAN}Drukarka {nazwa}: {_opis_drukarki(drukarka)}{C.RESET}\n")
        for komenda, opis, odpowiedz in query_printer_status(drukarka):
            print(f"  {C.BOLD}{komenda}{C.RESET} ({opis}):\n      {odpowiedz}\n")
    print("Brak odpowiedzi na wszystkie komendy nie musi znaczyć awarii — Xprinter ma\n"
          "emulację ZPL i może nie wspierać zapytań o stan. Ale jeśli nie udaje się\n"
          "nawet POŁĄCZYĆ, drukarka jest odcięta i to jest odpowiedź sama w sobie.")


KOMENDA_KALIBRACJI = b'GAPDETECT\r\n'


def kalibruj(cfg, nazwa):
    """Kalibracja czujnika przerwy (TSPL GAPDETECT): drukarka przewija kilka pustych
    etykiet i zapamiętuje, gdzie zaczyna się etykieta. Obowiązkowa przy instalacji
    drukarki paczek i po zmianie rolki na inną — bez niej XP-410B drukował ~6 mm
    za nisko (spec etapu 4, 6.4)."""
    drukarki = _drukarki(cfg)
    if nazwa not in drukarki:
        raise ValueError(f"Nie ma drukarki „{nazwa}” w config.ini (są: {', '.join(drukarki)})")
    wyslij_surowe(drukarki[nazwa], KOMENDA_KALIBRACJI)


def calibrate_mode(nazwa):
    """`python print_agent.py --kalibruj [nazwa]` — domyślnie drukarka paczek."""
    cfg = load_config(os.path.join(SCRIPT_DIR, 'config.ini'))
    kalibruj(cfg, nazwa)
    ok(f"Wysłano kalibrację do drukarki {nazwa} — przewinie kilka pustych etykiet. "
       "Potem zrób wydruk próbny z panelu CRM (Konfiguracja → Drukarka etykiet).")


if __name__ == '__main__':
    if '--kalibruj' in sys.argv:
        i = sys.argv.index('--kalibruj')
        calibrate_mode(sys.argv[i + 1] if len(sys.argv) > i + 1 else 'wysylka')
    elif '--drukarka' in sys.argv or '--printer-status' in sys.argv:
        printer_status_mode()
    else:
        main()
```

Sprawdź `grep -n "printer_ip\|printer_port\|printer_timeout" tools/print_agent/print_agent.py` — jedyne trafienie ma być w `_drukarki` (zgodność wsteczna).

- [ ] **Step 7: Atrapy w dotychczasowych testach agenta**

W `tests/test_print_agent_sse.py` (dokładnie 4 miejsca):
- ok. :221 `lambda c: (pobrania.append(1), porcje.pop(0))[1]` → `lambda c, drukarka='etykiety': (pobrania.append(1), porcje.pop(0))[1]`
- ok. :247, :274, :293 `def fetch(c):` → `def fetch(c, drukarka='etykiety'):`

- [ ] **Step 8: Wzór konfiguracji i README**

W `tools/print_agent/config.example.ini` zamień sekcję `[printer]` na:

```ini
; Drukarki. Każda sekcja [printer:<nazwa>] to jedna drukarka; nazwa musi się zgadzać
; z CRM: `etykiety` (etykiety produktów 60x40) albo `wysylka` (etykiety paczek 100x150).
;   type = tcp     → drukarka w sieci: ip + port (zwykle 9100)
;   type = windows → drukarka podpięta do tego komputera (np. USB): name = nazwa kolejki
;                    wydruku z Ustawienia → Drukarki (dokładnie, z wielkością liter)
; Stara sekcja [printer] (sprzed etapu 4) działa dalej jako drukarka `etykiety`.
[printer:etykiety]
type = tcp
ip = 192.168.100.199
port = 9100
send_timeout_seconds = 15

; Drukarka paczek — odkomentuj po instalacji (adres w sieci hali), potem
; `python print_agent.py --kalibruj wysylka` i wydruk próbny z panelu CRM.
;[printer:wysylka]
;type = tcp
;ip =
;port = 9100
;send_timeout_seconds = 15
```

W `tools/print_agent/README.md`:
- w „Co to jest” zamień „do drukarki Xprinter XP-423B w sieci lokalnej” na „do drukarek Xprinter: XP-423B (etykiety produktów 60×40) i XP-410B (etykiety paczek 100×150, od etapu 4 logistyki)”;
- w „Wymagania” zamień linię o LAN na „Dostęp do drukarek: w sieci LAN (np. `192.168.100.199:9100`) albo podpiętych do tego komputera (kolejka wydruku Windows)”;
- dopisz przed „## Diagnostyka” (albo na końcu, jeśli nagłówka nie ma) sekcję:

```markdown
## Dwie drukarki (od etapu 4 logistyki)

Każda drukarka to osobna sekcja `[printer:<nazwa>]` w `config.ini` — wzór w
`config.example.ini`. Nazwy są wspólne z CRM: `etykiety` (etykiety produktów 60×40)
i `wysylka` (etykiety paczek 100×150). Agent pyta CRM o zadania każdej drukarki
osobno, więc awaria jednej nie wstrzymuje drugiej. Stary `config.ini` z sekcją
`[printer]` działa dalej jako drukarka `etykiety`.

Drukarka podpięta do tego komputera (USB): `type = windows` i `name = <nazwa kolejki
wydruku>` — dokładnie tak, jak w Ustawienia → Drukarki. Agent wysyła ZPL „na surowo”
(typ danych RAW), sterownik go nie przerabia.

### Aktualizacja agenta na komputerze hali

1. Zatrzymaj agenta (zamknij okno).
2. Podmień `print_agent.py` i `README.md` w folderze agenta (`config.ini` zostaw).
3. W `config.ini` dopisz sekcję `[printer:wysylka]` (adres drukarki paczek w sieci hali).
4. `python print_agent.py --kalibruj wysylka` — drukarka przewinie kilka pustych etykiet.
5. Uruchom agenta (`start.bat`) i w CRM: Konfiguracja → Drukarka etykiet → „Wydruk
   próbny: Drukarka paczek”. Ramka ma mieć ok. 3 mm od każdej krawędzi; jeśli nie,
   popraw „Drukarka paczek: przesunięcie” (8 punktów = 1 mm), zapisz i drukuj ponownie.

### Kalibracja (`--kalibruj`)

`python print_agent.py --kalibruj wysylka` wysyła do drukarki komendę TSPL `GAPDETECT`.
Rób to przy instalacji i po każdej zmianie rolki na inny rozmiar — bez kalibracji
XP-410B drukował ok. 6 mm za nisko.
```

- [ ] **Step 9: Uruchom — ma przejść (nowe i dotychczasowe testy agenta)**

Run: `PYTEST tests/test_print_agent_drukarki.py tests/test_print_agent_sse.py`
Expected: PASS.

- [ ] **Step 10: Pełny pakiet**, potem **Commit**

```bash
git add tools/print_agent/print_agent.py tools/print_agent/config.example.ini tools/print_agent/README.md tests/test_print_agent_drukarki.py tests/test_print_agent_sse.py
git commit -m "feat(production): agent druku na dwie drukarki, kolejka Windows i kalibracja

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Weryfikacja na MySQL i na drukarce testowej, dopisanie odstępstw do specu

Bez nowego kodu produkcyjnego; skrypty pomocnicze leżą POZA repo. Kroki oznaczone **[Konrad]** wymagają człowieka przy drukarce.

**Files:**
- Modify: `docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md` (6.1, 6.2, 6.4)
- Poza repo: `C:\Users\Grafik\Documents\woodpower-podglady\logistyka4\` (kod podglądu, `core.json`, agent testowy)

- [ ] **Step 1: Pełny pakiet i Python 3.9**

Run: `docker compose -p logistyka4 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider`
Expected: 0 failed, passed = baseline + wszystkie nowe testy kroku.

Run: `MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD:/app" -w /app python:3.9-slim python -m py_compile modules/production/services/package_label.py modules/production/services/print_queue_service.py modules/production/routers/api/print_agent_api.py modules/production/routers/api/config_api.py tools/print_agent/print_agent.py`
Expected: brak wyjścia (kompiluje się na 3.9).

- [ ] **Step 2: Kopia bazy podglądu**

```bash
docker exec woodpower-crm-db-1 mysql -uroot -e "CREATE DATABASE IF NOT EXISTS logistyka4_podglad CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
docker exec woodpower-crm-db-1 sh -c "mysqldump -uroot --single-transaction logistyka3_prod | mysql -uroot logistyka4_podglad"
docker exec woodpower-crm-db-1 mysql -uroot logistyka4_podglad -e "SELECT COUNT(*) FROM prod_print_queue; UPDATE prod_print_queue SET status='expired', error_message='podglad: zadania z kopii produkcji' WHERE status='pending'"
```
Expected: kopia bez błędów; żadne zadanie z produkcji nie zostaje `pending` (agent testowy nie może wydrukować cudzych etykiet).

- [ ] **Step 3: Migracja na MySQL, dwa razy**

```bash
docker exec -i woodpower-crm-db-1 mysql -uroot logistyka4_podglad < migrations/2026-09-30-druk-dwie-drukarki.sql
docker exec -i woodpower-crm-db-1 mysql -uroot logistyka4_podglad < migrations/2026-09-30-druk-dwie-drukarki.sql
docker exec woodpower-crm-db-1 mysql -uroot logistyka4_podglad -e "SHOW CREATE TABLE prod_print_queue\G" | grep -E "printer|package_id|ix_prod_print_queue_printer_status"
docker exec woodpower-crm-db-1 mysql -uroot logistyka4_podglad -e "SELECT printer, COUNT(*) FROM prod_print_queue GROUP BY printer"
```
Expected: oba przebiegi bez błędu (drugi wypisuje „… juz jest”); kolumny `printer varchar(20) NOT NULL DEFAULT 'etykiety'`, `package_id int DEFAULT NULL`, indeks; wszystkie stare wiersze mają `etykiety`. Zanotuj czas pierwszego przebiegu (tabela z produkcji — ALTER ADD COLUMN na MySQL 8 jest natychmiastowy).

- [ ] **Step 4: Podgląd 5004 z kodem gałęzi**

Katalog `P=/c/Users/Grafik/Documents/woodpower-podglady/logistyka4` (poza repo; `core.json` z hasłem bazy nie może trafić do gita).

```bash
mkdir -p "$P/kod"
git archive --output="$P/kod.tar" HEAD
tar -xf "$P/kod.tar" -C "$P/kod"
```

Create `$P/przygotuj_config.py` i uruchom `python "$P/przygotuj_config.py"` (Python na Windows):

```python
# -*- coding: utf-8 -*-
"""core.json podglądu etapu 4 (5004) z core.json podglądu etapu 3 (5003).
Nie wypisuje wartości — tylko nazwy zmienionych kluczy."""
import json
import os
import secrets

TU = os.path.dirname(os.path.abspath(__file__))
ZRODLO = r'C:\Users\Grafik\AppData\Local\Temp\claude\C--Users-Grafik-Documents-woodpower-crm\320e7d76-d002-459d-83b4-3b0a3df0403a\scratchpad\podglad-prod\kod\config\core.json'
CEL = os.path.join(TU, 'kod', 'config', 'core.json')

with open(ZRODLO, encoding='utf-8') as f:
    cfg = json.load(f)
uri = cfg.get('DATABASE_URI') or ''
if '/logistyka3_prod' not in uri:
    raise SystemExit('DATABASE_URI zrodla nie wskazuje logistyka3_prod - przerywam')
cfg['DATABASE_URI'] = uri.replace('/logistyka3_prod', '/logistyka4_podglad', 1)
klucz = secrets.token_hex(32)
cfg['SECRET_KEY'] = klucz
# 5003 i 5004 to ten sam host 127.0.0.1 — ciasteczka nie rozróżniają portów.
cfg['SESSION_COOKIE_NAME'] = 'session_lg4'
cfg['REMEMBER_COOKIE_NAME'] = 'remember_lg4'
cfg['RUN_DB_SETUP'] = False
with open(CEL, 'w', encoding='utf-8') as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
with open(os.path.join(TU, 'env.list'), 'w', encoding='utf-8', newline='\n') as f:
    f.write('FLASK_APP=app.py\nFLASK_DEBUG=1\nFLASK_SECRET_KEY=%s\n' % klucz)
print('Zapisano core.json i env.list: DATABASE_URI, SECRET_KEY, SESSION/REMEMBER_COOKIE_NAME, RUN_DB_SETUP')
```

Jeśli plik źródłowy nie istnieje (katalog tymczasowy zniknął) — przerwij i zgłoś; podgląd 5003 trzeba wtedy postawić od nowa wg przekazania etapu 3, sekcja 0.

```bash
MSYS_NO_PATHCONV=1 docker run -d --name logistyka4-podglad --network woodpower-crm_default -p 127.0.0.1:5004:5000 --env-file "C:/Users/Grafik/Documents/woodpower-podglady/logistyka4/env.list" -v "C:/Users/Grafik/Documents/woodpower-podglady/logistyka4/kod:/app" -w /app logistyka3-app flask run --host=0.0.0.0 --port=5000
docker logs logistyka4-podglad 2>&1 | grep -i "migrat" | tail -5
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5004/login
```
Expected: `[Migrations]` w logu wykonuje `2026-09-30-druk-dwie-drukarki.sql` bez błędu. Kopia bazy nie ma jej w `schema_migrations`, więc runner odpali ją trzeci raz — kolumny już są, osłonięte `ALTER`-y nic nie zmieniają, a runner odnotowuje plik (to sprawdza podział poleceń przez runner, którego klient `mysql` z Step 3 nie sprawdza). `/login` = 200.

- [ ] **Step 5: Token agenta testowego (tylko w kopii bazy)**

```bash
TOKEN=$(python -c "import secrets; print(secrets.token_hex(24))")
docker exec woodpower-crm-db-1 mysql -uroot logistyka4_podglad -e "UPDATE prod_config SET config_value='$TOKEN' WHERE config_key='LABEL_PRINTER_AGENT_TOKEN'"
```
Nie wypisuj tokena w czacie. Jeśli wiersza nie ma (`0 rows affected`) — `INSERT INTO prod_config (config_key, config_value, config_type) VALUES ('LABEL_PRINTER_AGENT_TOKEN', '$TOKEN', 'string')`.

- [ ] **Step 6: Agent testowy na komputerze z drukarką**

```bash
mkdir -p "$P/agent" && cp tools/print_agent/print_agent.py "$P/agent/"
```
Create `$P/agent/config.ini` (wstaw `$TOKEN` z kroku 5):

```ini
[crm]
url = http://127.0.0.1:5004
token = <TOKEN z kroku 5>
jobs_limit = 10
request_timeout_seconds = 10

[printer:wysylka]
type = windows
name = Xprinter XP-410B
send_timeout_seconds = 15

[polling]
interval_seconds = 5
push_idle_interval_seconds = 60
idle_check_interval_seconds = 60

[realtime]
enabled = false
sse_url =

[schedule]
workdays_start = 00:00
workdays_end = 23:59
saturday_start = 00:00
saturday_end = 23:59
```

Kalibracja przez agenta: `cd "$P/agent" && python print_agent.py --kalibruj wysylka`
Expected: komunikat „Wysłano kalibrację…”; **[Konrad]** drukarka przewija kilka pustych etykiet.

Start agenta w tle (Bash tool z `run_in_background: true`): `cd "$P/agent" && python print_agent.py`
Expected w wyjściu: baner z linią `Drukarka wysylka:  kolejka Windows „Xprinter XP-410B”`, potem cisza.

- [ ] **Step 7: Wydruk próbny przez kolejkę CRM**

Create `$P/kod/_wydruk.py`:

```python
# -*- coding: utf-8 -*-
"""Wydruk próbny drukarki paczek przez kolejkę CRM (podgląd etapu 4, poza gitem)."""
from app import create_app
from modules.production.services import print_queue_service as pqs

app = create_app()
with app.app_context():
    job = pqs.wydruk_probny('wysylka', {'type': 'user', 'id': 0})
    print('zadanie', job.id, job.printer)
```

Run: `MSYS_NO_PATHCONV=1 docker exec -w /app logistyka4-podglad python _wydruk.py`
Expected: `zadanie <id> wysylka`; w ciągu ok. 5 s agent loguje `✓ [wysylka] id=<id> short=TEST-wysylka` i `ACK: 1/1`; w bazie `SELECT status FROM prod_print_queue WHERE id=<id>` = `printed`.
**[Konrad]** Ramka ma mieć ok. 3 mm od każdej krawędzi. Jeśli odstęp u góry i na dole się różni (30.09 po kalibracji było 4 mm / 2 mm), ustaw przesunięcie w kopii bazy i powtórz wydruk — tekst „Przesuniecie teraz: X=0, Y=-8” potwierdza odczyt:

```bash
docker exec woodpower-crm-db-1 mysql -uroot logistyka4_podglad -e "INSERT INTO prod_config (config_key, config_value, config_type) VALUES ('PACKAGE_LABEL_OFFSET_Y_DOTS', '-8', 'integer') ON DUPLICATE KEY UPDATE config_value = '-8'"
MSYS_NO_PATHCONV=1 docker exec -w /app logistyka4-podglad python _wydruk.py
```

- [ ] **Step 8: Wzór etykiety paczki z prawdziwego zamówienia**

Create `$P/kod/_wzor_paczki.py`:

```python
# -*- coding: utf-8 -*-
"""Etykieta paczki z danych zamówienia (podgląd etapu 4, poza gitem). Krok 4.2 zbuduje
te dane z prod_packages — tu składamy je ręcznie, żeby sprawdzić generator na żywych danych."""
import sys

from app import create_app
from extensions import db
from modules.production.models import ProductionOrder
from modules.production.services import package_label as pl, print_queue_service as pqs

NUMER = sys.argv[1] if len(sys.argv) > 1 else '1450'
app = create_app()
with app.app_context():
    order = ProductionOrder.query.filter_by(internal_order_number=NUMER).one()
    aktywne = [p for p in sorted(order.products, key=lambda p: p.product_sequence_in_order or 0)
               if p.current_status != 'anulowane']
    pozycje = [pl.PozycjaEtykiety(
        gatunek=p.configuration.species if p.configuration else '',
        technologia=p.configuration.technology if p.configuration else '',
        klasa=p.configuration.wood_class if p.configuration else '',
        dlugosc_cm=p.parsed_length_cm or 0, szerokosc_cm=p.parsed_width_cm or 0,
        grubosc_cm=p.parsed_thickness_cm or 0, ilosc=p.quantity or 0,
        wykonczenie=p.parsed_finish_state) for p in aktywne]
    m3 = sum(float(p.volume_m3 or 0) * (p.quantity or 0) for p in aktywne)
    dane = pl.DaneEtykietyPaczki(
        numer_zamowienia=order.internal_order_number, kod_paczki='P-TEST', rodzaj='paleta',
        typ_palety='eur', numer=1, z_ilu=1, sposob='TRANSPORT WOODPOWER',
        odbiorca=order.delivery_fullname or order.client_name, pozycje=pozycje, m3=m3,
        base_id=order.baselinker_order_id, zamowienie_klienta=order.client_order_number)
    zpl = pl.generate_package_label_zpl(dane, pl.wczytaj_przesuniecie())
    job = pqs.zakolejkuj_zpl('wysylka', zpl, 'P-TEST', 'panel', {'type': 'user', 'id': 0},
                             baselinker_order_id=order.baselinker_order_id)
    db.session.commit()
    print('zadanie', job.id, 'pozycji', len(pozycje))
```

Run: `MSYS_NO_PATHCONV=1 docker exec -w /app logistyka4-podglad python _wzor_paczki.py 1450`
Expected: agent drukuje; **[Konrad]** etykieta zgodna z zatwierdzonym wzorem (1450, PALETA 1 / 1, TRANSPORT WOODPOWER, „Dar*** Kow***”, 14 pozycji, bez adresu), treść nie ucięta. Jeśli `order.products` nie istnieje jako relacja, użyj `ProductionProduct.query.filter_by(order_id=order.id)`.

- [ ] **Step 9: Panel w przeglądarce**

Wbudowana przeglądarka (nigdy Chrome Konrada): sesja admina skryptem wg `…\podglad-prod\kod\_sesja.py` (skopiuj do `$P/kod`, ciasteczko `session_lg4`), otwórz `http://127.0.0.1:5004/production` → Konfiguracja → karta drukarki. Sprawdź: dwa pola „Drukarka paczek: przesunięcie…”, zapis `-8` (toast „Konfiguracja zapisana”), „Przywróć domyślne” = 0, przyciski „Wydruk próbny” — „Drukarka paczek” daje toast z komunikatem z serwera, a agent drukuje; „Drukarka etykiet” daje toast, a zadanie `etykiety` zostaje `pending` (agent testowy nie ma tej drukarki — to poprawne). Zapis `200` → toast błędu walidacji. Albo **[Konrad]** loguje się sam na `127.0.0.1:5004` i klika.

- [ ] **Step 10: Sprzątanie testu i odstępstwa w specu**

Zatrzymaj agenta testowego (zakończ proces w tle). Podgląd 5004 i baza `logistyka4_podglad` ZOSTAJĄ na krok 4.2 (zapisz to w podsumowaniu).

W specu dopisz:
- 6.1: w zdaniu o ustawieniach zamień „(przesunięcie `^LH`, domyślnie 0)” na „(przesunięcie w punktach dodawane do współrzędnych każdego pola — `^LH` nie przyjmuje wartości ujemnych; domyślnie 0, zakres ±120)”.
- 6.2: „`type = tcp` (`host`, `port`…” → „`type = tcp` (`ip`, `port`…”; dopisz punkt: „`python print_agent.py --kalibruj [nazwa]` wysyła TSPL `GAPDETECT` (kalibracja z 6.4 bez dodatkowych narzędzi na hubie).”

```bash
git add -f docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md
git commit -m "docs: krok 4.1 logistyki - odstepstwa od projektu po realizacji

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 11: Przegląd całego kroku**

Adwersaryjny przegląd zmian `112aa34b..HEAD` (backend, agent, UI) wg Review Focus — raport i poprawki przed zamknięciem kroku. Lista wdrożenia kroku 4.1 (do przekazania Konradowi, wykonuje się dopiero po wdrożeniu etapów 1–3): migracja przy deployu → nowy agent na komputerze hali (README, „Aktualizacja agenta na komputerze hali”) → drukarka paczek w sieci hali → `--kalibruj wysylka` → wydruk próbny i przesunięcie w panelu.
