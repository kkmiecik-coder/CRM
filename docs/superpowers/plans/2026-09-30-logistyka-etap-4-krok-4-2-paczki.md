# Logistyka etap 4, krok 4.2 — paczki na pakowaniu — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pakowacz deklaruje z tabletu, ile i jakich paczek (paczek albo palet) ma zamówienie, a CRM zapisuje je w `prod_packages`, drukuje etykietę 100×150 na każdą z nich (drukarka `wysylka`), pozwala wydrukować je ponownie i pokazuje w panelu Logistyki etykiety sprzed zmiany sposobu dostawy albo trasy.

**Architecture:** Nowa tabela `prod_packages` (model `ProductionPackage` obok `LabelPrintJob`). Serwis `logistics/services/paczki.py` liczy podpowiedź (`packing_hint`), czyta i unieważnia paczki oraz przyjmuje deklarację, a serwis `logistics/services/paczki_druk.py` składa z bazy `DaneEtykietyPaczki` (krok 4.1) i kolejkuje ZPL na drukarkę `wysylka`. API mobilne dostaje `PUT/GET /orders/<nr>/packages` i dwa endpointy ponownego druku. Sygnał dla agenta druku wysyła `@with_idempotency` dopiero po commicie. Panel Logistyki porównuje napis z pasa sposobu dostawy zapamiętany na paczce z dzisiejszym.

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, MySQL 8.4 (produkcja) / SQLite (testy), pytest, vanilla JS, ZPL.

**Spec:** `docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md` — sekcje 2, 3, 5.1–5.3, 5.5, 6.1 i 6.3 (fragmenty „przeniesione do kroku 4.2”), 7, 12 pkt 2, 13, 14 pkt 2, 15. Wzór formatu i dorobek kroku 4.1: `docs/superpowers/plans/2026-09-30-logistyka-etap-4-krok-4-1-druk.md`.

## Global Constraints

- Kod zgodny z **Pythonem 3.9** (produkcja): bez `X | Y` w adnotacjach, bez `match`, `typing.Optional/List`.
- Komentarze i docstringi **po polsku**; teksty w UI i komunikaty API po polsku; w UI „Base.” zamiast BaseLinker.
- Błędy API: `{"error": <kod>, "message": <tekst dla człowieka>}` (spec 13).
- Etykieta paczki: **tylko ASCII**, odbiorca zanonimizowany, **zero danych adresowych**, `^` i `~` usuwane z danych, `^PR3` (krok 4.1 — generator bez zmian układu).
- Funkcje serwisów **nie commitują**; w API mobilnym commit robi `@with_idempotency`. Sygnał dla agenta druku (`realtime_service.publish_print_signal`) **wyłącznie po commicie**.
- `prod_packages`: kod paczki = `P-<id>`; aktualna deklaracja = `voided_at IS NULL`; paczek nigdy nie kasujemy (skan starej etykiety ma dostać „nieaktualna”, nie „nie ma”).
- Stanowiska uprawnione do deklaracji i druku etykiet paczek: `('packaging', 'verification')` — stała niezależna od `LABEL_PRINTER_ALLOWED_STATIONS`.
- `serialize_order` i ścieżka `complete` **nie czytają `prod_packages`** (wiele testów stawia własne tabele bez niej, a kolejka ma zostać tak szybka jak dziś).
- `KSZTALT_ODPOWIEDZI_KOLEJKI = 4` (nowe pole `packing_hint`).
- Migracja: `migrations/2026-09-30-logistyka-paczki.sql`, idempotentna, `ALTER` osłonięte `information_schema` + `PREPARE/EXECUTE`, bez zmiany separatora poleceń (słowo nie może paść nawet w komentarzu — test szuka go w całym pliku).
- Zapisy ze stanu, który mógł zmienić równoległy zapis: zamówienie deklaracji i paczki czytane **z blokadą** (`with_for_update().populate_existing()`), bo MySQL pracuje na REPEATABLE READ (reguła z CLAUDE.md gałęzi).
- Testy WYŁĄCZNIE z katalogu worktree: `docker compose -p <projekt> run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider`; **nigdy** `docker compose exec`; nie twórz `config/core.json` w worktree.
- Commity: Conventional Commits po polsku **bez polskich znaków w temacie**, stopka `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Bez pushu (push robi Konrad), nigdy do `main`.
- Repo publiczne: żadnych sekretów, adresów IP drukarek ani uwag bezpieczeństwa w commitowanych plikach.

## Review Focus

1. **Powtórka z kolejki offline** (ten sam `X-Operation-Id` po timeoucie) nie może zadeklarować paczek drugi raz ani drugi raz wydrukować etykiet — `test_ten_sam_operation_id_nie_deklaruje_drugi_raz` (Task 4), `test_ponowny_druk_ten_sam_operation_id_drukuje_raz` (Task 5).
2. **Deklaracja, zanim zamówienie jest w całości spakowane** (kolejka appki nie gwarantuje, że wszystkie COMPLETE przeszły; Base. dołożył pozycję) — 409 `order_not_packed`, **niezapamiętane**, ten sam `X-Operation-Id` przechodzi po spakowaniu; pozycje anulowane się nie liczą — `test_niespakowane_zamowienie_409_i_ponowienie_po_spakowaniu`, `test_anulowana_pozycja_nie_blokuje_deklaracji` (Task 4).
3. **Stara etykieta po ponownej deklaracji** — poprzednie paczki unieważnione, ich ponowny druk to 409 `package_void`, nowe numerowane od 1 — `test_ponowna_deklaracja_uniewaznia_poprzednia` (Task 4), `test_uniewazniona_paczka_409` (Task 5).
4. **Sygnał dla agenta przed commitem albo przy odmowie** (agent przyszedłby po zadania, których nie ma) — `test_sygnal_dla_agenta_dopiero_po_commicie`, `sygnaly == []` w testach 409/422 (Task 4).
5. **Dane „z życia” na etykiecie**: długa nazwa trasy nie może zgubić daty, `^`/`~` w nazwie trasy, trasa wykonana nie trafia na etykietę, konfiguracja `unknown`, brak objętości — `test_napis_sposobu`, `test_trasa_wykonana_nie_trafia_na_etykiete`, `test_dane_etykiety_z_zamowienia` (Task 3), `test_podpowiedz_pakowania` (Task 2).

## Decyzje Konrada z 30.09 (przed planem)

- **Ikona „etykiety paczek sprzed zmiany”**: paczka zapamiętuje napis z pasa sposobu dostawy z chwili druku (`prod_packages.label_delivery_text`); ikona, gdy dzisiejszy napis jest inny (zmiana sposobu, dodanie/zdjęcie z trasy, zmiana nazwy/daty trasy). Ponowny druk gasi ikonę. Kolumny nie było w specu 5.2.
- **Okno paczek w appce**: tylko „Zatwierdź” albo „Wróć” — „Wróć” anuluje ZAKOŃCZ (zamówienie zostaje niedomknięte). Nowa appka zawsze deklaruje paczki; „BEZ PACZEK” (krok 4.3) dotyczy starej appki i zmian admina.
- **Dodatkowy `GET /api/mobile/orders/<nr>/packages`** (spoza specu): tablet pokazuje aktualne paczki i drukuje ponownie pojedynczą albo wszystkie.

## Odstępstwa od specu (świadome, do dopisania w specu w Task 7)

- 5.2: nowa kolumna `label_delivery_text VARCHAR(40) NULL` (decyzja Konrada wyżej).
- 5.3: w kroku 4.2 dochodzi tylko `packages_declared_at`; `verified_*`, `problem_*`, `repack_reason` — w migracji kroku 4.3 (razem z kodem, który ich używa). `prod_packages` powstaje od razu z kolumnami weryfikacji i załadunku (dopisywanie ich później = osłonięte ALTER-y na pełnej tabeli).
- 7.2: blokada deklaracji po weryfikacji (409 `order_verified`) wchodzi w kroku 4.3 razem z `prod_orders.verified_at` — w 4.2 nikt nie weryfikuje. Walidacja pomija pola bez znaczenia (wymiar przy EUR i przy paczce, typ palety przy paczce): 422 z kolejki offline to utracona deklaracja, a te pola nie zmieniają jej sensu. Kody błędów: `invalid_packages` (422), `order_not_found` (404), `station_not_allowed` (403), `order_not_packed` (409).
- 7.3: kody `package_not_found` (404) i `no_packages` (409); ponowny druk bierze **bieżące** dane zamówienia (sposób, trasa aktywna, zawartość) i aktualizuje `label_delivery_text`.
- 8.4 i 15: `KSZTALT_ODPOWIEDZI_KOLEJKI` dostaje 4 już w kroku 4.2 (`packing_hint`), więc krok 4.3 (`repack_reason`) podbija 4 → 5.
- `package_label.WAGA_KG_NA_M3` zostaje kopią `sposoby.WAGA_KG_NA_M3` z testem zgodności: import pakietu `modules.production.logistics` ładuje jego routery (`__init__.py`), a `package_label` ma zostać lekki. `routes.WAGA_KG_NA_M3` bierze wartość ze `sposoby`.

## Poza zakresem kroku 4.2 (celowo)

- Unieważnianie paczek przy doróbce, nowej pozycji z Base., przepakowaniu na kuriera i cofnięciu do pakowania (spec 4.5 i 8.5) — krok 4.3, jedną regułą „zamówienie przestało być w całości spakowane → paczki unieważnione”. W 4.2 paczki unieważnia tylko nowa deklaracja; zmianę sposobu dostawy pokazuje ikona.
- Paczki w panelu Logistyki („2 × paczka” pod kolumną Etap, filtry „Bez paczek”) — spec 11, razem z kolumną Etap w kroku 4.3. W 4.2 panel dostaje tylko ikonę.
- Drobiazgi agenta druku (`sys.stdout.reconfigure(errors='replace')`, `--kalibruj Wysylka` wielkimi literami, `EndPagePrinter`/`EndDocPrinter` bez sprawdzania wyniku, angielskie komunikaty `configparser`) — krok 4.2 nie zmienia `tools/print_agent`, więc czekają na najbliższe wydanie agenta (każda zmiana = nowa paczka dla hali).

## Kontrakt API mobilnego kroku 4.2 (dla appki i przeglądu)

Wszystkie wymagają `Authorization: Bearer <JWT urządzenia>`. Błędy: `{"error", "message"}`.

| Endpoint | Stanowisko | Idempotencja | Odpowiedź 200 | Błędy |
|---|---|---|---|---|
| `GET /stations/<kod>/orders` (bez zmian ścieżki) | jak dziś | — | każda pozycja ma `packing_hint: {"kind": "paczka"\|"paleta", "count": 1, "pallet_type": "eur"\|null, "weight_kg": int}`; ETag z kształtem 4 | jak dziś |
| `PUT /orders/<nr>/packages` body `{"kind", "count", "pallet_type", "length_cm", "width_cm"}` | `packaging`, `verification` | `X-Operation-Id`; 400/403/404/409 niezapamiętane | `{"internal_order_number", "packages_declared_at", "packages": [paczka…], "labels_queued": N, "message"}` | 422 `invalid_packages`, 404 `order_not_found`, 403 `station_not_allowed`, 409 `order_not_packed`, błędy `X-Worker-Ids` jak w `complete` |
| `GET /orders/<nr>/packages` | każde | — (`no-store`) | `{"internal_order_number", "packages_declared_at", "packages": [paczka…]}` | 404 `order_not_found` |
| `POST /packages/<id>/print` | `packaging`, `verification` | jak PUT | `{"success": true, "labels_queued": 1, "package": paczka, "message"}` | 404 `package_not_found`, 409 `package_void`, 403 |
| `POST /orders/<nr>/packages/print` | `packaging`, `verification` | jak PUT | `{"success": true, "labels_queued": N, "packages": [paczka…], "message"}` | 404 `order_not_found`, 409 `no_packages`, 403 |

Paczka: `{"id", "code": "P-<id>", "seq", "kind", "pallet_type", "length_cm", "width_cm", "label_print_count", "label_printed_at"}`.
Body PUT: `count` 1–10 (liczba całkowita, nie `true`), `kind` = `paczka` albo `paleta`; przy palecie `pallet_type` = `eur` (wymiar zawsze 120×80) albo `niestandardowa` z `length_cm`/`width_cm` 20–400. Stara appka (bez deklaracji) pakuje jak dziś.

## Środowisko i tory równoległe

- Główny worktree (Git Bash): `cd /c/Users/Grafik/Documents/woodpower-crm/.claude/worktrees/logistyka-etap-4`, gałąź `claude/logistyka-etap-4`, projekt dockera `logistyka4`.
- `PYTEST <ścieżki>` w krokach = `docker compose -p <projekt> run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider` uruchomione z katalogu worktree zadania.
- Punkt wyjścia: `5018 passed, 3 skipped` (koniec kroku 4.1, `cc173b10`). Po każdym zadaniu pełny pakiet: 0 failed, passed = poprzednio + nowe. **Najwyżej 2 pełne pakiety naraz** (Docker VM 15,5 GB — wcześniej OOM, exit 137).
- Kolejność i tory (każdy tor równoległy we własnym worktree i gałęzi pomocniczej, z własnym `-p`; scalanie cherry-pickiem do `claude/logistyka-etap-4`, gdy w głównym worktree nikt nie pracuje; po scaleniu pełny pakiet w głównym worktree, potem usunięcie gałęzi i worktree toru):

| Etap | Główny worktree | Tor równoległy |
|---|---|---|
| 1 | Task 1 (schemat) | — |
| 2 | Task 2 (podpowiedź) | Task 3 (etykiety) — `.claude/worktrees/logistyka-etap-4-t3`, `-p logistyka4-t3`, baza = commit Task 1 |
| 3 | Task 4 (deklaracja) | Task 6 (panel) — `…-t6`, `-p logistyka4-t6`, baza = główna gałąź po scaleniu Task 3 |
| 4 | Task 5 (ponowny druk) | — |
| 5 | Task 7 (MySQL, podgląd, drukarka z Konradem, spec) | — |

Tor: `git worktree add .claude/worktrees/logistyka-etap-4-t3 -b claude/logistyka-etap-4-t3 <BASE>` z katalogu głównego repo. Pliki torów są rozłączne (tabela „Mapa plików” — kolumna Task).

## Mapa plików

| Plik | Task | Rola |
|---|---|---|
| `migrations/2026-09-30-logistyka-paczki.sql` (nowy) | 1 | `prod_packages`, `prod_orders.packages_declared_at`, log: akcja `paczki` + `worker_id`/`device_id`, FK `prod_print_queue.package_id` |
| `modules/production/models.py` | 1 | `ProductionPackage`, `ProductionOrder.packages_declared_at`, FK w `LabelPrintJob.package_id` |
| `modules/production/logistics/models.py` | 1 | `AKCJE_LOGU` + `paczki`, kolumny `worker_id`, `device_id` |
| `modules/production/logistics/services/delivery.py` | 1 | `zapisz_log(..., worker_id, device_id)` |
| `modules/production/logistics/sposoby.py` | 1 | `WAGA_KG_NA_M3`, `PROG_PALETY_KG` |
| `tests/logistyka_fixtures.py` | 1 | tabele paczek i kolejki, `zamowienie(numer_wewnetrzny=...)` |
| `modules/production/logistics/services/paczki.py` (nowy) | 2, 4, 5 | podpowiedź, odczyty i serializacja paczek (2), deklaracja i unieważnianie (4), ponowny druk (5) |
| `modules/production/services/mobile_api_service.py` | 2, 4 | `serialize_order(..., packing_hints)` (2), sygnał po commicie w `with_idempotency` (4) |
| `modules/production/routers/mobile_api.py` | 2, 4, 5 | kształt 4 i mapa podpowiedzi (2), `PUT/GET …/packages` (4), ponowny druk (5) |
| `modules/production/logistics/services/routes.py` | 2 | `WAGA_KG_NA_M3` ze `sposoby` |
| `modules/production/logistics/services/paczki_druk.py` (nowy) | 3 | napis pasa sposobu, `DaneEtykietyPaczki` z bazy, druk N etykiet |
| `modules/production/services/package_label.py` | 3 | `tekst_ascii`, `base_id` przez `int()` |
| `modules/production/services/print_queue_service.py` | 3 | sygnał po commicie (`zaplanuj_…`/`wyslij_…`) |
| `modules/production/logistics/services/lista.py`, `logistics/routers/panel_api.py`, `logistics/routers/trasy_api.py` | 6 | `etykiety_paczek_sprzed_zmiany` (paczki jednym zapytaniem) |
| `modules/production/logistics/static/js/logistics.js`, `logistics/templates/logistics/tab_content.html` | 6 | ikona, legenda, wersja skryptu |
| `tests/test_paczki_schemat.py`, `test_paczki_podpowiedz.py`, `test_paczki_etykiety.py`, `test_paczki_deklaracja.py`, `test_paczki_ponowny_druk.py`, `test_paczki_panel.py` (nowe) | 1–6 | testy |
| `tests/test_logistyka_mobile.py` (2), `tests/test_etykieta_paczki.py` (3) | 2, 3 | kształt 4; wstrzyknięcia i stopka |

---

### Task 1: Schemat paczek (migracja, modele, log, stałe, fikstury)

**Files:**
- Create: `migrations/2026-09-30-logistyka-paczki.sql`
- Modify: `modules/production/models.py` (`ProductionOrder` ok. :186–207, `LabelPrintJob` ok. :917–978 + nowa klasa po niej)
- Modify: `modules/production/logistics/models.py` (`AKCJE_LOGU`, `LogisticsLog`)
- Modify: `modules/production/logistics/services/delivery.py` (`zapisz_log`)
- Modify: `modules/production/logistics/sposoby.py`
- Modify: `tests/logistyka_fixtures.py`
- Test: `tests/test_paczki_schemat.py`

**Interfaces:**
- Produces: `ProductionPackage` (tabela `prod_packages`; stałe `RODZAJE = ('paczka', 'paleta')`, `TYPY_PALET = ('eur', 'niestandardowa')`, `SPOSOBY_POTWIERDZENIA = ('skan', 'reczne')`; kolumny ze specu 5.2 + `label_delivery_text`; relacja `order`; właściwość `kod -> 'P-<id>'`), `ProductionOrder.packages_declared_at`, `LogisticsLog.worker_id`, `LogisticsLog.device_id`, akcja logu `'paczki'`, `delivery.zapisz_log(order, akcja, stara=None, nowa=None, user_id=None, note=None, route_id=None, teraz=None, worker_id=None, device_id=None)`, `sposoby.WAGA_KG_NA_M3 = 800`, `sposoby.PROG_PALETY_KG = 40`, fikstura `zamowienie(..., numer_wewnetrzny=None)` (cyfry jak na produkcji; domyślnie dotychczasowe `'26/%05d'`), tabele `LabelPrintJob` i `ProductionPackage` w `tests.logistyka_fixtures.TABLES`.

- [ ] **Step 0: Punkt wyjścia**

Run: `PYTEST tests/` (projekt `logistyka4`)
Expected: `5018 passed, 3 skipped`.

- [ ] **Step 1: Test, który padnie**

Create `tests/test_paczki_schemat.py`:

```python
# -*- coding: utf-8 -*-
"""Schemat paczek (logistyka etap 4, krok 4.2, spec 5.1–5.3 i 5.5)."""
import os
from datetime import datetime

from extensions import db
from migrations.migration_service import MigrationService
from modules.production.logistics import sposoby
from modules.production.logistics.models import AKCJE_LOGU, LogisticsLog
from modules.production.logistics.services import delivery
from modules.production.models import LabelPrintJob, ProductionPackage
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

MIGRACJA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', '2026-09-30-logistyka-paczki.sql')


def _paczka(order, seq=1, kind='paczka', **kolumny):
    p = ProductionPackage(order_id=order.id, seq=seq, kind=kind,
                          declared_at=datetime(2026, 9, 30, 12, 0), **kolumny)
    db.session.add(p)
    db.session.commit()
    return p


def _polecenia():
    with open(MIGRACJA, encoding='utf-8') as f:
        sql = f.read()
    return sql, [' '.join(p.split()) for p in MigrationService.split_statements(sql)]


def test_paczka_ma_kod_i_stan_poczatkowy(app):
    order = zamowienie(statusy=('spakowane',))
    p = _paczka(order)
    assert p.kod == 'P-%d' % p.id
    assert (p.label_print_count, p.voided_at, p.label_delivery_text) == (0, None, None)
    assert p.order.id == order.id


def test_paleta_niestandardowa(app):
    p = _paczka(zamowienie(statusy=('spakowane',)), kind='paleta',
                pallet_type='niestandardowa', length_cm=150, width_cm=100)
    assert (p.kind, p.pallet_type, p.length_cm, p.width_cm) == ('paleta', 'niestandardowa', 150, 100)


def test_zamowienie_bez_deklaracji(app):
    assert zamowienie().packages_declared_at is None


def test_zadanie_wydruku_wskazuje_paczke(app):
    p = _paczka(zamowienie(statusy=('spakowane',)))
    job = LabelPrintJob(printer='wysylka', package_id=p.id, short_product_id=p.kod,
                        zpl_payload='^XA^XZ', station_code='packaging',
                        requested_by_type='device', requested_by_id='TAB-1')
    db.session.add(job)
    db.session.commit()
    assert LabelPrintJob.query.get(job.id).package_id == p.id


def test_log_logistyki_z_pracownikiem_i_urzadzeniem(app):
    order = zamowienie(statusy=('spakowane',))
    delivery.zapisz_log(order, 'paczki', None, u'3 × paczka', worker_id=5, device_id=7)
    db.session.commit()
    wpis = LogisticsLog.query.filter_by(order_id=order.id).one()
    assert (wpis.action, wpis.new_value, wpis.worker_id, wpis.device_id, wpis.user_id) == \
        ('paczki', u'3 × paczka', 5, 7, None)


def test_stale_wagi():
    assert sposoby.WAGA_KG_NA_M3 == 800 and sposoby.PROG_PALETY_KG == 40


def test_fikstura_numeru_wewnetrznego(app):
    """Endpointy paczek mają numer w ścieżce — na produkcji to same cyfry (bez '/')."""
    assert zamowienie(numer_wewnetrzny='1450').internal_order_number == '1450'


def test_migracja_paczek():
    sql, polecenia = _polecenia()
    tabela = next(p for p in polecenia if p.startswith('CREATE TABLE IF NOT EXISTS prod_packages'))
    for kolumna in ('seq SMALLINT NOT NULL', "kind ENUM('paczka','paleta') NOT NULL",
                    "pallet_type ENUM('eur','niestandardowa') NULL", 'declared_at DATETIME NOT NULL',
                    'voided_at DATETIME NULL', 'label_print_count INT NOT NULL DEFAULT 0',
                    'label_delivery_text VARCHAR(40) NULL', "verified_method ENUM('skan','reczne') NULL",
                    "loaded_method ENUM('skan','reczne') NULL", 'loaded_route_id INT NULL',
                    'KEY ix_prod_packages_order_id (order_id)', 'KEY ix_prod_packages_voided_at (voided_at)'):
        assert kolumna in tabela, kolumna
    assert 'REFERENCES prod_orders (id) ON DELETE CASCADE' in tabela
    enum = next(p for p in polecenia if p.startswith('ALTER TABLE prod_logistics_log MODIFY action'))
    for akcja in AKCJE_LOGU:
        assert "'%s'" % akcja in enum, akcja
    assert 'paczki' in AKCJE_LOGU
    # 3 kolumny + klucz obcy — każdy ALTER dodający coś osłonięty warunkiem (runner wykonuje
    # katalog przy każdym deployu); MODIFY enuma jest idempotentny sam z siebie.
    assert sql.count('FROM information_schema.') == 4
    assert sql.count('PREPARE krok FROM @sql') == 4
    assert "CONSTRAINT_NAME = 'fk_prod_print_queue_package'" in sql
    assert 'REFERENCES prod_packages (id) ON DELETE SET NULL' in sql
    assert 'DELIMITER' not in sql.upper()


def test_runner_rozpoznaje_migracje():
    assert MigrationService(db=None)._match(os.path.basename(MIGRACJA)) is not None
    assert os.path.basename(MIGRACJA) > '2026-09-30-druk-klucze-przesuniecia.sql'
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_paczki_schemat.py`
Expected: FAIL przy imporcie (`ImportError: cannot import name 'ProductionPackage'`).

- [ ] **Step 3: Migracja**

Create `migrations/2026-09-30-logistyka-paczki.sql`:

```sql
-- Logistyka etap 4, krok 4.2 (spec 2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md, sekcje 5.1-5.3
-- i 5.5): paczki zamówienia (paczka albo paleta) z etykietą 100x150 na drukarce 'wysylka'.
-- prod_packages powstaje od razu z kolumnami weryfikacji i załadunku (kroki 4.3-4.4) - dopisywanie ich
-- później wymagałoby osłoniętych ALTER-ów na tabeli, która będzie już pełna. label_delivery_text:
-- napis z pasa sposobu dostawy w chwili druku (ikona „etykiety paczek sprzed zmiany”, decyzja 30.09).
-- Idempotentna: CREATE TABLE IF NOT EXISTS, a ALTER dodające kolumny i klucz obcy osłonięte warunkiem
-- z information_schema przez PREPARE/EXECUTE (bez zmiany separatora poleceń), jak w
-- 2026-09-30-druk-dwie-drukarki.sql.

CREATE TABLE IF NOT EXISTS prod_packages (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    seq SMALLINT NOT NULL,
    kind ENUM('paczka','paleta') NOT NULL,
    pallet_type ENUM('eur','niestandardowa') NULL,
    length_cm SMALLINT NULL,
    width_cm SMALLINT NULL,
    declared_at DATETIME NOT NULL,
    declared_by_worker_id INT NULL,
    declared_device_id INT NULL,
    voided_at DATETIME NULL,
    label_printed_at DATETIME NULL,
    label_print_count INT NOT NULL DEFAULT 0,
    label_delivery_text VARCHAR(40) NULL,
    verified_at DATETIME NULL,
    verified_by_worker_id INT NULL,
    verified_method ENUM('skan','reczne') NULL,
    loaded_at DATETIME NULL,
    loaded_by_worker_id INT NULL,
    loaded_method ENUM('skan','reczne') NULL,
    loaded_route_id INT NULL,
    KEY ix_prod_packages_order_id (order_id),
    KEY ix_prod_packages_voided_at (voided_at),
    CONSTRAINT fk_prod_packages_order FOREIGN KEY (order_id)
        REFERENCES prod_orders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Ostatnia ważna deklaracja paczek zamówienia.
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND COLUMN_NAME = 'packages_declared_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN packages_declared_at DATETIME NULL',
              'SELECT "packages_declared_at juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Log logistyki: akcja 'paczki' (MODIFY do tej samej definicji jest bezpieczny przy każdym
-- przebiegu - lista wartości tylko rośnie) oraz pracownik i urządzenie (akcje z tabletów
-- i telefonów nie mają użytkownika panelu).
ALTER TABLE prod_logistics_log MODIFY action
    ENUM('sposob_dostawy','wydane','przepakowanie',
         'trasa_dodane','trasa_usuniete','trasa_status','adres','paczki') NOT NULL;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_logistics_log'
               AND COLUMN_NAME = 'worker_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_logistics_log ADD COLUMN worker_id INT NULL',
              'SELECT "worker_id juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_logistics_log'
               AND COLUMN_NAME = 'device_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_logistics_log ADD COLUMN device_id INT NULL',
              'SELECT "device_id juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Klucz obcy kolejki wydruku do paczki (krok 4.1 dodał samą kolumnę). Osierocone wartości
-- zerujemy najpierw - bez tego ADD CONSTRAINT kończy się błędem 1452.
UPDATE prod_print_queue SET package_id = NULL
WHERE package_id IS NOT NULL AND package_id NOT IN (SELECT id FROM prod_packages);

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.TABLE_CONSTRAINTS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_print_queue'
               AND CONSTRAINT_NAME = 'fk_prod_print_queue_package');
SET @sql = IF(@brak, 'ALTER TABLE prod_print_queue ADD CONSTRAINT fk_prod_print_queue_package FOREIGN KEY (package_id) REFERENCES prod_packages (id) ON DELETE SET NULL',
              'SELECT "klucz paczki juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;
```

- [ ] **Step 4: Modele**

W `modules/production/models.py`:

a) `ProductionOrder` — pod `logistics_completed_at = Column(DateTime, index=True)`:

```python
    # Ostatnia ważna deklaracja paczek (logistyka etap 4, krok 4.2). Same paczki:
    # ProductionPackage (prod_packages); aktualne = voided_at IS NULL.
    packages_declared_at = Column(DateTime)
```

b) `LabelPrintJob.package_id` — zamień definicję kolumny:

```python
    # Paczka, której dotyczy etykieta (krok 4.2 — prod_packages); NULL dla etykiet produktów.
    package_id = Column(Integer, ForeignKey('prod_packages.id', ondelete='SET NULL'), nullable=True)
```

c) Bezpośrednio po klasie `LabelPrintJob` (przed `class ProductionSecurityEvent`):

```python
class ProductionPackage(db.Model):
    """
    Paczka albo paleta zamówienia (logistyka etap 4, spec 5.2). Kod na etykiecie i w QR:
    'P-<id>'. Aktualna deklaracja zamówienia = jego paczki z voided_at IS NULL. Nowa
    deklaracja (a od kroku 4.3 także cofnięcie do pakowania i doróbka) unieważnia
    poprzednie — wiersze zostają, bo skan starej etykiety ma odpowiedzieć „nieaktualna”,
    a nie „nie ma takiej paczki”.
    """
    __tablename__ = 'prod_packages'

    RODZAJE = ('paczka', 'paleta')
    TYPY_PALET = ('eur', 'niestandardowa')
    SPOSOBY_POTWIERDZENIA = ('skan', 'reczne')

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey('prod_orders.id', ondelete='CASCADE'),
                      nullable=False, index=True)
    seq = Column(SmallInteger, nullable=False)              # 1..N w deklaracji
    kind = Column(Enum(*RODZAJE, name='package_kind'), nullable=False)
    pallet_type = Column(Enum(*TYPY_PALET, name='package_pallet_type'))
    length_cm = Column(SmallInteger)                         # EUR 120x80, niestandardowa 20-400
    width_cm = Column(SmallInteger)
    declared_at = Column(DateTime, nullable=False, default=get_local_now)
    declared_by_worker_id = Column(Integer)
    declared_device_id = Column(Integer)                     # prod_devices.id
    voided_at = Column(DateTime, index=True)
    label_printed_at = Column(DateTime)
    label_print_count = Column(Integer, nullable=False, default=0)
    # Napis z pasa sposobu dostawy w chwili druku (np. 'TRASA: Rzeszow 07.10'). Inny napis
    # dziś = etykieta sprzed zmiany — ikona w panelu Logistyki (decyzja Konrada 30.09).
    label_delivery_text = Column(String(40))
    # Weryfikacja (krok 4.3) i załadunek (krok 4.4).
    verified_at = Column(DateTime)
    verified_by_worker_id = Column(Integer)
    verified_method = Column(Enum(*SPOSOBY_POTWIERDZENIA, name='package_verified_method'))
    loaded_at = Column(DateTime)
    loaded_by_worker_id = Column(Integer)
    loaded_method = Column(Enum(*SPOSOBY_POTWIERDZENIA, name='package_loaded_method'))
    loaded_route_id = Column(Integer)

    order = relationship('ProductionOrder')

    @property
    def kod(self):
        """Kod paczki na etykiecie, w QR i w API: 'P-<id>'."""
        return 'P-%d' % self.id

    def __repr__(self):
        return f'<ProductionPackage P-{self.id} order={self.order_id} seq={self.seq}>'
```

W `modules/production/logistics/models.py`:

```python
AKCJE_LOGU = ('sposob_dostawy', 'wydane', 'przepakowanie',
              'trasa_dodane', 'trasa_usuniete', 'trasa_status', 'adres',
              'paczki')
```

i w `LogisticsLog` pod `user_id = Column(Integer, index=True)`:

```python
    # Akcje z tabletów i telefonów (etap 4) mają pracownika i urządzenie (prod_devices.id),
    # a nie użytkownika panelu.
    worker_id = Column(Integer)
    device_id = Column(Integer)
```

- [ ] **Step 5: Log, stałe, fikstury**

`modules/production/logistics/services/delivery.py` — zamień `zapisz_log`:

```python
def zapisz_log(order, akcja, stara=None, nowa=None, user_id=None, note=None,
               route_id=None, teraz=None, worker_id=None, device_id=None):
    db.session.add(LogisticsLog(
        order_id=order.id, action=akcja, old_value=stara, new_value=nowa,
        user_id=user_id, worker_id=worker_id, device_id=device_id, note=note,
        route_id=route_id, created_at=teraz or get_local_now()))
```

`modules/production/logistics/sposoby.py` — pod `STATUS_PO_SPAKOWANIU = {...}`:

```python
# Szacunek wagi drewna (logistyka etap 4, spec 7.1): podpowiedź paczek na tablecie pakowania,
# podsumowanie trasy i eksport Routimo liczą z tej samej gęstości (etykieta paczki ma kopię
# w package_label — test pilnuje zgodności).
WAGA_KG_NA_M3 = 800
# Podpowiedź na tablecie pakowania: szacunek powyżej progu → paleta EUR, do progu → paczka.
PROG_PALETY_KG = 40
```

`tests/logistyka_fixtures.py`:
- do importu z `modules.production.models` dopisz `LabelPrintJob, ProductionPackage`,
- do krotki w `TABLES` dopisz `LabelPrintJob, ProductionPackage` (po `RouteStop`),
- w `zamowienie(...)` dodaj parametr `numer_wewnetrzny=None` (po `bl_id=None`) i zamień przypisanie numeru:

```python
        internal_order_number=(numer_wewnetrzny if numer_wewnetrzny is not None
                               else '26/%05d' % numer),
```

oraz w docstringu dopisz: „`numer_wewnetrzny` — same cyfry jak na produkcji; potrzebne tam, gdzie numer idzie w ścieżce URL (endpointy paczek)”.

- [ ] **Step 6: Uruchom testy zadania**

Run: `PYTEST tests/test_paczki_schemat.py`
Expected: PASS (9 testów).

- [ ] **Step 7: Pełny pakiet**

Run: `PYTEST tests/`
Expected: `5027 passed, 3 skipped` (5018 + 9), 0 failed. Jeśli padnie test, który stawia własną listę tabel z `LabelPrintJob` (np. `tests/druk_fixtures.py`) — klucz obcy do `prod_packages` nie wymaga tej tabeli w SQLite (brak `PRAGMA foreign_keys`); przyczyny szukaj gdzie indziej i opisz ją w raporcie.

- [ ] **Step 8: Commit**

```bash
git add migrations/2026-09-30-logistyka-paczki.sql modules/production/models.py modules/production/logistics/models.py modules/production/logistics/services/delivery.py modules/production/logistics/sposoby.py tests/logistyka_fixtures.py tests/test_paczki_schemat.py
git commit -m "feat(production): tabela paczek zamowienia i log paczek z pracownikiem

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Podpowiedź paczek w kolejce pakowania

**Files:**
- Create: `modules/production/logistics/services/paczki.py`
- Modify: `modules/production/services/mobile_api_service.py` (`serialize_order`, ok. :1051–1202)
- Modify: `modules/production/routers/mobile_api.py` (`KSZTALT_ODPOWIEDZI_KOLEJKI` :123–134, `station_orders` :299–312, `orders_search` :358–370)
- Modify: `modules/production/logistics/services/routes.py:32`
- Modify: `tests/test_logistyka_mobile.py:48`
- Test: `tests/test_paczki_podpowiedz.py`

**Interfaces:**
- Consumes: `ProductionPackage`, `sposoby.WAGA_KG_NA_M3`, `sposoby.PROG_PALETY_KG`, fikstury z Task 1.
- Produces (moduł `modules.production.logistics.services.paczki`):
  - `podpowiedz_pakowania(produkty) -> dict` — `{'kind', 'count', 'pallet_type', 'weight_kg'}`,
  - `podpowiedzi_zamowien(pozycje) -> {order_id: dict}`,
  - `aktualne_paczki(order_id, do_zapisu=False) -> List[ProductionPackage]` (po `seq`, `id`; `do_zapisu=True` = odczyt z blokadą),
  - `aktualne_paczki_zamowien(order_ids) -> {order_id: List[ProductionPackage]}` (jedno zapytanie),
  - `serializuj_paczke(p) -> dict` (kształt „Paczka” z kontraktu API),
  - `serialize_order(item, station_code=None, label_numbering=None, packing_hints=None)` z polem `packing_hint`, `KSZTALT_ODPOWIEDZI_KOLEJKI = 4`.

- [ ] **Step 1: Test, który padnie**

Create `tests/test_paczki_podpowiedz.py`:

```python
# -*- coding: utf-8 -*-
"""Podpowiedź paczek w kolejce pakowania i odczyty paczek (logistyka etap 4, krok 4.2, spec 7.1)."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import paczki, routes
from modules.production.models import ProductionDevice, ProductionPackage
from modules.production.routers import mobile_api
from modules.production.services.mobile_api_service import generate_token, serialize_order
from tests.logistyka_fixtures import app, client, zamowienie  # noqa: F401

PACZKA = {'kind': 'paczka', 'count': 1, 'pallet_type': None}
PALETA = {'kind': 'paleta', 'count': 1, 'pallet_type': 'eur'}


def _poz(m3, ilosc=1, status='czeka_na_pakowanie', order_id=1):
    return SimpleNamespace(volume_m3=Decimal(str(m3)) if m3 is not None else None,
                           quantity=ilosc, current_status=status, order_id=order_id)


def _token(app, stanowisko='packaging'):
    device = ProductionDevice(device_id='TAB-podpowiedz-%s' % stanowisko,
                              device_name='Tablet', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return generate_token(device)


def _paczka(order, seq, voided=False, **kolumny):
    p = ProductionPackage(order_id=order.id, seq=seq, kind=kolumny.pop('kind', 'paczka'),
                          declared_at=datetime(2026, 9, 30, 10, 0),
                          voided_at=datetime(2026, 9, 30, 11, 0) if voided else None, **kolumny)
    db.session.add(p)
    db.session.commit()
    return p


@pytest.mark.parametrize('pozycje, oczekiwane', [
    ([_poz(0.024, 2)], dict(PACZKA, weight_kg=38)),              # 0,048 m³ × 800 = 38,4 kg
    ([_poz(0.373)], dict(PALETA, weight_kg=298)),                # wzór ze specu 7.1
    ([_poz(0.05)], dict(PACZKA, weight_kg=40)),                  # dokładnie próg — jeszcze paczka
    ([_poz(0.0513)], dict(PALETA, weight_kg=41)),
    ([_poz(0.3, status='anulowane'), _poz(0.01)], dict(PACZKA, weight_kg=8)),
    ([_poz(None, 3)], dict(PACZKA, weight_kg=0)),                # pozycja bez objętości
    ([], dict(PACZKA, weight_kg=0)),
])
def test_podpowiedz_pakowania(pozycje, oczekiwane):
    assert paczki.podpowiedz_pakowania(pozycje) == oczekiwane


def test_podpowiedzi_zamowien_grupuje_po_zamowieniu():
    mapa = paczki.podpowiedzi_zamowien([_poz(0.03, status='spakowane', order_id=1),
                                        _poz(0.01, order_id=2), _poz(0.03, order_id=1)])
    assert mapa == {1: dict(PALETA, weight_kg=48), 2: dict(PACZKA, weight_kg=8)}


def test_kolejka_pakowania_niesie_podpowiedz_calego_zamowienia(app, client):
    # 2 pozycje × 0,024 m³ × 2 szt. = 0,096 m³ = 77 kg — liczy się też pozycja już spakowana
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    dane = client.get('/api/mobile/stations/packaging/orders',
                      headers={'Authorization': 'Bearer ' + _token(app)}).get_json()
    pozycje = [o for o in dane['orders'] if o['internal_order_number'] == order.internal_order_number]
    assert len(pozycje) == 2
    assert all(o['packing_hint'] == dict(PALETA, weight_kg=77) for o in pozycje)


def test_etag_kolejki_niesie_ksztalt_4(app, client):
    zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
    r = client.get('/api/mobile/stations/packaging/orders',
                   headers={'Authorization': 'Bearer ' + _token(app)})
    assert mobile_api.KSZTALT_ODPOWIEDZI_KOLEJKI == 4
    assert r.headers['ETag'].endswith(':4"')


def test_wyszukiwarka_niesie_podpowiedz(app, client):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
    order.products[0].volume_m3 = 0.01
    db.session.commit()
    dane = client.get('/api/mobile/orders/search', query_string={'q': order.client_name},
                      headers={'Authorization': 'Bearer ' + _token(app)}).get_json()
    trafienie = next(o for o in dane['orders'] if o['internal_order_number'] == order.internal_order_number)
    assert trafienie['packing_hint'] == dict(PACZKA, weight_kg=16)


def test_pojedyncza_pozycja_liczy_podpowiedz_z_calego_zamowienia(app):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie', 'anulowane'))
    dane = serialize_order(order.products[1], station_code='packaging')
    assert dane['packing_hint'] == dict(PALETA, weight_kg=77)     # anulowana się nie liczy


def test_trasy_licza_ta_sama_gestoscia():
    assert routes.WAGA_KG_NA_M3 == s.WAGA_KG_NA_M3


def test_aktualne_paczki_bez_uniewaznionych_po_numerach(app):
    order = zamowienie(statusy=('spakowane',))
    _paczka(order, 1, voided=True)
    druga, pierwsza = _paczka(order, 2), _paczka(order, 1)
    assert [p.id for p in paczki.aktualne_paczki(order.id)] == [pierwsza.id, druga.id]
    assert [p.id for p in paczki.aktualne_paczki(order.id, do_zapisu=True)] == [pierwsza.id, druga.id]
    inne = zamowienie(statusy=('spakowane',))
    _paczka(inne, 1)
    mapa = paczki.aktualne_paczki_zamowien([order.id, inne.id, 999999])
    assert [p.id for p in mapa[order.id]] == [pierwsza.id, druga.id]
    assert len(mapa[inne.id]) == 1 and 999999 not in mapa
    assert paczki.aktualne_paczki_zamowien([]) == {}


def test_serializuj_paczke(app):
    p = _paczka(zamowienie(statusy=('spakowane',)), 1, kind='paleta', pallet_type='eur',
                length_cm=120, width_cm=80, label_print_count=2,
                label_printed_at=datetime(2026, 9, 30, 12, 5))
    assert paczki.serializuj_paczke(p) == {
        'id': p.id, 'code': 'P-%d' % p.id, 'seq': 1, 'kind': 'paleta', 'pallet_type': 'eur',
        'length_cm': 120, 'width_cm': 80, 'label_print_count': 2,
        'label_printed_at': '2026-09-30T12:05:00'}
```

W `tests/test_logistyka_mobile.py` zmień `test_ksztalt_odpowiedzi_podbity`:

```python
def test_ksztalt_odpowiedzi_podbity():
    assert mobile_api.KSZTALT_ODPOWIEDZI_KOLEJKI == 4   # 4 — packing_hint (etap 4, krok 4.2)
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_paczki_podpowiedz.py tests/test_logistyka_mobile.py`
Expected: FAIL (`ImportError: cannot import name 'paczki'`, `assert 3 == 4`).

- [ ] **Step 3: Serwis paczek (podpowiedź i odczyty)**

Create `modules/production/logistics/services/paczki.py`:

```python
# -*- coding: utf-8 -*-
"""
Paczki zamówienia (logistyka etap 4, krok 4.2, spec 5.2 i 7).

Paczka = paczka albo paleta zadeklarowana przy pakowaniu; kod na etykiecie i w QR to
'P-<id>'. Aktualna deklaracja zamówienia = jego paczki z voided_at IS NULL. Funkcje
NIE commitują — robi to wołający (API mobilne przez @with_idempotency).
"""
from modules.production.logistics import sposoby
from modules.production.models import ProductionPackage


def podpowiedz_pakowania(produkty):
    """
    Obiekt `packing_hint` (spec 7.1) z pozycji JEDNEGO zamówienia: szacunek wagi
    (Σ objętość × sztuki niezanulowanych pozycji × WAGA_KG_NA_M3), powyżej
    PROG_PALETY_KG paleta EUR ×1, do progu paczka ×1. Waga zaokrąglona do kilograma
    i porównywana po zaokrągleniu — próg ma działać tak, jak liczba widziana na tablecie.
    """
    m3 = sum(float(p.volume_m3 or 0) * (p.quantity or 1)
             for p in produkty if p.current_status != 'anulowane')
    waga = int(round(m3 * sposoby.WAGA_KG_NA_M3))
    if waga > sposoby.PROG_PALETY_KG:
        return {'kind': 'paleta', 'count': 1, 'pallet_type': 'eur', 'weight_kg': waga}
    return {'kind': 'paczka', 'count': 1, 'pallet_type': None, 'weight_kg': waga}


def podpowiedzi_zamowien(pozycje):
    """
    {order_id: packing_hint} z listy pozycji, w której są WSZYSTKIE pozycje każdego
    zamówienia — tak budują ją kolejka stanowiska i wyszukiwarka API mobilnego, więc
    mapa nie kosztuje ani jednego zapytania.
    """
    grupy = {}
    for p in pozycje:
        grupy.setdefault(p.order_id, []).append(p)
    return {order_id: podpowiedz_pakowania(produkty) for order_id, produkty in grupy.items()}


def aktualne_paczki(order_id, do_zapisu=False):
    """
    Paczki aktualnej deklaracji w kolejności numerów. `do_zapisu=True` — odczyt bieżący
    z blokadą wierszy (FOR UPDATE): MySQL pracuje na REPEATABLE READ, więc zwykły SELECT
    po zablokowaniu zamówienia widziałby migawkę sprzed czekania na blokadę i przegapił
    paczki zadeklarowane w tym czasie przez inne urządzenie.
    """
    zapytanie = (ProductionPackage.query
                 .filter(ProductionPackage.order_id == order_id,
                         ProductionPackage.voided_at.is_(None))
                 .order_by(ProductionPackage.seq, ProductionPackage.id))
    if do_zapisu:
        zapytanie = zapytanie.with_for_update().populate_existing()
    return zapytanie.all()


def aktualne_paczki_zamowien(order_ids):
    """{order_id: [paczki aktualnej deklaracji]} jednym zapytaniem (listy panelu Logistyki)."""
    if not order_ids:
        return {}
    wynik = {}
    for p in (ProductionPackage.query
              .filter(ProductionPackage.order_id.in_(list(order_ids)),
                      ProductionPackage.voided_at.is_(None))
              .order_by(ProductionPackage.order_id, ProductionPackage.seq, ProductionPackage.id)):
        wynik.setdefault(p.order_id, []).append(p)
    return wynik


def serializuj_paczke(p):
    """Paczka w API mobilnym (kontrakt kroku 4.2; krok 4.3 dołoży stan weryfikacji)."""
    return {
        'id': p.id,
        'code': p.kod,
        'seq': p.seq,
        'kind': p.kind,
        'pallet_type': p.pallet_type,
        'length_cm': p.length_cm,
        'width_cm': p.width_cm,
        'label_print_count': p.label_print_count or 0,
        'label_printed_at': p.label_printed_at.isoformat() if p.label_printed_at else None,
    }
```

- [ ] **Step 4: Serializer i endpointy list**

`modules/production/services/mobile_api_service.py`, `serialize_order`:
- sygnatura: `def serialize_order(item, station_code=None, label_numbering=None, packing_hints=None):`
- do docstringu dopisz akapit: „`packing_hints` — gotowa mapa {order_id: packing_hint} z paczki.podpowiedzi_zamowien(); listy MUSZĄ ją podawać (jak label_numbering), pojedyncza pozycja policzy podpowiedź z pozycji swojego zamówienia.”
- tuż przed `return {` (po bloku `transport = ...`):

```python
    # Podpowiedź paczek (logistyka etap 4, spec 7.1) — ta sama dla wszystkich pozycji
    # zamówienia; tablet zaznacza nią wybór w oknie paczek przy „ZAKOŃCZ”. Obecność pola
    # mówi appce, że backend przyjmuje deklarację paczek (jak `transport` w etapie 1).
    from modules.production.logistics.services import paczki
    if packing_hints is not None and item.order_id in packing_hints:
        packing_hint = packing_hints[item.order_id]
    else:
        packing_hint = paczki.podpowiedz_pakowania(item.order.products if item.order else [item])
```

- w słowniku wynikowym, po `'transport': transport,`:

```python
        'packing_hint': packing_hint,
```

`modules/production/routers/mobile_api.py`:
- lista historii kształtu i stała:

```python
#   3 — 2026-09-25: obiekt `transport` (logistyka równoległa)
#   4 — 2026-09-30: `packing_hint` (logistyka etap 4, krok 4.2 — okno paczek na pakowaniu)
KSZTALT_ODPOWIEDZI_KOLEJKI = 4
```

- `station_orders`: pod `numeracja = compute_label_offsets(items)` dopisz

```python
    # Podpowiedź paczek z tej samej listy (są w niej wszystkie pozycje każdego zamówienia).
    from modules.production.logistics.services.paczki import podpowiedzi_zamowien
    podpowiedzi = podpowiedzi_zamowien(items)
```

i w liście: `serialize_order(it, station_code=station_code, label_numbering=numeracja, packing_hints=podpowiedzi)`.
- `orders_search`: analogicznie po `numeracja = compute_label_offsets(items)` — `podpowiedzi = podpowiedzi_zamowien(items)` (ten sam import lokalny) i `serialize_order(it, label_numbering=numeracja, packing_hints=podpowiedzi)`.

`modules/production/logistics/services/routes.py:32`:

```python
WAGA_KG_NA_M3 = sposoby.WAGA_KG_NA_M3   # etap 4: jedno źródło gęstości (sposoby.py)
```

- [ ] **Step 5: Uruchom testy zadania**

Run: `PYTEST tests/test_paczki_podpowiedz.py tests/test_logistyka_mobile.py`
Expected: PASS.

- [ ] **Step 6: Pełny pakiet**

Run: `PYTEST tests/`
Expected: 0 failed, passed = wynik Task 1 + 15 (testy `test_paczki_podpowiedz.py` wliczając parametry; zmieniony test w `test_logistyka_mobile.py` się nie dolicza).

- [ ] **Step 7: Commit**

```bash
git add modules/production/logistics/services/paczki.py modules/production/services/mobile_api_service.py modules/production/routers/mobile_api.py modules/production/logistics/services/routes.py tests/test_paczki_podpowiedz.py tests/test_logistyka_mobile.py
git commit -m "feat(production): podpowiedz paczek w kolejce pakowania

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Etykiety paczek z danych zamówienia (tor równoległy do Task 2)

**Files:**
- Create: `modules/production/logistics/services/paczki_druk.py`
- Modify: `modules/production/services/package_label.py` (stała wagi — komentarz, `tekst_ascii`, stopka)
- Modify: `modules/production/services/print_queue_service.py`
- Modify: `tests/test_etykieta_paczki.py` (dopisane testy)
- Test: `tests/test_paczki_etykiety.py`

**Interfaces:**
- Consumes: `ProductionPackage` (`.kod`, `.seq`, `.kind`, `.pallet_type`, `.length_cm`, `.width_cm`, `.label_*`), `routes.trasa_dla_tabletu(order_id)`, `package_label.DaneEtykietyPaczki/PozycjaEtykiety/generate_package_label_zpl/wczytaj_przesuniecie`, `print_queue_service.zakolejkuj_zpl`, `label_print_service._format_finish_label(item)`.
- Produces:
  - `paczki_druk.napis_sposobu(order, trasa=None) -> str` — ASCII, najwyżej 26 znaków, `trasa` = trasa AKTYWNA albo None,
  - `paczki_druk.dane_etykiety(order, paczka, z_ilu, napis) -> DaneEtykietyPaczki`,
  - `paczki_druk.drukuj_etykiety(order, paczki, z_ilu, stanowisko, aktor, teraz) -> int` (kolejkuje na `wysylka`, ustawia `label_printed_at`, `label_print_count += 1`, `label_delivery_text`, planuje sygnał),
  - `package_label.tekst_ascii(tekst, maks) -> str`,
  - `print_queue_service.zaplanuj_sygnal_po_commicie(liczba)`, `print_queue_service.wyslij_zaplanowany_sygnal() -> int`.

Uwaga dla implementera: `test_kod_paczki_i_pozycje_nie_wstrzykuja_komend_zpl` i `test_waga_ta_sama_co_w_logistyce` przejdą od razu — przypinają zachowanie z kroku 4.1 (luka w testach z przeglądu), a nie nową funkcję. To oczekiwane.

- [ ] **Step 1: Testy, które padną**

Dopisz na końcu `tests/test_etykieta_paczki.py`:

```python
def test_stopka_numer_base_jako_liczba():
    """Numer Base. idzie do ZPL przez int() — tekst z komendą nie przejdzie po cichu."""
    assert '^FDBase.: 12345678   Zam. klienta: 1234/2026' in pl.generate_package_label_zpl(_dane())
    assert '^FDBase.: -   Zam. klienta:' in pl.generate_package_label_zpl(_dane(base_id=None))
    with pytest.raises(ValueError):
        pl.generate_package_label_zpl(_dane(base_id='12^FS'))


def test_kod_paczki_i_pozycje_nie_wstrzykuja_komend_zpl():
    """Kod paczki (QR i tekst) i pola pozycji też idą przez _ascii (luka z przeglądu 4.1)."""
    zpl = pl.generate_package_label_zpl(_dane(
        kod_paczki='P-1^XZ~JA',
        pozycje=[_pozycja(gatunek='^XA', technologia='~JA', klasa='^FS', wykonczenie='~DG')]))
    assert zpl.count('^XZ') == 1 and zpl.count('^XA') == 1 and '~' not in zpl


def test_tekst_ascii_publiczny():
    assert pl.tekst_ascii(u'Łódź ^ ~ „x”', 26) == 'Lodz "x"'


def test_waga_ta_sama_co_w_logistyce():
    from modules.production.logistics import sposoby
    assert pl.WAGA_KG_NA_M3 == sposoby.WAGA_KG_NA_M3
```

Create `tests/test_paczki_etykiety.py`:

```python
# -*- coding: utf-8 -*-
"""Etykiety paczek z danych zamówienia (logistyka etap 4, krok 4.2, spec 6.3 i 7.2)."""
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import Route, RouteStop
from modules.production.logistics.services import paczki_druk
from modules.production.models import LabelPrintJob, ProductionConfiguration, ProductionPackage
from modules.production.services import print_queue_service as pqs
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

AKTOR = {'type': 'device', 'id': 'TAB-1'}


@pytest.fixture()
def sygnaly(monkeypatch):
    wyslane = []
    monkeypatch.setattr(pqs.realtime_service, 'publish_print_signal',
                        lambda n: wyslane.append(n) or True)
    return wyslane


def _trasa(nazwa=u'Rzeszów', od=date(2026, 10, 7)):
    return SimpleNamespace(name=nazwa, date_from=od)


def _paczka(order, seq=1, **kolumny):
    p = ProductionPackage(order_id=order.id, seq=seq, kind=kolumny.pop('kind', 'paczka'),
                          declared_at=datetime(2026, 9, 30, 10, 0), **kolumny)
    db.session.add(p)
    db.session.flush()
    return p


@pytest.mark.parametrize('sposob, trasa, napis', [
    (s.KURIER, None, 'KURIER'),
    (s.ODBIOR, None, 'ODBIOR OSOBISTY'),
    (s.TRANSPORT, None, 'TRANSPORT WOODPOWER'),
    (None, None, 'NIE USTAWIONO'),
    ('cos_innego', None, 'NIE USTAWIONO'),
    (s.TRANSPORT, _trasa(), 'TRASA: Rzeszow 07.10'),
    (s.KURIER, _trasa(), 'KURIER'),                            # trasa liczy się tylko dla transportu
    (s.TRANSPORT, _trasa(u'Kraków + Tarnów + Nowy Sącz'), 'TRASA: Krakow + T... 07.10'),
    (s.TRANSPORT, _trasa(u'^XA~JA Łódź'), 'TRASA: XA JA Lodz 07.10'),
])
def test_napis_sposobu(sposob, trasa, napis):
    wynik = paczki_druk.napis_sposobu(SimpleNamespace(override_delivery_method=sposob), trasa)
    assert wynik == napis
    assert len(wynik) <= 26 and all(ord(z) < 128 for z in wynik)


def test_dane_etykiety_z_zamowienia(app):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'spakowane', 'anulowane'),
                       delivery_fullname='Janusz Testowy', delivery_company='TESTBUD',
                       client_order_number='1234/2026')
    konfiguracja = ProductionConfiguration(species=u'dąb', technology='lity', wood_class='A/B')
    db.session.add(konfiguracja)
    db.session.flush()
    pierwsza, druga, _anulowana = sorted(order.products, key=lambda p: p.product_sequence_in_order)
    pierwsza.configuration = konfiguracja
    pierwsza.parsed_length_cm, pierwsza.parsed_width_cm, pierwsza.parsed_thickness_cm = 97, 29, 4
    pierwsza.parsed_finish_type, pierwsza.parsed_finish_gloss = 'lakierowane', 'matowy'
    pierwsza.packaging_completed_at = datetime(2026, 9, 29, 15, 0)
    druga.packaging_completed_at = datetime(2026, 9, 30, 9, 0)
    paczka = _paczka(order, seq=2, kind='paleta', pallet_type='niestandardowa',
                     length_cm=150, width_cm=100)
    db.session.commit()

    dane = paczki_druk.dane_etykiety(order, paczka, 3, 'KURIER')
    assert (dane.numer_zamowienia, dane.kod_paczki, dane.rodzaj, dane.numer, dane.z_ilu, dane.sposob) == \
        (order.internal_order_number, paczka.kod, 'paleta', 2, 3, 'KURIER')
    assert dane.odbiorca == 'Janusz Testowy'
    assert (dane.typ_palety, dane.dlugosc_cm, dane.szerokosc_cm) == ('niestandardowa', 150, 100)
    assert len(dane.pozycje) == 2                                  # anulowana nie trafia na etykietę
    p1 = dane.pozycje[0]
    assert (p1.gatunek, p1.technologia, p1.klasa, p1.wykonczenie, p1.ilosc) == \
        (u'dąb', 'lity', 'A/B', 'LAK MAT', 2)
    assert (p1.dlugosc_cm, p1.szerokosc_cm, p1.grubosc_cm) == (97.0, 29.0, 4.0)
    assert (dane.pozycje[1].gatunek, dane.pozycje[1].wykonczenie) == ('', None)   # bez konfiguracji, surowe
    assert dane.m3 == pytest.approx(0.096)                         # 2 × 0,024 m³ × 2 szt.
    assert dane.spakowano == date(2026, 9, 30)
    assert (dane.base_id, dane.zamowienie_klienta) == (order.baselinker_order_id, '1234/2026')


def test_konfiguracja_unknown_nie_trafia_na_etykiete(app):
    order = zamowienie(statusy=('spakowane',))
    order.products[0].configuration = ProductionConfiguration(
        species='unknown', technology='unknown', wood_class='unknown')
    paczka = _paczka(order)
    dane = paczki_druk.dane_etykiety(order, paczka, 1, 'KURIER')
    assert (dane.pozycje[0].gatunek, dane.pozycje[0].technologia, dane.pozycje[0].klasa) == ('', '', '')


@pytest.mark.parametrize('kolumny, odbiorca', [
    ({'delivery_fullname': 'Jan Nowak', 'delivery_company': 'Firma'}, 'Jan Nowak'),
    ({'delivery_fullname': '', 'delivery_company': 'TESTBUD'}, 'TESTBUD'),
    ({'delivery_fullname': None, 'delivery_company': None}, 'KLIENT'),
])
def test_odbiorca_osoba_firma_klient(app, kolumny, odbiorca):
    order = zamowienie(statusy=('spakowane',), **kolumny)
    dane = paczki_druk.dane_etykiety(order, _paczka(order), 1, 'KURIER')
    assert dane.odbiorca == (order.client_name if odbiorca == 'KLIENT' else odbiorca)


def test_paleta_eur_bez_wymiaru_na_danych(app):
    order = zamowienie(statusy=('spakowane',))
    paczka = _paczka(order, kind='paleta', pallet_type='eur', length_cm=120, width_cm=80)
    dane = paczki_druk.dane_etykiety(order, paczka, 1, 'KURIER')
    assert (dane.typ_palety, dane.dlugosc_cm, dane.szerokosc_cm) == ('eur', None, None)


def test_drukuj_etykiety_kolejkuje_na_drukarke_paczek(app, sygnaly):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
    lista = [_paczka(order, seq=1), _paczka(order, seq=2)]
    teraz = datetime(2026, 9, 30, 10, 5)
    with app.test_request_context():
        assert paczki_druk.drukuj_etykiety(order, lista, 2, 'packaging', AKTOR, teraz) == 2
        db.session.commit()
        assert sygnaly == []                        # sygnał dopiero przez wyslij_zaplanowany_sygnal
        assert pqs.wyslij_zaplanowany_sygnal() == 2
    assert sygnaly == [2]
    zadania = LabelPrintJob.query.order_by(LabelPrintJob.id).all()
    assert [(z.printer, z.package_id, z.short_product_id, z.station_code, z.baselinker_order_id)
            for z in zadania] == [('wysylka', p.id, p.kod, 'packaging', order.baselinker_order_id)
                                  for p in lista]
    assert '^FDLA,%s^FS' % lista[0].kod in zadania[0].zpl_payload
    assert '^FR^FD1 / 2^FS' in zadania[0].zpl_payload and '^FR^FD2 / 2^FS' in zadania[1].zpl_payload
    assert '^FR^FDKURIER^FS' in zadania[1].zpl_payload
    assert all((p.label_printed_at, p.label_print_count, p.label_delivery_text) == (teraz, 1, 'KURIER')
               for p in lista)


def test_trasa_wykonana_nie_trafia_na_etykiete(app, sygnaly):
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    trasa = Route(name=u'Rzeszów', date_from=date(2026, 10, 7), date_to=date(2026, 10, 7),
                  status='wykonana')
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
    paczka = _paczka(order)
    paczki_druk.drukuj_etykiety(order, [paczka], 1, 'packaging', AKTOR, datetime(2026, 9, 30, 10, 5))
    assert paczka.label_delivery_text == 'TRANSPORT WOODPOWER'
    trasa.status = 'zatwierdzona'
    db.session.flush()
    paczki_druk.drukuj_etykiety(order, [paczka], 1, 'packaging', AKTOR, datetime(2026, 9, 30, 10, 6))
    assert (paczka.label_delivery_text, paczka.label_print_count) == ('TRASA: Rzeszow 07.10', 2)


def test_sygnal_po_commicie_raz_na_zadanie(app, sygnaly):
    with app.test_request_context():
        pqs.zaplanuj_sygnal_po_commicie(2)
        pqs.zaplanuj_sygnal_po_commicie(1)
        assert pqs.wyslij_zaplanowany_sygnal() == 3
        assert pqs.wyslij_zaplanowany_sygnal() == 0
    assert sygnaly == [3]
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_paczki_etykiety.py tests/test_etykieta_paczki.py`
Expected: FAIL (`ImportError: cannot import name 'paczki_druk'`; `test_stopka_numer_base_jako_liczba` — brak `ValueError`; `test_tekst_ascii_publiczny` — brak `tekst_ascii`).

- [ ] **Step 3: `package_label.py`**

Komentarz przy stałej wagi zamień na:

```python
# Kopia sposoby.WAGA_KG_NA_M3 (logistyka etap 4) — test pilnuje zgodności. Import zamiast
# kopii ładowałby pakiet modules.production.logistics z jego routerami, a ten moduł ma
# zostać lekki (czytają go serwisy druku).
WAGA_KG_NA_M3 = 800
```

Pod `_ascii` dodaj:

```python
def tekst_ascii(tekst, maks):
    """Publiczne _ascii: napis pasa sposobu dostawy składa serwis paczek
    (logistics/services/paczki_druk.py) i porównuje go z zapisanym na paczce."""
    return _ascii(tekst, maks)
```

W `generate_package_label_zpl`, sekcja 6 (stopka) — zamień dwa ostatnie wywołania `z.pole(...)` stopki na:

```python
    # 6. Stopka. Numer Base. przez int(): to liczba z bazy, a tekst (np. z komendą ZPL)
    # ma się wywrócić głośno, zamiast trafić do pola.
    base = '%d' % int(dane.base_id) if dane.base_id else '-'
    z.pole(32, 1100, '^GB736,2,2^FS')
    z.pole(32, 1108, '^A0N,22,22^FDBase.: %s   Zam. klienta: %s   WoodPower, Bachorz 14N^FS'
           % (base, _ascii(dane.zamowienie_klienta or '-', MAKS_ZAMOWIENIA_KLIENTA)))
```

- [ ] **Step 4: Sygnał po commicie w `print_queue_service.py`**

Dopisz import `from flask import g` i na końcu modułu:

```python
def zaplanuj_sygnal_po_commicie(liczba):
    """
    Sygnał dla agenta druku PO commicie transakcji żądania (etykiety paczek z API
    mobilnego, krok 4.2). W API mobilnym commit robi @with_idempotency, więc handler nie
    może wysłać sygnału sam — agent obudzony przed commitem wróciłby z pustymi rękami.
    Wysyła go wyslij_zaplanowany_sygnal() wołane przez dekorator po udanym commicie;
    odmowa i błąd kończą się rollbackiem bez sygnału (g żyje tylko do końca żądania).
    """
    g.sygnal_druku_po_commicie = getattr(g, 'sygnal_druku_po_commicie', 0) + int(liczba)


def wyslij_zaplanowany_sygnal():
    """Wysyła zaplanowany sygnał (jeden na żądanie, z sumą zadań). Zwraca liczbę zadań."""
    liczba = getattr(g, 'sygnal_druku_po_commicie', 0)
    g.sygnal_druku_po_commicie = 0
    if liczba:
        realtime_service.publish_print_signal(liczba)
    return liczba
```

- [ ] **Step 5: `paczki_druk.py`**

Create `modules/production/logistics/services/paczki_druk.py`:

```python
# -*- coding: utf-8 -*-
"""
Etykiety paczek (logistyka etap 4, krok 4.2, spec 6.3 i 7): dane etykiety z bazy i druk na
drukarce 'wysylka'. ZPL składa package_label (krok 4.1), kolejkuje print_queue_service.

Funkcje NIE commitują. Sygnał dla agenta druku idzie PO commicie wołającego
(print_queue_service.zaplanuj_sygnal_po_commicie).
"""
from modules.production.logistics import sposoby
from modules.production.logistics.services.routes import trasa_dla_tabletu
from modules.production.models import LabelPrintJob
from modules.production.services import package_label, print_queue_service
from modules.production.services.label_print_service import _format_finish_label

NAPISY = {sposoby.KURIER: 'KURIER', sposoby.ODBIOR: 'ODBIOR OSOBISTY',
          sposoby.TRANSPORT: 'TRANSPORT WOODPOWER'}
NIE_USTAWIONO = 'NIE USTAWIONO'
# Tyle znaków mieści pas sposobu dostawy (package_label: _ascii(dane.sposob, 26)).
MAKS_NAPISU = 26
# 'TRASA: ' + nazwa + ' dd.mm' = 26 — przy długiej nazwie ucinamy nazwę, nie datę.
MAKS_NAZWY_TRASY = 13


def napis_sposobu(order, trasa=None):
    """
    Tekst pasa sposobu dostawy (spec 6.3, pkt 2), już w ASCII i przycięty. Ten sam napis
    trafia na etykietę i do prod_packages.label_delivery_text — panel Logistyki porównuje
    go z dzisiejszym („etykiety paczek sprzed zmiany”). `trasa` — trasa AKTYWNA zamówienia
    (robocza/zatwierdzona) albo None; trasa wykonana już nie jedzie, więc nie trafia na etykietę.
    """
    sposob = sposoby.normalizuj(getattr(order, 'override_delivery_method', None))
    if sposob == sposoby.TRANSPORT and trasa is not None:
        data = trasa.date_from.strftime('%d.%m') if trasa.date_from else ''
        napis = u'TRASA: %s %s' % (package_label.tekst_ascii(trasa.name, MAKS_NAZWY_TRASY), data)
    else:
        napis = NAPISY.get(sposob, NIE_USTAWIONO)
    return package_label.tekst_ascii(napis, MAKS_NAPISU)


def _cecha(konfiguracja, nazwa):
    # find_or_create zapisuje 'unknown' dla nieparsowalnych nazw — na etykiecie puste pole.
    wartosc = getattr(konfiguracja, nazwa, None) if konfiguracja is not None else None
    return '' if wartosc in (None, '', 'unknown') else wartosc


def _aktywne(order):
    return sorted((p for p in order.products if p.current_status != 'anulowane'),
                  key=lambda p: (p.product_sequence_in_order or 0, p.id or 0))


def dane_etykiety(order, paczka, z_ilu, napis):
    """DaneEtykietyPaczki (krok 4.1) dla jednej paczki: cała zawartość zamówienia (bez
    przypisania pozycji do paczek — spec 2 pkt 5), odbiorca osoba → firma → klient
    (anonimizuje generator), wymiar tylko palety niestandardowej (EUR ma go w nazwie)."""
    aktywne = _aktywne(order)
    spakowane = [p.packaging_completed_at for p in aktywne if p.packaging_completed_at]
    niestandardowa = paczka.pallet_type == 'niestandardowa'
    return package_label.DaneEtykietyPaczki(
        numer_zamowienia=order.internal_order_number or '',
        kod_paczki=paczka.kod,
        rodzaj=paczka.kind,
        numer=paczka.seq,
        z_ilu=z_ilu,
        sposob=napis,
        odbiorca=order.delivery_fullname or order.delivery_company or order.client_name,
        pozycje=[package_label.PozycjaEtykiety(
            gatunek=_cecha(p.configuration, 'species'),
            technologia=_cecha(p.configuration, 'technology'),
            klasa=_cecha(p.configuration, 'wood_class'),
            dlugosc_cm=float(p.parsed_length_cm or 0),
            szerokosc_cm=float(p.parsed_width_cm or 0),
            grubosc_cm=float(p.parsed_thickness_cm or 0),
            ilosc=int(p.quantity or 0),
            wykonczenie=_format_finish_label(p) or None) for p in aktywne],
        typ_palety=paczka.pallet_type,
        dlugosc_cm=paczka.length_cm if niestandardowa else None,
        szerokosc_cm=paczka.width_cm if niestandardowa else None,
        m3=sum(float(p.volume_m3 or 0) * (p.quantity or 1) for p in aktywne),
        spakowano=max(spakowane).date() if spakowane else None,
        base_id=order.baselinker_order_id,
        zamowienie_klienta=order.client_order_number,
    )


def drukuj_etykiety(order, paczki, z_ilu, stanowisko, aktor, teraz):
    """
    Kolejkuje etykiety `paczki` na drukarkę 'wysylka' z BIEŻĄCYMI danymi zamówienia
    (sposób dostawy, trasa aktywna, zawartość) i zapisuje stan druku paczek. `z_ilu` —
    liczba paczek aktualnej deklaracji (mianownik „2 / 3”). Zwraca liczbę zadań.
    """
    napis = napis_sposobu(order, trasa_dla_tabletu(order.id))
    przesuniecie = package_label.wczytaj_przesuniecie()
    for paczka in paczki:
        zpl = package_label.generate_package_label_zpl(
            dane_etykiety(order, paczka, z_ilu, napis), przesuniecie)
        print_queue_service.zakolejkuj_zpl(
            LabelPrintJob.DRUKARKA_WYSYLKA, zpl, paczka.kod, stanowisko, aktor,
            baselinker_order_id=order.baselinker_order_id, package_id=paczka.id)
        paczka.label_printed_at = teraz
        paczka.label_print_count = (paczka.label_print_count or 0) + 1
        paczka.label_delivery_text = napis
    if paczki:
        print_queue_service.zaplanuj_sygnal_po_commicie(len(paczki))
    return len(paczki)
```

- [ ] **Step 6: Uruchom testy zadania**

Run: `PYTEST tests/test_paczki_etykiety.py tests/test_etykieta_paczki.py`
Expected: PASS.

- [ ] **Step 7: Pełny pakiet (w worktree toru, projekt `logistyka4-t3`)**

Run: `PYTEST tests/`
Expected: 0 failed, passed = wynik Task 1 + nowe testy tego zadania (tor nie ma jeszcze testów Task 2 — suma zgadza się dopiero po scaleniu).

- [ ] **Step 8: Commit**

```bash
git add modules/production/logistics/services/paczki_druk.py modules/production/services/package_label.py modules/production/services/print_queue_service.py tests/test_paczki_etykiety.py tests/test_etykieta_paczki.py
git commit -m "feat(production): etykiety paczek z danych zamowienia na drukarce paczek

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Deklaracja paczek z tabletu (`PUT` i `GET …/packages`)

Start po scaleniu Task 2 i Task 3 w `claude/logistyka-etap-4` (pełny pakiet po scaleniu = suma obu).

**Files:**
- Modify: `modules/production/logistics/services/paczki.py` (deklaracja, walidacja, unieważnianie, opis)
- Modify: `modules/production/services/mobile_api_service.py` (`with_idempotency`, ok. :617–626)
- Modify: `modules/production/routers/mobile_api.py` (nowa sekcja PACZKI po sekcji DRUKOWANIE ETYKIET)
- Test: `tests/test_paczki_deklaracja.py`

**Interfaces:**
- Consumes: z Task 2 `aktualne_paczki`, `serializuj_paczke`; z Task 3 `paczki_druk.drukuj_etykiety`, `print_queue_service.wyslij_zaplanowany_sygnal`; z Task 1 `delivery.zapisz_log(..., worker_id, device_id)`, `ProductionOrder.packages_declared_at`.
- Produces (w `paczki`): `STANOWISKA_PACZEK = ('packaging', 'verification')`, `MAKS_PACZEK = 10`, `WYMIAR_EUR = (120, 80)`, `WYMIAR_MIN_CM = 20`, `WYMIAR_MAX_CM = 400`, `class PaczkiBlad(Exception)` (`kod`, `komunikat`, `status`), `Deklaracja(kind, count, pallet_type=None, length_cm=None, width_cm=None)`, `waliduj_deklaracje(dane) -> Deklaracja`, `opis(kind, count, pallet_type=None, length_cm=None, width_cm=None) -> str`, `opis_paczek(paczki) -> Optional[str]`, `uniewaznij(paczki, teraz) -> int`, `zadeklaruj(order, deklaracja, stanowisko, aktor, worker_id=None, device_id=None, teraz=None) -> List[ProductionPackage]`. W routerze: `_stanowisko_paczek()`, `_zamowienie_po_numerze(numer, do_zapisu=False)`, `_brak_zamowienia(numer)`, `_odpowiedz_paczek(order, paczki_lista, **dodatkowe)`, `_blad_paczek(e)`, `_aktor()`; endpointy `order_packages` (GET) i `order_packages_declare` (PUT).

- [ ] **Step 1: Test, który padnie**

Create `tests/test_paczki_deklaracja.py`:

```python
# -*- coding: utf-8 -*-
"""Deklaracja paczek z tabletu pakowania (logistyka etap 4, krok 4.2, spec 7.2)."""
import itertools
from datetime import datetime

import pytest
from sqlalchemy import event

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog
from modules.production.logistics.services import paczki
from modules.production.models import (LabelPrintJob, ProductionDevice, ProductionOrder,
                                       ProductionPackage, ProductionProduct)
from modules.production.routers import mobile_api
from modules.production.services import print_queue_service as pqs
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import app, client, pracownik, zamowienie  # noqa: F401

_numery = itertools.count(1400)
_licznik = itertools.count(1)


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    """Spakowanie odpala synchronizację statusu Base. po commicie — w testach jej nie chcemy."""
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


@pytest.fixture()
def sygnaly(monkeypatch):
    wyslane = []
    monkeypatch.setattr(pqs.realtime_service, 'publish_print_signal',
                        lambda n: wyslane.append(n) or True)
    return wyslane


def _urzadzenie(stanowisko='packaging'):
    device = ProductionDevice(device_id='TAB-%s-%d' % (stanowisko, next(_licznik)),
                              device_name='Tablet', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return device


def _naglowki(device, op_id=None, **inne):
    naglowki = {'Authorization': 'Bearer ' + generate_token(device),
                'X-Operation-Id': op_id or 'op-paczki-%d' % next(_licznik)}
    naglowki.update(inne)
    return naglowki


def _spakowane(sposob=s.KURIER, statusy=('spakowane', 'spakowane'), **kolumny):
    return zamowienie(sposob=sposob, statusy=statusy, numer_wewnetrzny=str(next(_numery)), **kolumny)


def _url(order):
    return '/api/mobile/orders/%s/packages' % order.internal_order_number


def _put(client, order, device, dane, **naglowki):
    return client.put(_url(order), json=dane, headers=_naglowki(device, **naglowki))


def test_deklaracja_tworzy_paczki_i_kolejkuje_etykiety(app, client, sygnaly):
    order, device = _spakowane(), _urzadzenie()
    r = _put(client, order, device, {'kind': 'paczka', 'count': 3})
    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    nowe = ProductionPackage.query.filter_by(order_id=order.id).order_by(ProductionPackage.seq).all()
    assert [(p.seq, p.kind, p.pallet_type, p.voided_at) for p in nowe] == \
        [(1, 'paczka', None, None), (2, 'paczka', None, None), (3, 'paczka', None, None)]
    assert all((p.declared_device_id, p.label_print_count, p.label_delivery_text) == (device.id, 1, 'KURIER')
               for p in nowe)
    assert [p['code'] for p in dane['packages']] == [p.kod for p in nowe]
    assert dane['labels_queued'] == 3 and dane['internal_order_number'] == order.internal_order_number
    assert u'3 × paczka' in dane['message'] and dane['packages_declared_at']
    zadania = LabelPrintJob.query.order_by(LabelPrintJob.id).all()
    assert [(z.printer, z.package_id, z.short_product_id) for z in zadania] == \
        [('wysylka', p.id, p.kod) for p in nowe]
    assert '^FR^FD3 / 3^FS' in zadania[2].zpl_payload
    assert ProductionOrder.query.get(order.id).packages_declared_at is not None
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='paczki').one()
    assert (wpis.old_value, wpis.new_value, wpis.device_id) == (None, u'3 × paczka', device.id)
    assert sygnaly == [3]


@pytest.mark.parametrize('dane, zapisane, na_etykiecie', [
    ({'kind': 'paleta', 'count': 1, 'pallet_type': 'eur'}, ('paleta', 'eur', 120, 80), 'PALETA EUR 120x80'),
    ({'kind': 'paleta', 'count': 1, 'pallet_type': 'eur', 'length_cm': 100, 'width_cm': 100},
     ('paleta', 'eur', 120, 80), 'PALETA EUR 120x80'),
    ({'kind': 'paleta', 'count': 2, 'pallet_type': 'niestandardowa', 'length_cm': 150, 'width_cm': 100},
     ('paleta', 'niestandardowa', 150, 100), 'PALETA 150x100'),
    ({'kind': 'paczka', 'count': 1, 'pallet_type': 'eur', 'length_cm': 50},
     ('paczka', None, None, None), 'PACZKA'),
])
def test_rodzaje_i_wymiary(app, client, sygnaly, dane, zapisane, na_etykiecie):
    order = _spakowane()
    assert _put(client, order, _urzadzenie(), dane).status_code == 200
    p = paczki.aktualne_paczki(order.id)[0]
    assert (p.kind, p.pallet_type, p.length_cm, p.width_cm) == zapisane
    assert '^FD%s^FS' % na_etykiecie in LabelPrintJob.query.first().zpl_payload


@pytest.mark.parametrize('dane', [
    None, [], {}, {'kind': 'skrzynia', 'count': 1}, {'kind': 'paczka'},
    {'kind': 'paczka', 'count': 0}, {'kind': 'paczka', 'count': 11},
    {'kind': 'paczka', 'count': True}, {'kind': 'paczka', 'count': '2'}, {'kind': 'paczka', 'count': 1.5},
    {'kind': 'paleta', 'count': 1}, {'kind': 'paleta', 'count': 1, 'pallet_type': 'duza'},
    {'kind': 'paleta', 'count': 1, 'pallet_type': 'niestandardowa'},
    {'kind': 'paleta', 'count': 1, 'pallet_type': 'niestandardowa', 'length_cm': 19, 'width_cm': 100},
    {'kind': 'paleta', 'count': 1, 'pallet_type': 'niestandardowa', 'length_cm': 150, 'width_cm': 401},
    {'kind': 'paleta', 'count': 1, 'pallet_type': 'niestandardowa', 'length_cm': '150', 'width_cm': 100},
])
def test_zle_dane_422(app, client, sygnaly, dane):
    order = _spakowane()
    r = _put(client, order, _urzadzenie(), dane)
    assert r.status_code == 422 and r.get_json()['error'] == 'invalid_packages'
    assert r.get_json()['message']
    assert ProductionPackage.query.count() == 0 and LabelPrintJob.query.count() == 0 and sygnaly == []


def test_niespakowane_zamowienie_409_i_ponowienie_po_spakowaniu(app, client, sygnaly):
    """Review Focus 2: kolejka appki nie gwarantuje, że ostatni COMPLETE przeszedł pierwszy."""
    order, device = _spakowane(statusy=('spakowane', 'czeka_na_pakowanie')), _urzadzenie()
    naglowki = _naglowki(device, op_id='op-rata')
    r = client.put(_url(order), json={'kind': 'paczka', 'count': 1}, headers=naglowki)
    assert r.status_code == 409 and r.get_json()['error'] == 'order_not_packed'
    assert order.internal_order_number in r.get_json()['message']
    assert ProductionPackage.query.count() == 0 and LabelPrintJob.query.count() == 0 and sygnaly == []
    for p in order.products:
        p.current_status = 'spakowane'
    db.session.commit()
    r = client.put(_url(order), json={'kind': 'paczka', 'count': 1}, headers=naglowki)
    assert r.status_code == 200 and ProductionPackage.query.count() == 1


def test_anulowana_pozycja_nie_blokuje_deklaracji(app, client, sygnaly):
    order = _spakowane(statusy=('spakowane', 'anulowane'))
    assert _put(client, order, _urzadzenie(), {'kind': 'paczka', 'count': 1}).status_code == 200


def test_zamowienie_calkiem_anulowane_409(app, client, sygnaly):
    r = _put(client, _spakowane(statusy=('anulowane',)), _urzadzenie(), {'kind': 'paczka', 'count': 1})
    assert r.status_code == 409 and r.get_json()['error'] == 'order_not_packed'


def test_ponowna_deklaracja_uniewaznia_poprzednia(app, client, sygnaly):
    order, device = _spakowane(), _urzadzenie()
    assert _put(client, order, device, {'kind': 'paczka', 'count': 2}).status_code == 200
    stare_id = [p.id for p in paczki.aktualne_paczki(order.id)]
    assert _put(client, order, device, {'kind': 'paleta', 'count': 1, 'pallet_type': 'eur'}).status_code == 200
    aktualne = paczki.aktualne_paczki(order.id)
    assert [(p.seq, p.kind) for p in aktualne] == [(1, 'paleta')]
    assert all(ProductionPackage.query.get(i).voided_at is not None for i in stare_id)
    assert LabelPrintJob.query.count() == 3 and sygnaly == [2, 1]
    wpisy = LogisticsLog.query.filter_by(order_id=order.id, action='paczki').order_by(LogisticsLog.id).all()
    assert [(w.old_value, w.new_value) for w in wpisy] == [(None, u'2 × paczka'), (u'2 × paczka', u'1 × EUR')]


def test_ten_sam_operation_id_nie_deklaruje_drugi_raz(app, client, sygnaly):
    """Review Focus 1: powtórka z kolejki offline po timeoucie."""
    order, device = _spakowane(), _urzadzenie()
    pierwsza = _put(client, order, device, {'kind': 'paczka', 'count': 2}, op_id='op-powtorka')
    druga = _put(client, order, device, {'kind': 'paczka', 'count': 2}, op_id='op-powtorka')
    assert druga.status_code == 200 and druga.get_json() == pierwsza.get_json()
    assert ProductionPackage.query.count() == 2 and LabelPrintJob.query.count() == 2 and sygnaly == [2]


@pytest.mark.parametrize('stanowisko', ['cutting', 'edges', 'formatting'])
def test_stanowisko_bez_prawa_do_paczek_403(app, client, sygnaly, stanowisko):
    r = _put(client, _spakowane(), _urzadzenie(stanowisko), {'kind': 'paczka', 'count': 1})
    assert r.status_code == 403 and r.get_json()['error'] == 'station_not_allowed'
    assert ProductionPackage.query.count() == 0


def test_stanowiska_paczek():
    assert paczki.STANOWISKA_PACZEK == ('packaging', 'verification')


def test_nieznane_zamowienie_404(app, client, sygnaly):
    r = client.put('/api/mobile/orders/999999/packages', json={'kind': 'paczka', 'count': 1},
                   headers=_naglowki(_urzadzenie()))
    assert r.status_code == 404 and r.get_json()['error'] == 'order_not_found'


def test_deklaracja_podbija_updated_at_pozycji(app, client, sygnaly):
    order = _spakowane()
    for p in order.products:
        p.updated_at = datetime(2026, 9, 1)
    db.session.commit()
    assert _put(client, order, _urzadzenie(), {'kind': 'paczka', 'count': 1}).status_code == 200
    assert all(ProductionProduct.query.get(p.id).updated_at > datetime(2026, 9, 1) for p in order.products)


def test_pracownik_z_naglowka(app, client, sygnaly, monkeypatch):
    monkeypatch.setattr(mobile_api.worker_service, 'touch_sessions', lambda ids, **k: {})
    kto, order, device = pracownik(), _spakowane(), _urzadzenie()
    r = _put(client, order, device, {'kind': 'paczka', 'count': 1}, **{'X-Worker-Ids': str(kto.id)})
    assert r.status_code == 200
    assert paczki.aktualne_paczki(order.id)[0].declared_by_worker_id == kto.id
    assert LogisticsLog.query.filter_by(order_id=order.id, action='paczki').one().worker_id == kto.id


def test_sygnal_dla_agenta_dopiero_po_commicie(app, client, monkeypatch):
    """Review Focus 4."""
    kolejnosc = []
    monkeypatch.setattr(pqs.realtime_service, 'publish_print_signal',
                        lambda n: kolejnosc.append(('sygnal', n)) or True)

    def _po_commicie(sesja):
        kolejnosc.append('commit')

    order, device = _spakowane(), _urzadzenie()
    event.listen(db.session, 'after_commit', _po_commicie)
    try:
        assert _put(client, order, device, {'kind': 'paczka', 'count': 2}).status_code == 200
    finally:
        event.remove(db.session, 'after_commit', _po_commicie)
    assert kolejnosc[-2:] == ['commit', ('sygnal', 2)]
    assert kolejnosc.count(('sygnal', 2)) == 1


def test_get_zwraca_aktualne_paczki(app, client, sygnaly):
    order, device = _spakowane(), _urzadzenie()
    pusta = client.get(_url(order), headers=_naglowki(device))
    assert pusta.status_code == 200 and 'no-store' in pusta.headers['Cache-Control']
    assert pusta.get_json() == {'internal_order_number': order.internal_order_number,
                                'packages_declared_at': None, 'packages': []}
    _put(client, order, device, {'kind': 'paczka', 'count': 2})
    _put(client, order, device, {'kind': 'paczka', 'count': 1})
    dane = client.get(_url(order), headers=_naglowki(device)).get_json()
    assert [p['seq'] for p in dane['packages']] == [1] and dane['packages_declared_at']
    assert client.get('/api/mobile/orders/999999/packages', headers=_naglowki(device)).status_code == 404


def test_get_z_kazdego_stanowiska(app, client):
    order = _spakowane()
    assert client.get(_url(order), headers=_naglowki(_urzadzenie('cutting'))).status_code == 200


def test_stara_appka_pakuje_bez_deklaracji(app, client, sygnaly):
    """Spec 7.2: backend przyjmuje pakowanie bez deklaracji (stara appka, admin)."""
    order, device = _spakowane(statusy=('czeka_na_pakowanie',)), _urzadzenie()
    r = client.post('/api/mobile/orders/%d/complete' % order.products[0].id, headers=_naglowki(device))
    assert r.status_code == 200 and r.get_json()['status'] == 'spakowane'
    assert paczki.aktualne_paczki(order.id) == [] and LabelPrintJob.query.count() == 0


@pytest.mark.parametrize('argumenty, tekst', [
    (('paczka', 3), u'3 × paczka'),
    (('paleta', 1, 'eur', 120, 80), u'1 × EUR'),
    (('paleta', 2, 'niestandardowa', 150, 100), u'2 × paleta 150×100'),
])
def test_opis_deklaracji(argumenty, tekst):
    assert paczki.opis(*argumenty) == tekst
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_paczki_deklaracja.py`
Expected: FAIL (405 Method Not Allowed na `PUT …/packages`, `AttributeError: … 'STANOWISKA_PACZEK'`).

- [ ] **Step 3: Deklaracja w serwisie**

W `modules/production/logistics/services/paczki.py` zamień importy na:

```python
from dataclasses import dataclass
from typing import Optional

from extensions import db
from modules.production.logistics import sposoby
from modules.production.logistics.services import delivery, paczki_druk
from modules.production.models import ProductionPackage, get_local_now
```

i dopisz pod importami:

```python
# Stanowiska, które deklarują paczki i drukują ich etykiety (spec 6.1) — niezależnie od
# LABEL_PRINTER_ALLOWED_STATIONS (etykiety produktów). 'verification' dochodzi w kroku 4.3.
STANOWISKA_PACZEK = ('packaging', 'verification')
MAKS_PACZEK = 10
WYMIAR_EUR = (120, 80)
WYMIAR_MIN_CM, WYMIAR_MAX_CM = 20, 400


class PaczkiBlad(Exception):
    """Odmowa z kodem dla appki (`error`) i komunikatem dla człowieka (`message`)."""

    def __init__(self, kod, komunikat, status):
        super().__init__(komunikat)
        self.kod = kod
        self.komunikat = komunikat
        self.status = status


@dataclass(frozen=True)
class Deklaracja:
    kind: str
    count: int
    pallet_type: Optional[str] = None
    length_cm: Optional[int] = None
    width_cm: Optional[int] = None


def _liczba(wartosc):
    """Liczba całkowita z JSON-a; bool to nie liczba (w Pythonie True == 1)."""
    return wartosc if isinstance(wartosc, int) and not isinstance(wartosc, bool) else None


def waliduj_deklaracje(dane):
    """
    Body PUT …/packages → Deklaracja albo PaczkiBlad 422 `invalid_packages`.

    Pola bez znaczenia dla danego rodzaju pomijamy zamiast odrzucać (wymiar przy EUR i przy
    paczce, typ palety przy paczce): 422 z kolejki offline tabletu to deklaracja utracona
    bez śladu, a te pola nie zmieniają jej sensu. EUR ma zawsze 120×80.
    """
    def blad(tekst):
        return PaczkiBlad('invalid_packages', tekst, 422)

    if not isinstance(dane, dict):
        raise blad(u'Brak danych paczek.')
    kind = dane.get('kind')
    if kind not in ProductionPackage.RODZAJE:
        raise blad(u'Rodzaj musi być „paczka” albo „paleta”.')
    count = _liczba(dane.get('count'))
    if count is None or not 1 <= count <= MAKS_PACZEK:
        raise blad(u'Liczba paczek od 1 do %d.' % MAKS_PACZEK)
    if kind == 'paczka':
        return Deklaracja('paczka', count)
    typ = dane.get('pallet_type')
    if typ == 'eur':
        return Deklaracja('paleta', count, 'eur', *WYMIAR_EUR)
    if typ == 'niestandardowa':
        dlugosc, szerokosc = _liczba(dane.get('length_cm')), _liczba(dane.get('width_cm'))
        if dlugosc is None or szerokosc is None or not all(
                WYMIAR_MIN_CM <= w <= WYMIAR_MAX_CM for w in (dlugosc, szerokosc)):
            raise blad(u'Wymiar palety niestandardowej: od %d do %d cm.' % (WYMIAR_MIN_CM, WYMIAR_MAX_CM))
        return Deklaracja('paleta', count, 'niestandardowa', dlugosc, szerokosc)
    raise blad(u'Typ palety: „eur” albo „niestandardowa”.')


def opis(kind, count, pallet_type=None, length_cm=None, width_cm=None):
    """„3 × paczka”, „1 × EUR”, „2 × paleta 150×100” — log logistyki i komunikaty (spec 11)."""
    if kind != 'paleta':
        rodzaj = u'paczka'
    elif pallet_type == 'eur':
        rodzaj = u'EUR'
    elif length_cm and width_cm:
        rodzaj = u'paleta %d×%d' % (length_cm, width_cm)
    else:
        rodzaj = u'paleta'
    return u'%d × %s' % (count, rodzaj)


def opis_paczek(lista):
    """Opis zapisanej deklaracji (jeden rodzaj na zamówienie — mieszane poza zakresem, spec 3)."""
    if not lista:
        return None
    p = lista[0]
    return opis(p.kind, len(lista), p.pallet_type, p.length_cm, p.width_cm)


def uniewaznij(lista, teraz):
    """Unieważnia paczki (wiersze zostają — skan starej etykiety ma dostać „nieaktualna”)."""
    for p in lista:
        p.voided_at = teraz
    return len(lista)


def zadeklaruj(order, deklaracja, stanowisko, aktor, worker_id=None, device_id=None, teraz=None):
    """
    Nowa deklaracja paczek (spec 7.2): unieważnia poprzednią, tworzy N paczek z numerami
    1..N, zapisuje log `paczki`, podbija ETag kolejek tabletów i kolejkuje N etykiet na
    drukarkę 'wysylka'. NIE commituje.

    `order` MUSI być odczytany z blokadą (router: _zamowienie_po_numerze(do_zapisu=True)) —
    dwie deklaracje naraz (dwa tablety, powtórka z nowym X-Operation-Id) dałyby dwa komplety
    paczek. Poprzednie paczki czytamy odczytem bieżącym z tego samego powodu.
    Stan pozycji czytamy zwykłym odczytem: migawka sprzed blokady może najwyżej dać
    fałszywe 409 order_not_packed, które appka ponawia.
    """
    if not delivery.wszystkie_spakowane(order):
        raise PaczkiBlad('order_not_packed', u'Zamówienie {} nie jest jeszcze w całości spakowane — '
                         u'paczki deklaruje się po spakowaniu ostatniej pozycji.'.format(
                             order.internal_order_number), 409)
    teraz = teraz or get_local_now()
    stare = aktualne_paczki(order.id, do_zapisu=True)
    uniewaznij(stare, teraz)
    nowe = [ProductionPackage(order_id=order.id, seq=numer, kind=deklaracja.kind,
                              pallet_type=deklaracja.pallet_type, length_cm=deklaracja.length_cm,
                              width_cm=deklaracja.width_cm, declared_at=teraz,
                              declared_by_worker_id=worker_id, declared_device_id=device_id)
            for numer in range(1, deklaracja.count + 1)]
    db.session.add_all(nowe)
    db.session.flush()
    order.packages_declared_at = teraz
    delivery.zapisz_log(order, 'paczki', opis_paczek(stare),
                        opis(deklaracja.kind, deklaracja.count, deklaracja.pallet_type,
                             deklaracja.length_cm, deklaracja.width_cm),
                        worker_id=worker_id, device_id=device_id,
                        note=u'stanowisko: {}'.format(stanowisko), teraz=teraz)
    # ETag kolejek tabletów liczy się z MAX(updated_at) pozycji.
    delivery.podbij_pozycje(order, teraz)
    paczki_druk.drukuj_etykiety(order, nowe, len(nowe), stanowisko, aktor, teraz)
    return nowe
```

- [ ] **Step 4: Sygnał po commicie w `with_idempotency`**

W `modules/production/services/mobile_api_service.py`, w `with_idempotency`, bezpośrednio pod blokiem `# Hook BL: …` (`flush_pending_syncs()` w `try/except`) dopisz:

```python
            # Etykiety paczek (logistyka etap 4): sygnał dla agenta druku dopiero po commicie —
            # handler tylko go zaplanował (print_queue_service.zaplanuj_sygnal_po_commicie).
            try:
                from .print_queue_service import wyslij_zaplanowany_sygnal
                wyslij_zaplanowany_sygnal()
            except Exception as sygnal_error:
                logger.error("Mobile API: błąd sygnału dla agenta druku", extra={
                    'error': str(sygnal_error),
                })
```

- [ ] **Step 5: Endpointy**

W `modules/production/routers/mobile_api.py` pod sekcją „DRUKOWANIE ETYKIET (MOBILE)” (przed „DEVICES — heartbeat”) dodaj:

```python
# ============================================================================
# PACZKI (logistyka etap 4, krok 4.2 — spec 7.2 i 7.3)
# ============================================================================

def _stanowisko_paczek():
    """
    (kod, None), gdy stanowisko z JWT deklaruje paczki i drukuje ich etykiety
    (paczki.STANOWISKA_PACZEK), inaczej (None, odpowiedź 403). Kod bierzemy z JWT jak
    druk etykiet produktów — klient nie przysyła go w body, więc nie ma czego porównywać
    pod kątem station_mismatch.
    """
    from modules.production.logistics.services import paczki
    kod = resolve_station_code((g.device.station_code or '').strip())
    if kod not in paczki.STANOWISKA_PACZEK:
        return None, (jsonify({
            'error': 'station_not_allowed',
            'message': u'Paczki deklaruje i drukuje stanowisko Pakowanie albo Weryfikacja.',
        }), 403)
    return kod, None


def _zamowienie_po_numerze(numer, do_zapisu=False):
    """Zamówienie po numerze wewnętrznym. `do_zapisu=True` — z blokadą wiersza (FOR UPDATE)."""
    zapytanie = ProductionOrder.query.filter_by(internal_order_number=str(numer).strip())
    if do_zapisu:
        zapytanie = zapytanie.with_for_update().populate_existing()
    return zapytanie.first()


def _brak_zamowienia(numer):
    return jsonify({'error': 'order_not_found',
                    'message': u'Nie ma zamówienia {}.'.format(numer)}), 404


def _blad_paczek(e):
    return jsonify({'error': e.kod, 'message': e.komunikat}), e.status


def _aktor():
    return {'type': 'device', 'id': g.device.device_id}


def _odpowiedz_paczek(order, paczki_lista, **dodatkowe):
    from modules.production.logistics.services import paczki
    dane = {
        'internal_order_number': order.internal_order_number,
        'packages_declared_at': (order.packages_declared_at.isoformat()
                                 if order.packages_declared_at else None),
        'packages': [paczki.serializuj_paczke(p) for p in paczki_lista],
    }
    dane.update(dodatkowe)
    return dane


@mobile_api_bp.route('/orders/<numer>/packages', methods=['GET'])
@require_device_token
def order_packages(numer):
    """
    GET /api/mobile/orders/<internal_order_number>/packages — aktualne paczki zamówienia
    (decyzja Konrada 30.09: tablet pokazuje je i drukuje ponownie jedną albo wszystkie).
    Każde stanowisko może czytać. Bez cache: stan zmienia się deklaracją z innego urządzenia.
    """
    from modules.production.logistics.services import paczki
    order = _zamowienie_po_numerze(numer)
    if order is None:
        return _brak_zamowienia(numer)
    return no_store_json(_odpowiedz_paczek(order, paczki.aktualne_paczki(order.id)))


@mobile_api_bp.route('/orders/<numer>/packages', methods=['PUT'])
@require_device_token
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def order_packages_declare(numer):
    """
    PUT /api/mobile/orders/<internal_order_number>/packages — deklaracja paczek (spec 7.2).

    Body: {"kind": "paczka"|"paleta", "count": 1..10, "pallet_type": "eur"|"niestandardowa"|null,
           "length_cm": int|null, "width_cm": int|null}

    Appka wysyła ją po „ZAKOŃCZ”, który domyka zamówienie — po zakończeniach pozycji, tą samą
    kolejką offline. 409 order_not_packed jest w BLEDY_DO_PONOWIENIA (niezapamiętane): kolejka
    appki nie gwarantuje, że wszystkie COMPLETE przeszły przed deklaracją, więc ten sam
    X-Operation-Id musi przejść, gdy zamówienie się domknie. Stara appka pakuje bez deklaracji
    (backend to przyjmuje), a nowa appka na starym backendzie dostaje 404 i pomija deklarację.
    """
    from modules.production.logistics.services import paczki
    stanowisko, err = _stanowisko_paczek()
    if err:
        return err
    try:
        deklaracja = paczki.waliduj_deklaracje(request.get_json(silent=True))
    except paczki.PaczkiBlad as e:
        return _blad_paczek(e)
    order = _zamowienie_po_numerze(numer, do_zapisu=True)
    if order is None:
        return _brak_zamowienia(numer)
    worker_ids, _sesje, err = _resolve_workers()
    if err:
        return err
    try:
        nowe = paczki.zadeklaruj(order, deklaracja, stanowisko, _aktor(),
                                 worker_id=worker_ids[0] if worker_ids else None,
                                 device_id=g.device.id)
    except paczki.PaczkiBlad as e:
        return _blad_paczek(e)

    tekst = paczki.opis(deklaracja.kind, deklaracja.count, deklaracja.pallet_type,
                        deklaracja.length_cm, deklaracja.width_cm)
    logger.info("Mobile API: paczki zadeklarowane", extra={
        'internal_order_number': order.internal_order_number, 'paczki': tekst,
        'station_code': stanowisko, 'device_id': g.device.device_id,
    })
    return jsonify(_odpowiedz_paczek(
        order, nowe, labels_queued=len(nowe),
        message=u'Zadeklarowano {}. Etykiety poszły do drukarki paczek.'.format(tekst))), 200
```

- [ ] **Step 6: Uruchom testy zadania**

Run: `PYTEST tests/test_paczki_deklaracja.py tests/test_paczki_podpowiedz.py tests/test_paczki_etykiety.py`
Expected: PASS.

- [ ] **Step 7: Pełny pakiet**

Run: `PYTEST tests/`
Expected: 0 failed, passed = wynik po scaleniu Task 2+3 + nowe z `test_paczki_deklaracja.py`.

- [ ] **Step 8: Commit**

```bash
git add modules/production/logistics/services/paczki.py modules/production/services/mobile_api_service.py modules/production/routers/mobile_api.py tests/test_paczki_deklaracja.py
git commit -m "feat(production): deklaracja paczek z tabletu pakowania i druk ich etykiet

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Ponowny druk etykiet paczek

**Files:**
- Modify: `modules/production/logistics/services/paczki.py`
- Modify: `modules/production/routers/mobile_api.py` (sekcja PACZKI; import `ProductionPackage`)
- Test: `tests/test_paczki_ponowny_druk.py`

**Interfaces:**
- Consumes: z Task 4 `PaczkiBlad`, `_stanowisko_paczek`, `_zamowienie_po_numerze`, `_brak_zamowienia`, `_blad_paczek`, `_aktor`, `_odpowiedz_paczek`; z Task 3 `paczki_druk.drukuj_etykiety`.
- Produces: `paczki.drukuj_ponownie_paczke(paczka, stanowisko, aktor, teraz=None) -> None` (409 `package_void`), `paczki.drukuj_ponownie_zamowienie(order, stanowisko, aktor, teraz=None) -> List[ProductionPackage]` (409 `no_packages`); endpointy `package_print` (`POST /packages/<int:package_id>/print`) i `order_packages_print` (`POST /orders/<numer>/packages/print`).

- [ ] **Step 1: Test, który padnie**

Create `tests/test_paczki_ponowny_druk.py`:

```python
# -*- coding: utf-8 -*-
"""Ponowny druk etykiet paczek (logistyka etap 4, krok 4.2, spec 7.3)."""
import itertools

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import paczki
from modules.production.models import LabelPrintJob, ProductionDevice, ProductionPackage
from modules.production.services import print_queue_service as pqs
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import app, client, zamowienie  # noqa: F401

_numery = itertools.count(1600)
_licznik = itertools.count(1)


@pytest.fixture()
def sygnaly(monkeypatch):
    wyslane = []
    monkeypatch.setattr(pqs.realtime_service, 'publish_print_signal',
                        lambda n: wyslane.append(n) or True)
    return wyslane


def _urzadzenie(stanowisko='packaging'):
    device = ProductionDevice(device_id='TAB-druk-%s-%d' % (stanowisko, next(_licznik)),
                              device_name='Tablet', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return device


def _naglowki(device, op_id=None):
    return {'Authorization': 'Bearer ' + generate_token(device),
            'X-Operation-Id': op_id or 'op-druk-%d' % next(_licznik)}


def _zadeklarowane(client, device, liczba, sposob=s.KURIER):
    order = zamowienie(sposob=sposob, statusy=('spakowane',), numer_wewnetrzny=str(next(_numery)))
    r = client.put('/api/mobile/orders/%s/packages' % order.internal_order_number,
                   json={'kind': 'paczka', 'count': liczba}, headers=_naglowki(device))
    assert r.status_code == 200, r.get_json()
    return order


def test_ponowny_druk_paczki_z_biezacymi_danymi(app, client, sygnaly):
    device = _urzadzenie()
    order = _zadeklarowane(client, device, 2, sposob=s.TRANSPORT)
    druga = paczki.aktualne_paczki(order.id)[1]
    assert druga.label_delivery_text == 'TRANSPORT WOODPOWER'
    order.override_delivery_method = s.ODBIOR          # logistyk zmienił sposób po druku
    db.session.commit()
    r = client.post('/api/mobile/packages/%d/print' % druga.id, headers=_naglowki(device))
    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert dane['success'] is True and dane['labels_queued'] == 1
    assert dane['package']['label_print_count'] == 2 and druga.kod in dane['message']
    zadanie = LabelPrintJob.query.order_by(LabelPrintJob.id.desc()).first()
    assert zadanie.package_id == druga.id and zadanie.printer == 'wysylka'
    assert '^FR^FD2 / 2^FS' in zadanie.zpl_payload and '^FR^FDODBIOR OSOBISTY^FS' in zadanie.zpl_payload
    p = ProductionPackage.query.get(druga.id)
    assert (p.label_print_count, p.label_delivery_text) == (2, 'ODBIOR OSOBISTY')
    assert sygnaly == [2, 1]


def test_uniewazniona_paczka_409(app, client, sygnaly):
    """Review Focus 3: stara etykieta po ponownej deklaracji."""
    device = _urzadzenie()
    order = _zadeklarowane(client, device, 2)
    stara = paczki.aktualne_paczki(order.id)[0]
    client.put('/api/mobile/orders/%s/packages' % order.internal_order_number,
               json={'kind': 'paczka', 'count': 1}, headers=_naglowki(device))
    r = client.post('/api/mobile/packages/%d/print' % stara.id, headers=_naglowki(device))
    assert r.status_code == 409 and r.get_json()['error'] == 'package_void'
    assert u'nieaktualna' in r.get_json()['message']
    assert LabelPrintJob.query.filter_by(package_id=stara.id).count() == 1


def test_nieznana_paczka_404(app, client, sygnaly):
    r = client.post('/api/mobile/packages/999999/print', headers=_naglowki(_urzadzenie()))
    assert r.status_code == 404 and r.get_json()['error'] == 'package_not_found'


def test_druk_wszystkich_paczek_zamowienia(app, client, sygnaly):
    device = _urzadzenie()
    order = _zadeklarowane(client, device, 3)
    r = client.post('/api/mobile/orders/%s/packages/print' % order.internal_order_number,
                    headers=_naglowki(device))
    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert dane['labels_queued'] == 3 and [p['seq'] for p in dane['packages']] == [1, 2, 3]
    assert all(p['label_print_count'] == 2 for p in dane['packages'])
    assert LabelPrintJob.query.count() == 6 and sygnaly == [3, 3]


def test_druk_wszystkich_bez_paczek_409(app, client, sygnaly):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',), numer_wewnetrzny=str(next(_numery)))
    r = client.post('/api/mobile/orders/%s/packages/print' % order.internal_order_number,
                    headers=_naglowki(_urzadzenie()))
    assert r.status_code == 409 and r.get_json()['error'] == 'no_packages'
    assert r.get_json()['message'] and sygnaly == []


def test_druk_wszystkich_nieznane_zamowienie_404(app, client, sygnaly):
    r = client.post('/api/mobile/orders/999999/packages/print', headers=_naglowki(_urzadzenie()))
    assert r.status_code == 404 and r.get_json()['error'] == 'order_not_found'


def test_ponowny_druk_stanowisko_bez_prawa_403(app, client, sygnaly):
    order = _zadeklarowane(client, _urzadzenie(), 1)
    obcy = _urzadzenie('cutting')
    p = paczki.aktualne_paczki(order.id)[0]
    for url in ('/api/mobile/packages/%d/print' % p.id,
                '/api/mobile/orders/%s/packages/print' % order.internal_order_number):
        r = client.post(url, headers=_naglowki(obcy))
        assert r.status_code == 403 and r.get_json()['error'] == 'station_not_allowed'
    assert LabelPrintJob.query.count() == 1


def test_ponowny_druk_ten_sam_operation_id_drukuje_raz(app, client, sygnaly):
    """Review Focus 1."""
    device = _urzadzenie()
    order = _zadeklarowane(client, device, 1)
    p = paczki.aktualne_paczki(order.id)[0]
    for _ in range(2):
        r = client.post('/api/mobile/packages/%d/print' % p.id, headers=_naglowki(device, op_id='op-raz'))
        assert r.status_code == 200
    assert LabelPrintJob.query.filter_by(package_id=p.id).count() == 2      # deklaracja + jeden przedruk
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_paczki_ponowny_druk.py`
Expected: FAIL (404 na `/packages/<id>/print` i `/orders/<nr>/packages/print`).

- [ ] **Step 3: Serwis**

Dopisz w `modules/production/logistics/services/paczki.py`:

```python
def drukuj_ponownie_paczke(paczka, stanowisko, aktor, teraz=None):
    """
    Ponowny druk etykiety jednej ważnej paczki (spec 7.3) z BIEŻĄCYMI danymi zamówienia —
    gasi ikonę „etykiety paczek sprzed zmiany”. Paczka z unieważnionej deklaracji → 409.
    `paczka` MUSI być odczytana z blokadą (równoległa deklaracja mogła ją unieważnić).
    """
    if paczka.voided_at is not None:
        raise PaczkiBlad('package_void', u'Etykieta nieaktualna — paczki zadeklarowano ponownie.', 409)
    z_ilu = len(aktualne_paczki(paczka.order_id))
    paczki_druk.drukuj_etykiety(paczka.order, [paczka], z_ilu, stanowisko, aktor,
                                teraz or get_local_now())


def drukuj_ponownie_zamowienie(order, stanowisko, aktor, teraz=None):
    """Ponowny druk etykiet wszystkich ważnych paczek zamówienia. Zwraca paczki; bez
    deklaracji → 409 no_packages. `order` z blokadą (jak w zadeklaruj)."""
    aktualne = aktualne_paczki(order.id, do_zapisu=True)
    if not aktualne:
        raise PaczkiBlad('no_packages', u'Zamówienie {} nie ma zadeklarowanych paczek.'.format(
            order.internal_order_number), 409)
    paczki_druk.drukuj_etykiety(order, aktualne, len(aktualne), stanowisko, aktor,
                                teraz or get_local_now())
    return aktualne
```

- [ ] **Step 4: Endpointy**

W `modules/production/routers/mobile_api.py` dopisz `ProductionPackage` do importu z `modules.production.models`, a w sekcji PACZKI (po `order_packages_declare`):

```python
@mobile_api_bp.route('/packages/<int:package_id>/print', methods=['POST'])
@require_device_token
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def package_print(package_id):
    """
    POST /api/mobile/packages/<id>/print — ponowny druk etykiety jednej paczki (spec 7.3),
    z tabletu pakowania i (krok 4.3) telefonu Weryfikacji. Etykieta z bieżącymi danymi.
    X-Operation-Id chroni przed podwójnym wydrukiem przy powtórce po timeoucie.
    """
    from modules.production.logistics.services import paczki
    stanowisko, err = _stanowisko_paczek()
    if err:
        return err
    paczka = (ProductionPackage.query.filter_by(id=package_id)
              .with_for_update().populate_existing().first())
    if paczka is None:
        return jsonify({'error': 'package_not_found',
                        'message': u'Nie ma paczki P-{}.'.format(package_id)}), 404
    try:
        paczki.drukuj_ponownie_paczke(paczka, stanowisko, _aktor())
    except paczki.PaczkiBlad as e:
        return _blad_paczek(e)
    logger.info("Mobile API: ponowny druk etykiety paczki", extra={
        'package': paczka.kod, 'station_code': stanowisko, 'device_id': g.device.device_id,
        'worker_id': _profil_do_logu(),
    })
    return jsonify({
        'success': True, 'labels_queued': 1, 'package': paczki.serializuj_paczke(paczka),
        'message': u'Etykieta {} poszła do drukarki paczek.'.format(paczka.kod),
    }), 200


@mobile_api_bp.route('/orders/<numer>/packages/print', methods=['POST'])
@require_device_token
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def order_packages_print(numer):
    """POST /api/mobile/orders/<internal_order_number>/packages/print — ponowny druk etykiet
    wszystkich ważnych paczek zamówienia (spec 7.3)."""
    from modules.production.logistics.services import paczki
    stanowisko, err = _stanowisko_paczek()
    if err:
        return err
    order = _zamowienie_po_numerze(numer, do_zapisu=True)
    if order is None:
        return _brak_zamowienia(numer)
    try:
        aktualne = paczki.drukuj_ponownie_zamowienie(order, stanowisko, _aktor())
    except paczki.PaczkiBlad as e:
        return _blad_paczek(e)
    logger.info("Mobile API: ponowny druk etykiet paczek zamówienia", extra={
        'internal_order_number': order.internal_order_number, 'etykiet': len(aktualne),
        'station_code': stanowisko, 'device_id': g.device.device_id,
        'worker_id': _profil_do_logu(),
    })
    return jsonify({
        'success': True, 'labels_queued': len(aktualne),
        'packages': [paczki.serializuj_paczke(p) for p in aktualne],
        'message': u'Etykiety paczek zamówienia {} ({}) poszły do drukarki paczek.'.format(
            order.internal_order_number, len(aktualne)),
    }), 200
```

- [ ] **Step 5: Uruchom testy zadania**

Run: `PYTEST tests/test_paczki_ponowny_druk.py tests/test_paczki_deklaracja.py`
Expected: PASS.

- [ ] **Step 6: Pełny pakiet**

Run: `PYTEST tests/`
Expected: 0 failed, passed = poprzednio + 8.

- [ ] **Step 7: Commit**

```bash
git add modules/production/logistics/services/paczki.py modules/production/routers/mobile_api.py tests/test_paczki_ponowny_druk.py
git commit -m "feat(production): ponowny druk etykiet paczek z tabletu

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Ikona „etykiety paczek sprzed zmiany” w panelu Logistyki (tor równoległy do Task 4)

Baza toru: `claude/logistyka-etap-4` po scaleniu Task 2 i Task 3.

**Files:**
- Modify: `modules/production/logistics/services/lista.py` (`serializuj`, `pobierz`)
- Modify: `modules/production/logistics/routers/panel_api.py` (hurt, ok. :179–186)
- Modify: `modules/production/logistics/routers/trasy_api.py` (szczegóły trasy, ok. :215–218)
- Modify: `modules/production/logistics/static/js/logistics.js` (ikony wiersza, ok. :877–879)
- Modify: `modules/production/logistics/templates/logistics/tab_content.html` (legenda :278–285, wersja `logistics.js` :701)
- Test: `tests/test_paczki_panel.py`

**Interfaces:**
- Consumes: `paczki.aktualne_paczki(order_id)`, `paczki.aktualne_paczki_zamowien(order_ids)` (Task 2), `paczki_druk.napis_sposobu(order, trasa)` (Task 3), `STATUSY_TRASY_AKTYWNE` (`logistics/models.py`).
- Produces: `lista.serializuj(order, geo=None, trasa=None, paczki_zamowienia=None)` z polem `etykiety_paczek_sprzed_zmiany: bool` (`paczki_zamowienia=None` → jedno zapytanie dla tego zamówienia; listy podają mapę z `aktualne_paczki_zamowien`).

Interfejs: ikona w istniejącym wzorze (`ikona('fa-box', 'lg-ikona--etykiety', …)`) — bez nowego stylu. Kolor ten sam co ikona etykiet produktów (`lg-ikona--etykiety`, ostrzeżenie).

- [ ] **Step 1: Test, który padnie**

Create `tests/test_paczki_panel.py`:

```python
# -*- coding: utf-8 -*-
"""Ikona „etykiety paczek sprzed zmiany” w panelu Logistyki (etap 4, krok 4.2, spec 6.3)."""
import os
import re
from datetime import date, datetime

import pytest
from sqlalchemy import event

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import Route, RouteStop
from modules.production.logistics.services import lista
from modules.production.models import ProductionPackage
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401

LOGISTYKA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'modules', 'production', 'logistics')


def _plik(*czesci):
    with open(os.path.join(LOGISTYKA, *czesci), encoding='utf-8') as f:
        return f.read()


def _wersja(html, plik):
    m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
    assert m, plik
    return m.group(1)


def _paczka(order, napis, voided=False, wydrukowana=True):
    p = ProductionPackage(order_id=order.id, seq=1, kind='paczka',
                          declared_at=datetime(2026, 9, 30, 10, 0),
                          label_printed_at=datetime(2026, 9, 30, 10, 1) if wydrukowana else None,
                          label_print_count=1 if wydrukowana else 0, label_delivery_text=napis,
                          voided_at=datetime(2026, 9, 30, 11, 0) if voided else None)
    db.session.add(p)
    db.session.commit()
    return p


def _wiersz(client, order):
    return next(w for w in client.get(BASE + '/orders').get_json()['orders'] if w['id'] == order.id)


@pytest.mark.parametrize('napis, voided, wydrukowana, ikona', [
    ('TRANSPORT WOODPOWER', False, True, False),
    ('KURIER', False, True, True),
    ('KURIER', True, True, False),          # unieważniona paczka się nie liczy
    (None, False, False, False),            # niewydrukowana
])
def test_ikona_etykiet_paczek(app, napis, voided, wydrukowana, ikona):
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    _paczka(order, napis, voided, wydrukowana)
    assert lista.serializuj(order)['etykiety_paczek_sprzed_zmiany'] is ikona


def test_bez_paczek_bez_ikony(app):
    assert lista.serializuj(zamowienie(sposob=s.KURIER))['etykiety_paczek_sprzed_zmiany'] is False


def test_ikona_po_dodaniu_do_trasy_i_po_wykonaniu_trasy(app, client):
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    _paczka(order, 'TRANSPORT WOODPOWER')
    assert _wiersz(client, order)['etykiety_paczek_sprzed_zmiany'] is False
    trasa = Route(name=u'Rzeszów', date_from=date(2026, 10, 7), date_to=date(2026, 10, 7))
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
    db.session.commit()
    assert _wiersz(client, order)['etykiety_paczek_sprzed_zmiany'] is True     # etykieta bez trasy
    trasa.status = 'wykonana'                  # trasa wykonana nie trafia na etykietę
    db.session.commit()
    assert _wiersz(client, order)['etykiety_paczek_sprzed_zmiany'] is False


def test_lista_czyta_paczki_jednym_zapytaniem(app, client):
    for _ in range(3):
        _paczka(zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)), 'KURIER')
    zapytania = []

    def nasluch(conn, cursor, statement, parameters, context, executemany):
        if 'FROM PROD_PACKAGES' in ' '.join(statement.upper().split()):
            zapytania.append(statement)

    event.listen(db.engine, 'before_cursor_execute', nasluch)
    try:
        wiersze = client.get(BASE + '/orders').get_json()['orders']
    finally:
        event.remove(db.engine, 'before_cursor_execute', nasluch)
    assert sum(1 for w in wiersze if w['etykiety_paczek_sprzed_zmiany']) == 3
    assert len(zapytania) == 1, zapytania


def test_hurt_czyta_paczki_jednym_zapytaniem(app, client):
    ids = [zamowienie(statusy=('czeka_na_pakowanie',)).id for _ in range(3)]
    zapytania = []

    def nasluch(conn, cursor, statement, parameters, context, executemany):
        if 'FROM PROD_PACKAGES' in ' '.join(statement.upper().split()):
            zapytania.append(statement)

    event.listen(db.engine, 'before_cursor_execute', nasluch)
    try:
        r = client.post(BASE + '/orders/delivery-method', json={'order_ids': ids, 'sposob': s.KURIER})
    finally:
        event.remove(db.engine, 'before_cursor_execute', nasluch)
    assert r.status_code == 200
    assert all(w['etykiety_paczek_sprzed_zmiany'] is False for w in r.get_json()['orders'])
    assert len(zapytania) == 1, zapytania


def test_ikona_i_legenda_w_panelu():
    js = _plik('static', 'js', 'logistics.js')
    assert 'w.etykiety_paczek_sprzed_zmiany' in js and "'fa-box'" in js
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert 'etykiety paczek sprzed zmiany' in html
    assert _wersja(html, 'js/logistics.js') != '20260928d'
```

- [ ] **Step 2: Uruchom — ma paść**

Run: `PYTEST tests/test_paczki_panel.py`
Expected: FAIL (`KeyError: 'etykiety_paczek_sprzed_zmiany'`, brak ikony w JS).

- [ ] **Step 3: `lista.py`**

Importy: `from modules.production.logistics.models import RouteStop, STATUSY_TRASY_AKTYWNE` i `from modules.production.logistics.services import geocoding, paczki, paczki_druk, routes`.

Nad `def serializuj(...)`:

```python
def _etykiety_paczek_sprzed_zmiany(order, trasa, paczki_zamowienia):
    """
    Spec 6.3: etykiety paczki nie przedrukowujemy sami po zmianie sposobu dostawy albo
    trasy — panel pokazuje ikonę, gdy napis z pasa na wydrukowanej etykiecie (zapamiętany
    na paczce) różni się od dzisiejszego. Liczy się tylko trasa aktywna: wykonana nie
    trafia na etykietę (jak w paczki_druk.drukuj_etykiety → routes.trasa_dla_tabletu).
    """
    wydrukowane = [p for p in paczki_zamowienia if p.label_printed_at is not None]
    if not wydrukowane:
        return False
    aktywna = trasa if trasa is not None and trasa.status in STATUSY_TRASY_AKTYWNE else None
    napis = paczki_druk.napis_sposobu(order, aktywna)
    return any(p.label_delivery_text != napis for p in wydrukowane)
```

`serializuj`:
- sygnatura `def serializuj(order, geo=None, trasa=None, paczki_zamowienia=None):`
- na początku funkcji:

```python
    if paczki_zamowienia is None:
        # Pojedynczy wiersz (odświeżenie po akcji) — listy podają mapę jednym zapytaniem.
        paczki_zamowienia = paczki.aktualne_paczki(order.id)
```

- w słowniku, pod `'etykiety_sprzed_zmiany': ...`:

```python
        'etykiety_paczek_sprzed_zmiany': _etykiety_paczek_sprzed_zmiany(order, trasa, paczki_zamowienia),
```

`pobierz`: pod `trasy = routes.trasy_zamowien(ids)`:

```python
    pakunki = paczki.aktualne_paczki_zamowien(ids)
    wiersze = [serializuj(o, punkty.get(o.id), trasy.get(o.id), pakunki.get(o.id, []))
               for o in zamowienia]
```

(zamiast dotychczasowej linii `wiersze = [...]`).

- [ ] **Step 4: Listy w routerach**

`modules/production/logistics/routers/panel_api.py` (odpowiedź hurtowej zmiany sposobu, ok. :181–186): pod `trasy = routes.trasy_zamowien(ids)` dopisz `pakunki = paczki.aktualne_paczki_zamowien(ids)` i w liście `lista.serializuj(o, punkty.get(o.id), trasy.get(o.id), pakunki.get(o.id, []))`. Import: dopisz `paczki` do `from modules.production.logistics.services import bl_sync, delivery, geocoding, lista, routes` (:19).

`modules/production/logistics/routers/trasy_api.py` (szczegóły trasy, ok. :215): przed `dane['przystanki'] = …` dopisz `pakunki = paczki.aktualne_paczki_zamowien([o.id for o in zamowienia])` i w liście `lista.serializuj(o, punkty.get(o.id), route, pakunki.get(o.id, []))`. Import: dopisz `paczki` do `from modules.production.logistics.services import fleet, geocoding, lista, routes, routimo, routing` (:22).

Pozostałe wywołania `lista.serializuj` (pojedyncze zamówienie w `panel_api.py`) zostają bez zmian — policzą paczki same.

- [ ] **Step 5: JS i szablon**

`modules/production/logistics/static/js/logistics.js` — pod linią z `w.etykiety_sprzed_zmiany`:

```js
        if (w.etykiety_paczek_sprzed_zmiany) ikony.push(ikona('fa-box', 'lg-ikona--etykiety', 'Etykiety paczek sprzed zmiany sposobu dostawy lub trasy. Wydrukuj je ponownie na pakowaniu.'));
```

`modules/production/logistics/templates/logistics/tab_content.html`:
- w legendzie, pod linią z `fa-tags`:

```html
          <span><i class="fas fa-box lg-ikona--etykiety" aria-hidden="true"></i>etykiety paczek sprzed zmiany sposobu lub trasy</span>
```

- wersja skryptu: `js/logistics.js') }}?v=20260928d` → `?v=20260930a`.

- [ ] **Step 6: Uruchom testy zadania**

Run: `PYTEST tests/test_paczki_panel.py tests/test_logistyka_panel_api.py tests/test_logistyka_dymek_ui.py`
Expected: PASS.

- [ ] **Step 7: Pełny pakiet (worktree toru, `-p logistyka4-t6`)**

Run: `PYTEST tests/`
Expected: 0 failed, passed = wynik bazy toru + nowe z `test_paczki_panel.py`.

- [ ] **Step 8: Commit**

```bash
git add modules/production/logistics/services/lista.py modules/production/logistics/routers/panel_api.py modules/production/logistics/routers/trasy_api.py modules/production/logistics/static/js/logistics.js modules/production/logistics/templates/logistics/tab_content.html tests/test_paczki_panel.py
git commit -m "feat(production): ikona etykiet paczek sprzed zmiany w panelu Logistyki

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: MySQL, podgląd z drukarką, spec

Bez nowego kodu produkcyjnego; skrypty pomocnicze leżą POZA repo (katalog podglądu). Kroki **[Konrad]** wymagają człowieka przy drukarce XP-410B (Rzeszów, USB). Podział jak w 4.1: subagent robi kroki 1–4 i 9, kontroler kroki 5–8 z Konradem.

**Files:**
- Modify: `docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md`
- Poza repo: `C:\Users\Grafik\Documents\woodpower-podglady\logistyka4\` (`P` niżej; `kod` = kod podglądu, `agent` = agent testowy)

- [ ] **Step 1: Pełny pakiet i Python 3.9**

Run: `PYTEST tests/` (główny worktree, `-p logistyka4`)
Expected: 0 failed, passed = 5018 + wszystkie nowe testy kroku.

Run: `MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD:/app" -w /app python:3.9-slim python -m py_compile modules/production/logistics/services/paczki.py modules/production/logistics/services/paczki_druk.py modules/production/logistics/services/lista.py modules/production/services/package_label.py modules/production/services/print_queue_service.py modules/production/services/mobile_api_service.py modules/production/routers/mobile_api.py modules/production/models.py modules/production/logistics/models.py`
Expected: brak wyjścia.

- [ ] **Step 2: Migracja na MySQL, dwa razy (kopia produkcji `logistyka4_podglad`)**

```bash
time docker exec -i woodpower-crm-db-1 mysql -uroot logistyka4_podglad < migrations/2026-09-30-logistyka-paczki.sql
docker exec -i woodpower-crm-db-1 mysql -uroot logistyka4_podglad < migrations/2026-09-30-logistyka-paczki.sql
docker exec woodpower-crm-db-1 mysql -uroot logistyka4_podglad -e "SHOW CREATE TABLE prod_packages\G; SHOW CREATE TABLE prod_print_queue\G" | grep -E "CONSTRAINT|label_delivery_text|packages_declared_at"
docker exec woodpower-crm-db-1 mysql -uroot logistyka4_podglad -e "SHOW COLUMNS FROM prod_orders LIKE 'packages_declared_at'; SHOW COLUMNS FROM prod_logistics_log WHERE Field IN ('action','worker_id','device_id')"
```
Expected: oba przebiegi bez błędu (drugi wypisuje „… juz jest”); `fk_prod_packages_order` i `fk_prod_print_queue_package … ON DELETE SET NULL`; enum z `paczki`. Zanotuj czas pierwszego przebiegu (FK na `prod_print_queue` ~4 tys. wierszy przepisuje tabelę — ma zająć sekundy).

- [ ] **Step 3: Odświeżenie kodu podglądu 5004**

```bash
P=/c/Users/Grafik/Documents/woodpower-podglady/logistyka4
git archive --output="$P/kod.tar" HEAD
tar -xf "$P/kod.tar" -C "$P/kod"
docker restart logistyka4-podglad
docker logs logistyka4-podglad 2>&1 | grep -i "migrat" | tail -5
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5004/login
```
Expected: runner wykonuje `2026-09-30-logistyka-paczki.sql` trzeci raz bez błędu i odnotowuje go; `/login` = 200. (`kod/config/core.json` podglądu nie jest w archiwum — `tar` go nie nadpisuje.)

- [ ] **Step 4: Tablet testowy i wyścig dwóch deklaracji na MySQL**

Create `$P/kod/_paczki_tablet.py`:

```python
# -*- coding: utf-8 -*-
"""Deklaracja paczek przez prawdziwe API na bazie podglądu (etap 4, krok 4.2, poza gitem).
Użycie: python _paczki_tablet.py <numer> <json body> | wyscig <numer>"""
import json
import sys
import threading

from app import create_app
from extensions import db
from modules.production.models import ProductionDevice, ProductionOrder
from modules.production.logistics.services import paczki
from modules.production.services.mobile_api_service import generate_token

app = create_app()


def token():
    with app.app_context():
        device = ProductionDevice.query.filter_by(device_id='PODGLAD-PAKOWANIE').first()
        if device is None:
            device = ProductionDevice(device_id='PODGLAD-PAKOWANIE', device_name='Podglad 4.2',
                                      station_code='packaging')
            db.session.add(device)
            db.session.commit()
        return generate_token(device)


def put(numer, body, op_id):
    with app.test_client() as klient:
        r = klient.put('/api/mobile/orders/%s/packages' % numer, json=body,
                       headers={'Authorization': 'Bearer ' + token(), 'X-Operation-Id': op_id})
        return r.status_code, r.get_json()


if sys.argv[1] == 'wyscig':
    numer = sys.argv[2]
    wyniki = []
    watki = [threading.Thread(target=lambda i=i: wyniki.append(
        put(numer, {'kind': 'paczka', 'count': 2}, 'podglad-wyscig-%s-%d' % (numer, i))))
        for i in range(2)]
    [w.start() for w in watki]
    [w.join() for w in watki]
    with app.app_context():
        order = ProductionOrder.query.filter_by(internal_order_number=numer).one()
        print('statusy', sorted(s for s, _ in wyniki), 'aktualnych paczek',
              len(paczki.aktualne_paczki(order.id)))
else:
    import uuid
    print(put(sys.argv[1], json.loads(sys.argv[2]), 'podglad-%s' % uuid.uuid4()))
```

Wybierz zamówienie w całości spakowane z kopii (np. `SELECT o.internal_order_number FROM prod_orders o WHERE NOT EXISTS (SELECT 1 FROM prod_products p WHERE p.order_id=o.id AND p.current_status NOT IN ('spakowane','anulowane')) ORDER BY o.id DESC LIMIT 3`) i uruchom:

```bash
MSYS_NO_PATHCONV=1 docker exec -w /app logistyka4-podglad python _paczki_tablet.py wyscig <numer>
docker exec woodpower-crm-db-1 mysql -uroot logistyka4_podglad -e "UPDATE prod_print_queue SET status='expired', error_message='podglad: test wyscigu' WHERE status='pending' AND printer='wysylka'"
```
Expected: `statusy [200, 200] aktualnych paczek 2` — blokada wiersza zamówienia serializuje deklaracje na MySQL (druga unieważnia pierwszą). Zadania z testu wyścigu wygaszamy, żeby agent ich nie drukował.

- [ ] **Step 5: Agent testowy [kontroler]**

`$P/agent` ma `print_agent.py` i `config.ini` z kroku 4.1 (`[printer:wysylka]`, `type = windows`, `Xprinter XP-410B`, CRM `http://127.0.0.1:5004`). Jeśli token agenta w kopii bazy się zmienił — ustaw go jak w planie 4.1, Task 7 Step 5 (nie wypisuj tokena w czacie). Start w tle: `cd "$P/agent" && PYTHONIOENCODING=utf-8 python print_agent.py`.
Expected: baner z `Drukarka wysylka: kolejka Windows „Xprinter XP-410B”`.

- [ ] **Step 6: Deklaracja z wydrukiem [Konrad]**

```bash
MSYS_NO_PATHCONV=1 docker exec -w /app logistyka4-podglad python _paczki_tablet.py <numer> '{"kind": "paczka", "count": 2}'
```
Expected: `(200, {... "labels_queued": 2 ...})`; agent drukuje 2 etykiety. **[Konrad]** ocenia: „PACZKA 1 / 2” i „2 / 2”, QR `P-<id>` (skan telefonem), pas sposobu dostawy zgodny z panelem, zanonimizowany odbiorca, cała zawartość zamówienia, brak adresu.

Potem paleta niestandardowa: `… _paczki_tablet.py <numer> '{"kind": "paleta", "count": 1, "pallet_type": "niestandardowa", "length_cm": 150, "width_cm": 100}'` → jedna etykieta „PALETA 1 / 1”, „PALETA 150x100”.

- [ ] **Step 7: Ikona w panelu i ponowny druk [Konrad]**

Wbudowana przeglądarka (nigdy Chrome Konrada; sesja admina skryptem `_sesja.py` z podglądu, ciasteczko `session_lg4`) albo Konrad sam na `127.0.0.1:5004`: w zakładce Logistyka zmień sposób dostawy zamówienia z kroku 6 (albo dodaj je do trasy roboczej) → w wierszu ikona pudełka z opisem „Etykiety paczek sprzed zmiany…”, w legendzie nowa pozycja. Ponowny druk wszystkich (skrypt: `klient.post('/api/mobile/orders/<numer>/packages/print', …)` — dopisz tryb `druk` do `_paczki_tablet.py` albo wywołaj z `python -c`) → jedna etykieta z nowym pasem; po odświeżeniu listy ikona znika.

- [ ] **Step 8: Sprzątanie testu [kontroler]**

Zatrzymaj agenta testowego. Wygaś zostawione zadania `pending` na `wysylka` w kopii bazy (jak w kroku 4). Podgląd 5004 i baza `logistyka4_podglad` zostają na krok 4.3.

- [ ] **Step 9: Odstępstwa w specu**

W specu dopisz (krótko, w miejscach, których dotyczą):
- 5.2: wiersz `label_delivery_text | VARCHAR(40) NULL | napis z pasa sposobu dostawy w chwili druku (ikona „sprzed zmiany”)`.
- 5.3: „`packages_declared_at` — krok 4.2; pozostałe kolumny — migracja kroku 4.3”.
- 6.3 (akapit o ikonie): „porównanie napisu zapamiętanego na paczce z dzisiejszym; ponowny druk gasi ikonę”.
- 7.2: kody `invalid_packages` 422 (pola bez znaczenia pomijane), `order_not_found` 404, `station_not_allowed` 403; kształt odpowiedzi; `GET …/packages` (decyzja 30.09); `order_verified` przeniesione do 4.3.
- 7.3: `package_not_found` 404, `no_packages` 409; druk z bieżącymi danymi.
- 8.4 i 15: `KSZTALT_ODPOWIEDZI_KOLEJKI` 4 → 5 w kroku 4.3 (4 = `packing_hint` z kroku 4.2).
- 12 pkt 2: okno tylko przy obecnym `packing_hint`; „Zatwierdź” albo „Wróć” (Wróć anuluje ZAKOŃCZ); ponowny druk online przez `GET …/packages`.

```bash
git add -f docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md
git commit -m "docs: krok 4.2 logistyki - odstepstwa od projektu po realizacji

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 10: Przegląd całego kroku**

Adwersaryjny przegląd zmian `cc173b10..HEAD` najmocniejszym modelem wg Review Focus i kontraktu API, raport i poprawki przed zamknięciem kroku. Lista wdrożenia kroku 4.2 (wykonuje się po wdrożeniu etapów 1–3 i kroku 4.1): migracja przy deployu → backend → drukarka paczek na hali z agentem `[printer:wysylka]` (bez niej zadania `wysylka` wygasają po godzinie — nic się nie psuje) → dopiero potem APK z oknem paczek (stara appka działa z nowym backendem bez zmian).
