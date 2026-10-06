# Logistyka równoległa — Etap 1: sposób dostawy — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wyjąć logistykę z pipeline'u produkcji: sposób dostawy staje się atrybutem zamówienia ustawianym przez logistyka w dowolnym momencie, pakowanie bez niego jest zablokowane, zmiany trafiają do Base. z zachowaniem limitu API, a panel produkcji dostaje zakładkę „Logistyka” z listą zamówień.

**Architecture:** Nowy podpakiet `modules/production/logistics/` (wzór: `modules/production/sawmill/`) z czystym modułem mapowań (`sposoby.py`), serwisem cyklu życia (`services/delivery.py`), wysyłką do Base. z dzierżawą i bezpiecznikiem (`services/bl_sync.py`), listą dla panelu (`services/lista.py`) i blueprintem `/production/api/logistics`. Model `ProductionProduct.complete_task` przestaje znać `czeka_na_logistyke`; API mobilne dostaje obiekt `transport` i 409 przy pakowaniu bez sposobu dostawy.

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, MySQL 8.4 (produkcja) / SQLite in-memory (testy), pytest, Jinja2, vanilla JS (bez bundlera), Bootstrap z `modules/production/static/vendor/`.

**Spec:** `docs/superpowers/specs/2026-09-24-logistyka-rownolegla-trasy-design.md` (sekcje 2, 4, 5.1–5.2, 6, 8.3, 9–13). Plik jest poza gitem — czytaj go ze ścieżki bezwzględnej `C:\Users\Grafik\Documents\woodpower-crm\docs\superpowers\specs\2026-09-24-logistyka-rownolegla-trasy-design.md`.

## Kontekst (dla sesji, która nie widziała rozmowy projektowej)

**Skąd ta zmiana.** Logistyka była etapem pipeline'u: po Krawędziach/Lakierni produkt dostawał
`czeka_na_logistyke`, logistyk na stronie `/production/logistics` wybierał kuriera albo transport
WoodPower, produkt szedł do pakowania; odbiór osobisty (heurystyka `ProductionOrder.is_personal_pickup`)
omijał logistykę. W praktyce etap był pomijany — w sierpniu–wrześniu ok. 1040 przejść z
`czeka_na_logistyke` to hurtowa zmiana statusu z listy produktów, a `override_delivery_method` od lipca
nie był ustawiony ani razu; logistyk rozdzielał towar ręcznie na hali. Konrad (właściciel CRM)
zatwierdził 24.09.2026 przebudowę w trzech etapach; ten plan to **etap 1**.

**Decyzje, które ten etap realizuje (nie dyskutuj ich ponownie):**
1. Sposób dostawy = `prod_orders.override_delivery_method`, domyślnie NULL = „Nie ustawiono”; wartość z
   Base. (`delivery_method`) to tylko podpowiedź. **Każde** zamówienie (także odbiór osobisty) przechodzi
   przez logistykę; brak automatycznego omijania.
2. `czeka_na_logistyke` znika z pipeline'u — produkcja kończy się wejściem do `czeka_na_pakowanie`.
3. Pakowanie bez sposobu dostawy jest zablokowane (API mobilne 409). Pakowacz widzi takie zamówienie,
   pomija je i bierze kolejne.
4. Zmiana sposobu dostawy **zawsze** nadpisuje w Base. pole „Metoda dostawy” tekstem „Kurier” /
   „Odbiór osobisty” / „Transport WoodPower” (także gdy było „DPD”). Po spakowaniu status Base. według
   sposobu (138623 / 417343 / 149777); zmiana po spakowaniu przestawia status. „Wydane klientowi”
   (tylko odbiór) → 149779 „Odebrane”. Cen dostawy nie ruszamy.
5. Zamówienie znika z widoku logistyki: kurier — po spakowaniu; odbiór — po „Wydane klientowi”;
   transport własny — po odhaczeniu trasy (etap 3; w etapie 1 transport własny zostaje widoczny).
6. Zmiana na kuriera zamówienia spakowanego pod transport własny/odbiór → **przepakowanie**: wraca do
   kolejki pakowania z banerem „PRZEPAKUJ NA KURIERA” (`transport.repack_required`).
7. Dzień wdrożenia: **nic nie wypełniamy automatycznie** — logistyk przeklikuje (lista ma hurt).
8. Tablet: kurier „KURIER”, odbiór „ODBIÓR OSOBISTY”, transport własny = nazwa trasy (etap 3) albo
   „TRANSPORT WOODPOWER”, brak = „NIE USTAWIONO”. Etykieta produktu „Dostawa:” — ten sam tekst.
9. Furtka pod przyszłe stanowisko kierowcy (statusy 149763/149778) — zaimplementowana, niewołana.
10. W UI piszemy „Base.”, nie „BaseLinker”. Interfejs robimy ze skillem `frontend-design`.

**Aplikacja tabletowa** (osobne repo `C:\Users\Grafik\Documents\woodpower_prod_app`, Kotlin) dostała
24.09 od tej sesji wymagania (spec, sekcja 12) i robi własny plan. Kontrakt, którego backend MUSI
dotrzymać: każda pozycja w odpowiedziach mobilnych ma `delivery_type` (stare wartości) i **zawsze**
obiekt `transport {mode, trip_name, trip_date, vehicle_name, repack_required}`. Appka wychodzi
**przed** backendem tego etapu (bez obiektu `transport` zachowuje się jak dziś).

**Poza zakresem etapu 1:** geokodowanie i mapa (etap 2, plan
`docs/superpowers/plans/2026-09-24-logistyka-etap-2-mapa.md`), trasy i flota (etap 3, plan
`docs/superpowers/plans/2026-09-24-logistyka-etap-3-trasy-flota.md`), usunięcie `czeka_na_logistyke` z ENUM.

**Pamięć projektu** (czytaj, jeśli coś jest niejasne): katalog
`C:\Users\Grafik\.claude\projects\C--Users-Grafik-Documents-woodpower-crm\memory\`, pliki
`project_logistyka_rownolegla.md`, `feedback_baselinker_limit_api.md`, `reference_worktree_docker_testy.md`,
`feedback_commit_style.md`, `feedback_nazwa_base.md`, `reference_repo_publiczne.md`.

## Global Constraints

- Komentarze w kodzie **po polsku**; odpowiedzi w czacie po polsku.
- W tekstach widocznych dla użytkownika piszemy **„Base.”**, nie „BaseLinker”/„BL”. Identyfikatory w kodzie (`bl_*`, `baselinker_*`) bez zmian.
- Commity: Conventional Commits po polsku, scope = moduł (`feat(production): …`, `test(production): …`), każdy commit kończy linia `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Nie commitujemy** `docs/superpowers/**`, `MIGRATION_PLAN.md`, `CLAUDE.local.md`, `config/core.json` (repo publiczne).
- Migracje: plik `migrations/2026-09-25-logistyka-sposob-dostawy.sql`, idempotentny, bez `DELIMITER`, `ALTER` osłonięte `information_schema` + `PREPARE/EXECUTE`.
- SQLAlchemy < 2.0 (API `Model.query`, `session.query`).
- Limit API Base. = 100 zapytań/min **na całe konto**: logistyka wysyła najwyżej 1 zapytanie / 1,5 s, jeden nadawca na serwer (dzierżawa), bezpiecznik na „Query limit exceeded / token blocked until”.
- **Żadnej długiej pracy w żądaniu HTTP:** produkcja to gunicorn `-w 4` z sync workerami i **timeoutem 30 s** (memory `project_apk_timeouty_nginx`). Wysyłka do Base. idzie wyłącznie w wątku w tle (dopychacz); endpointy i cron tylko go uruchamiają i od razu odpowiadają. Również pojedyncza zmiana sposobu dostawy nie woła Base. w żądaniu.
- Nowy backend **zawsze** wysyła obiekt `transport` w API mobilnym; `delivery_type` zachowuje stare wartości (`transport_woodpower` / `personal_pickup` / `courier`), dla braku sposobu = `courier`.
- Każde zadanie UI (Task 10) wykonujemy ze skillem **`frontend-design:frontend-design`**.
- Wartość `czeka_na_logistyke` **zostaje w ENUM** `production_status` (sprzątanie osobną migracją później), ale żaden kod jej już nie ustawia.

## Środowisko pracy (przeczytaj przed Task 1)

- W głównym checkoucie `C:\Users\Grafik\Documents\woodpower-crm` pracują równolegle inne sesje — **nie przełączaj tam gałęzi**. Pracuj w worktree:
  ```bash
  cd /c/Users/Grafik/Documents/woodpower-crm
  git fetch origin
  git worktree add ../woodpower-crm-logistyka -b feature/logistyka-etap1 origin/main
  ```
- Testy uruchamiaj **z katalogu worktree** własnym projektem compose (inaczej `docker compose exec` testuje cudzy kod z głównego checkoutu):
  ```bash
  cd /c/Users/Grafik/Documents/woodpower-crm-logistyka
  docker compose -p logistyka run --rm --no-deps app pytest tests/<plik>.py -v
  ```
  Pierwszy przebieg buduje obraz (~80 s). Dalej w planie skrót `PYTEST <ścieżki>` = powyższa komenda.
- Subagentom podawaj **ścieżki bezwzględne** (spec, plan, worktree).

## Review Focus

1. **Dwa workery gunicorna i hurtowa zmiana 300 zamówień** — Base. ma dostać najwyżej ~40 zapytań/min od logistyki łącznie; drugi dopychacz nie może wystartować, gdy pierwszy trzyma dzierżawę. Test: `test_druga_dzierzawa_jest_odrzucona` (Task 5).
2. **„Query limit exceeded, token blocked until …” w połowie wysyłki** — wysyłki logistyki stoją do podanej chwili (także po uruchomieniu z crona), znaczniki zostają, nic nie ginie. Testy: `test_limit_base_wstrzymuje_i_zostawia_znaczniki`, `test_pauza_blokuje_dopychacz` (Task 5), `test_cron_zwraca_pauze` (Task 6).
3. **Przepakowanie, a pakowanie kończy się, zanim dopychacz wyśle 138620** — stary status „Produkcja zakończona” nie może nadpisać świeżego 138623. Test: `test_spakowanie_po_przepakowaniu_kasuje_zalegly_status_138620` (Task 3).
4. **Tablet z zamówieniem na ekranie, logistyk zmienia sposób** — `updated_at` wszystkich pozycji rośnie, więc ETag kolejki się zmienia. Test: `test_zmiana_sposobu_podbija_updated_at_wszystkich_pozycji` (Task 3) i `test_kolejka_pakowania_zmienia_etag_po_zmianie_sposobu` (Task 7).
5. **Base. dokłada pozycję do zamkniętego zamówienia kurierskiego** — zamówienie wraca do widoku logistyki przy najbliższym cronie. Test: `test_cron_otwiera_zamowienie_z_nowa_aktywna_pozycja` (Task 6).

---

## Mapa plików

**Nowe:**
| Plik | Odpowiedzialność |
|---|---|
| `migrations/2026-09-25-logistyka-sposob-dostawy.sql` | kolumny `prod_orders`, tabela `prod_logistics_log`, wiersze `prod_config`, przeniesienie statusów, zamknięcie historii |
| `modules/production/logistics/__init__.py` | blueprint `logistics_panel_bp` + import modeli i routerów |
| `modules/production/logistics/models.py` | `LogisticsLog` |
| `modules/production/logistics/sposoby.py` | czyste mapowania: tryb, legacy, tekst Base., statusy, etykieta, obiekt `transport` |
| `modules/production/logistics/services/__init__.py` | pusty |
| `modules/production/logistics/services/delivery.py` | cykl życia: log, podbijanie `updated_at`, zamknięcie, zmiana sposobu, przepakowanie, wydanie |
| `modules/production/logistics/services/dzierzawa.py` | dzierżawa „jeden wykonawca na serwer” w `prod_config` (Base. teraz, geokodowanie w etapie 2) |
| `modules/production/logistics/services/bl_sync.py` | wysyłka do Base.: znaczniki, pauza po limicie, dopychacz w tle, furtka kierowcy |
| `modules/production/logistics/services/lista.py` | zapytanie i serializacja listy dla panelu, podpowiedź z Base. |
| `modules/production/logistics/routers/__init__.py` | pusty |
| `modules/production/logistics/routers/panel_api.py` | `/tab-content`, `/orders`, `/orders/delivery-method`, `/orders/<id>/handed-over` |
| `modules/production/logistics/routers/cron_api.py` | `/cron` |
| `modules/production/logistics/templates/logistics/tab_content.html` | zakładka (Task 10) |
| `modules/production/logistics/static/css/logistics.css`, `static/js/logistics.js` | UI zakładki (Task 10) |
| `tests/logistyka_fixtures.py` | wspólna apka testowa i fabryki danych |
| `tests/test_logistyka_*.py` | testy zadań |

**Modyfikowane:** `modules/production/models.py`, `app.py`, `modules/production/services/baselinker_status_sync.py`, `modules/production/services/mobile_api_service.py`, `modules/production/routers/mobile_api.py`, `modules/production/services/label_print_service.py`, `modules/production/routers/api/products_api.py`, `modules/production/routers/api/dashboard_api.py`, `modules/production/routers/api/__init__.py`, `modules/production/routers/main_routers.py`, `modules/production/services/dashboard_alerts.py`, `modules/production/templates/components/dashboard-tab-content.html`, `modules/production/templates/components/products-tab-content.html`, `modules/production/templates/panel/dashboard.html`, `modules/production/static/js/production-app-loader.js`, `modules/production/static/js/modules/products-module.js`, `modules/production/static/js/modules/dashboard-module.js`, `CLAUDE.md`, istniejące testy wymienione w zadaniach.

**Usuwane:** `modules/production/routers/api/logistics_api.py`, `modules/production/templates/logistics/logistics.html`.

---

### Task 1: Schemat — migracja, kolumny, log, szkielet podpakietu, fixture testowe

**Files:**
- Create: `migrations/2026-09-25-logistyka-sposob-dostawy.sql`
- Create: `modules/production/logistics/__init__.py`, `modules/production/logistics/models.py`, `modules/production/logistics/services/__init__.py`, `modules/production/logistics/routers/__init__.py`
- Modify: `modules/production/models.py:186-187` (kolumny `ProductionOrder`)
- Modify: `app.py:877-879` (rejestracja blueprintu)
- Create: `tests/logistyka_fixtures.py`
- Test: `tests/test_logistyka_schemat.py`

**Interfaces:**
- Produces: kolumny `ProductionOrder.delivery_method_set_at`, `.delivery_method_set_by`, `.handed_over_at`, `.handed_over_by`, `.repack_required` (bool, default False), `.logistics_closed_at`, `.bl_delivery_method_pending` (bool, default False), `.bl_status_pending_id`; model `LogisticsLog(order_id, action, old_value, new_value, route_id, user_id, note, created_at)`; blueprint `logistics_panel_bp` (nazwa `'logistics_panel'`) pod `/production/api/logistics`; fixture `app`, `client`, stała `BASE = '/production/api/logistics'`, fabryka `zamowienie(...)` w `tests/logistyka_fixtures.py`.

- [ ] **Step 1: Napisz test schematu (failing)**

`tests/test_logistyka_schemat.py`:
```python
# -*- coding: utf-8 -*-
"""Schemat etapu 1 logistyki: kolumny zamówienia, log, migracja."""
import os
import re

from extensions import db
from modules.production.logistics.models import LogisticsLog
from modules.production.models import ProductionOrder
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRACJA = os.path.join(KATALOG, 'migrations', '2026-09-25-logistyka-sposob-dostawy.sql')


def test_nowe_zamowienie_ma_domyslne_wartosci_logistyki(app):
    with app.app_context():
        order = zamowienie()
        assert order.override_delivery_method is None
        assert order.repack_required is False
        assert order.bl_delivery_method_pending is False
        assert order.bl_status_pending_id is None
        assert order.logistics_closed_at is None
        assert order.handed_over_at is None


def test_log_logistyki_zapisuje_sie(app):
    with app.app_context():
        order = zamowienie()
        db.session.add(LogisticsLog(order_id=order.id, action='sposob_dostawy',
                                    old_value=None, new_value='kurier_baselinker'))
        db.session.commit()
        assert LogisticsLog.query.filter_by(order_id=order.id).count() == 1


def test_migracja_zawiera_wszystkie_kroki():
    sql = open(MIGRACJA, encoding='utf-8').read()
    for kolumna in ('delivery_method_set_at', 'delivery_method_set_by', 'handed_over_at',
                    'handed_over_by', 'repack_required', 'logistics_closed_at',
                    'bl_delivery_method_pending', 'bl_status_pending_id'):
        assert kolumna in sql, kolumna
    assert 'CREATE TABLE IF NOT EXISTS prod_logistics_log' in sql
    assert "SET current_status = 'czeka_na_pakowanie'" in sql
    assert 'logistyka_bl_dzierzawa' in sql and 'logistyka_bl_wstrzymane_do' in sql
    assert 'DELIMITER' not in sql
    # Każdy ALTER musi być osłonięty (idempotencja przy każdym deployu).
    assert not re.search(r'^\s*ALTER TABLE', sql, re.MULTILINE)
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_schemat.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.production.logistics'`.

- [ ] **Step 3: Kolumny w modelu**

W `modules/production/models.py` zastąp linie 186-187:
```python
    override_delivery_method = Column(String(255))
    logistics_completed_at = Column(DateTime, index=True)
```
na:
```python
    # SPOSÓB DOSTAWY (logistyka równoległa, 2026-09). NULL = „Nie ustawiono”.
    # Wartości i wszystko, co z nich wynika: modules/production/logistics/sposoby.py.
    override_delivery_method = Column(String(255))
    delivery_method_set_at = Column(DateTime)
    delivery_method_set_by = Column(Integer)
    # „Wydane klientowi” — tylko odbiór osobisty.
    handed_over_at = Column(DateTime)
    handed_over_by = Column(Integer)
    # Spakowane pod transport/odbiór, zmienione na kuriera — wraca do pakowania.
    repack_required = Column(Boolean, nullable=False, default=False)
    # Koniec cyklu logistycznego; NULL = zamówienie widoczne w zakładce Logistyka.
    # Liczy go WYŁĄCZNIE logistics.services.delivery.przelicz_zamkniecie().
    logistics_closed_at = Column(DateTime, index=True)
    # Znaczniki „do wysłania do Base.” — przeżywają restart, dopycha je bl_sync.
    bl_delivery_method_pending = Column(Boolean, nullable=False, default=False)
    bl_status_pending_id = Column(Integer)
    # Chwila, w której ostatni niezanulowany produkt wszedł do pakowania
    # („Zeszło z produkcji” w Arkuszu). Nazwa historyczna — kolumnę czyta raport.
    logistics_completed_at = Column(DateTime, index=True)
```
(`Boolean` jest już importowany w tym pliku — sprawdź nagłówek; jeśli nie, dopisz do importu z `sqlalchemy`.)

- [ ] **Step 4: Model logu i szkielet podpakietu**

`modules/production/logistics/models.py`:
```python
# -*- coding: utf-8 -*-
"""Modele logistyki równoległej. Kolumny zamówienia siedzą na ProductionOrder."""
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String

from extensions import db
from modules.production.models import get_local_now

AKCJE_LOGU = ('sposob_dostawy', 'wydane', 'przepakowanie',
              'trasa_dodane', 'trasa_usuniete', 'trasa_status')


class LogisticsLog(db.Model):
    """Każda zmiana logistyki zamówienia zostawia tu jeden wiersz."""
    __tablename__ = 'prod_logistics_log'

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey('prod_orders.id', ondelete='CASCADE'),
                      nullable=False, index=True)
    action = Column(Enum(*AKCJE_LOGU, name='logistics_log_action'), nullable=False)
    old_value = Column(String(64))
    new_value = Column(String(64))
    route_id = Column(Integer)
    user_id = Column(Integer, index=True)
    note = Column(String(255))
    created_at = Column(DateTime, nullable=False, default=get_local_now, index=True)
```

`modules/production/logistics/__init__.py`:
```python
# -*- coding: utf-8 -*-
"""
Logistyka równoległa — sposób dostawy zamówienia, niezależny od pipeline'u
produkcji. Spec: docs/superpowers/specs/2026-09-24-logistyka-rownolegla-trasy-design.md
(poza gitem). Blueprint rejestrowany w app.py pod /production/api/logistics.
"""
from flask import Blueprint

logistics_panel_bp = Blueprint(
    'logistics_panel', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/static/logistics',
)

# Model musi być w metadata, zanim ktokolwiek zrobi create_all.
from modules.production.logistics import models  # noqa: E402,F401
```
Puste pliki: `modules/production/logistics/services/__init__.py`, `modules/production/logistics/routers/__init__.py` (po jednej linii `# -*- coding: utf-8 -*-`).

W `app.py` po liniach 877-879 (rejestracja trakowni) dopisz:
```python
        from modules.production.logistics import logistics_panel_bp
        app.register_blueprint(logistics_panel_bp, url_prefix='/production/api/logistics')
```

- [ ] **Step 5: Fixture testowe**

`tests/logistyka_fixtures.py`:
```python
# -*- coding: utf-8 -*-
"""
Wspólna apka testowa logistyki. Importuj w pliku testów:

    from tests.logistyka_fixtures import BASE, app, client, zamowienie, produkt  # noqa: F401

Rejestruje panel logistyki i API mobilne na jednej minimalnej apce (SQLite
in-memory). Dekorator dostępu do modułu podmieniamy na przelotkę — tak samo
i z tych samych powodów co tests/sawmill_fixtures.py.
"""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProcessedMobileOperation, ProductionConfig, ProductionConfiguration,
    ProductionDevice, ProductionOrder, ProductionProduct, ProductionReworkLog,
    ProductionStationEvent, ProductionWorker,
)
from modules.production.logistics.models import LogisticsLog
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401
from modules.quotes.models import QuoteStatus  # noqa: F401

BASE = '/production/api/logistics'
SEKRET_CRONA = 'sekret-testowy-logistyki'

TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProcessedMobileOperation,
    ProductionOrder, ProductionProduct, ProductionConfiguration,
    ProductionReworkLog, ProductionStationEvent, ProductionWorker, LogisticsLog,
)]

# LONGTEXT nie istnieje w SQLite — ten sam zabieg co w tests/test_routing_krawedzie.py.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

_licznik = itertools.count(1)


@pytest.fixture()
def app(monkeypatch):
    import modules.users.decorators as decorators
    monkeypatch.setattr(decorators, 'require_module_access',
                        lambda *a, **k: (lambda f: f))

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['LOGIN_DISABLED'] = True
    app.config['PRODUCTION_CRON_SECRET'] = SEKRET_CRONA
    app.config['API_MOBILE'] = {
        'jwt_secret': 'x' * 64, 'token_ttl_days': 365,
        'ip_whitelist': [], 'min_supported_app_version': '0.0.0',
    }

    from modules.production.logistics import logistics_panel_bp
    from modules.production.routers.mobile_api import mobile_api_bp
    app.register_blueprint(logistics_panel_bp, url_prefix=BASE)
    app.register_blueprint(mobile_api_bp, url_prefix='/api/mobile')
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABLES)
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


def zamowienie(sposob=None, statusy=('czeka_na_wyciecie',), delivery_method='Kurier DPD',
               miasto='Kraków', bl_id=None, **kolumny):
    """Zamówienie z jednym produktem na każdy podany status (quantity=2)."""
    numer = next(_licznik)
    order = ProductionOrder(
        baselinker_order_id=bl_id if bl_id is not None else 700000 + numer,
        internal_order_number='26/%05d' % numer,
        client_name='Klient %d' % numer,
        delivery_method=delivery_method,
        delivery_address='ul. Testowa %d' % numer,
        delivery_city=miasto,
        delivery_postcode='30-001',
        override_delivery_method=sposob,
        **kolumny)
    db.session.add(order)
    db.session.flush()
    for i, status in enumerate(statusy, start=1):
        produkt(order, status=status, sekwencja=i)
    db.session.commit()
    return order


def produkt(order, status='czeka_na_wyciecie', sekwencja=None, quantity=2, **kolumny):
    sekwencja = sekwencja or (len(order.products) + 1)
    p = ProductionProduct(
        order_id=order.id,
        short_product_id='%d_%d' % (order.id, sekwencja),
        product_sequence_in_order=sekwencja,
        original_product_name='Blat dębowy 100x60x4',
        quantity=quantity,
        volume_m3=0.024,
        current_status=status,
        **kolumny)
    db.session.add(p)
    db.session.flush()
    if status == 'spakowane':
        p.quantity_done_packaging = quantity
    return p
```

- [ ] **Step 6: Migracja SQL**

`migrations/2026-09-25-logistyka-sposob-dostawy.sql` — dla KAŻDEJ z ośmiu kolumn ten sam blok (poniżej pełny wzór dla pierwszej; pozostałe różnią się wyłącznie nazwą i definicją kolumny, wypisz wszystkie osiem):
```sql
-- Logistyka równoległa, etap 1 (spec 2026-09-24-logistyka-rownolegla-trasy-design.md).
-- Idempotentna: runner (migrations/migration_service.py) uruchamia katalog przy
-- każdym deployu. ALTER nie ma IF NOT EXISTS, więc warunek składamy
-- z information_schema i wykonujemy przez PREPARE/EXECUTE (DELIMITER nie działa).

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND COLUMN_NAME = 'delivery_method_set_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN delivery_method_set_at DATETIME NULL',
              'SELECT "delivery_method_set_at juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;
```
Definicje pozostałych kolumn (nazwa → definicja w `ADD COLUMN`):
- `delivery_method_set_by` → `INT NULL`
- `handed_over_at` → `DATETIME NULL`
- `handed_over_by` → `INT NULL`
- `repack_required` → `TINYINT(1) NOT NULL DEFAULT 0`
- `logistics_closed_at` → `DATETIME NULL`
- `bl_delivery_method_pending` → `TINYINT(1) NOT NULL DEFAULT 0`
- `bl_status_pending_id` → `INT NULL`

Indeks (osłonięty tak samo, po `information_schema.STATISTICS`, `INDEX_NAME = 'ix_prod_orders_logistics_closed_at'`):
```sql
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND INDEX_NAME = 'ix_prod_orders_logistics_closed_at');
SET @sql = IF(@brak, 'CREATE INDEX ix_prod_orders_logistics_closed_at ON prod_orders (logistics_closed_at)',
              'SELECT "indeks juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;
```
Dalej w tym samym pliku:
```sql
CREATE TABLE IF NOT EXISTS prod_logistics_log (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    action ENUM('sposob_dostawy','wydane','przepakowanie',
                'trasa_dodane','trasa_usuniete','trasa_status') NOT NULL,
    old_value VARCHAR(64) NULL,
    new_value VARCHAR(64) NULL,
    route_id INT NULL,
    user_id INT NULL,
    note VARCHAR(255) NULL,
    created_at DATETIME NOT NULL,
    KEY ix_prod_logistics_log_order_id (order_id),
    KEY ix_prod_logistics_log_user_id (user_id),
    KEY ix_prod_logistics_log_created_at (created_at),
    CONSTRAINT fk_prod_logistics_log_order FOREIGN KEY (order_id)
        REFERENCES prod_orders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Stan wysyłki do Base.: dzierżawa jednego nadawcy i pauza po limicie API.
INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type, created_at, updated_at)
VALUES ('logistyka_bl_dzierzawa', '1970-01-01T00:00:00',
        'Logistyka: dzierzawa nadawcy do Base. (waznosc ISO)', 'string', NOW(), NOW()),
       ('logistyka_bl_wstrzymane_do', '1970-01-01T00:00:00',
        'Logistyka: wysylki do Base. wstrzymane do (ISO) po limicie API', 'string', NOW(), NOW());

-- Logistyka przestaje być etapem pipeline'u. Wartość zostaje w ENUM do osobnego
-- sprzątania — między tą migracją a restartem stary kod może ją jeszcze zapisać.
UPDATE prod_products SET current_status = 'czeka_na_pakowanie'
WHERE current_status = 'czeka_na_logistyke';

-- Historia: zamówienia w całości spakowane/anulowane przed wdrożeniem kończą cykl
-- logistyczny, inaczej zalałyby widok (np. ~100 zamówień transport_woodpower
-- z kwietnia–czerwca). Odbiór osobisty nie istnieje jeszcze jako wartość, więc
-- warunek na odbior_osobisty chroni jedynie przed ponownym przebiegiem po wdrożeniu.
UPDATE prod_orders o SET o.logistics_closed_at = NOW()
WHERE o.logistics_closed_at IS NULL
  AND (o.override_delivery_method IS NULL OR o.override_delivery_method <> 'odbior_osobisty')
  AND NOT EXISTS (SELECT 1 FROM prod_products p
                  WHERE p.order_id = o.id
                    AND p.current_status NOT IN ('spakowane', 'anulowane'));
```

- [ ] **Step 7: Uruchom testy**

Run: `PYTEST tests/test_logistyka_schemat.py tests/test_migration_service.py`
Expected: PASS (w tym test nazw plików migracji).

- [ ] **Step 8: Commit**

```bash
git add migrations/2026-09-25-logistyka-sposob-dostawy.sql modules/production/logistics modules/production/models.py app.py tests/logistyka_fixtures.py tests/test_logistyka_schemat.py
git commit -m "feat(production): schemat logistyki rownoleglej - kolumny zamowienia, log i migracja

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `sposoby` — mapowania i obiekt `transport`

**Files:**
- Create: `modules/production/logistics/sposoby.py`
- Test: `tests/test_logistyka_sposoby.py`

**Interfaces:**
- Produces (moduł `modules.production.logistics.sposoby`): stałe `KURIER='kurier_baselinker'`, `TRANSPORT='transport_woodpower'`, `ODBIOR='odbior_osobisty'`, `SPOSOBY`, `MODE`, `TEKST_BASE`, `STATUS_PRODUKCJA_ZAKONCZONA=138620`, `STATUS_SPAKOWANE=138623`, `STATUS_PLANOWANA_TRASA=417343`, `STATUS_CZEKA_NA_ODBIOR=149777`, `STATUS_ODEBRANE=149779`, `STATUS_WYSLANE_TRANSPORT=149763`, `STATUS_DOSTARCZONE_TRANSPORT=149778`, `STATUS_PO_SPAKOWANIU: dict`, `NIE_USTAWIONO='Nie ustawiono'`; funkcje `normalizuj(wartosc) -> Optional[str]`, `etykieta(sposob, nazwa_trasy=None) -> str`, `legacy_delivery_type(sposob) -> str`, `transport_payload(order, trasa=None) -> dict`, `podpowiedz(order) -> str`.
- Moduł **nie importuje** niczego z aplikacji (używany z `models.py`, `baselinker_status_sync.py`, API mobilnego — ma nie tworzyć cykli).

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_sposoby.py`:
```python
# -*- coding: utf-8 -*-
from datetime import date
from types import SimpleNamespace as NS

import pytest

from modules.production.logistics import sposoby as s


@pytest.mark.parametrize('wartosc, oczekiwane', [
    (None, None), ('', None), ('  kurier_baselinker ', 'kurier_baselinker'),
    ('transport_woodpower', 'transport_woodpower'), ('odbior_osobisty', 'odbior_osobisty'),
    ('DPD', None),
])
def test_normalizuj(wartosc, oczekiwane):
    assert s.normalizuj(wartosc) == oczekiwane


def test_etykiety():
    assert s.etykieta(None) == 'Nie ustawiono'
    assert s.etykieta(s.KURIER) == 'Kurier'
    assert s.etykieta(s.ODBIOR) == 'Odbiór osobisty'
    assert s.etykieta(s.TRANSPORT) == 'Transport WoodPower'
    assert s.etykieta(s.TRANSPORT, nazwa_trasy='Kraków + Tarnów') == 'Kraków + Tarnów'
    # Nazwa trasy nie przykrywa innego sposobu.
    assert s.etykieta(s.KURIER, nazwa_trasy='Kraków') == 'Kurier'


def test_legacy_delivery_type_ma_tylko_stare_wartosci():
    assert s.legacy_delivery_type(None) == 'courier'
    assert s.legacy_delivery_type(s.KURIER) == 'courier'
    assert s.legacy_delivery_type(s.TRANSPORT) == 'transport_woodpower'
    assert s.legacy_delivery_type(s.ODBIOR) == 'personal_pickup'


def test_transport_bez_sposobu_i_bez_trasy():
    order = NS(override_delivery_method=None, repack_required=False)
    assert s.transport_payload(order) == {
        'mode': None, 'trip_name': None, 'trip_date': None,
        'vehicle_name': None, 'repack_required': False}


def test_transport_z_trasa_i_przepakowaniem():
    order = NS(override_delivery_method=s.TRANSPORT, repack_required=True)
    trasa = NS(name='Kraków + Tarnów', date_from=date(2026, 9, 30),
               vehicle=NS(name='Iveco KR 12345'))
    assert s.transport_payload(order, trasa) == {
        'mode': 'wlasny', 'trip_name': 'Kraków + Tarnów', 'trip_date': '2026-09-30',
        'vehicle_name': 'Iveco KR 12345', 'repack_required': True}


def test_transport_dla_braku_zamowienia_to_nadal_obiekt():
    """Nowy backend ZAWSZE wysyła obiekt — appka odróżnia po nim stary backend."""
    assert s.transport_payload(None)['mode'] is None


def test_statusy_po_spakowaniu():
    assert s.STATUS_PO_SPAKOWANIU == {s.KURIER: 138623, s.TRANSPORT: 417343, s.ODBIOR: 149777}


@pytest.mark.parametrize('metoda, pickup, oczekiwane', [
    ('Odbiór osobisty', True, 'odbior_osobisty'),
    ('Transport WoodPower', False, 'transport_woodpower'),
    ('dopłata za nasz transport 350 zł', False, 'transport_woodpower'),
    ('Transport własny', False, 'transport_woodpower'),
    ('Kurier', False, 'kurier_baselinker'),
    ('InPost-Kurier', False, 'kurier_baselinker'),
])
def test_podpowiedz_z_base(metoda, pickup, oczekiwane):
    order = NS(delivery_method=metoda, is_personal_pickup=pickup)
    assert s.podpowiedz(order) == oczekiwane
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_sposoby.py`
Expected: FAIL — `ImportError: cannot import name 'sposoby'`.

- [ ] **Step 3: Implementacja**

`modules/production/logistics/sposoby.py`:
```python
# -*- coding: utf-8 -*-
"""
Sposoby dostawy — JEDYNE miejsce, które tłumaczy wartość
prod_orders.override_delivery_method na wszystko, co z niej wynika: tryb dla
tabletu, stare delivery_type, tekst do Base., status Base. po spakowaniu
i napis na plakietce/etykiecie.

Moduł celowo nie importuje niczego z aplikacji — czytają go models.py,
baselinker_status_sync.py i API mobilne, więc import z nich tworzyłby cykle.
"""

KURIER = 'kurier_baselinker'
TRANSPORT = 'transport_woodpower'
ODBIOR = 'odbior_osobisty'
SPOSOBY = (KURIER, TRANSPORT, ODBIOR)

# Obiekt `transport.mode` w API mobilnym (kontrakt uzgodniony z appką).
MODE = {KURIER: 'kurier', TRANSPORT: 'wlasny', ODBIOR: 'odbior'}

# Stare pole `delivery_type` — tylko wartości, które znają dzisiejsze APK.
LEGACY_DELIVERY_TYPE = {KURIER: 'courier', TRANSPORT: 'transport_woodpower',
                        ODBIOR: 'personal_pickup'}

# Tekst pola „Metoda dostawy” w Base. — zawsze nadpisujemy (decyzja 24.09).
TEKST_BASE = {KURIER: 'Kurier', TRANSPORT: 'Transport WoodPower',
              ODBIOR: 'Odbiór osobisty'}

STATUS_PRODUKCJA_ZAKONCZONA = 138620
STATUS_SPAKOWANE = 138623
STATUS_PLANOWANA_TRASA = 417343
STATUS_CZEKA_NA_ODBIOR = 149777
STATUS_ODEBRANE = 149779
# Furtka pod stanowisko kierowcy — w etapie 1 nikt ich nie ustawia.
STATUS_WYSLANE_TRANSPORT = 149763
STATUS_DOSTARCZONE_TRANSPORT = 149778

STATUS_PO_SPAKOWANIU = {KURIER: STATUS_SPAKOWANE, TRANSPORT: STATUS_PLANOWANA_TRASA,
                        ODBIOR: STATUS_CZEKA_NA_ODBIOR}

NIE_USTAWIONO = 'Nie ustawiono'
_ETYKIETA = {KURIER: 'Kurier', TRANSPORT: 'Transport WoodPower', ODBIOR: 'Odbiór osobisty'}


def normalizuj(wartosc):
    """Wartość z bazy albo z żądania → jedna z SPOSOBY albo None."""
    if wartosc is None:
        return None
    w = str(wartosc).strip()
    return w if w in SPOSOBY else None


def etykieta(sposob, nazwa_trasy=None):
    """Napis dla człowieka: plakietka tabletu, linia „Dostawa:” na etykiecie, lista."""
    s = normalizuj(sposob)
    if s is None:
        return NIE_USTAWIONO
    if s == TRANSPORT and nazwa_trasy:
        return nazwa_trasy
    return _ETYKIETA[s]


def legacy_delivery_type(sposob):
    """Brak sposobu → 'courier': stare APK pokażą „KURIER” (świadomie, okres przejściowy)."""
    return LEGACY_DELIVERY_TYPE.get(normalizuj(sposob), 'courier')


def transport_payload(order, trasa=None):
    """
    Obiekt `transport` API mobilnego. ZAWSZE słownik, nigdy None — brak obiektu
    oznacza dla appki stary backend (brak blokady pakowania).
    `trasa` dochodzi w etapie 3; do tego czasu pola trip_* są puste.
    """
    sposob = normalizuj(getattr(order, 'override_delivery_method', None)) if order is not None else None
    pojazd = getattr(trasa, 'vehicle', None) if trasa is not None else None
    data = getattr(trasa, 'date_from', None) if trasa is not None else None
    return {
        'mode': MODE.get(sposob),
        'trip_name': trasa.name if trasa is not None else None,
        'trip_date': data.isoformat() if data is not None else None,
        'vehicle_name': pojazd.name if pojazd is not None else None,
        'repack_required': bool(getattr(order, 'repack_required', False)) if order is not None else False,
    }


def podpowiedz(order):
    """Sposób, który sugeruje metoda dostawy z Base. — tylko podpowiedź dla logistyka."""
    tekst = (getattr(order, 'delivery_method', None) or '').lower()
    if getattr(order, 'is_personal_pickup', False):
        return ODBIOR
    if 'transport' in tekst and ('woodpower' in tekst or 'wood power' in tekst
                                 or 'własny' in tekst or 'wlasny' in tekst or 'nasz' in tekst):
        return TRANSPORT
    return KURIER
```

- [ ] **Step 4: Uruchom testy**

Run: `PYTEST tests/test_logistyka_sposoby.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/production/logistics/sposoby.py tests/test_logistyka_sposoby.py
git commit -m "feat(production): mapowania sposobu dostawy i obiekt transport

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Serwis cyklu życia — zmiana sposobu, przepakowanie, wydanie, zamknięcie

**Files:**
- Create: `modules/production/logistics/services/delivery.py`
- Test: `tests/test_logistyka_delivery.py`

**Interfaces:**
- Consumes: `sposoby.*` (Task 2), `LogisticsLog` (Task 1), `ProductionProduct.set_quantity_done(station_code, value, source=...)` (istniejące, `models.py:512`).
- Produces (moduł `modules.production.logistics.services.delivery`):
  - `class LogistykaBlad(Exception)` z polami `komunikat: str`, `status: int` (409 domyślnie, 422 dla złych danych),
  - `aktywne_produkty(order) -> list`, `wszystkie_spakowane(order) -> bool`,
  - `zapisz_log(order, akcja, stara=None, nowa=None, user_id=None, note=None, route_id=None, teraz=None) -> None`,
  - `podbij_pozycje(order, teraz) -> None`,
  - `zamkniecie_wyliczone(order) -> bool`, `przelicz_zamkniecie(order, teraz=None) -> bool` (True = zmienił stan),
  - `odnotuj_wejscie_do_pakowania(order, teraz) -> None`, `po_spakowaniu(order, teraz) -> None`,
  - `ustaw_sposob_dostawy(order, sposob, user_id=None, teraz=None) -> dict` (`{'zmieniono': bool, 'przepakowanie': bool}`),
  - `wydaj_klientowi(order, user_id=None, teraz=None) -> None`,
  - `przelicz_otwarte(teraz=None) -> int`.
- Funkcje **nie commitują** — commit robi wołający (router/model/cron).

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_delivery.py`:
```python
# -*- coding: utf-8 -*-
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog
from modules.production.logistics.services import delivery as d
from tests.logistyka_fixtures import app, produkt, zamowienie  # noqa: F401

T0 = datetime(2026, 9, 25, 10, 0, 0)
T1 = datetime(2026, 9, 25, 11, 0, 0)


def test_ustawienie_sposobu_zapisuje_kto_kiedy_log_i_znacznik_base(app):
    with app.app_context():
        order = zamowienie(delivery_method='DPD')
        wynik = d.ustaw_sposob_dostawy(order, s.KURIER, user_id=7, teraz=T0)
        db.session.commit()
        assert wynik == {'zmieniono': True, 'przepakowanie': False}
        assert order.override_delivery_method == s.KURIER
        assert order.delivery_method_set_at == T0 and order.delivery_method_set_by == 7
        assert order.bl_delivery_method_pending is True
        assert order.bl_status_pending_id is None  # nic jeszcze nie spakowane
        log = LogisticsLog.query.filter_by(order_id=order.id).one()
        assert (log.action, log.old_value, log.new_value, log.user_id) == (
            'sposob_dostawy', None, s.KURIER, 7)


def test_ten_sam_sposob_to_brak_zmiany(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER)
        assert d.ustaw_sposob_dostawy(order, s.KURIER, teraz=T0)['zmieniono'] is False
        assert LogisticsLog.query.count() == 0


def test_bez_zapytania_do_base_gdy_tekst_juz_sie_zgadza(app):
    with app.app_context():
        order = zamowienie(delivery_method='Odbiór osobisty')
        d.ustaw_sposob_dostawy(order, s.ODBIOR, teraz=T0)
        assert order.bl_delivery_method_pending is False


def test_nieznany_sposob_to_422(app):
    with app.app_context():
        order = zamowienie()
        with pytest.raises(d.LogistykaBlad) as e:
            d.ustaw_sposob_dostawy(order, 'DPD')
        assert e.value.status == 422


def test_zmiana_sposobu_podbija_updated_at_wszystkich_pozycji(app):
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_wyciecie', 'czeka_na_pakowanie'))
        for p in order.products:
            p.updated_at = datetime(2026, 1, 1)
        db.session.commit()
        d.ustaw_sposob_dostawy(order, s.TRANSPORT, teraz=T1)
        db.session.commit()
        assert all(p.updated_at == T1 for p in order.products)


def test_zmiana_po_spakowaniu_ustawia_status_base_nowego_sposobu(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        d.ustaw_sposob_dostawy(order, s.TRANSPORT, teraz=T0)
        assert order.bl_status_pending_id == s.STATUS_PLANOWANA_TRASA
        assert order.products[0].current_status == 'spakowane'  # bez przepakowania


def test_przepakowanie_na_kuriera(app):
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane', 'spakowane'))
        wynik = d.ustaw_sposob_dostawy(order, s.KURIER, user_id=3, teraz=T0)
        db.session.commit()
        assert wynik['przepakowanie'] is True
        assert order.repack_required is True
        for p in order.products:
            assert p.current_status == 'czeka_na_pakowanie'
            assert p.quantity_done_packaging == 0
            assert p.packaging_completed_at is None
        assert order.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA
        assert order.logistics_closed_at is None
        akcje = [l.action for l in LogisticsLog.query.order_by(LogisticsLog.id)]
        assert akcje == ['sposob_dostawy', 'przepakowanie']


def test_spakowanie_po_przepakowaniu_kasuje_zalegly_status_138620(app):
    """Review Focus 3: stary 138620 nie może nadpisać świeżego 138623."""
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',))
        d.ustaw_sposob_dostawy(order, s.KURIER, teraz=T0)
        p = order.products[0]
        p.current_status = 'spakowane'
        d.po_spakowaniu(order, T1)
        assert order.repack_required is False
        assert order.bl_status_pending_id is None
        assert order.logistics_closed_at == T1  # kurier spakowany = koniec cyklu


def test_kurier_na_transport_po_spakowaniu_bez_przepakowania(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        assert d.ustaw_sposob_dostawy(order, s.ODBIOR, teraz=T0)['przepakowanie'] is False
        assert order.repack_required is False
        assert order.bl_status_pending_id == s.STATUS_CZEKA_NA_ODBIOR
        assert order.logistics_closed_at is None  # odbiór czeka na wydanie


def test_wydanie_klientowi(app):
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',))
        d.wydaj_klientowi(order, user_id=5, teraz=T0)
        assert order.handed_over_at == T0 and order.handed_over_by == 5
        assert order.bl_status_pending_id == s.STATUS_ODEBRANE
        assert order.logistics_closed_at == T0


@pytest.mark.parametrize('sposob, statusy', [
    (s.KURIER, ('spakowane',)),
    (s.ODBIOR, ('czeka_na_pakowanie',)),
])
def test_wydanie_tylko_dla_spakowanego_odbioru(app, sposob, statusy):
    with app.app_context():
        order = zamowienie(sposob=sposob, statusy=statusy)
        with pytest.raises(d.LogistykaBlad):
            d.wydaj_klientowi(order)


def test_po_wydaniu_nie_mozna_zmienic_sposobu(app):
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',))
        d.wydaj_klientowi(order, teraz=T0)
        with pytest.raises(d.LogistykaBlad) as e:
            d.ustaw_sposob_dostawy(order, s.KURIER)
        assert e.value.status == 409


@pytest.mark.parametrize('sposob, statusy, kolumny, zamkniete', [
    (None, ('anulowane',), {}, True),
    (None, ('spakowane',), {}, False),
    (s.KURIER, ('spakowane', 'anulowane'), {}, True),
    (s.KURIER, ('spakowane', 'czeka_na_pakowanie'), {}, False),
    (s.KURIER, ('spakowane',), {'repack_required': True}, False),
    (s.ODBIOR, ('spakowane',), {}, False),
    (s.ODBIOR, ('spakowane',), {'handed_over_at': T0}, True),
    (s.TRANSPORT, ('spakowane',), {}, False),
])
def test_tabela_zamkniecia(app, sposob, statusy, kolumny, zamkniete):
    with app.app_context():
        order = zamowienie(sposob=sposob, statusy=statusy, **kolumny)
        assert d.zamkniecie_wyliczone(order) is zamkniete


def test_przelicz_zamkniecie_otwiera_i_zamyka(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        assert d.przelicz_zamkniecie(order, T0) is True and order.logistics_closed_at == T0
        assert d.przelicz_zamkniecie(order, T1) is False and order.logistics_closed_at == T0
        produkt(order, status='czeka_na_wyciecie')
        assert d.przelicz_zamkniecie(order, T1) is True and order.logistics_closed_at is None


def test_wejscie_do_pakowania_ustawia_zeszlo_z_produkcji_dopiero_przy_ostatnim(app):
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_pakowanie', 'czeka_na_lakiernie'))
        d.odnotuj_wejscie_do_pakowania(order, T0)
        assert order.logistics_completed_at is None
        order.products[1].current_status = 'czeka_na_pakowanie'
        d.odnotuj_wejscie_do_pakowania(order, T1)
        assert order.logistics_completed_at == T1
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_delivery.py`
Expected: FAIL — `ImportError` (brak `delivery`).

- [ ] **Step 3: Implementacja**

`modules/production/logistics/services/delivery.py`:
```python
# -*- coding: utf-8 -*-
"""
Cykl życia zamówienia w logistyce (spec, sekcje 6.2 i 6.4).

Funkcje NIE commitują — robi to wołający (router, model, cron), żeby zmiana
sposobu dostawy, przepakowanie i log szły w jednej transakcji.
"""
from sqlalchemy.orm import selectinload

from extensions import db
from modules.production.logistics import sposoby
from modules.production.logistics.models import LogisticsLog
from modules.production.models import get_local_now

STATUSY_PO_PRODUKCJI = ('czeka_na_pakowanie', 'spakowane')


class LogistykaBlad(Exception):
    """Odmowa z komunikatem dla człowieka. status = kod HTTP (409 stan, 422 dane)."""

    def __init__(self, komunikat, status=409):
        super().__init__(komunikat)
        self.komunikat = komunikat
        self.status = status


def aktywne_produkty(order):
    return [p for p in order.products if p.current_status != 'anulowane']


def wszystkie_spakowane(order):
    aktywne = aktywne_produkty(order)
    return bool(aktywne) and all(p.current_status == 'spakowane' for p in aktywne)


def zapisz_log(order, akcja, stara=None, nowa=None, user_id=None, note=None,
               route_id=None, teraz=None):
    db.session.add(LogisticsLog(
        order_id=order.id, action=akcja, old_value=stara, new_value=nowa,
        user_id=user_id, note=note, route_id=route_id,
        created_at=teraz or get_local_now()))


def podbij_pozycje(order, teraz):
    """ETag kolejek tabletów liczy się z MAX(updated_at) pozycji — bez tego tablet dostanie 304."""
    for p in order.products:
        p.updated_at = teraz


def zamkniecie_wyliczone(order):
    """Tabela z sekcji 6.2 specu. Transport własny zamyka dopiero trasa wykonana (etap 3)."""
    aktywne = aktywne_produkty(order)
    if not aktywne:
        return True
    sposob = sposoby.normalizuj(order.override_delivery_method)
    if sposob is None or order.repack_required:
        return False
    if sposob == sposoby.KURIER:
        return all(p.current_status == 'spakowane' for p in aktywne)
    if sposob == sposoby.ODBIOR:
        return order.handed_over_at is not None
    return False


def przelicz_zamkniecie(order, teraz=None):
    """Ustawia albo czyści logistics_closed_at. Zwraca True, gdy stan się zmienił."""
    zamkniete = zamkniecie_wyliczone(order)
    if zamkniete and order.logistics_closed_at is None:
        order.logistics_closed_at = teraz or get_local_now()
        return True
    if not zamkniete and order.logistics_closed_at is not None:
        order.logistics_closed_at = None
        return True
    return False


def odnotuj_wejscie_do_pakowania(order, teraz):
    """„Zeszło z produkcji” (Arkusz): chwila, gdy OSTATNI aktywny produkt wszedł do pakowania."""
    if order.logistics_completed_at is not None:
        return
    aktywne = aktywne_produkty(order)
    if aktywne and all(p.current_status in STATUSY_PO_PRODUKCJI for p in aktywne):
        order.logistics_completed_at = teraz


def po_spakowaniu(order, teraz):
    """Wołane z complete_task('packaging'). Kończy przepakowanie i przelicza cykl."""
    if order.repack_required and wszystkie_spakowane(order):
        order.repack_required = False
        # Zaległe 138620 z przepakowania nie może nadpisać 138623, które właśnie
        # wysyła ścieżka pakowania (baselinker_status_sync).
        if order.bl_status_pending_id == sposoby.STATUS_PRODUKCJA_ZAKONCZONA:
            order.bl_status_pending_id = None
        podbij_pozycje(order, teraz)
    przelicz_zamkniecie(order, teraz)


def ustaw_sposob_dostawy(order, sposob, user_id=None, teraz=None):
    nowy = sposoby.normalizuj(sposob)
    if nowy is None:
        raise LogistykaBlad(u'Nieznany sposób dostawy: {}'.format(sposob), status=422)
    if order.handed_over_at is not None:
        raise LogistykaBlad(u'Zamówienie {} zostało już wydane klientowi.'.format(
            order.internal_order_number))
    if not aktywne_produkty(order):
        raise LogistykaBlad(u'Zamówienie {} jest anulowane.'.format(order.internal_order_number))

    stary = sposoby.normalizuj(order.override_delivery_method)
    if stary == nowy:
        return {'zmieniono': False, 'przepakowanie': False}

    teraz = teraz or get_local_now()
    order.override_delivery_method = nowy
    order.delivery_method_set_at = teraz
    order.delivery_method_set_by = user_id
    zapisz_log(order, 'sposob_dostawy', stary, nowy, user_id=user_id, teraz=teraz)

    spakowane = [p for p in aktywne_produkty(order) if p.current_status == 'spakowane']
    przepakowanie = (nowy == sposoby.KURIER
                     and stary in (sposoby.TRANSPORT, sposoby.ODBIOR)
                     and bool(spakowane))
    if przepakowanie:
        order.repack_required = True
        for p in spakowane:
            # Zdarzenie systemowe bez atrybucji: cofnięcie spakowania nie jest
            # niczyją pracą, a statystyki pierwotnego pakowacza zostają.
            p.set_quantity_done('packaging', 0, source='system')
            p.packaging_completed_at = None
            p.current_status = 'czeka_na_pakowanie'
        if all(p.current_status in STATUSY_PO_PRODUKCJI for p in aktywne_produkty(order)):
            order.bl_status_pending_id = sposoby.STATUS_PRODUKCJA_ZAKONCZONA
        zapisz_log(order, 'przepakowanie', stary, nowy, user_id=user_id, teraz=teraz)
    elif wszystkie_spakowane(order):
        order.bl_status_pending_id = sposoby.STATUS_PO_SPAKOWANIU[nowy]

    if (order.delivery_method or '').strip() != sposoby.TEKST_BASE[nowy]:
        order.bl_delivery_method_pending = True

    podbij_pozycje(order, teraz)
    przelicz_zamkniecie(order, teraz)
    return {'zmieniono': True, 'przepakowanie': przepakowanie}


def wydaj_klientowi(order, user_id=None, teraz=None):
    if sposoby.normalizuj(order.override_delivery_method) != sposoby.ODBIOR:
        raise LogistykaBlad(u'„Wydane klientowi” dotyczy tylko odbioru osobistego.')
    if order.handed_over_at is not None:
        raise LogistykaBlad(u'Zamówienie {} jest już wydane.'.format(order.internal_order_number))
    if not wszystkie_spakowane(order):
        raise LogistykaBlad(u'Zamówienie {} nie jest jeszcze w całości spakowane.'.format(
            order.internal_order_number))
    teraz = teraz or get_local_now()
    order.handed_over_at = teraz
    order.handed_over_by = user_id
    order.bl_status_pending_id = sposoby.STATUS_ODEBRANE
    zapisz_log(order, 'wydane', user_id=user_id, teraz=teraz)
    podbij_pozycje(order, teraz)
    przelicz_zamkniecie(order, teraz)


def przelicz_otwarte(teraz=None):
    """
    Siatka bezpieczeństwa dla crona: przelicza zamówienia otwarte oraz zamknięte,
    które znów mają aktywne produkty (Base. dołożył pozycję, doróbka).
    """
    from modules.production.models import ProductionOrder, ProductionProduct
    teraz = teraz or get_local_now()
    otwarte = (ProductionOrder.query.options(selectinload(ProductionOrder.products))
               .filter(ProductionOrder.logistics_closed_at.is_(None)).all())
    do_otwarcia = (ProductionOrder.query.options(selectinload(ProductionOrder.products))
                   .filter(ProductionOrder.logistics_closed_at.isnot(None))
                   .filter(ProductionOrder.products.any(
                       ProductionProduct.current_status.notin_(('spakowane', 'anulowane'))))
                   .all())
    return sum(1 for order in otwarte + do_otwarcia if przelicz_zamkniecie(order, teraz))
```

- [ ] **Step 4: Uruchom testy**

Run: `PYTEST tests/test_logistyka_delivery.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/production/logistics/services/delivery.py tests/test_logistyka_delivery.py
git commit -m "feat(production): cykl zycia zamowienia w logistyce, przepakowanie i wydanie

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Pipeline bez logistyki + status Base. po spakowaniu

**Files:**
- Modify: `modules/production/models.py:590-645` (`should_skip_to_logistics`, `complete_task`)
- Modify: `modules/production/services/baselinker_status_sync.py:1-35` (docstring), `:50-54`, `:235-262`
- Modify: `modules/production/services/mobile_api_service.py:1211-1225` (docstring `mark_order_complete` — usuń zdanie o omijaniu logistyki)
- Modify tests: `tests/test_routing_krawedzie.py`, `tests/test_krawedzie_parytet_reguly.py:95,109`, `tests/test_mobile_api_alias_krawedzi.py:126,358,544`, `tests/test_baselinker_krawedzie.py`
- Test: `tests/test_logistyka_pipeline.py`

**Interfaces:**
- Consumes: `delivery.odnotuj_wejscie_do_pakowania`, `delivery.po_spakowaniu` (Task 3), `sposoby.normalizuj`, `sposoby.STATUS_PO_SPAKOWANIU` (Task 2).
- Produces: `complete_task` nigdy nie ustawia `czeka_na_logistyke`; `baselinker_status_sync.POSTPROD_STATUSES == {'czeka_na_pakowanie', 'spakowane'}`; `_determine_packaging_target_status(order)` czyta wyłącznie `override_delivery_method`.

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_pipeline.py`:
```python
# -*- coding: utf-8 -*-
import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.services import baselinker_status_sync as bl
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401


@pytest.mark.parametrize('stanowisko, status, kolumny', [
    ('edges', 'czeka_na_krawedzie', {'parsed_edge_processing': True}),
    ('painting', 'czeka_na_lakiernie', {'parsed_finish_type': 'olejowane'}),
    ('formatting', 'czeka_na_formatowanie', {'parsed_edge_processing': False}),
    ('gluing', 'czeka_na_sklejanie', {'cut_to_size': False}),
])
def test_kazde_wyjscie_z_produkcji_prowadzi_do_pakowania(app, stanowisko, status, kolumny):
    with app.app_context():
        order = zamowienie(statusy=(status,))
        p = order.products[0]
        for k, v in kolumny.items():
            setattr(p, k, v)
        p.complete_task(stanowisko)
        db.session.commit()
        assert p.current_status == 'czeka_na_pakowanie'
        assert order.logistics_completed_at is not None


def test_odbior_osobisty_nie_omija_logistyki_i_nie_dostaje_sposobu(app):
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_krawedzie',), delivery_method='Odbiór osobisty')
        p = order.products[0]
        p.parsed_edge_processing = True
        p.complete_task('edges')
        assert p.current_status == 'czeka_na_pakowanie'
        assert order.override_delivery_method is None


def test_spakowanie_kuriera_zamyka_cykl(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
        order.products[0].complete_task('packaging')
        assert order.products[0].current_status == 'spakowane'
        assert order.logistics_closed_at is not None


def test_postprod_bez_logistyki():
    assert bl.POSTPROD_STATUSES == frozenset({'czeka_na_pakowanie', 'spakowane'})


@pytest.mark.parametrize('sposob, status', [
    (s.KURIER, 138623), (s.TRANSPORT, 417343), (s.ODBIOR, 149777), (None, 138623),
])
def test_status_base_po_spakowaniu_tylko_z_decyzji_logistyki(app, sposob, status):
    with app.app_context():
        # Heurystyka odbioru z Base. już NIE decyduje — tylko override.
        order = zamowienie(sposob=sposob, delivery_method='Odbiór osobisty')
        assert bl._determine_packaging_target_status(order) == status
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_pipeline.py`
Expected: FAIL (produkty lądują w `czeka_na_logistyke`, `POSTPROD_STATUSES` zawiera logistykę).

- [ ] **Step 3: Model — `complete_task`**

W `modules/production/models.py`:
1. `should_skip_to_logistics` (`:590-591`) zmień nazwę na `should_skip_formatting` i docstring: `"""Bez docięcia na wymiar produkt omija formatowanie i Krawędzie — idzie prosto do pakowania."""`. Zmień jedyne wywołanie w `complete_task` (`:614`).
2. W `next_status_map` (`:602-610`) `'edges'` i `'painting'` → `'czeka_na_pakowanie'`.
3. W bloku gluing (`:614-615`) `next_status = 'czeka_na_pakowanie'`.
4. W bloku formatowania bez krawędzi (`:626-631`) gałąź `else` → `next_status = 'czeka_na_pakowanie'`; komentarz nad blokiem zmień na: `# Trzecie wyjście z formatowania: bez obróbki krawędzi → Lakiernia (olej/lakier) albo prosto do pakowania.`
5. **Usuń** blok odbioru osobistego (`:637-640`).
6. Po `self.current_status = next_status` (`:642`) dopisz:
```python
            # Logistyka jest równoległa do produkcji (spec 2026-09-24): produkcja
            # kończy się wejściem do pakowania, a sposób dostawy żyje na zamówieniu.
            if self.order is not None:
                from modules.production.logistics.services import delivery as _logistyka
                if next_status == 'czeka_na_pakowanie':
                    _logistyka.odnotuj_wejscie_do_pakowania(self.order, now)
                elif next_status == 'spakowane':
                    _logistyka.po_spakowaniu(self.order, now)
```

- [ ] **Step 4: Status Base.**

W `modules/production/services/baselinker_status_sync.py`:
- `:53-54`:
```python
# Statusy lokalne CRM oznaczające „produkcja zakończona” (czeka na pakowanie / po pakowaniu).
# Logistyka nie jest już etapem — żyje równolegle na zamówieniu.
POSTPROD_STATUSES = frozenset({'czeka_na_pakowanie', 'spakowane'})
```
- `_determine_packaging_target_status` (`:235-262`) zastąp:
```python
def _determine_packaging_target_status(order) -> int:
    """
    Status Base. po spakowaniu ostatniego produktu — WYŁĄCZNIE z decyzji logistyka
    (override_delivery_method), mapa w logistics/sposoby.py. Heurystyka odbioru
    osobistego z metody dostawy Base. nie decyduje już o niczym.

    Brak decyzji jest możliwy tylko przez ręczną zmianę statusu przez admina
    (tablet bez sposobu dostawy dostaje 409) → 138623 z ostrzeżeniem.
    """
    from modules.production.logistics import sposoby
    sposob = sposoby.normalizuj(order.override_delivery_method)
    if sposob is not None:
        return sposoby.STATUS_PO_SPAKOWANIU[sposob]
    logger.warning("Pakowanie ukończone bez decyzji logistyki - fallback na 'spakowane'", extra={
        'internal_order_number': order.internal_order_number,
        'baselinker_order_id': order.baselinker_order_id,
    })
    return ORDER_PACKED_STATUS_ID
```
- W docstringu modułu (`:17-21`) zdanie „Wyjść z produkcji jest trzy…” zostaw; dopisz: `Warunek: wszystkie pozycje w POSTPROD_STATUSES (pakowanie / spakowane).`

- [ ] **Step 5: Aktualizacja istniejących testów**

Zasada: tam, gdzie test oczekiwał `czeka_na_logistyke` jako wyniku stanowiska, oczekuje teraz `czeka_na_pakowanie`. Konkretnie:
- `tests/test_routing_krawedzie.py`: wszystkie asercje `== 'czeka_na_logistyke'` → `== 'czeka_na_pakowanie'`; nazwy testów z „logistyki” → „pakowania” (np. `test_z_krawedzi_surowy_idzie_do_pakowania`); test `test_odbior_osobisty_zamienia_logistyke_na_pakowanie_na_kazdym_z_trzech_wyjsc` przemianuj na `test_odbior_osobisty_idzie_do_pakowania_jak_kazde_zamowienie`, zostaw asercje statusów, a ostatnią zamień na `assert z_lakierni.order.override_delivery_method is None`; docstring pliku: „→ logistyka” → „→ pakowanie”; w helperze `_produkt` usuń zdanie o tym, że heurystyka „zamieniłaby logistykę na pakowanie”.
- `tests/test_krawedzie_parytet_reguly.py:95,109`: `'czeka_na_logistyke'` → `'czeka_na_pakowanie'`.
- `tests/test_mobile_api_alias_krawedzi.py:358,544`: j.w.; docstring `:126` — usuń zdanie o zamianie logistyki na pakowanie przy odbiorze.
- `tests/test_baselinker_krawedzie.py`: jeśli któryś test sprawdza `'czeka_na_logistyke' in bl.POSTPROD_STATUSES`, zmień na `not in`.

- [ ] **Step 6: Uruchom testy**

Run: `PYTEST tests/test_logistyka_pipeline.py tests/test_routing_krawedzie.py tests/test_krawedzie_parytet_reguly.py tests/test_mobile_api_alias_krawedzi.py tests/test_baselinker_krawedzie.py tests/test_logistyka_delivery.py`
Expected: PASS. Jeśli `test_mobile_api_alias_krawedzi.py` pada na pakowaniu z powodu 409 — to Task 7; tu nie powinien (409 dochodzi dopiero w Task 7).

- [ ] **Step 7: Commit**

```bash
git add modules/production/models.py modules/production/services/baselinker_status_sync.py modules/production/services/mobile_api_service.py tests/
git commit -m "feat(production): produkcja konczy sie wejsciem do pakowania, logistyka poza pipeline'em

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Wysyłka do Base. — dzierżawa, znaczniki, pauza, dopychacz w tle

**Files:**
- Create: `modules/production/logistics/services/dzierzawa.py`
- Create: `modules/production/logistics/services/bl_sync.py`
- Test: `tests/test_logistyka_bl_sync.py`

**Interfaces:**
- Consumes: `sposoby.TEKST_BASE`, `sposoby.normalizuj`, `sposoby.STATUS_WYSLANE_TRANSPORT`, `sposoby.STATUS_DOSTARCZONE_TRANSPORT`; `get_sync_service()._make_api_request(dict)` i `.api_key` (`modules/production/services/sync_service.py:2811, :3687`); `ProductionConfig` (`prod_config`: `config_key`, `config_value`, `config_type`, `config_description`).
- Produces:
  - moduł `modules.production.logistics.services.dzierzawa`: `ZERO = '1970-01-01T00:00:00'`, `wiersz(klucz) -> ProductionConfig`, `przejmij(klucz, czas_s, teraz=None) -> Optional[str]`, `odnow(klucz, znacznik, czas_s, teraz=None) -> Optional[str]`, `zwolnij(klucz, znacznik) -> None`. **Etap 2 użyje tego modułu dla geokodowania** (klucz `logistyka_geo_dzierzawa`).
  - moduł `modules.production.logistics.services.bl_sync`: stałe `ODSTEP_S = 1.5`, `CZAS_DZIERZAWY_S = 90`, `KLUCZ_DZIERZAWY = 'logistyka_bl_dzierzawa'`, `KLUCZ_PAUZY = 'logistyka_bl_wstrzymane_do'`; `class LimitBase(Exception)` (`do_kiedy: datetime`); `wyslij_zamowienie(order) -> int`; `wstrzymane_do(teraz=None) -> Optional[datetime]`; `wstrzymaj_do(chwila) -> None`; `dopychaj(limit_zapytan=None, limit_czasu_s=None, spij=time.sleep, zegar=time.monotonic) -> dict` (`{'zamowienia', 'zapytania', 'wstrzymane', 'dzierzawa'}`); `uruchom_w_tle(app) -> bool`; `po_zmianie(order_ids) -> None`; `oznacz_wyslane(order)`, `oznacz_dostarczone(order)`.

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_bl_sync.py`:
```python
# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import bl_sync, dzierzawa
from modules.production.models import ProductionOrder
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401


class FakeBase(object):
    """Podstawka pod get_sync_service(): zapisuje wywołania, odpowiada skryptem."""

    def __init__(self, odpowiedzi=None):
        self.api_key = 'token'
        self.wywolania = []
        self.odpowiedzi = list(odpowiedzi or [])

    def _make_api_request(self, dane):
        import json
        self.wywolania.append((dane['method'], json.loads(dane['parameters'])))
        if self.odpowiedzi:
            return self.odpowiedzi.pop(0)
        return {'status': 'SUCCESS'}


@pytest.fixture()
def base(monkeypatch):
    fake = FakeBase()
    import modules.production.services.sync_service as ss
    monkeypatch.setattr(ss, 'get_sync_service', lambda: fake)
    return fake


def test_wysylka_metody_i_statusu_czysci_znaczniki(app, base):
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, delivery_method='Kurier',
                           bl_delivery_method_pending=True, bl_status_pending_id=417343)
        assert bl_sync.wyslij_zamowienie(order) == 2
        assert base.wywolania == [
            ('setOrderFields', {'order_id': order.baselinker_order_id,
                                'delivery_method': 'Transport WoodPower'}),
            ('setOrderStatus', {'order_id': order.baselinker_order_id, 'status_id': 417343}),
        ]
        assert order.bl_delivery_method_pending is False
        assert order.bl_status_pending_id is None
        assert order.delivery_method == 'Transport WoodPower'


def test_brak_zapytania_gdy_tekst_juz_zgodny(app, base):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, delivery_method='Kurier',
                           bl_delivery_method_pending=True)
        assert bl_sync.wyslij_zamowienie(order) == 0
        assert base.wywolania == [] and order.bl_delivery_method_pending is False


def test_blad_base_zostawia_znacznik(app, base):
    base.odpowiedzi = [{'status': 'ERROR', 'error_message': 'Invalid order_id'}]
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, bl_delivery_method_pending=True)
        bl_sync.wyslij_zamowienie(order)
        assert order.bl_delivery_method_pending is True


def test_limit_base_wstrzymuje_i_zostawia_znaczniki(app, base):
    """Review Focus 2."""
    base.odpowiedzi = [{'status': 'ERROR', 'error_message':
                        'Query limit exceeded, token blocked until 2099-01-01 15:40:05'}]
    with app.app_context():
        a = zamowienie(sposob=s.KURIER, bl_delivery_method_pending=True)
        b = zamowienie(sposob=s.ODBIOR, bl_delivery_method_pending=True)
        wynik = bl_sync.dopychaj(spij=lambda _: None)
        assert wynik['wstrzymane'] is True
        assert bl_sync.wstrzymane_do() == datetime(2099, 1, 1, 15, 40, 5)
        db.session.expire_all()
        assert ProductionOrder.query.get(a.id).bl_delivery_method_pending is True
        assert ProductionOrder.query.get(b.id).bl_delivery_method_pending is True
        assert len(base.wywolania) == 1  # po limicie nie pytamy dalej


def test_pauza_blokuje_dopychacz(app, base):
    """Review Focus 2."""
    with app.app_context():
        zamowienie(sposob=s.KURIER, bl_delivery_method_pending=True)
        bl_sync.wstrzymaj_do(datetime(2099, 1, 1))
        assert bl_sync.dopychaj(spij=lambda _: None)['wstrzymane'] is True
        assert base.wywolania == []


def test_druga_dzierzawa_jest_odrzucona(app):
    """Review Focus 1: jeden nadawca na cały serwer."""
    with app.app_context():
        teraz = datetime(2026, 9, 25, 12, 0, 0)
        klucz = bl_sync.KLUCZ_DZIERZAWY
        assert dzierzawa.przejmij(klucz, 90, teraz) is not None
        assert dzierzawa.przejmij(klucz, 90, teraz + timedelta(seconds=10)) is None
        # Po wygaśnięciu dzierżawy (proces padł) ktoś inny może ją przejąć.
        assert dzierzawa.przejmij(klucz, 90, teraz + timedelta(seconds=91)) is not None


def test_dzierzawy_o_roznych_kluczach_sa_niezalezne(app):
    with app.app_context():
        teraz = datetime(2026, 9, 25, 12, 0, 0)
        assert dzierzawa.przejmij('logistyka_bl_dzierzawa', 90, teraz)
        assert dzierzawa.przejmij('logistyka_geo_dzierzawa', 90, teraz)


def test_dopychacz_ma_odstep_i_zwalnia_dzierzawe(app, base):
    przerwy = []
    with app.app_context():
        for _ in range(3):
            zamowienie(sposob=s.TRANSPORT, bl_delivery_method_pending=True)
        wynik = bl_sync.dopychaj(spij=przerwy.append)
        assert wynik['zapytania'] == 3
        assert przerwy == [bl_sync.ODSTEP_S] * 3
        assert dzierzawa.przejmij(bl_sync.KLUCZ_DZIERZAWY, 90) is not None  # zwolniona


def test_limit_zapytan_przebiegu(app, base):
    with app.app_context():
        for _ in range(5):
            zamowienie(sposob=s.TRANSPORT, bl_delivery_method_pending=True)
        assert bl_sync.dopychaj(limit_zapytan=2, spij=lambda _: None)['zapytania'] == 2


def test_nieudane_zamowienie_nie_mieli_sie_w_kolko(app, base):
    base.odpowiedzi = [{'status': 'ERROR', 'error_message': 'x'}] * 10
    with app.app_context():
        zamowienie(sposob=s.TRANSPORT, bl_delivery_method_pending=True)
        wynik = bl_sync.dopychaj(spij=lambda _: None)
        assert wynik['zapytania'] == 1


def test_zamowienie_bez_id_base_czysci_znaczniki_bez_zapytania(app, base):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, bl_delivery_method_pending=True)
        order.baselinker_order_id = 0
        assert bl_sync.wyslij_zamowienie(order) == 0
        assert order.bl_delivery_method_pending is False and base.wywolania == []


def test_po_zmianie_uruchamia_dopychacz_w_tle_bez_zapytan_w_zadaniu(app, base, monkeypatch):
    """Timeout gunicorna 30 s: żądanie HTTP nigdy nie czeka na Base."""
    uruchomione = []
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: uruchomione.append(1))
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, bl_delivery_method_pending=True)
        bl_sync.po_zmianie([order.id])
        assert base.wywolania == [] and uruchomione == [1]


def test_po_zmianie_bez_zamowien_nic_nie_robi(app, monkeypatch):
    uruchomione = []
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: uruchomione.append(1))
    with app.app_context():
        bl_sync.po_zmianie([])
        assert uruchomione == []


def test_furtka_kierowcy_ustawia_znaczniki():
    from types import SimpleNamespace as NS
    order = NS(bl_status_pending_id=None)
    bl_sync.oznacz_wyslane(order)
    assert order.bl_status_pending_id == 149763
    bl_sync.oznacz_dostarczone(order)
    assert order.bl_status_pending_id == 149778
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_bl_sync.py`
Expected: FAIL — brak modułów `bl_sync`, `dzierzawa`.

- [ ] **Step 3: Dzierżawa**

`modules/production/logistics/services/dzierzawa.py`:
```python
# -*- coding: utf-8 -*-
"""
Dzierżawa „jeden wykonawca na cały serwer” w tabeli prod_config.

Gunicorn ma kilka workerów (procesów). Wątek w tle uruchomiony w każdym z nich
osobno przekroczyłby limity usług zewnętrznych (Base.: 100 zapytań/min na konto,
Nominatim: 1 zapytanie/s). Dzierżawa to wiersz prod_config z chwilą ważności
w ISO; przejmuje ją warunkowy UPDATE (atomowy w MySQL), odnawia porównanie
z poprzednią wartością. Proces, który padł, oddaje ją sam po `czas_s`.

Klucze: 'logistyka_bl_dzierzawa' (wysyłka do Base., etap 1),
'logistyka_geo_dzierzawa' (geokodowanie, etap 2).
"""
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.production.models import ProductionConfig, get_local_now

ZERO = '1970-01-01T00:00:00'


def _iso(chwila):
    return chwila.replace(microsecond=0).isoformat()


def wiersz(klucz):
    """Wiersz prod_config; tworzy go, jeśli migracja go nie założyła (testy, świeża baza)."""
    rekord = ProductionConfig.query.filter_by(config_key=klucz).first()
    if rekord is None:
        db.session.add(ProductionConfig(
            config_key=klucz, config_value=ZERO, config_type='string',
            config_description=u'Logistyka: stan pracy w tle'))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
        rekord = ProductionConfig.query.filter_by(config_key=klucz).first()
    return rekord


def przejmij(klucz, czas_s, teraz=None):
    """Znacznik ważności przy sukcesie, None gdy dzierżawę trzyma ktoś inny."""
    teraz = teraz or get_local_now()
    wiersz(klucz)
    nowa = _iso(teraz + timedelta(seconds=czas_s))
    wynik = db.session.execute(
        text('UPDATE prod_config SET config_value = :nowa '
             'WHERE config_key = :klucz AND config_value < :teraz'),
        {'nowa': nowa, 'klucz': klucz, 'teraz': _iso(teraz)})
    db.session.commit()
    return nowa if wynik.rowcount == 1 else None


def odnow(klucz, znacznik, czas_s, teraz=None):
    """Przedłuża własną dzierżawę; None, gdy ktoś ją przejął (nasza wygasła)."""
    teraz = teraz or get_local_now()
    nowa = _iso(teraz + timedelta(seconds=czas_s))
    if nowa == znacznik:
        return znacznik
    wynik = db.session.execute(
        text('UPDATE prod_config SET config_value = :nowa '
             'WHERE config_key = :klucz AND config_value = :stara'),
        {'nowa': nowa, 'klucz': klucz, 'stara': znacznik})
    db.session.commit()
    return nowa if wynik.rowcount == 1 else None


def zwolnij(klucz, znacznik):
    db.session.execute(
        text('UPDATE prod_config SET config_value = :zero '
             'WHERE config_key = :klucz AND config_value = :znacznik'),
        {'zero': ZERO, 'klucz': klucz, 'znacznik': znacznik})
    db.session.commit()
```

- [ ] **Step 4: Wysyłka do Base.**

`modules/production/logistics/services/bl_sync.py`:
```python
# -*- coding: utf-8 -*-
"""
Wysyłka decyzji logistyki do Base. (spec, sekcja 6.3).

LIMIT API: 100 zapytań/min NA CAŁE KONTO, wspólny z synchronizacją CRM.
24.09.2026 skrypt bez odstępu zablokował token całego konta (memory:
feedback_baselinker_limit_api). Dlatego:
  - decyzja zapisuje w zamówieniu ZNACZNIKI (przeżywają restart gunicorna),
  - wysyła JEDEN wątek na cały serwer (dzierżawa, services/dzierzawa.py),
  - odstęp ODSTEP_S między zapytaniami (≤ 40/min),
  - „Query limit exceeded / token blocked until …” wstrzymuje wszystkie
    wysyłki logistyki do podanej chwili (zapisanej w prod_config).
TIMEOUT: sync worker gunicorna ma 30 s na żądanie — Base. wołamy WYŁĄCZNIE
z wątku w tle (uruchom_w_tle), nigdy w żądaniu HTTP.
"""
import json
import re
import threading
import time
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import or_

from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import sposoby
from modules.production.logistics.services import dzierzawa
from modules.production.models import ProductionOrder, get_local_now

logger = get_structured_logger('production.logistics.bl_sync')

ODSTEP_S = 1.5
CZAS_DZIERZAWY_S = 90
DOMYSLNA_PAUZA = timedelta(minutes=15)
KLUCZ_DZIERZAWY = 'logistyka_bl_dzierzawa'
KLUCZ_PAUZY = 'logistyka_bl_wstrzymane_do'
_WZOR_BLOKADY = re.compile(r'until\s+(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})')


class LimitBase(Exception):
    """Base. odrzucił zapytanie z powodu limitu — nie pytamy do `do_kiedy`."""

    def __init__(self, do_kiedy):
        super().__init__(str(do_kiedy))
        self.do_kiedy = do_kiedy


# ── Pauza po limicie ───────────────────────────────────────────────────────

def wstrzymane_do(teraz=None):
    teraz = teraz or get_local_now()
    db.session.expire_all()
    try:
        chwila = datetime.fromisoformat(dzierzawa.wiersz(KLUCZ_PAUZY).config_value)
    except ValueError:
        return None
    return chwila if chwila > teraz else None


def wstrzymaj_do(chwila):
    rekord = dzierzawa.wiersz(KLUCZ_PAUZY)
    rekord.config_value = chwila.replace(microsecond=0).isoformat()
    db.session.commit()


# ── Pojedyncze zapytanie i zamówienie ─────────────────────────────────────

def _wywolaj(metoda, parametry):
    """True przy SUCCESS, False przy błędzie; LimitBase przy limicie konta."""
    from modules.production.services.sync_service import get_sync_service
    serwis = get_sync_service()
    if serwis is None or not getattr(serwis, 'api_key', None):
        logger.error("Brak klucza API Base. - wysylka logistyki pominieta")
        return False
    try:
        odpowiedz = serwis._make_api_request({
            'token': serwis.api_key, 'method': metoda,
            'parameters': json.dumps(parametry)})
    except Exception as e:  # SyncError po wyczerpaniu prób sieciowych
        logger.error("Blad sieci przy wysylce logistyki do Base.", extra={
            'metoda': metoda, 'error': str(e)})
        return False
    if odpowiedz.get('status') == 'SUCCESS':
        return True
    komunikat = odpowiedz.get('error_message') or ''
    if 'limit' in komunikat.lower() or 'blocked' in komunikat.lower():
        dopasowanie = _WZOR_BLOKADY.search(komunikat)
        if dopasowanie:
            do_kiedy = datetime.fromisoformat('{}T{}'.format(*dopasowanie.groups()))
        else:
            do_kiedy = get_local_now() + DOMYSLNA_PAUZA
        raise LimitBase(do_kiedy)
    logger.error("Base. odrzucil zapis logistyki", extra={
        'metoda': metoda, 'order_id': parametry.get('order_id'), 'error': komunikat})
    return False


def wyslij_zamowienie(order):
    """Wysyła znaczniki jednego zamówienia. Zwraca liczbę zapytań. NIE commituje."""
    if not order.baselinker_order_id:
        order.bl_delivery_method_pending = False
        order.bl_status_pending_id = None
        return 0
    zapytania = 0
    if order.bl_delivery_method_pending:
        tekst = sposoby.TEKST_BASE.get(sposoby.normalizuj(order.override_delivery_method))
        if tekst is None or (order.delivery_method or '').strip() == tekst:
            order.bl_delivery_method_pending = False
        else:
            zapytania += 1
            if _wywolaj('setOrderFields', {'order_id': order.baselinker_order_id,
                                           'delivery_method': tekst}):
                order.delivery_method = tekst
                order.bl_delivery_method_pending = False
    if order.bl_status_pending_id:
        zapytania += 1
        if _wywolaj('setOrderStatus', {'order_id': order.baselinker_order_id,
                                       'status_id': order.bl_status_pending_id}):
            order.bl_status_pending_id = None
    return zapytania


# ── Dopychacz ─────────────────────────────────────────────────────────────

def _czeka(order):
    return bool(order.bl_delivery_method_pending or order.bl_status_pending_id)


def dopychaj(limit_zapytan=None, limit_czasu_s=None, spij=time.sleep, zegar=time.monotonic):
    wynik = {'zamowienia': 0, 'zapytania': 0, 'wstrzymane': False, 'dzierzawa': False}
    if wstrzymane_do() is not None:
        wynik['wstrzymane'] = True
        return wynik
    znacznik = dzierzawa.przejmij(KLUCZ_DZIERZAWY, CZAS_DZIERZAWY_S)
    if znacznik is None:
        return wynik
    wynik['dzierzawa'] = True
    start = zegar()
    pominiete = []
    try:
        while True:
            if limit_zapytan is not None and wynik['zapytania'] >= limit_zapytan:
                break
            if limit_czasu_s is not None and zegar() - start >= limit_czasu_s:
                break
            zapytanie = ProductionOrder.query.filter(or_(
                ProductionOrder.bl_delivery_method_pending.is_(True),
                ProductionOrder.bl_status_pending_id.isnot(None)))
            if pominiete:
                zapytanie = zapytanie.filter(~ProductionOrder.id.in_(pominiete))
            order = zapytanie.order_by(ProductionOrder.id).first()
            if order is None:
                break
            try:
                zapytania = wyslij_zamowienie(order)
            except LimitBase as e:
                db.session.commit()  # to, co przeszło przed limitem, zostaje
                wstrzymaj_do(e.do_kiedy)
                logger.error("Limit API Base. - wysylki logistyki wstrzymane", extra={
                    'do_kiedy': e.do_kiedy.isoformat()})
                wynik['wstrzymane'] = True
                wynik['zapytania'] += 1
                break
            db.session.commit()
            wynik['zamowienia'] += 1
            wynik['zapytania'] += zapytania
            if _czeka(order):
                pominiete.append(order.id)  # nieudane — nie mielimy w kółko w tym przebiegu
            znacznik = dzierzawa.odnow(KLUCZ_DZIERZAWY, znacznik, CZAS_DZIERZAWY_S)
            if znacznik is None:
                break
            if zapytania:
                spij(ODSTEP_S)
    finally:
        if znacznik:
            dzierzawa.zwolnij(KLUCZ_DZIERZAWY, znacznik)
    return wynik


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
                    dopychaj()
                except Exception as e:
                    logger.error("Dopychacz logistyki przerwany", extra={'error': str(e)})
                finally:
                    db.session.remove()

        _watek = threading.Thread(target=_praca, name='logistyka-base', daemon=True)
        _watek.start()
        return True


def po_zmianie(order_ids):
    """Wołać PO commicie decyzji logistyka. Nigdy nie woła Base. w żądaniu (timeout 30 s)."""
    if not order_ids:
        return
    uruchom_w_tle(current_app._get_current_object())


# ── Furtka pod stanowisko kierowcy (etap „kierowca”, dziś NIEWOŁANE) ──────

def oznacz_wyslane(order):
    order.bl_status_pending_id = sposoby.STATUS_WYSLANE_TRANSPORT


def oznacz_dostarczone(order):
    order.bl_status_pending_id = sposoby.STATUS_DOSTARCZONE_TRANSPORT
```

- [ ] **Step 5: Uruchom testy**

Run: `PYTEST tests/test_logistyka_bl_sync.py`
Expected: PASS. Jeśli `test_dopychacz_ma_odstep_i_zwalnia_dzierzawe` pada na `odnow` zwracającym `None` — sprawdź gałąź `nowa == znacznik` (ta sama sekunda).

- [ ] **Step 6: Commit**

```bash
git add modules/production/logistics/services/dzierzawa.py modules/production/logistics/services/bl_sync.py tests/test_logistyka_bl_sync.py
git commit -m "feat(production): wysylka decyzji logistyki do Base. w tle z dzierzawa, odstepem i bezpiecznikiem limitu

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Cron logistyki

**Files:**
- Create: `modules/production/logistics/routers/cron_api.py`
- Modify: `modules/production/logistics/__init__.py` (import routera)
- Test: `tests/test_logistyka_cron.py`

**Interfaces:**
- Consumes: `bl_sync.uruchom_w_tle`, `bl_sync.wstrzymane_do` (Task 5), `delivery.przelicz_otwarte` (Task 3), `cron_auth.cron_secret_required`.
- Produces: `POST /production/api/logistics/cron` → `200 {'success': True, 'przeliczone': int, 'dopychacz_uruchomiony': bool, 'base_wstrzymane_do': ISO|None}`. Endpoint kończy się w ułamku sekundy — praca idzie w wątku. **Etap 2 dopisze tu uruchomienie geokodowania w tle.**

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_cron.py`:
```python
# -*- coding: utf-8 -*-
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import bl_sync
from modules.production.models import ProductionOrder
from tests.logistyka_fixtures import BASE, SEKRET_CRONA, app, client, produkt, zamowienie  # noqa: F401

NAGLOWEK = {'X-Cron-Secret': SEKRET_CRONA}


@pytest.fixture()
def watki(monkeypatch):
    uruchomione = []
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: uruchomione.append(1) or True)
    return uruchomione


def test_cron_bez_sekretu_to_403(client, watki):
    assert client.post(BASE + '/cron').status_code == 403
    assert watki == []


def test_cron_uruchamia_dopychacz_i_odpowiada_od_razu(client, watki):
    r = client.post(BASE + '/cron', headers=NAGLOWEK)
    assert r.status_code == 200
    assert r.get_json()['dopychacz_uruchomiony'] is True
    assert watki == [1]


def test_cron_zwraca_pauze(client, app, watki):
    """Review Focus 2 — pauza jest widoczna w odpowiedzi crona (log crontaba)."""
    with app.app_context():
        bl_sync.wstrzymaj_do(datetime(2099, 1, 1))
    assert client.post(BASE + '/cron', headers=NAGLOWEK).get_json()['base_wstrzymane_do'] \
        == '2099-01-01T00:00:00'


def test_cron_otwiera_zamowienie_z_nowa_aktywna_pozycja(client, app, watki):
    """Review Focus 5: Base. dołożył pozycję do zamkniętego zamówienia kurierskiego."""
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',),
                           logistics_closed_at=datetime(2026, 9, 20))
        produkt(order, status='czeka_na_wyciecie')
        db.session.commit()
        order_id = order.id
    r = client.post(BASE + '/cron', headers=NAGLOWEK)
    assert r.get_json()['przeliczone'] == 1
    with app.app_context():
        assert ProductionOrder.query.get(order_id).logistics_closed_at is None
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_cron.py`
Expected: FAIL — 404 (brak trasy).

- [ ] **Step 3: Implementacja**

`modules/production/logistics/routers/cron_api.py`:
```python
# -*- coding: utf-8 -*-
"""
Cron logistyki — co godzinę z crontaba serwera:
    scripts/cron_endpoint.sh POST /production/api/logistics/cron

Endpoint NIE wykonuje długiej pracy: sync worker gunicorna ma 30 s na żądanie.
Przelicza cykl zamówień (szybkie, w bazie) i uruchamia dopychacz Base. w tle.
Etap 2 dołoży tu uruchomienie geokodowania w tle.
"""
from flask import current_app, jsonify

from cron_auth import cron_secret_required
from extensions import db
from modules.production.logistics import logistics_panel_bp
from modules.production.logistics.services import bl_sync, delivery


@logistics_panel_bp.route('/cron', methods=['POST'])
@cron_secret_required
def cron():
    przeliczone = delivery.przelicz_otwarte()
    db.session.commit()
    uruchomiony = bl_sync.uruchom_w_tle(current_app._get_current_object())
    wstrzymane = bl_sync.wstrzymane_do()
    return jsonify({
        'success': True,
        'przeliczone': przeliczone,
        'dopychacz_uruchomiony': bool(uruchomiony),
        'base_wstrzymane_do': wstrzymane.isoformat() if wstrzymane else None,
    })
```
W `modules/production/logistics/__init__.py` na końcu dopisz:
```python
from modules.production.logistics.routers import cron_api  # noqa: E402,F401
```

- [ ] **Step 4: Uruchom testy**

Run: `PYTEST tests/test_logistyka_cron.py tests/test_sekret_crona.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/production/logistics tests/test_logistyka_cron.py
git commit -m "feat(production): cron logistyki przelicza cykl zamowien i uruchamia wysylke do Base.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: API mobilne i etykieta — obiekt `transport`, 409 przy pakowaniu

**Files:**
- Modify: `modules/production/services/mobile_api_service.py:1098-1109` (usunięcie starego wyliczania `delivery_type`), `:1144` (pole w słowniku)
- Modify: `modules/production/routers/mobile_api.py:131-133` (`KSZTALT_ODPOWIEDZI_KOLEJKI`), `:444-450` (`order_complete`)
- Modify: `modules/production/services/label_print_service.py:346-369`
- Modify tests: `tests/test_mobile_complete_bl_sync_queue.py` (`_zlecenie_gotowe_do_pakowania` ustawia `override_delivery_method='kurier_baselinker'`; asercja `:257` → `'czeka_na_pakowanie'`), inne testy pakowania przez API mobilne, które padną na 409 — dopisz im `override_delivery_method`.
- Test: `tests/test_logistyka_mobile.py`

**Interfaces:**
- Consumes: `sposoby.transport_payload`, `sposoby.legacy_delivery_type`, `sposoby.etykieta`, `sposoby.normalizuj` (Task 2); `delivery.ustaw_sposob_dostawy` (Task 3, w teście ETagu).
- Produces: każda pozycja w odpowiedziach mobilnych ma `delivery_type` (stare wartości) i `transport` (zawsze słownik); `POST /api/mobile/orders/<id>/complete` na pakowaniu bez sposobu → `409 {'error': 'delivery_method_not_set', 'message': str}`; `KSZTALT_ODPOWIEDZI_KOLEJKI == 3`.

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_mobile.py`:
```python
# -*- coding: utf-8 -*-
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import delivery
from modules.production.models import ProductionDevice, ProductionProduct
from modules.production.routers import mobile_api
from modules.production.services.mobile_api_service import generate_token, serialize_order
from modules.production.services.label_print_service import _format_delivery_label
from tests.logistyka_fixtures import app, client, zamowienie  # noqa: F401


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    """Spakowanie odpala synchronizację statusu Base. po commicie — w testach jej nie chcemy
    (ten sam zabieg co tests/test_mobile_complete_bl_sync_queue.py)."""
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


def _token(app, stanowisko='packaging'):
    with app.app_context():
        device = ProductionDevice(device_id='TAB-%s' % stanowisko,
                                  device_name='Tablet', station_code=stanowisko)
        db.session.add(device)
        db.session.commit()
        return generate_token(device)


def test_serializer_zawsze_ma_obiekt_transport_i_stare_delivery_type(app):
    with app.app_context():
        bez = zamowienie(statusy=('czeka_na_pakowanie',), delivery_method='Odbiór osobisty')
        dane = serialize_order(bez.products[0], station_code='packaging')
        assert dane['transport'] == {'mode': None, 'trip_name': None, 'trip_date': None,
                                     'vehicle_name': None, 'repack_required': False}
        assert dane['delivery_type'] == 'courier'  # heurystyka odbioru już nie decyduje
        z = zamowienie(sposob=s.ODBIOR, statusy=('czeka_na_pakowanie',))
        dane = serialize_order(z.products[0], station_code='packaging')
        assert dane['transport']['mode'] == 'odbior'
        assert dane['delivery_type'] == 'personal_pickup'


def test_ksztalt_odpowiedzi_podbity():
    assert mobile_api.KSZTALT_ODPOWIEDZI_KOLEJKI == 3


def test_pakowanie_bez_sposobu_to_409_z_komunikatem(app, client):
    token = _token(app)
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_pakowanie',))
        pid, numer = order.products[0].id, order.internal_order_number
    r = client.post('/api/mobile/orders/%d/complete' % pid,
                    headers={'Authorization': 'Bearer ' + token, 'X-Operation-Id': 'op-1'})
    assert r.status_code == 409
    assert r.get_json()['error'] == 'delivery_method_not_set'
    assert numer in r.get_json()['message']
    with app.app_context():
        assert ProductionProduct.query.get(pid).current_status == 'czeka_na_pakowanie'


def test_to_samo_op_id_przechodzi_po_decyzji_logistyka(app, client):
    """409 nie jest zapamiętywane (BLEDY_DO_PONOWIENIA) — kolejka offline tabletu dośle akcję."""
    token = _token(app)
    naglowki = {'Authorization': 'Bearer ' + token, 'X-Operation-Id': 'op-2'}
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_pakowanie',))
        pid, oid = order.products[0].id, order.id
    assert client.post('/api/mobile/orders/%d/complete' % pid, headers=naglowki).status_code == 409
    with app.app_context():
        from modules.production.models import ProductionOrder
        delivery.ustaw_sposob_dostawy(ProductionOrder.query.get(oid), s.KURIER)
        db.session.commit()
    r = client.post('/api/mobile/orders/%d/complete' % pid, headers=naglowki)
    assert r.status_code == 200
    assert r.get_json()['status'] == 'spakowane'


def test_inne_stanowiska_nie_sa_blokowane(app, client):
    token = _token(app, stanowisko='cutting')
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_wyciecie',))
        pid = order.products[0].id
    r = client.post('/api/mobile/orders/%d/complete' % pid,
                    headers={'Authorization': 'Bearer ' + token, 'X-Operation-Id': 'op-3'})
    assert r.status_code == 200


def test_kolejka_pakowania_zmienia_etag_po_zmianie_sposobu(app, client):
    """Review Focus 4."""
    token = _token(app)
    naglowki = {'Authorization': 'Bearer ' + token}
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_pakowanie',))
        order.products[0].updated_at = datetime(2026, 9, 1)
        db.session.commit()
        oid = order.id
    pierwszy = client.get('/api/mobile/stations/packaging/orders', headers=naglowki)
    etag = pierwszy.headers['ETag']
    with app.app_context():
        from modules.production.models import ProductionOrder
        delivery.ustaw_sposob_dostawy(ProductionOrder.query.get(oid), s.TRANSPORT,
                                      teraz=datetime(2026, 9, 25, 12, 0))
        db.session.commit()
    drugi = client.get('/api/mobile/stations/packaging/orders',
                       headers=dict(naglowki, **{'If-None-Match': etag}))
    assert drugi.status_code == 200


def test_etykieta_druku_ma_ten_sam_tekst_co_tablet(app):
    with app.app_context():
        bez = zamowienie(delivery_method='DPD')
        assert _format_delivery_label(bez.products[0]) == 'Nie ustawiono'
        z = zamowienie(sposob=s.TRANSPORT)
        assert _format_delivery_label(z.products[0]) == 'Transport WoodPower'
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_mobile.py`
Expected: FAIL (brak `transport`, 200 zamiast 409, `KSZTALT == 2`).

- [ ] **Step 3: Serializer**

W `modules/production/services/mobile_api_service.py` usuń komentarz „Kategoria dostawy — kolejność warunków…” (`:1090-1093`) oraz blok `override_delivery = …` / `if … delivery_type = …` (`:1101-1109`) i wstaw w to miejsce:
```python
    # Sposób dostawy — jedno źródło: logistics/sposoby.py (logistyka równoległa).
    # `delivery_type` zostaje dla starych APK (tylko stare wartości), a `transport`
    # jest ZAWSZE obecny: jego brak oznacza dla appki stary backend.
    from modules.production.logistics import sposoby
    delivery_type = sposoby.legacy_delivery_type(
        item.order.override_delivery_method if item.order else None)
    transport = sposoby.transport_payload(item.order)
```
W słowniku zwrotnym zaraz po `'delivery_type': delivery_type,` dopisz `'transport': transport,`.
W docstringu `mark_order_complete` usuń fragment „, personal_pickup omija logistykę”.

- [ ] **Step 4: Blokada i kształt odpowiedzi**

W `modules/production/routers/mobile_api.py`:
- `:131-133`:
```python
# PODBIJ przy każdej zmianie zestawu pól w serialize_order().
#   2 — 2026-09-18: label_print_count, label_offset, label_total (panel kafelków)
#   3 — 2026-09-25: obiekt `transport` (logistyka równoległa)
KSZTALT_ODPOWIEDZI_KOLEJKI = 3
```
- w `order_complete` po `if not item: return … 404` (`:444-446`) dopisz:
```python
    # Logistyka równoległa: bez sposobu dostawy pakowacz pomija zamówienie.
    # 409 jest w BLEDY_DO_PONOWIENIA — dekorator go NIE zapamiętuje, więc akcja
    # z kolejki offline przejdzie z tym samym X-Operation-Id po decyzji logistyka.
    if station_code == 'packaging' and item.order is not None:
        from modules.production.logistics import sposoby
        if sposoby.normalizuj(item.order.override_delivery_method) is None:
            return jsonify({
                'error': 'delivery_method_not_set',
                'message': u'Logistyka nie ustawiła jeszcze sposobu dostawy dla zamówienia {}. '
                           u'Pomiń je i weź kolejne.'.format(item.order.internal_order_number),
            }), 409
```

- [ ] **Step 5: Etykieta druku**

W `modules/production/services/label_print_service.py` zastąp całe `_format_delivery_label` (`:346-369`):
```python
def _format_delivery_label(item):
    """Linia „Dostawa:” — ten sam tekst co plakietka tabletu (logistics/sposoby.etykieta).

    Etykieta wydrukowana przed decyzją logistyka ma „Nie ustawiono”; lista logistyki
    pokazuje wtedy ikonę „etykiety sprzed zmiany”.
    """
    from modules.production.logistics import sposoby
    order = item.order if item.order else None
    return _normalize_text(sposoby.etykieta(order.override_delivery_method if order else None))
```
Uwaga: `_normalize_text` może zdejmować polskie znaki (ZPL) — test oczekuje wartości po normalizacji dla napisów bez ogonków; jeśli `_normalize_text('Nie ustawiono')` zwraca inny zapis, dostosuj asercję do wyniku `_normalize_text`.

- [ ] **Step 6: Istniejące testy pakowania**

W `tests/test_mobile_complete_bl_sync_queue.py` w `_zlecenie_gotowe_do_pakowania` dodaj `override_delivery_method='kurier_baselinker'` do `ProductionOrder(...)`; asercję `:257` zmień na `'czeka_na_pakowanie'`. Uruchom cały katalog testów mobilnych i popraw analogicznie każdy test, który pakuje zamówienie przez API i dostaje teraz 409 (dopisz sposób dostawy do zamówienia).

- [ ] **Step 7: Uruchom testy**

Run: `PYTEST tests/test_logistyka_mobile.py tests/test_mobile_complete_bl_sync_queue.py tests/test_mobile_api_alias_krawedzi.py` a potem `PYTEST tests/ -k "mobile or label or druk"`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add modules/production/services/mobile_api_service.py modules/production/routers/mobile_api.py modules/production/services/label_print_service.py tests/
git commit -m "feat(production): API mobilne niesie obiekt transport i blokuje pakowanie bez sposobu dostawy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: API panelu Logistyki — lista, zmiana hurtowa, wydanie

**Files:**
- Create: `modules/production/logistics/services/lista.py`
- Create: `modules/production/logistics/routers/panel_api.py`
- Create: `modules/production/logistics/templates/logistics/tab_content.html` (szkielet; wygląd w Task 10)
- Modify: `modules/production/logistics/__init__.py` (import `panel_api`)
- Test: `tests/test_logistyka_panel_api.py`

**Interfaces:**
- Consumes: `delivery.*` (Task 3), `bl_sync.po_zmianie`, `bl_sync.wstrzymane_do` (Task 5), `sposoby.*` (Task 2).
- Produces:
  - `lista.serializuj(order) -> dict` z kluczami: `id, numer, baselinker_order_id, klient, miasto, kod, adres, metoda_z_base, podpowiedz, sposob, sposob_etykieta, etap: {'status', 'nazwa'}, termin (ISO|None), m3 (float), spakowane (bool), wydane (ISO|None), zamkniete (bool), base_czeka (bool), etykiety_sprzed_zmiany (bool), przepakowanie (bool)`.
  - `lista.pobierz(sposob=None, etap=None, q=None, zamkniete=False) -> list[dict]` — `sposob` ∈ `{None, 'brak', KURIER, TRANSPORT, ODBIOR}`; sortowanie: `sposob None` najpierw, potem `termin` rosnąco (brak terminu na końcu), potem `numer`.
  - `lista.liczniki() -> dict` (`{'brak': n, KURIER: n, TRANSPORT: n, ODBIOR: n}` dla otwartych).
  - HTTP (prefiks `/production/api/logistics`, wszystko za `guard`):
    - `GET /tab-content` → HTML,
    - `GET /orders?sposob=&etap=&q=&zamkniete=0|1` → `{'success': True, 'orders': [...], 'liczniki': {...}, 'base_wstrzymane_do': ISO|None}`; `zamkniete=1` bez `q` → 422,
    - `POST /orders/delivery-method` body `{'order_ids': [int, ...], 'sposob': str}` → `{'success': True, 'zmienione': [id], 'przepakowanie': [id], 'bledy': [{'order_id', 'komunikat'}], 'orders': [serializuj...]}`; zły `sposob` → 422; pusta lista lub > 500 → 422,
    - `POST /orders/<id>/handed-over` → `{'success': True, 'order': serializuj}`; odmowa → `LogistykaBlad.status` + `{'success': False, 'error': komunikat}`.

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_panel_api.py`:
```python
# -*- coding: utf-8 -*-
from datetime import date, datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import bl_sync
from modules.production.models import ProductionOrder
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401


@pytest.fixture(autouse=True)
def bez_base(monkeypatch):
    wywolane = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolane.append(list(ids)))
    return wywolane


def test_lista_otwartych_z_nieustawionymi_na_gorze(client, app):
    with app.app_context():
        a = zamowienie(sposob=s.KURIER)
        a.products[0].deadline_date = date(2026, 9, 26)
        b = zamowienie()
        b.products[0].deadline_date = date(2026, 10, 30)
        zamowienie(sposob=s.KURIER, statusy=('spakowane',),
                   logistics_closed_at=datetime(2026, 9, 1))  # zamknięte — niewidoczne
        db.session.commit()
        numery = [a.internal_order_number, b.internal_order_number]
    dane = client.get(BASE + '/orders').get_json()
    assert [o['numer'] for o in dane['orders']] == [numery[1], numery[0]]
    assert dane['liczniki']['brak'] == 1 and dane['liczniki'][s.KURIER] == 1


def test_wiersz_listy(client, app):
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_lakiernie', 'czeka_na_pakowanie'),
                           delivery_method='Odbiór osobisty')
        order.products[0].label_printed_at = datetime(2026, 9, 24, 8, 0)
        order.override_delivery_method = s.KURIER
        order.delivery_method_set_at = datetime(2026, 9, 24, 9, 0)
        db.session.commit()
    wiersz = client.get(BASE + '/orders').get_json()['orders'][0]
    assert wiersz['sposob'] == s.KURIER and wiersz['sposob_etykieta'] == 'Kurier'
    assert wiersz['podpowiedz'] == s.ODBIOR
    assert wiersz['metoda_z_base'] == 'Odbiór osobisty'
    assert wiersz['etap']['status'] == 'czeka_na_lakiernie'
    assert wiersz['m3'] == pytest.approx(0.096)  # 2 pozycje × 0.024 × 2 szt.
    assert wiersz['etykiety_sprzed_zmiany'] is True


def test_filtr_i_wyszukiwarka(client, app):
    with app.app_context():
        zamowienie(sposob=s.KURIER, miasto='Tarnów')
        zamowienie(miasto='Rzeszów')
    assert len(client.get(BASE + '/orders?sposob=brak').get_json()['orders']) == 1
    assert client.get(BASE + '/orders?q=Tarn').get_json()['orders'][0]['miasto'] == 'Tarnów'


def test_zamkniete_tylko_z_wyszukiwaniem(client, app):
    with app.app_context():
        zamowienie(sposob=s.KURIER, statusy=('spakowane',), miasto='Gdańsk',
                   logistics_closed_at=datetime(2026, 9, 1))
    assert client.get(BASE + '/orders?zamkniete=1').status_code == 422
    dane = client.get(BASE + '/orders?zamkniete=1&q=Gda').get_json()
    assert dane['orders'][0]['zamkniete'] is True


def test_hurtowe_ustawienie_sposobu(client, app, bez_base):
    with app.app_context():
        ids = [zamowienie().id, zamowienie().id]
    r = client.post(BASE + '/orders/delivery-method',
                    json={'order_ids': ids, 'sposob': s.TRANSPORT})
    dane = r.get_json()
    assert r.status_code == 200 and sorted(dane['zmienione']) == sorted(ids)
    assert bez_base == [sorted(ids)] or bez_base == [ids]
    with app.app_context():
        assert all(ProductionOrder.query.get(i).override_delivery_method == s.TRANSPORT
                   for i in ids)


def test_hurt_z_czesciowa_odmowa(client, app):
    with app.app_context():
        ok = zamowienie().id
        wydane = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',),
                            handed_over_at=datetime(2026, 9, 20)).id
    dane = client.post(BASE + '/orders/delivery-method',
                       json={'order_ids': [ok, wydane], 'sposob': s.KURIER}).get_json()
    assert dane['zmienione'] == [ok]
    assert dane['bledy'][0]['order_id'] == wydane


@pytest.mark.parametrize('body', [
    {'order_ids': [], 'sposob': 'kurier_baselinker'},
    {'order_ids': [1], 'sposob': 'DPD'},
    {'order_ids': list(range(501)), 'sposob': 'kurier_baselinker'},
])
def test_walidacja_hurtu(client, body):
    assert client.post(BASE + '/orders/delivery-method', json=body).status_code == 422


def test_wydane_klientowi(client, app):
    with app.app_context():
        oid = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',)).id
        nie = zamowienie(sposob=s.KURIER, statusy=('spakowane',)).id
    r = client.post(BASE + '/orders/%d/handed-over' % oid)
    assert r.status_code == 200 and r.get_json()['order']['wydane'] is not None
    r = client.post(BASE + '/orders/%d/handed-over' % nie)
    assert r.status_code == 409 and r.get_json()['success'] is False


def test_zakladka_renderuje_sie(client):
    r = client.get(BASE + '/tab-content')
    assert r.status_code == 200
    assert b'id="logistics-root"' in r.data
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_panel_api.py`
Expected: FAIL — 404.

- [ ] **Step 3: Serwis listy**

`modules/production/logistics/services/lista.py`:
```python
# -*- coding: utf-8 -*-
"""Lista zamówień zakładki Logistyka (spec, sekcja 6.7)."""
from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from modules.production.logistics import sposoby
from modules.production.logistics.services.delivery import aktywne_produkty, wszystkie_spakowane
from modules.production.models import ProductionOrder

# Najwcześniejszy etap zamówienia = etap jego najbardziej zaległej pozycji.
KOLEJNOSC_ETAPOW = ('wstrzymane', 'czeka_na_wyciecie', 'czeka_na_skladanie',
                    'czeka_na_sklejanie', 'czeka_na_formatowanie', 'czeka_na_krawedzie',
                    'czeka_na_lakiernie', 'czeka_na_pakowanie', 'spakowane')
LIMIT_ZAMKNIETYCH = 50


def _ranga(status):
    return KOLEJNOSC_ETAPOW.index(status) if status in KOLEJNOSC_ETAPOW else len(KOLEJNOSC_ETAPOW)


def _etap(aktywne):
    if not aktywne:
        return {'status': 'anulowane', 'nazwa': 'Anulowane'}
    najwczesniejszy = min(aktywne, key=lambda p: _ranga(p.current_status))
    return {'status': najwczesniejszy.current_status,
            'nazwa': najwczesniejszy.status_display_name}


def serializuj(order):
    aktywne = aktywne_produkty(order)
    sposob = sposoby.normalizuj(order.override_delivery_method)
    terminy = [p.deadline_date for p in aktywne if p.deadline_date]
    ustawiono = order.delivery_method_set_at
    return {
        'id': order.id,
        'numer': order.internal_order_number,
        'baselinker_order_id': order.baselinker_order_id,
        'klient': order.client_name,
        'miasto': order.delivery_city,
        'kod': order.delivery_postcode,
        'adres': order.delivery_address,
        'metoda_z_base': order.delivery_method,
        'podpowiedz': sposoby.podpowiedz(order),
        'sposob': sposob,
        'sposob_etykieta': sposoby.etykieta(sposob),
        'etap': _etap(aktywne),
        'termin': min(terminy).isoformat() if terminy else None,
        'm3': round(sum(float(p.volume_m3 or 0) * (p.quantity or 1) for p in aktywne), 4),
        'spakowane': wszystkie_spakowane(order),
        'wydane': order.handed_over_at.isoformat() if order.handed_over_at else None,
        'zamkniete': order.logistics_closed_at is not None,
        'base_czeka': bool(order.bl_delivery_method_pending or order.bl_status_pending_id),
        'etykiety_sprzed_zmiany': bool(ustawiono) and any(
            p.label_printed_at is not None and p.label_printed_at < ustawiono for p in aktywne),
        'przepakowanie': bool(order.repack_required),
    }


def _klucz(wiersz):
    return (wiersz['sposob'] is not None, wiersz['termin'] is None,
            wiersz['termin'] or '', wiersz['numer'] or '')


def pobierz(sposob=None, etap=None, q=None, zamkniete=False):
    zapytanie = ProductionOrder.query.options(selectinload(ProductionOrder.products))
    if q:
        wzor = u'%{}%'.format(q.strip())
        zapytanie = zapytanie.filter(or_(
            ProductionOrder.internal_order_number.ilike(wzor),
            ProductionOrder.client_name.ilike(wzor),
            ProductionOrder.delivery_city.ilike(wzor)))
    if zamkniete:
        zapytanie = zapytanie.order_by(ProductionOrder.id.desc()).limit(LIMIT_ZAMKNIETYCH)
    else:
        zapytanie = zapytanie.filter(ProductionOrder.logistics_closed_at.is_(None))
    if sposob == 'brak':
        zapytanie = zapytanie.filter(ProductionOrder.override_delivery_method.is_(None))
    elif sposoby.normalizuj(sposob):
        zapytanie = zapytanie.filter(ProductionOrder.override_delivery_method == sposob)
    wiersze = [serializuj(o) for o in zapytanie.all()]
    if etap:
        wiersze = [w for w in wiersze if w['etap']['status'] == etap]
    return sorted(wiersze, key=_klucz)


def liczniki():
    wynik = {'brak': 0, sposoby.KURIER: 0, sposoby.TRANSPORT: 0, sposoby.ODBIOR: 0}
    for (wartosc,) in (ProductionOrder.query.with_entities(ProductionOrder.override_delivery_method)
                       .filter(ProductionOrder.logistics_closed_at.is_(None)).all()):
        klucz = sposoby.normalizuj(wartosc) or 'brak'
        wynik[klucz] += 1
    return wynik
```

- [ ] **Step 4: Router panelu**

`modules/production/logistics/routers/panel_api.py`:
```python
# -*- coding: utf-8 -*-
"""
API zakładki Logistyka — /production/api/logistics/*

Kontrola dostępu jak w Trakowni (sawmill/routers/panel_api.py:53, tam pełne
uzasadnienie kolejności i leniwego odwołania do dekoratora).
"""
from functools import wraps

from flask import jsonify, render_template, request
from flask_login import current_user, login_required

import modules.users.decorators as user_decorators
from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import logistics_panel_bp, sposoby
from modules.production.logistics.services import bl_sync, delivery, lista
from modules.production.models import ProductionOrder

logger = get_structured_logger('production.logistics.panel_api')
LIMIT_HURTU = 500


def guard(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        checked = user_decorators.require_module_access('production', as_json=True)(
            login_required(f))
        return checked(*args, **kwargs)
    return wrapped


def _user_id():
    return getattr(current_user, 'id', None)


def _blad(komunikat, status):
    return jsonify({'success': False, 'error': komunikat}), status


@logistics_panel_bp.route('/tab-content', methods=['GET'])
@guard
def tab_content():
    return render_template('logistics/tab_content.html')


@logistics_panel_bp.route('/orders', methods=['GET'])
@guard
def orders():
    zamkniete = request.args.get('zamkniete') == '1'
    q = (request.args.get('q') or '').strip() or None
    if zamkniete and not q:
        return _blad(u'Wyszukiwanie zamkniętych zamówień wymaga frazy.', 422)
    wstrzymane = bl_sync.wstrzymane_do()
    return jsonify({
        'success': True,
        'orders': lista.pobierz(sposob=request.args.get('sposob') or None,
                                etap=request.args.get('etap') or None,
                                q=q, zamkniete=zamkniete),
        'liczniki': lista.liczniki(),
        'base_wstrzymane_do': wstrzymane.isoformat() if wstrzymane else None,
    })


@logistics_panel_bp.route('/orders/delivery-method', methods=['POST'])
@guard
def delivery_method():
    dane = request.get_json(silent=True) or {}
    ids = dane.get('order_ids')
    sposob = sposoby.normalizuj(dane.get('sposob'))
    if not isinstance(ids, list) or not ids or len(ids) > LIMIT_HURTU:
        return _blad(u'Podaj od 1 do {} zamówień.'.format(LIMIT_HURTU), 422)
    if sposob is None:
        return _blad(u'Nieznany sposób dostawy.', 422)

    zmienione, przepakowanie, bledy = [], [], []
    for order in ProductionOrder.query.filter(ProductionOrder.id.in_(ids)).all():
        try:
            wynik = delivery.ustaw_sposob_dostawy(order, sposob, user_id=_user_id())
        except delivery.LogistykaBlad as e:
            bledy.append({'order_id': order.id, 'komunikat': e.komunikat})
            continue
        if wynik['zmieniono']:
            zmienione.append(order.id)
        if wynik['przepakowanie']:
            przepakowanie.append(order.id)
    db.session.commit()
    logger.info("Logistyka: zmiana sposobu dostawy", extra={
        'user_id': _user_id(), 'sposob': sposob, 'zmienione': len(zmienione),
        'bledy': len(bledy)})

    bl_sync.po_zmianie(zmienione)
    odswiezone = ProductionOrder.query.filter(ProductionOrder.id.in_(ids)).all()
    return jsonify({'success': True, 'zmienione': zmienione, 'przepakowanie': przepakowanie,
                    'bledy': bledy, 'orders': [lista.serializuj(o) for o in odswiezone]})


@logistics_panel_bp.route('/orders/<int:order_id>/handed-over', methods=['POST'])
@guard
def handed_over(order_id):
    order = ProductionOrder.query.get(order_id)
    if order is None:
        return _blad(u'Nie ma takiego zamówienia.', 404)
    try:
        delivery.wydaj_klientowi(order, user_id=_user_id())
    except delivery.LogistykaBlad as e:
        db.session.rollback()
        return _blad(e.komunikat, e.status)
    db.session.commit()
    bl_sync.po_zmianie([order.id])
    return jsonify({'success': True, 'order': lista.serializuj(ProductionOrder.query.get(order_id))})
```
W `modules/production/logistics/__init__.py` zmień ostatni import na:
```python
from modules.production.logistics.routers import cron_api, panel_api  # noqa: E402,F401
```

- [ ] **Step 5: Szkielet szablonu (wygląd w Task 10)**

`modules/production/logistics/templates/logistics/tab_content.html`:
```html
{# Zakładka Logistyka — wygląd i JS powstają w Task 10 (skill frontend-design). #}
<div id="logistics-root" class="logistics-tab" data-api="{{ url_for('logistics_panel.orders') }}">
</div>
```

- [ ] **Step 6: Uruchom testy**

Run: `PYTEST tests/test_logistyka_panel_api.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add modules/production/logistics tests/test_logistyka_panel_api.py
git commit -m "feat(production): API zakladki Logistyka - lista, hurtowa zmiana sposobu i wydanie klientowi

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Sprzątanie starej logistyki w panelu produkcji

**Files:**
- Delete: `modules/production/routers/api/logistics_api.py`, `modules/production/templates/logistics/logistics.html`
- Modify: `modules/production/routers/api/__init__.py:30` (usuń `from . import logistics_api`)
- Modify: `modules/production/routers/main_routers.py:200-204`
- Modify: `modules/production/routers/api/products_api.py:1292-1300` (walidacja statusu), pętla `update_status` + commit w `bulk_action`
- Modify: `modules/production/routers/api/dashboard_api.py:261-265, :1004-1011`
- Modify: `modules/production/templates/components/dashboard-tab-content.html:273-282`
- Modify: `modules/production/services/dashboard_alerts.py:53-65`
- Modify: `modules/production/templates/components/products-tab-content.html:305`
- Modify: `modules/production/static/js/modules/products-module.js:2779, :3929, :4013-4022, :4096, :4106, :4142, :4150, :4160`
- Modify: `modules/production/static/js/modules/dashboard-module.js:509-513`
- Modify tests: `tests/test_dashboard_krawedzie.py:324-338`, `tests/test_produkty_formularz_statusu.py:40-44`, `tests/test_produkty_js_mapy_pol_stanowisk.py:26-27`, `tests/test_dashboard_statusy_produkcji.py:108-125` (jeśli pada)
- Test: `tests/test_logistyka_sprzatanie.py`

**Interfaces:**
- Consumes: `delivery.przelicz_zamkniecie` (Task 3).
- Produces: `GET /production/logistics` → 302 na `/production/?tab=logistics`; `dashboard_stats['logistics']['pending_count']` = liczba otwartych zamówień bez sposobu dostawy; `bulk_action` odrzuca `czeka_na_logistyke` (400) i przelicza zamknięcie zamówień po zmianie statusów.

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_sprzatanie.py`:
```python
# -*- coding: utf-8 -*-
import os

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _plik(*sciezka):
    return open(os.path.join(KATALOG, *sciezka), encoding='utf-8').read()


def test_stara_logistyka_usunieta():
    assert not os.path.exists(os.path.join(KATALOG, 'modules', 'production', 'routers',
                                           'api', 'logistics_api.py'))
    assert not os.path.exists(os.path.join(KATALOG, 'modules', 'production', 'templates',
                                           'logistics', 'logistics.html'))
    assert 'logistics_api' not in _plik('modules', 'production', 'routers', 'api', '__init__.py')


def test_lista_hurtowa_nie_oferuje_logistyki():
    assert 'value="czeka_na_logistyke"' not in _plik(
        'modules', 'production', 'templates', 'components', 'products-tab-content.html')
    js = _plik('modules', 'production', 'static', 'js', 'modules', 'products-module.js')
    assert "{ value: 'czeka_na_logistyke'" not in js
    assert "commonStations.push('logistics'" not in js


def test_bramka_dashboardu_liczy_brak_sposobu():
    html = _plik('modules', 'production', 'templates', 'components', 'dashboard-tab-content.html')
    blok = html.split('data-station="logistics"')[1].split('data-station=')[0]
    assert 'id="logistics-pending"' in blok
    assert 'bez sposobu dostawy' in blok
    assert '?tab=logistics' in blok


def test_bulk_action_odrzuca_logistyke():
    kod = _plik('modules', 'production', 'routers', 'api', 'products_api.py')
    assert "- {'czeka_na_logistyke'}" in kod
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_sprzatanie.py`
Expected: FAIL.

- [ ] **Step 3: Usunięcia i przekierowanie**

```bash
git rm modules/production/routers/api/logistics_api.py modules/production/templates/logistics/logistics.html
```
W `modules/production/routers/api/__init__.py` usuń linię `from . import logistics_api`.
W `modules/production/routers/main_routers.py` zastąp `:200-204`:
```python
@main_bp.route('/logistics')
@login_required
def logistics():
    """Stara strona logistyki — dziś zakładka panelu produkcji (zakładki z linków i zakładek przeglądarki)."""
    return redirect(url_for('production.production_main.dashboard') + '?tab=logistics')
```

- [ ] **Step 4: `bulk_action`**

W `modules/production/routers/api/products_api.py`:
- linia z `dozwolone_statusy = set(ProductionItem.current_status.type.enums)` →
```python
            # 'czeka_na_logistyke' zostaje w ENUM do sprzątania, ale nie jest już
            # etapem pipeline'u — logistyka żyje równolegle na zamówieniu.
            dozwolone_statusy = set(ProductionItem.current_status.type.enums) - {'czeka_na_logistyke'}
```
- tuż przed `db.session.commit()` kończącym akcje mutujące dopisz:
```python
        if action == 'update_status':
            # Ręczna zmiana statusu może zamknąć albo otworzyć cykl logistyczny zamówienia.
            from modules.production.logistics.services.delivery import przelicz_zamkniecie
            for zamowienie in {p.order for p in products if p.order is not None}:
                przelicz_zamkniecie(zamowienie)
```

- [ ] **Step 5: Dashboard produkcji**

`modules/production/routers/api/dashboard_api.py`:
- usuń gałąź `elif status == 'czeka_na_logistyke': stations_stats['logistics'] = {...}` (`:261-265`),
- zastąp zapytanie `logistics_pending` (`:1004-1011`):
```python
        # Bramka Logistyki: otwarte zamówienia, którym logistyk nie ustawił jeszcze
        # sposobu dostawy (logistyka jest równoległa — nie liczymy statusu produktu).
        logistics_pending = db.session.query(db.func.count(ProductionOrder.id)).filter(
            ProductionOrder.logistics_closed_at.is_(None),
            ProductionOrder.override_delivery_method.is_(None),
            ProductionOrder.products.any(ProductionItem.current_status != 'anulowane'),
        ).scalar() or 0
        dashboard_stats['logistics'] = {
            'pending_count': logistics_pending
        }
```
`modules/production/templates/components/dashboard-tab-content.html:273-282`:
```html
        {# LOGISTYKA — równoległa do produkcji: licznik zamówień bez sposobu dostawy #}
        <div class="il-station il-station--gate" data-station="logistics">
          <div></div>
          <div class="il-rail-name"><span class="il-rail-name-main">Logistyka</span></div>
          <div class="il-rail-gate">
            <span class="il-rail-gate-n" id="logistics-pending">{{ dashboard_stats.logistics.pending_count|default(0) }}</span>
            <span class="il-rail-gate-l">bez sposobu dostawy</span>
          </div>
          <a href="{{ url_for('production.production_main.dashboard') }}?tab=logistics" class="il-rail-open" title="Otwórz zakładkę Logistyka" aria-label="Otwórz zakładkę Logistyka"><i class="fas fa-external-link-alt"></i></a>
        </div>
```
`tests/test_dashboard_krawedzie.py:324-338`: docstring → „Logistyka to bramka licząca zamówienia bez sposobu dostawy…”, asercja `'oczekuje na decyzję'` → `'bez sposobu dostawy'`.

`modules/production/static/js/modules/dashboard-module.js:509-513` — łuk ze Sklejania kończy się teraz na Pakowaniu:
```javascript
        // Trasy omijające wynikają z ProductionProduct.complete_task():
        // brak docięcia na wymiar wyrzuca pozycję ze Sklejania wprost do
        // Pakowania, a brak obróbki krawędzi — z Formatowania do Lakierni.
        const lukDlugi = `M${X},${Y(2)} C${L},${Y(2) + 51} ${L},${Y(7) - 51} ${X},${Y(7)}`;
```

`modules/production/services/dashboard_alerts.py:53-65`: usuń wpis `'czeka_na_logistyke': (7, 'logistics'),` i klucz `'logistics': 'Logistyka',` z `_EXTRA_LABELS` (komentarz nad nim skróć do „Etykiety dla pozycji spoza pipeline'u stanowisk.”).

- [ ] **Step 6: Lista produktów (JS/HTML)**

- `products-tab-content.html:305` — usuń `<option value="czeka_na_logistyke">…</option>`.
- `products-module.js:2779` — usuń `{ value: 'czeka_na_logistyke', label: 'Logistyka' },`.
- `products-module.js:3929` — `commonStations.push('packaging');`.
- `products-module.js:4013-4022` — usuń obiekt stacji `code: 'logistics'`.
- `products-module.js:4096, :4106, :4142, :4150, :4160` — usuń wpisy `'logistics'` z `endFields`, `statusMap`, `stationOrder`.
- Zostaw `STATUS_TRANSLATIONS`/`STATUS_CONFIG`/`getStatusConfig` (`:41, :66, :1776, :1796, :4677-4681`) i obsługę historii `event_type === 'logistics'` (`:4486`) — to wyświetlanie historii.
- `tests/test_produkty_js_mapy_pol_stanowisk.py:26-27` — usuń `'logistics'` z `KODY`.
- `tests/test_produkty_formularz_statusu.py:40-44` — test przemianuj na `test_formularz_oferuje_krawedzie_i_lakiernie_bez_logistyki`, pętla po `('czeka_na_krawedzie', 'czeka_na_lakiernie')` i dopisz `assert 'value="czeka_na_logistyke"' not in html` (użyj tej samej zmiennej z treścią szablonu co w teście).

- [ ] **Step 7: Uruchom testy**

Run: `PYTEST tests/test_logistyka_sprzatanie.py tests/test_dashboard_krawedzie.py tests/test_produkty_formularz_statusu.py tests/test_produkty_js_mapy_pol_stanowisk.py tests/test_dashboard_statusy_produkcji.py tests/test_stanowiska_tab_krawedzie.py`
Expected: PASS. Jeśli `test_dashboard_statusy_produkcji.py:108-125` pada, bo mapa kolorów wykresu (`modules/dashboard/services/chart_service.py:245`) nadal zna logistykę — zostaw kolor (dane historyczne), a test ogranicz do Krawędzi i Lakierni.

- [ ] **Step 8: Commit**

```bash
git add -A modules/production tests/
git commit -m "refactor(production): usuniecie etapu logistyki z panelu produkcji i listy produktow

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Interfejs zakładki Logistyka (skill `frontend-design`)

**REQUIRED:** Przed napisaniem jakiegokolwiek HTML/CSS/JS wywołaj skill `frontend-design:frontend-design` i pracuj według niego. Zgodność z istniejącą oprawą panelu produkcji (IL Design System: zmienne `--il-*` z `production-panel.css`, JetBrains Mono w nagłówkach, Bootstrap z `modules/production/static/vendor/`, Font Awesome 6). Teksty po polsku, „Base.” zamiast „BaseLinker”.

**Files:**
- Modify: `modules/production/templates/panel/dashboard.html:60-70` (przycisk zakładki PRZED Trakownią), `:221-222` (pane)
- Modify: `modules/production/static/js/production-app-loader.js:90-91, :275-283, :714` + nowa metoda `loadLogisticsTab()`
- Modify: `modules/production/logistics/templates/logistics/tab_content.html`
- Create: `modules/production/logistics/static/css/logistics.css`, `modules/production/logistics/static/js/logistics.js`
- Test: `tests/test_logistyka_zakladka.py`

**Interfaces:**
- Consumes: HTTP z Task 8 (`/orders`, `/orders/delivery-method`, `/orders/<id>/handed-over`, `/tab-content`).
- Produces: zakładka `logistics-tab` (URL `?tab=logistics`), kontener `#logistics-tab-content`, korzeń `#logistics-root`.

**Wymagania funkcjonalne (spec 6.7):**
1. Przycisk zakładki „Logistyka” (ikona `fa-truck`) **między Archiwum a Trakownią**; pane `#logistics-tab-content` jak Trakownia (pusty div, treść z `/production/api/logistics/tab-content`).
2. Loader: `loadLogisticsTab()` — kopia wzoru `loadSawmillTab()` (fetch HTML, `innerHTML`, `executeInlineScripts`, 403 → „Brak dostępu do modułu produkcji”); `validTabs` w obu miejscach (`:90-91`, `:714`) dostaje `'logistics-tab'`; `switch` w `loadTabContent` dostaje `case 'logistics-tab'`.
3. Nagłówek z podzakładkami — w etapie 1 **tylko „Dashboard”** (Trasy i Flota dochodzą w etapie 3, nie pokazuj martwych przycisków).
4. Pasek liczników (`liczniki` z API): Nie ustawiono / Kurier / Transport własny / Odbiór osobisty — kliknięcie filtruje. Gdy `base_wstrzymane_do` ≠ null — widoczny baner „Wysyłka do Base. wstrzymana do HH:MM (limit API). Zmiany zostaną wysłane automatycznie.”.
5. Tabela: checkbox, numer, klient, miasto, „Metoda z Base.” (tekst + podpowiedź), **wybór sposobu dostawy** (select: Nie ustawiono (tylko wyświetlane, niewybieralne po ustawieniu) / Kurier / Transport własny / Odbiór osobisty — zmiana od razu wysyła `POST /orders/delivery-method` dla jednego id), etap produkcji, termin (czerwony po terminie), m³, ikony: `base_czeka` („Base.: czeka na wysłanie”), `etykiety_sprzed_zmiany` („Etykiety wydrukowane przed zmianą sposobu dostawy”), `przepakowanie` („Czeka na przepakowanie na kuriera”).
6. Wiersze „Nie ustawiono” wyróżnione wizualnie (to kolejka pracy logistyka).
7. Zaznaczanie wielu + pasek akcji: „Ustaw sposób dostawy…” (Kurier / Transport własny / Odbiór osobisty) i „Przyjmij podpowiedzi z Base.” (dla zaznaczonych: grupuje po `podpowiedz` i wysyła po jednym żądaniu na sposób). Po odpowiedzi: podmiana wierszy z `orders`, komunikat z liczbą zmienionych, lista `bledy` (numer + komunikat), osobny komunikat dla `przepakowanie`.
8. Przycisk „Wydane klientowi” w wierszu, gdy `sposob == 'odbior_osobisty' && spakowane && !wydane` — z potwierdzeniem („Zamówienie X zostało odebrane przez klienta?”).
9. Wyszukiwarka (numer / klient / miasto, debounce 300 ms) + przełącznik „także zamknięte” (wymaga frazy; bez frazy przełącznik nieaktywny z podpowiedzią).
10. Filtr etapu produkcji (select z etapami obecnymi na liście).
11. Pusty stan i stan błędu (komunikat + „Spróbuj ponownie”).
12. Odświeżanie listy co 60 s, gdy zakładka jest widoczna i nic nie jest zaznaczone.
13. Zero zależności z CDN (poza już używanymi w panelu Font Awesome / Google Fonts).

- [ ] **Step 1: Test (failing)**

`tests/test_logistyka_zakladka.py`:
```python
# -*- coding: utf-8 -*-
import os
import re

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _plik(*sciezka):
    return open(os.path.join(KATALOG, *sciezka), encoding='utf-8').read()


def test_zakladka_stoi_przed_trakownia():
    html = _plik('modules', 'production', 'templates', 'panel', 'dashboard.html')
    kolejnosc = re.findall(r'id="(\w+)-tab"\s', html)
    assert kolejnosc.index('logistics') == kolejnosc.index('sawmill') - 1
    assert 'id="logistics-tab-content"' in html


def test_loader_zna_zakladke():
    js = _plik('modules', 'production', 'static', 'js', 'production-app-loader.js')
    assert js.count("'logistics-tab'") >= 3  # dwa validTabs + switch
    assert 'async loadLogisticsTab()' in js
    assert '/production/api/logistics/tab-content' in js


def test_js_zakladki_uzywa_api_i_nazwy_base():
    js = _plik('modules', 'production', 'logistics', 'static', 'js', 'logistics.js')
    for sciezka in ('/orders/delivery-method', '/handed-over', 'zamkniete'):
        assert sciezka in js, sciezka
    tekst = js + _plik('modules', 'production', 'logistics', 'templates', 'logistics',
                       'tab_content.html')
    assert 'BaseLinker' not in tekst and 'Base.' in tekst


def test_brak_cdn_w_zakladce():
    tekst = _plik('modules', 'production', 'logistics', 'templates', 'logistics',
                  'tab_content.html')
    assert 'unpkg.com' not in tekst and 'cdn.jsdelivr' not in tekst
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_logistyka_zakladka.py`
Expected: FAIL.

- [ ] **Step 3: Przycisk, pane, loader**

`modules/production/templates/panel/dashboard.html` — przed przyciskiem `sawmill-tab` (`:63`):
```html
                    <button class="nav-link"
                            id="logistics-tab"
                            data-bs-toggle="tab"
                            data-bs-target="#logistics-tab-content"
                            type="button" role="tab"
                            aria-controls="logistics-tab-content"
                            aria-selected="false">
                        <i class="fas fa-truck me-2"></i>Logistyka
                    </button>
```
przed `<!-- Sawmill Tab (Trakownia) -->` (`:221`):
```html
                    <!-- Logistics Tab (Logistyka) -->
                    <div class="tab-pane fade" id="logistics-tab-content" role="tabpanel" aria-labelledby="logistics-tab"></div>
```
`production-app-loader.js`: dopisz `'logistics-tab'` do obu list `validTabs` (`:90-91`, `:714`), `case 'logistics-tab': await this.loadLogisticsTab(); break;` w `loadTabContent` i metodę:
```javascript
    /**
     * Zakładka Logistyka — jak Trakownia: własny blueprint zwraca gotowy HTML
     * (logistics_panel_bp), więc fetch() zamiast wspólnego ApiClient.
     */
    async loadLogisticsTab() {
        try {
            const response = await fetch('/production/api/logistics/tab-content', {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (!response.ok) {
                if (response.status === 403) {
                    throw new Error('Brak dostępu do modułu produkcji');
                }
                throw new Error(`HTTP ${response.status}`);
            }
            const container = document.getElementById('logistics-tab-content');
            if (container) {
                container.innerHTML = await response.text();
                this.executeInlineScripts(container);
            }
        } catch (error) {
            console.error('[ProductionApp] Logistics loading failed:', error);
            this.showTabError('logistics-tab', error.message);
            throw error;
        }
    }
```

- [ ] **Step 4: Szablon, CSS i JS zakładki — ze skillem `frontend-design`**

Wywołaj `frontend-design:frontend-design`, przekaż mu: wymagania 3–13 powyżej, kontrakt API z Task 8 (Interfaces), istniejący wygląd panelu (otwórz `modules/production/static/css/production-panel.css` i `modules/production/sawmill/templates/sawmill/tab_content.html` jako wzorzec oprawy zakładki). Pliki:
- `tab_content.html` — korzeń `<div id="logistics-root" class="logistics-tab" data-api="{{ url_for('logistics_panel.orders') }}">`, `<link rel="stylesheet" href="{{ url_for('logistics_panel.static', filename='css/logistics.css') }}">` i `<script src="{{ url_for('logistics_panel.static', filename='js/logistics.js') }}"></script>` na końcu (wykona je `executeInlineScripts`).
- `logistics.js` — IIFE bez globali poza `window.LogisticsTab`; bazowy URL z `data-api` (usuń końcowe `/orders`); wszystkie `fetch` z `credentials: 'same-origin'` i `Content-Type: application/json` przy POST; escapowanie każdego tekstu z API przed wstawieniem do HTML.
- `logistics.css` — style zakładki z prefiksem `.logistics-tab`, zmienne `--il-*`.

- [ ] **Step 5: Uruchom testy**

Run: `PYTEST tests/test_logistyka_zakladka.py tests/test_logistyka_panel_api.py`
Expected: PASS.

- [ ] **Step 6: Oględziny w przeglądarce**

Uruchom aplikację z worktree na lokalnej bazie **dopiero po** Task 11 Step 2 (migracja na lokalnej bazie) albo obejrzyj render przez test client (memory: `reference_podglad_strony_bez_logowania`). Sprawdź w przeglądarce (Browser pane): wejście w zakładkę, filtr „Nie ustawiono”, zmianę pojedynczą, hurtową, „Przyjmij podpowiedzi z Base.”, wyszukiwarkę z „także zamknięte”, „Wydane klientowi”, szerokość 1280 px i 768 px. Zrzut ekranu dołącz do raportu zadania.

- [ ] **Step 7: Commit**

```bash
git add modules/production/templates/panel/dashboard.html modules/production/static/js/production-app-loader.js modules/production/logistics tests/test_logistyka_zakladka.py
git commit -m "feat(production): zakladka Logistyka w panelu produkcji

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Dokumentacja, weryfikacja migracji na MySQL, pełny pakiet

**Files:**
- Modify: `CLAUDE.md` (sekcje „Zadania cykliczne (cron)” i „Deployment → Ważne”)

- [ ] **Step 1: CLAUDE.md**

W sekcji „Zadania cykliczne (cron)” po akapicie o `cron_secret_required` dopisz:
```markdown
Cron logistyki (od etapu 1 logistyki równoległej): `scripts/cron_endpoint.sh POST /production/api/logistics/cron`
co godzinę. Przelicza cykl logistyczny zamówień i **uruchamia w tle** dopychacz, który wysyła do Base. zaległe
zmiany sposobu dostawy i statusów (odstęp 1,5 s, jeden wątek na serwer — dzierżawa `logistyka_bl_dzierzawa`
w `prod_config`). Endpoint odpowiada od razu: sync worker gunicorna ma 30 s na żądanie, więc długiej pracy
w żądaniu nie robimy. Limit API Base. (100/min na konto) wstrzymuje wysyłki logistyki do chwili z komunikatu
błędu (`logistyka_bl_wstrzymane_do`).
```
W „Deployment → Ważne” dopisz punkt:
```markdown
- **Logistyka równoległa:** status `czeka_na_logistyke` nie jest już etapem — produkcja kończy się wejściem do
  pakowania, a sposób dostawy (`prod_orders.override_delivery_method`, NULL = „Nie ustawiono”) ustawia logistyk
  w zakładce „Logistyka”. Pakowanie bez niego: API mobilne zwraca 409 `delivery_method_not_set`. Mapowania:
  `modules/production/logistics/sposoby.py`. Appkę tabletową z obsługą obiektu `transport` wydajemy PRZED
  backendem (stara appka pokazuje nieustawione jako „KURIER”).
```

- [ ] **Step 2: Weryfikacja migracji na MySQL (kopia schematu, nie lokalna baza robocza)**

Lokalna baza jest wspólna z innymi sesjami — migrację sprawdzamy na **osobnej bazie ze zrzutem schematu**:
```bash
cd /c/Users/Grafik/Documents/woodpower-crm-logistyka
docker compose -p woodpower-crm exec -T db sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --no-data "$MYSQL_DATABASE" > /tmp/schemat.sql && mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "DROP DATABASE IF EXISTS logistyka_test; CREATE DATABASE logistyka_test" && mysql -uroot -p"$MYSQL_ROOT_PASSWORD" logistyka_test < /tmp/schemat.sql'
docker compose -p woodpower-crm exec -T db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" logistyka_test' < migrations/2026-09-25-logistyka-sposob-dostawy.sql
docker compose -p woodpower-crm exec -T db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" logistyka_test' < migrations/2026-09-25-logistyka-sposob-dostawy.sql
docker compose -p woodpower-crm exec -T db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" logistyka_test -e "SHOW COLUMNS FROM prod_orders LIKE \"%logist%\"; SHOW COLUMNS FROM prod_orders LIKE \"bl_%\"; SHOW CREATE TABLE prod_logistics_log\G; SELECT config_key FROM prod_config WHERE config_key LIKE \"logistyka%\""'
```
Expected: oba przebiegi migracji bez błędu (drugi wypisuje „… juz jest”), kolumny i tabela obecne, dwa wiersze `prod_config` (tabela `prod_config` w zrzucie bez danych — `INSERT IGNORE` je doda). Na końcu `DROP DATABASE logistyka_test`.

Dodatkowo test danych (przeniesienie statusów i zamknięcie historii) na kopii z danymi: `mysqldump` z danymi do `logistyka_test`, migracja, potem:
```sql
SELECT COUNT(*) FROM prod_products WHERE current_status = 'czeka_na_logistyke';            -- 0
SELECT COUNT(*) FROM prod_orders WHERE logistics_closed_at IS NULL;                        -- tylko zamówienia z aktywną produkcją
```

- [ ] **Step 3: Pełny pakiet testów**

Run: `docker compose -p logistyka run --rm --no-deps app pytest tests/ -q`
oraz `docker compose -p logistyka run --rm --no-deps app bash -c "cd integrations/blog_seo && python -m pytest -q"`
Expected: wszystko zielone. Porównaj liczbę testów z przebiegiem na `origin/main` (ta sama obecność `config/core.json` w worktree w obu przebiegach — memory `reference_worktree_docker_testy`, pkt 3).

- [ ] **Step 4: Przegląd całej gałęzi**

Wywołaj `superpowers:requesting-code-review` na całej gałęzi (adwersaryjnie, ze szczególnym naciskiem na Review Focus z nagłówka planu i regresje stanowisk tabletowych). Popraw znaleziska, powtórz testy.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: logistyka rownolegla - cron, 409 przy pakowaniu i kolejnosc wdrozenia z appka

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Lista kontrolna wdrożenia (do raportu, NIE wykonywać bez zgody Konrada)**

1. Appka z obsługą `transport` wydana i zainstalowana na tabletach.
2. Push gałęzi na `main` (= deploy; migracja przed restartem).
3. Na serwerze: wpis crontaba (jako `woodpower-crm`):
   `0 * * * * /home/woodpower-crm/htdocs/crm.woodpower.pl/scripts/cron_endpoint.sh POST /production/api/logistics/cron >> /home/woodpower-crm/logs/cron-endpointy.log 2>&1`
4. Logistyk przeklikuje sposoby dostawy (zaczynając od zamówień czekających na pakowanie).
5. Obserwacja `logs/` pod kątem „Limit API Base.” w pierwszej godzinie.
