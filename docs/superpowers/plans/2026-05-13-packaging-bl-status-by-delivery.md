# Status BL po pakowaniu wg metody dostawy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Po ukończeniu pakowania zamówienia, wybierać status BL na podstawie metody dostawy (odbiór osobisty / transport WoodPower / kurier) zamiast wysyłać zawsze "Zamówienie spakowane".

**Architecture:** Cała zmiana w `modules/production/services/baselinker_status_sync.py` — dodanie 2 stałych z ID statusów, nowego helpera `_determine_packaging_target_status(order)` i podmiana jednej linii w `_process_pending`. Helper czyta `order.is_personal_pickup` i `order.override_delivery_method` (już istniejące pola).

**Tech Stack:** Python 3.9 + Flask + SQLAlchemy. Logger: structured (`modules.logging.get_structured_logger`).

**Weryfikacja:** Brak unit testów (świadoma decyzja — mock SQLAlchemy byłby większy niż zmiana). Zamiast tego dry-run trace po implementacji (Task 3) + smoke test produkcyjny (manualny, po deploy).

**Spec:** `docs/superpowers/specs/2026-05-13-packaging-bl-status-by-delivery-design.md`

---

## File Structure

**Modyfikacje:**
- `modules/production/services/baselinker_status_sync.py` — 2 nowe stałe (po istniejących linia ~44), 1 nowy helper (przed `_process_pending`, ~linia 206), zmiana 1 linii w `_process_pending` (linia 228).

**Brak nowych plików.** Brak zmian w innych plikach.

---

### Task 1: Dodać stałe ID statusów BL

**Files:**
- Modify: `modules/production/services/baselinker_status_sync.py:42-44`

- [ ] **Step 1: Dodać dwie nowe stałe po istniejących**

Po linii 44 (`PRODUCTION_RAW_STATUS_ID = 138619  # fallback dla "W produkcji - surowe"`) dodać:

```python
# Statusy po pakowaniu - zależne od metody dostawy (patrz _determine_packaging_target_status)
WAITING_PERSONAL_PICKUP_STATUS_ID = 149777  # "Czeka na odbiór osobisty"
PLANNED_ROUTE_STATUS_ID = 417343            # "Planowana trasa" (transport WoodPower)
```

Cały blok stałych po edycji ma wyglądać:

```python
# Hardcoded ID statusów - potwierdzone przez biznes
PRODUCTION_COMPLETED_STATUS_ID = 138620
ORDER_PACKED_STATUS_ID = 138623
PRODUCTION_RAW_STATUS_ID = 138619  # fallback dla "W produkcji - surowe"

# Statusy po pakowaniu - zależne od metody dostawy (patrz _determine_packaging_target_status)
WAITING_PERSONAL_PICKUP_STATUS_ID = 149777  # "Czeka na odbiór osobisty"
PLANNED_ROUTE_STATUS_ID = 417343            # "Planowana trasa" (transport WoodPower)
```

- [ ] **Step 2: Sprawdzić że import nie wybucha**

Run: `python3 -c "from modules.production.services.baselinker_status_sync import WAITING_PERSONAL_PICKUP_STATUS_ID, PLANNED_ROUTE_STATUS_ID; print(WAITING_PERSONAL_PICKUP_STATUS_ID, PLANNED_ROUTE_STATUS_ID)"`

Expected output: `149777 417343`

Jeśli błąd "ModuleNotFoundError: No module named 'flask'" — uruchom z aktywnym venv:
```
source venv/bin/activate  # (Linux/macOS) lub venv\Scripts\activate (Windows)
```

---

### Task 2: Dodać helper `_determine_packaging_target_status`

**Files:**
- Modify: `modules/production/services/baselinker_status_sync.py` — wstaw nowy helper przed funkcją `_process_pending` (obecnie ~linia 206).

- [ ] **Step 1: Wstawić helper przed `_process_pending`**

Bezpośrednio przed linią `def _process_pending(app, internal_order_number: str, station_code: str) -> None:` dodać:

```python
def _determine_packaging_target_status(order) -> int:
    """
    Wybiera ID statusu BL po ukończeniu pakowania na podstawie typu dostawy zamówienia.

    Reguła decyzyjna (kolejność istotna):
    1. is_personal_pickup                              → 149777 (Czeka na odbiór osobisty)
    2. override_delivery_method == 'transport_woodpower' → 417343 (Planowana trasa)
    3. override_delivery_method == 'kurier_baselinker'   → 138623 (Zamówienie spakowane)
    4. fallback (NULL/unknown)                           → 138623 + warn log

    is_personal_pickup musi być pierwsze, bo dla odbioru osobistego logistyka
    jest pomijana i override_delivery_method jest NULL.
    """
    if order.is_personal_pickup:
        return WAITING_PERSONAL_PICKUP_STATUS_ID

    override = (order.override_delivery_method or '').strip()
    if override == 'transport_woodpower':
        return PLANNED_ROUTE_STATUS_ID
    if override == 'kurier_baselinker':
        return ORDER_PACKED_STATUS_ID

    logger.warning("Pakowanie ukończone bez decyzji logistyki - fallback na 'spakowane'", extra={
        'internal_order_number': order.internal_order_number,
        'baselinker_order_id': order.baselinker_order_id,
        'override_delivery_method': order.override_delivery_method,
    })
    return ORDER_PACKED_STATUS_ID


```

(Pusta linia na końcu zachowuje separację od `_process_pending`.)

- [ ] **Step 2: Sprawdzić że plik dalej parsuje się jako Python**

Run: `python3 -m py_compile modules/production/services/baselinker_status_sync.py && echo OK`

Expected output: `OK`

---

### Task 3: Podpiąć helper w `_process_pending`

**Files:**
- Modify: `modules/production/services/baselinker_status_sync.py:225-228` (gałąź `if station_code == 'packaging':`)

- [ ] **Step 1: Podmienić linię ustawiającą `target`**

Aktualny kod (linia 225-228, w `_process_pending`):

```python
    if station_code == 'packaging':
        if not all(p.current_status == 'spakowane' for p in products):
            return
        target = ORDER_PACKED_STATUS_ID
```

Po edycji:

```python
    if station_code == 'packaging':
        if not all(p.current_status == 'spakowane' for p in products):
            return
        target = _determine_packaging_target_status(products[0].order)
```

Zmiana tylko jedna linia (`target = ...`). Reszta gałęzi bez zmian, gałęzie `PRODUCTION_STATIONS` i fallback `else: return` pozostają niezmienione.

- [ ] **Step 2: Sprawdzić że plik dalej parsuje się jako Python**

Run: `python3 -m py_compile modules/production/services/baselinker_status_sync.py && echo OK`

Expected output: `OK`

- [ ] **Step 3: Quick lint — żadnych nieużywanych importów**

Run: `python3 -c "import ast; tree = ast.parse(open('modules/production/services/baselinker_status_sync.py').read()); print('parsed OK')"`

Expected output: `parsed OK`

---

### Task 4: Dry-run trace — weryfikacja logiki

**Files:** brak edycji, tylko weryfikacja.

- [ ] **Step 1: Trace scenariusza "odbiór osobisty"**

Dane wejściowe (mock):
```
order.is_personal_pickup = True
order.override_delivery_method = None
order.internal_order_number = "25/001"
order.baselinker_order_id = 9999
```

Przejdź przez `_determine_packaging_target_status` linia po linii i zaraportuj:
- Linia `if order.is_personal_pickup:` → `True`
- `return WAITING_PERSONAL_PICKUP_STATUS_ID` → zwraca `149777`

Expected wynik: **149777**. Brak logu warning.

- [ ] **Step 2: Trace scenariusza "transport WoodPower"**

Dane wejściowe:
```
order.is_personal_pickup = False
order.override_delivery_method = 'transport_woodpower'
```

Trace:
- `if order.is_personal_pickup:` → `False`, idziemy dalej
- `override = ('transport_woodpower' or '').strip()` → `'transport_woodpower'`
- `if override == 'transport_woodpower':` → `True`
- `return PLANNED_ROUTE_STATUS_ID` → zwraca `417343`

Expected wynik: **417343**. Brak logu warning.

- [ ] **Step 3: Trace scenariusza "kurier"**

Dane wejściowe:
```
order.is_personal_pickup = False
order.override_delivery_method = 'kurier_baselinker'
```

Trace:
- `if order.is_personal_pickup:` → `False`
- `override = 'kurier_baselinker'`
- `if override == 'transport_woodpower':` → `False`
- `if override == 'kurier_baselinker':` → `True`
- `return ORDER_PACKED_STATUS_ID` → zwraca `138623`

Expected wynik: **138623**. Brak logu warning.

- [ ] **Step 4: Trace fallback (override = NULL, nie-personal-pickup)**

Dane wejściowe:
```
order.is_personal_pickup = False
order.override_delivery_method = None
order.internal_order_number = "25/002"
order.baselinker_order_id = 8888
```

Trace:
- `if order.is_personal_pickup:` → `False`
- `override = (None or '').strip()` → `''`
- `if override == 'transport_woodpower':` → `False`
- `if override == 'kurier_baselinker':` → `False`
- `logger.warning(...)` z extra `{internal_order_number: "25/002", baselinker_order_id: 8888, override_delivery_method: None}`
- `return ORDER_PACKED_STATUS_ID` → zwraca `138623`

Expected wynik: **138623** + WARNING log z payloadem.

- [ ] **Step 5: Sprawdzić wywołanie w `_process_pending`**

Otworzyć plik, znaleźć gałąź `if station_code == 'packaging':`. Potwierdzić:
- Linia `if not all(p.current_status == 'spakowane' for p in products): return` — bez zmian
- Linia `target = _determine_packaging_target_status(products[0].order)` — nowa, używa helpera

Dla scenariusza "wszystkie produkty `spakowane`", `products[0].order` jest tym samym `ProductionOrder` dla każdego produktu zamówienia (joinedload), więc indeks `[0]` jest bezpieczny.

---

### Task 5: Commit

**Files:** wszystkie zmiany w `baselinker_status_sync.py` razem.

- [ ] **Step 1: Sprawdzić diff**

Run:
```bash
git diff modules/production/services/baselinker_status_sync.py
```

Spodziewany diff: +2 stałe, +helper (~20 linii), zmiana 1 linii w `_process_pending`. Nic poza tym (brak nieistotnych edycji w innych miejscach).

- [ ] **Step 2: Commit**

Run:
```bash
git add modules/production/services/baselinker_status_sync.py
git commit -m "$(cat <<'EOF'
feat(production): różnicuj status BL po pakowaniu wg metody dostawy

Po ukończeniu pakowania zamówienia wybieramy status BL na podstawie typu
dostawy: odbiór osobisty → 149777 (Czeka na odbiór osobisty), transport
WoodPower → 417343 (Planowana trasa), kurier → 138623 (Zamówienie
spakowane, bez zmian). Fallback przy braku decyzji logistyki: 138623 + warn log.

Spec: docs/superpowers/specs/2026-05-13-packaging-bl-status-by-delivery-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: jeden commit, 1 plik zmieniony, ~25 linii dodanych, 1 zmieniona.

- [ ] **Step 3: Push do main (deploy)**

> Decyzja użytkownika — zgodnie z [[feedback_pr_workflow]] preferuje push prosto na main. Zapytaj zanim wypchniesz jeśli nie ma jednoznacznej dyspozycji.

Run (po potwierdzeniu):
```bash
git push origin main
```

GitHub Actions automatycznie deploy'uje na produkcję.

---

## Smoke test po deploy (manualny, user)

Po wypchnięciu na main i restart Passenger (`tmp/restart.txt`), użytkownik wykonuje na produkcji:

1. **Zamówienie z odbiorem osobistym** — zakończ pakowanie, zweryfikuj że w panelu BL status zmienił się na "Czeka na odbiór osobisty" (ID 149777).
2. **Zamówienie z logistyką → transport WoodPower** — zakończ pakowanie, zweryfikuj status BL → "Planowana trasa" (ID 417343).
3. **Zamówienie z logistyką → kurier** — zakończ pakowanie, zweryfikuj status BL → "Zamówienie spakowane" (ID 138623).

Jeśli któryś przypadek nie działa, sprawdzić logi `modules/logging/logs/production.log` pod kątem zdarzeń `production.baselinker_status_sync`.
