# Równoległe stanowiska Wycinanie/Składanie — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zmiana przepływu produkcyjnego na równoległy — mikrowczep → Wycinanie, lity → Składanie, oba → Sklejanie.

**Architecture:** Modyfikacja hard-coded mapy przejść w `complete_task()`, warunkowe przypisanie pierwszego stanowiska wg `parsed_technology` w imporcie BaseLinker, walidacja technologii w preview i save, zmiana display names, usunięcie cross-pollingu, filtrowanie timeline wg technologii.

**Tech Stack:** Python/Flask (backend), Jinja2 (templates), vanilla JS (frontend), SQLAlchemy (ORM), MySQL

**Spec:** `docs/superpowers/specs/2026-04-08-parallel-stations-design.md`

---

## File Map

**Modyfikowane pliki:**

| Plik | Zmiana |
|------|--------|
| `modules/production/models.py` | `complete_task()` — nowa mapa przejść, usunięcie skipped_cutting |
| `modules/production/services/sync_service.py` | Import — przypisanie stanowiska wg technologii |
| `modules/production/routers/api/sync_api.py` | Preview — parsowanie technologii i walidacja |
| `modules/production/static/js/modules/dashboard_bl_sync_modal.js` | Modal — blokada zamówień z błędem technologii, badge technologii |
| `modules/production/static/css/dashboard_bl_sync_modal.css` | Style dla błędu technologii i badge |
| `modules/production/routers/api/stations_api.py` | Nazwa stanowiska |
| `modules/production/routers/api/dashboard_api.py` | Nazwy stanowisk w chart labels |
| `modules/production/routers/stations/interfaces.py` | station_name kwarg |
| `modules/production/routers/stations/monitors.py` | status display names |
| `modules/production/routers/stations/__init__.py` | station config names |
| `modules/production/templates/components/dashboard-tab-content.html` | Nazwy stanowisk w HTML |
| `modules/production/templates/stations/cutting.html` | stationName JS config |
| `modules/production/templates/stations/assembly.html` | stationName JS config, usunięcie badge-cut |
| `modules/production/static/js/modules/dashboard-module.js` | Nazwy stanowisk |
| `modules/production/static/js/modules/products-module.js` | STATUS_TRANSLATIONS, STATUS_CONFIG, timeline, getStatusConfig, usunięcie skip logic |
| `modules/production/static/js/stations/station-assembly.js` | Usunięcie cutting progress polling i badge |
| `modules/production/static/js/stations/station-cutting.js` | Usunięcie assembly progress polling |

---

### Task 1: Zmiana mapy przejść w `complete_task()`

**Files:**
- Modify: `modules/production/models.py:590-669`

- [ ] **Step 1: Zmień `next_status_map` — cutting prowadzi do sklejania**

W `modules/production/models.py`, linia 607-614, zmień mapę:

```python
# PRZED:
next_status_map = {
    'cutting': 'czeka_na_skladanie',
    'assembly': 'czeka_na_sklejanie',
    'gluing': 'czeka_na_formatowanie',
    'formatting': 'czeka_na_wykanczanie',
    'finishing': 'czeka_na_logistyke',
    'packaging': 'spakowane'
}

# PO:
next_status_map = {
    'cutting': 'czeka_na_sklejanie',    # Wycinanie → Sklejanie (równoległy przepływ)
    'assembly': 'czeka_na_sklejanie',   # Składanie → Sklejanie (równoległy przepływ)
    'gluing': 'czeka_na_formatowanie',
    'formatting': 'czeka_na_wykanczanie',
    'finishing': 'czeka_na_logistyke',
    'packaging': 'spakowane'
}
```

- [ ] **Step 2: Usuń logikę `skipped_cutting`**

W tym samym pliku:

1. Usuń linię 604: `skipped_cutting = False`
2. Usuń linie 619-628 (blok `if station_code == 'assembly' and self.current_status == 'czeka_na_wyciecie':`)
3. Usuń z logowania na końcu metody odniesienie do `skipped_cutting` (linia 666)

Zaktualizowany docstring metody (linie 591-602):

```python
def complete_task(self, station_code):
    """
    Ukończenie pracy na stanowisku - przejście do następnego statusu
    Wywoływane gdy wszystkie produkty w zamówieniu mają quantity_done == quantity

    PRZEPŁYW: Stanowiska cutting i assembly są równoległe.
    - cutting (mikrowczep) → sklejanie
    - assembly (lity) → sklejanie
    Produkty z wykończeniem "Surowe" pomijają stanowisko "finishing"
    i przechodzą bezpośrednio z "formatting" do logistyki.
    """
    now = get_local_now()
```

- [ ] **Step 3: Zweryfikuj że reszta metody działa**

Upewnij się, że po usunięciu `skipped_cutting`:
- Blok skip finishing (linie 632-646) — bez zmian, dalej działa
- Blok skip logistyki (linie 649-651) — bez zmian
- Linia `self.current_status = next_status` — bez zmian
- Linia `setattr(self, completed_attr, now)` — bez zmian

- [ ] **Step 4: Commit**

```bash
git add modules/production/models.py
git commit -m "feat: cutting i assembly oba prowadzą do sklejania (równoległy przepływ)"
```

---

### Task 2: Import BaseLinker — przypisanie stanowiska wg technologii

**Files:**
- Modify: `modules/production/services/sync_service.py:1085-1095`

- [ ] **Step 1: Zmień przypisanie `current_status` w `_prepare_product_data_enhanced()`**

W `modules/production/services/sync_service.py`, linia 1091, zamień:

```python
# PRZED (linia 1091):
'current_status': 'czeka_na_wyciecie',

# PO:
'current_status': self._get_initial_station_by_technology(parsed_data.get('technology')),
```

- [ ] **Step 2: Dodaj metodę `_get_initial_station_by_technology()` w klasie sync_service**

Dodaj nową metodę w klasie `SyncService` (przed `_prepare_product_data_enhanced`):

```python
def _get_initial_station_by_technology(self, technology):
    """
    Zwraca początkowy status produkcyjny na podstawie technologii.
    - mikrowczep → czeka_na_wyciecie (stanowisko Wycinanie)
    - lity → czeka_na_skladanie (stanowisko Składanie)
    
    Raises:
        ValueError: Gdy technologia nie jest rozpoznana
    """
    technology_to_station = {
        'mikrowczep': 'czeka_na_wyciecie',
        'lity': 'czeka_na_skladanie',
    }
    station = technology_to_station.get(technology)
    if station is None:
        raise ValueError(f"Nierozpoznana technologia: '{technology}' — dozwolone: mikrowczep, lity")
    return station
```

- [ ] **Step 3: Dodaj walidację technologii na poziomie zamówienia**

Znajdź w `process_orders_with_priority_logic()` miejsce gdzie iteruje się po produktach zamówienia (okolice linii 431-499). Przed tworzeniem produktów, dodaj walidację wszystkich pozycji:

W metodzie `_create_product_from_order_data()` (linia ~599-680), po wywołaniu parsera (linie 623-630), dodaj sprawdzenie:

```python
# Po sparsowaniu nazwy produktu
parsed_technology = parsed_data.get('technology')

# Walidacja technologii — musi być mikrowczep lub lity
if parsed_technology not in ('mikrowczep', 'lity'):
    error_msg = f"Nierozpoznana technologia w pozycji '{product_name}' zamówienia {order_number}"
    logger.error("Walidacja technologii nieudana", extra={
        'product_name': product_name,
        'parsed_technology': parsed_technology,
        'order_number': order_number
    })
    raise ValueError(error_msg)
```

W miejscu wywołującym `_create_product_from_order_data()`, złap `ValueError` i odrzuć całe zamówienie:
- Nie twórz żadnych produktów z tego zamówienia
- Zapisz `ProductionError` z `error_type='unknown_technology'`
- Zamówienie zostaje w BaseLinker ze starym statusem (nie zmieniaj statusu)

- [ ] **Step 4: Commit**

```bash
git add modules/production/services/sync_service.py
git commit -m "feat: przypisanie stanowiska wg technologii przy imporcie (mikrowczep→wycinanie, lity→składanie)"
```

---

### Task 3: Preview endpoint — parsowanie technologii dla modalu

**Files:**
- Modify: `modules/production/routers/api/sync_api.py:880-902`

- [ ] **Step 1: Dodaj parsowanie technologii w `fetch_orders_preview()`**

W `modules/production/routers/api/sync_api.py`, wewnątrz pętli `for product in order['products']:` (linia 883), po linii 884 (`product_name = ...`), dodaj parsowanie technologii:

```python
from modules.production.services.parser_service import parse_product_name

# ... wewnątrz pętli for product in order['products']: ...

product_name = product.get('name', 'Bez nazwy')
product_name_lower = product_name.strip().lower()

# Parsuj technologię z nazwy produktu
parsed_result = parse_product_name(product_name)
parsed_technology = parsed_result.get('technology')
is_valid_technology = parsed_technology in ('mikrowczep', 'lity')
```

- [ ] **Step 2: Dodaj pola technologii do odpowiedzi produktu**

W dict `processed_products.append({...})` (linie 893-901), dodaj pola:

```python
processed_products.append({
    'name': product_name,
    'sku': product.get('sku', ''),
    'variant': product.get('variant', ''),
    'quantity': float(product.get('quantity', 0)),
    'price': float(product.get('price_brutto', 0)),
    'unit': product.get('unit', 'szt.'),
    'already_in_db': already_exists,
    'parsed_technology': parsed_technology,       # NOWE
    'unknown_technology': not is_valid_technology  # NOWE
})
```

- [ ] **Step 3: Dodaj flagę `technology_error` na zamówieniu**

Po pętli produktów, przed `filtered_orders.append(order)` (linia 926), dodaj:

```python
# Sprawdź czy zamówienie ma błąd technologii
has_technology_error = any(
    p.get('unknown_technology', False) 
    for p in order.get('products', [])
    if not self_is_product_filtered(p)  # Pomiń produkty usługowe/materiałowe
)
order['technology_error'] = has_technology_error
```

Uwaga: filtrowanie produktów usługowych robi JS (klasa `DashboardBLSyncModal.isProductFiltered()`). W backendzie zastosuj tę samą logikę — sprawdź czy nazwa produktu zawiera słowa kluczowe z filtra (`'usługa', 'deska', 'worek', 'tarcica'` itd.). Jeśli produkt jest filtrowany, nie sprawdzaj jego technologii.

Alternatywnie (prostsze): wystarczy ustawić flagę na podstawie wszystkich nie-filtrowanych produktów. JS i tak sprawdza `isProductFiltered()` — więc backend może po prostu oznaczyć wszystkie produkty, a JS zdecyduje co wyświetlić.

Uproszczona wersja:
```python
# Sprawdź czy zamówienie ma błąd technologii (wśród wszystkich produktów)
has_technology_error = any(
    p.get('unknown_technology', False) for p in processed_products
)
order['technology_error'] = has_technology_error
```

- [ ] **Step 4: Commit**

```bash
git add modules/production/routers/api/sync_api.py
git commit -m "feat: parsowanie technologii w preview zamówień (badge + walidacja)"
```

---

### Task 4: Modal importu — blokada zamówień z błędem technologii i badge

**Files:**
- Modify: `modules/production/static/js/modules/dashboard_bl_sync_modal.js:935-990, 995-1040`
- Modify: `modules/production/static/css/dashboard_bl_sync_modal.css`

- [ ] **Step 1: Zablokuj zamówienia z `technology_error` w `renderOrdersList()`**

W `dashboard_bl_sync_modal.js`, w metodzie `renderOrdersList()` (linia 935), po linii 948 (zamknięcie `partialBadge`), dodaj badge błędu technologii:

```javascript
// Badge błędu technologii
let technologyBadge = '';
if (order.technology_error === true) {
    technologyBadge = `<span class="sync-order-tech-error-badge" title="Co najmniej jeden produkt ma nierozpoznaną technologię">
        <span style="color: #dc2626; font-size: 12px; padding: 2px 6px; background: rgba(220, 38, 38, 0.1); border-radius: 4px; margin-left: 8px;">
            ⚠ Nierozpoznana technologia
        </span>
    </span>`;
}
```

W HTML zamówienia, obok `${partialBadge}` (linia 963), dodaj:
```javascript
Zamówienie #${order.baselinker_order_id || order.id || `TEMP-${index}`}
${partialBadge}
${technologyBadge}
```

Zablokuj checkbox — w atrybutach checkboxa (linia 956), dodaj warunek disabled:
```javascript
<input type="checkbox"
       class="sync-order-checkbox"
       ${isSelected ? 'checked' : ''}
       ${order.technology_error ? 'disabled' : ''}
       onclick="event.stopPropagation(); window.dashboardBLSyncModal.toggleOrderSelection(${index})">
```

Zablokuj kliknięcie na header:
```javascript
<div class="sync-order-header" onclick="${order.technology_error ? '' : `window.dashboardBLSyncModal.toggleOrderSelection(${index})`}">
```

Dodaj klasę CSS:
```javascript
<div class="sync-order-item ${isSelected ? 'selected' : ''} ${isPartiallyExists ? 'partially-exists' : ''} ${order.technology_error ? 'technology-error' : ''}" ...>
```

- [ ] **Step 2: Dodaj badge technologii i label na produktach w `renderOrderProducts()`**

W `renderOrderProducts()` (linia 995), wewnątrz pętli produktów, po określeniu `statusLabel` (linia 1031), dodaj:

```javascript
// Badge technologii
let techBadge = '';
if (!isFiltered) {
    if (product.unknown_technology) {
        statusLabel = '<small style="color: #dc2626; font-weight: 600;">(nieznana technologia)</small>';
        itemClasses += ' tech-error';
    }
    
    if (product.parsed_technology) {
        const techLabel = product.parsed_technology === 'lity' ? 'lite' : product.parsed_technology;
        techBadge = `<span class="sync-product-tech-badge" style="font-size: 11px; padding: 1px 5px; background: rgba(99,102,241,0.1); color: #6366f1; border-radius: 3px; margin-left: 6px;">${techLabel}</span>`;
    }
}
```

W HTML produktu, obok nazwy produktu (linia ~1036-1037), dodaj `${techBadge}`:
```javascript
<div class="sync-product-name">
    ${product.name || 'Bez nazwy'} ${techBadge}
    ${statusLabel}
</div>
```

- [ ] **Step 3: Upewnij się że "Zaznacz wszystkie" pomija zablokowane zamówienia**

W metodzie obsługi "selectAllOrders" — znajdź gdzie zaznaczane są wszystkie zamówienia i dodaj warunek:

```javascript
// W selectAllOrders handler — pomiń zamówienia z błędem technologii
this.fetchedOrders.forEach(order => {
    if (!order.technology_error) {
        if (!this.selectedOrders.includes(order)) {
            this.selectedOrders.push(order);
        }
    }
});
```

- [ ] **Step 4: Dodaj style CSS**

W `modules/production/static/css/dashboard_bl_sync_modal.css`, dodaj:

```css
/* Zamówienie z błędem technologii - zablokowane */
.sync-order-item.technology-error {
    opacity: 0.7;
    border-left: 3px solid #dc2626;
    cursor: not-allowed;
}

.sync-order-item.technology-error .sync-order-checkbox {
    cursor: not-allowed;
}

.sync-product-item.tech-error {
    background: rgba(220, 38, 38, 0.05);
}
```

- [ ] **Step 5: Commit**

```bash
git add modules/production/static/js/modules/dashboard_bl_sync_modal.js modules/production/static/css/dashboard_bl_sync_modal.css
git commit -m "feat: blokada zamówień z nieznaną technologią w modalu importu + badge technologii"
```

---

### Task 5: Zmiana nazw stanowisk — Python backend

**Files:**
- Modify: `modules/production/routers/api/stations_api.py:91-99`
- Modify: `modules/production/routers/api/dashboard_api.py:303-310` (+ ~1165, ~1190)
- Modify: `modules/production/routers/stations/interfaces.py:187-188`
- Modify: `modules/production/routers/stations/monitors.py:183-191, 324-334`
- Modify: `modules/production/routers/stations/__init__.py:604-608, 647-658`

- [ ] **Step 1: `stations_api.py` — zmień station name mapping**

Linie 91-99:
```python
# PRZED:
'cutting': 'Wycinanie',
'assembly': 'Składanie',

# PO:
'cutting': 'Wycinanie - mikro',
'assembly': 'Składanie - lite',
```

- [ ] **Step 2: `dashboard_api.py` — zmień chart labels**

Linie 303-310 i pozostałe wystąpienia (~1165, ~1190) — zamień `'Wycinanie'` na `'Wycinanie - mikro'`, `'Składanie'` na `'Składanie - lite'` w mappingach `station_labels`.

- [ ] **Step 3: `interfaces.py` — zmień station_name kwargs**

Linia 187-188: zamień `station_name='Wycinanie'` na `station_name='Wycinanie - mikro'`.
Analogicznie dla assembly: zamień `station_name='Składanie'` na `station_name='Składanie - lite'`.

- [ ] **Step 4: `monitors.py` — zmień status display names**

Linie 183-191 i 324-334:
```python
# PRZED:
'czeka_na_wyciecie': 'Wycinanie',
'czeka_na_skladanie': 'Skladanie',

# PO:
'czeka_na_wyciecie': 'Wycinanie - mikro',
'czeka_na_skladanie': 'Składanie - lite',
```

- [ ] **Step 5: `__init__.py` — zmień station config names**

Linie 604-608:
```python
# PRZED:
'cutting': 'Wycinanie',
'assembly': 'Skladanie',

# PO:
'cutting': 'Wycinanie - mikro',
'assembly': 'Składanie - lite',
```

Analogicznie w pozostałych mappingach (~linie 647, 658).

- [ ] **Step 6: Commit**

```bash
git add modules/production/routers/
git commit -m "feat: zmiana nazw stanowisk na 'Wycinanie - mikro' i 'Składanie - lite' (backend)"
```

---

### Task 6: Zmiana nazw stanowisk — Frontend (HTML + JS)

**Files:**
- Modify: `modules/production/templates/components/dashboard-tab-content.html:25,62`
- Modify: `modules/production/templates/stations/cutting.html:268`
- Modify: `modules/production/templates/stations/assembly.html:268`
- Modify: `modules/production/static/js/modules/dashboard-module.js:286`
- Modify: `modules/production/static/js/modules/products-module.js:26-38, 42-59, 3673-3693, 3974-3995`

- [ ] **Step 1: `dashboard-tab-content.html` — zmień nazwy w HTML**

Linia 25: zamień `Wycinanie` na `Wycinanie - mikro`
Linia 62: zamień `Składanie` na `Składanie - lite`

- [ ] **Step 2: `cutting.html` i `assembly.html` — zmień stationName w JS config**

`cutting.html` linia 268: `stationName: 'Wycinanie - mikro',`
`assembly.html` linia 268: `stationName: 'Składanie - lite',`

- [ ] **Step 3: `dashboard-module.js` — zmień ternary mapping**

Linia 286:
```javascript
// PRZED:
name: key === 'cutting' ? 'Wycinanie' : key === 'assembly' ? 'Składanie' : 'Pakowanie',

// PO:
name: key === 'cutting' ? 'Wycinanie - mikro' : key === 'assembly' ? 'Składanie - lite' : 'Pakowanie',
```

- [ ] **Step 4: `products-module.js` — zmień STATUS_TRANSLATIONS**

Linie 26-38:
```javascript
// PRZED:
'czeka_na_wyciecie': 'Wycinanie',
'czeka_na_skladanie': 'Składanie',

// PO:
'czeka_na_wyciecie': 'Wycinanie - mikro',
'czeka_na_skladanie': 'Składanie - lite',
```

- [ ] **Step 5: `products-module.js` — zmień STATUS_CONFIG**

Linie 42-59:
```javascript
// PRZED:
'czeka_na_wyciecie': { icon: 'fa-cut', displayName: 'Wycinanie', ... },
'czeka_na_skladanie': { icon: 'fa-hammer', displayName: 'Składanie', ... },

// PO:
'czeka_na_wyciecie': { icon: 'fa-cut', displayName: 'Wycinanie - mikro', ... },
'czeka_na_skladanie': { icon: 'fa-hammer', displayName: 'Składanie - lite', ... },
```

- [ ] **Step 6: `products-module.js` — zmień nazwy w timeline stations**

Linie 3673-3693:
```javascript
// PRZED:
{ code: 'cutting', name: 'Wycięcie', ... },
{ code: 'assembly', name: 'Składanie', ... },

// PO:
{ code: 'cutting', name: 'Wycinanie - mikro', ... },
{ code: 'assembly', name: 'Składanie - lite', ... },
```

- [ ] **Step 7: `products-module.js` — zmień `getStatusConfig()`**

Linie 3974-3995:
```javascript
// PRZED:
'czeka_na_wyciecie': { ... displayName: 'Wycinanie' ... },
'w_trakcie_ciecia': { ... displayName: 'Wycinanie' ... },
'czeka_na_skladanie': { ... displayName: 'Składanie' ... },
'w_trakcie_skladania': { ... displayName: 'Składanie' ... },

// PO:
'czeka_na_wyciecie': { ... displayName: 'Wycinanie - mikro' ... },
'w_trakcie_ciecia': { ... displayName: 'Wycinanie - mikro' ... },
'czeka_na_skladanie': { ... displayName: 'Składanie - lite' ... },
'w_trakcie_skladania': { ... displayName: 'Składanie - lite' ... },
```

- [ ] **Step 8: Commit**

```bash
git add modules/production/templates/ modules/production/static/js/modules/
git commit -m "feat: zmiana nazw stanowisk na 'Wycinanie - mikro' i 'Składanie - lite' (frontend)"
```

---

### Task 7: Usunięcie cross-pollingu cutting↔assembly

**Files:**
- Modify: `modules/production/static/js/stations/station-assembly.js:120-260, 1083-1095`
- Modify: `modules/production/static/js/stations/station-cutting.js:120-260`
- Modify: `modules/production/templates/stations/assembly.html:184-186`

- [ ] **Step 1: `station-assembly.js` — usuń cutting progress polling**

Usuń następujące metody (linie ~120-253):
- `startCuttingProgressPolling()` (~linie 120-134)
- `stopCuttingProgressPolling()` (~linie 136-142)
- `fetchCuttingProgress()` (~linie 157-191)
- `updateCuttingCounters()` (~linie 193-253)

Usuń wywołania tych metod — szukaj `startCuttingProgressPolling` i `stopCuttingProgressPolling` w reszcie pliku i usuń te wywołania.

- [ ] **Step 2: `station-assembly.js` — usuń badge-cut scissors**

Usuń blok generujący badge z nożyczkami (~linie 1083-1095):
```javascript
// USUNĄĆ cały blok generujący badge-cut z SVG nożyczek i cut-counter
```

- [ ] **Step 3: `station-cutting.js` — usuń assembly progress polling**

Usuń analogiczne metody (linie ~120-249):
- `startAssemblyProgressPolling()` (~linie 120-134)
- `stopAssemblyProgressPolling()` (~linie 136-142)
- `fetchAssemblyProgress()` (~linie 157-191)
- `updateAssemblyCounters()` (~linie 193-249)

Usuń wywołania tych metod w reszcie pliku.

- [ ] **Step 4: `assembly.html` — usuń badge-cut template**

Usuń linie 184-186:
```html
<!-- USUNĄĆ -->
{% if product.quantity_done_cutting is defined and product.quantity_done_cutting and product.quantity_done_cutting > 0 %}
    <span class="badge badge-cut" title="Wycieto">✂ {{ product.quantity_done_cutting }}/{{ product.quantity }}</span>
{% endif %}
```

- [ ] **Step 5: Commit**

```bash
git add modules/production/static/js/stations/ modules/production/templates/stations/assembly.html
git commit -m "refactor: usunięcie cross-pollingu cutting↔assembly (stanowiska niezależne)"
```

---

### Task 8: Timeline w modalu szczegółów — filtrowanie wg technologii

**Files:**
- Modify: `modules/production/static/js/modules/products-module.js:3670-3780, 3786-3837, 3842-3909, 3914-3955`

- [ ] **Step 1: Dodaj helper do filtrowania stanowisk wg technologii**

Przed metodą `generateTimeline()` (~linia 3670), dodaj:

```javascript
/**
 * Zwraca listę stanowisk dla danej technologii produktu.
 * mikrowczep → wycinanie + wspólne stanowiska
 * lity → składanie + wspólne stanowiska
 */
getStationsForProduct(product) {
    const technology = (product.parsed_technology || '').toLowerCase();
    
    // Wspólne stanowiska (od sklejania dalej)
    const commonStations = ['gluing', 'formatting', 'finishing', 'logistics', 'packaging'];
    
    if (technology === 'mikrowczep') {
        return ['cutting', ...commonStations];
    } else if (technology === 'lity') {
        return ['assembly', ...commonStations];
    }
    
    // Fallback — pokaż oba (dla starych danych lub braku technologii)
    return ['cutting', 'assembly', ...commonStations];
}
```

- [ ] **Step 2: Filtruj stanowiska w `generateTimeline()`**

W `generateTimeline()` (~linia 3670), po definicji tablicy `stations` (linia 3744), dodaj filtr:

```javascript
// Filtruj stanowiska wg technologii produktu
const allowedCodes = this.getStationsForProduct(product);
const filteredStations = stations.filter(s => allowedCodes.includes(s.code));
```

Zmień `stations.forEach(station => {` (linia 3749) na:
```javascript
filteredStations.forEach(station => {
```

- [ ] **Step 3: Filtruj stanowiska w `generateQuantityProgress()`**

W `generateQuantityProgress()` (~linia 3786), zamień stałą listę `stations` (linia 3791):

```javascript
// PRZED:
const stations = ['cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'logistics', 'packaging'];

// PO:
const stations = this.getStationsForProduct(product);
```

- [ ] **Step 4: Usuń logikę "Pominięto wycinanie" z `getTimelineDetails()`**

W `getTimelineDetails()` (~linia 3914), usuń linie 3919-3929:

```javascript
// USUNĄĆ cały blok:
// Specjalna logika dla cutting: "Pominięto" gdy brak cutting_completed_at ale jest assembly_completed_at
if (station.code === 'cutting') {
    const cuttingCompleted = product['cutting_completed_at'];
    const assemblyCompleted = product['assembly_completed_at'];
    if (!cuttingCompleted && assemblyCompleted) {
        return {
            text: 'Produkt złożony bez wycinania'
        };
    }
}
```

- [ ] **Step 5: Usuń `prevStations` mapping**

W `getTimelineDetails()`, usuń linie 3947-3954:

```javascript
// USUNĄĆ:
const prevStations = {
    'assembly': 'wycięcie',
    'packaging': 'składanie'
};
const prevStation = prevStations[station.code];
return {
    text: prevStation ? `Oczekuje na ${prevStation}` : 'Oczekuje na rozpoczęcie'
};

// ZAMIENIĆ NA:
return {
    text: 'Oczekuje na rozpoczęcie'
};
```

- [ ] **Step 6: Commit**

```bash
git add modules/production/static/js/modules/products-module.js
git commit -m "feat: timeline filtrowany wg technologii produktu (mikrowczep/lity)"
```

---

### Task 9: Weryfikacja manualna i czyszczenie danych lokalnych

- [ ] **Step 1: Wyczyść lokalne dane produkcyjne**

```bash
# Uruchom Flask shell i wyczyść dane
cd C:/Users/Grafik/Desktop/Github/CRM/CRM
python -c "
from app import create_app
from extensions import db
from modules.production.models import ProductionItem, ProductionSyncLog, ProductionError

app = create_app()
with app.app_context():
    ProductionError.query.delete()
    ProductionSyncLog.query.delete()
    ProductionItem.query.delete()
    db.session.commit()
    print('Dane produkcyjne wyczyszczone')
"
```

- [ ] **Step 2: Uruchom aplikację i przetestuj ręcznie**

```bash
# Uruchom serwer
python -m flask run --host=127.0.0.1 --port=5000
```

Testy manualne:
1. **Dashboard** (`/production/`) — sprawdź że nazwy stanowisk to "Wycinanie - mikro" i "Składanie - lite"
2. **Import** — otwórz modal synchronizacji, pobierz zamówienia, sprawdź:
   - Badge technologii przy produktach
   - Zamówienia z nieznaną technologią są zablokowane (jeśli takie istnieją)
3. **Zaimportuj zamówienia** — sprawdź:
   - Pozycje mikrowczep trafiają na Wycinanie
   - Pozycje lity trafiają na Składanie
4. **Stanowisko** (`/production/cutting`, `/production/assembly`) — sprawdź nazwy
5. **Products tab** — otwórz modal szczegółów produktu, sprawdź timeline:
   - Produkt mikrowczep: timeline zaczyna się od "Wycinanie - mikro", brak "Składanie - lite"
   - Produkt lity: timeline zaczyna się od "Składanie - lite", brak "Wycinanie - mikro"
6. **Ukończ pozycję** na stanowisku — sprawdź że przechodzi na Sklejanie (nie na Składanie)

- [ ] **Step 3: Commit finalny (jeśli potrzebne poprawki)**

```bash
git add -A
git commit -m "fix: poprawki po weryfikacji manualnej równoległych stanowisk"
```
