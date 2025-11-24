# PRD: Refaktoryzacja stanowisk wycinania i montażu na model order-based

**Wersja:** 1.0
**Data utworzenia:** 2025-01-24
**Autor:** Konrad Kmiecik
**Status:** Draft - Do omówienia i zatwierdzenia

---

## 1. Executive Summary

### 1.1 Problem
Obecnie stanowiska **wycinania** (cutting) i **montażu** (assembly) wyświetlają produkty jako **pojedyncze karty** z pojedynczym przyciskiem do ukończenia. W przypadku zamówień wieloproduktowych (np. 14 elementów) pracownik musi:
- Szukać produktów po numerze ID w chaotycznej siatce
- Klikać 14 razy "ZAKOŃCZ" dla każdego produktu osobno
- Trudno jest śledzić postęp całego zamówienia

### 1.2 Rozwiązanie
Zmiana modelu wyświetlania z **product-based** na **order-based**, wzorując się na stanowisku **pakowania** (packaging):
- Jedna karta = jedno zamówienie
- Lista produktów z checkboxami wewnątrz karty
- Jeden przycisk "ZAKOŃCZ" dla całego zamówienia po zaznaczeniu wszystkich produktów
- Lepsze grupowanie, łatwiejsze śledzenie postępu

### 1.3 Cel biznesowy
- **Zwiększenie wydajności** pracy na stanowiskach o ~30-50%
- **Redukcja błędów** (pomylone produkty, pominięte elementy)
- **Lepsza przejrzystość** - pracownik widzi kontekst całego zamówienia
- **Spójność UX** - wszystkie 3 stanowiska działają identycznie

---

## 2. Obecny stan (AS-IS)

### 2.1 Architektura obecna - Cutting/Assembly

**Widok:**
- Siatka produktów (`grid-template-columns: repeat(auto-fit, minmax(360px, 1fr))`)
- Każdy produkt = osobna karta z:
  - Header: ID produktu, numer Baselinker, objętość m³
  - Badges: gatunek, technologia, klasa drewna (3 kolumny)
  - Wymiary (duży box na środku karty)
  - Przycisk "ZAKOŃCZ WYCIĘCIE" / "ZAKOŃCZ MONTAŻ"

**Logika:**
- 1 klik = 1 request do API
- Status zmienia się dla pojedynczego produktu
- Karta znika natychmiast po kliknięciu (optimistic UI)

**Problemy:**
1. **Brak kontekstu zamówienia** - produkty są rozproszone
2. **Wielokrotne kliknięcia** dla zamówień z wieloma produktami
3. **Trudne wyszukiwanie** - numeracja produktów nie jest posortowana w logiczny sposób
4. **Brak wizualnego postępu** - nie wiadomo ile zostało do zrobienia w ramach zamówienia
5. **Karty różnej długości** w siatce powodują nierówne wypełnienie przestrzeni

### 2.2 Architektura docelowa - Packaging (wzór)

**Widok:**
- Lista zamówień (nie siatka!)
- Każde zamówienie = karta z:
  - Header: numer zamówienia, deadline, postęp (X/Y produktów)
  - Lista produktów (product rows) z checkboxami
  - Każdy row: checkbox + ID + badges + nazwa + objętość
  - Przycisk "SPAKOWANE" na dole karty (aktywny po zaznaczeniu wszystkich)

**Logika:**
- Checkboxy zapisują stan w localStorage (`packaging_order_<number>`)
- Po zaznaczeniu wszystkich → przycisk staje się aktywny
- 1 klik = 1 request dla CAŁEGO zamówienia (bulk completion)
- Smart merge podczas auto-refresh (zachowuje stan checkboxów)

**Zalety:**
1. **Kontekst zamówienia** - widzisz wszystkie produkty naraz
2. **Wizualny postęp** - licznik "2/14 produktów"
3. **Jeden klik** na końcu = zakończenie całego zamówienia
4. **Elastyczny layout** - karty mogą być różnej wysokości bez problemów
5. **Zapisany stan** - po odświeżeniu checkboxy pozostają zaznaczone

---

## 3. Docelowy stan (TO-BE)

### 3.1 Zmiana modelu danych

**Backend - Nowy endpoint dla każdego stanowiska:**
```
GET /ajax/orders/cutting?sort=priority
GET /ajax/orders/assembly?sort=priority
```

**Odpowiedź JSON:**
```json
{
  "success": true,
  "data": {
    "orders": [
      {
        "order_number": "241118/2",
        "baselinker_order_id": 123456,
        "display_deadline": "23.01.2025",
        "deadline_date": "2025-01-23",
        "best_priority_rank": 1,
        "total_products": 14,
        "total_volume": 0.2345,
        "products": [
          {
            "id": 342,
            "short_product_id": "241118/2/1",
            "product_sequence_in_order": 1,
            "original_name": "Buk Lite 120x40x2",
            "dimensions": "120×40×2",
            "volume_m3": 0.0096,
            "wood_species": "BUK",
            "technology": "LITE",
            "wood_class": "A/B",
            "current_status": "czeka_na_wyciecie",
            "attachment_file_name": "rysunek.pdf",
            "attachment_file_url": "https://..."
          },
          // ... więcej produktów (sorted by product_sequence_in_order ASC)
        ]
      }
    ],
    "stats": {
      "total_orders": 5,
      "total_products": 42,
      "total_volume": 1.2345
    }
  }
}
```

**Grupowanie produktów po `internal_order_number`:**
- Backend zbiera produkty gdzie `current_status = 'czeka_na_wyciecie'` (dla cutting)
- Grupuje je po `internal_order_number`
- Dla każdego zamówienia wybiera:
  - `best_priority_rank` = najwyższy priorytet spośród produktów
  - `display_deadline` = formatowana data deadline
  - `total_volume` = suma objętości
  - `total_products` = liczba produktów

### 3.2 Nowy layout UI

**HTML struktura (wzór z packaging.html):**
```html
<div class="orders-list" id="orders-list">
  <div class="order-card"
       data-order-number="241118/2"
       data-priority-rank="1"
       data-total-products="14">

    <!-- ORDER HEADER -->
    <div class="order-header">
      <div class="order-title">
        <span class="order-number">241118/2</span>
        <span class="order-baselinker">BL-123456</span>
      </div>
      <div class="order-summary">
        <span class="deadline-info">📅 23.01.2025</span>
        <span class="summary-stats">
          <span class="products-checked">0</span>/14 produktów • 0.2345 m³
        </span>
      </div>
    </div>

    <!-- PRODUCTS LIST -->
    <div class="products-list">
      <div class="product-row" data-product-id="342">

        <!-- Checkbox -->
        <div class="product-checkbox">
          <input type="checkbox" class="product-check" id="check-342">
          <label for="check-342"></label>
        </div>

        <!-- ID produktu + ikona załącznika -->
        <div class="product-id-wrapper">
          <span class="product-id">342</span>
          <div class="attachment-icon-wrapper" ...>
            <svg>...</svg>
          </div>
        </div>

        <!-- Detale produktu -->
        <div class="product-details">
          <!-- BADGES nad nazwą -->
          <div class="product-badges">
            <span class="badge badge-species">BUK</span>
            <span class="badge badge-technology">LITE</span>
            <span class="badge badge-class">A/B</span>
            <span class="badge badge-dimensions">120×40×2</span>
          </div>
          <!-- Nazwa produktu pod badges -->
          <span class="product-name">Buk Lite 120x40x2</span>
        </div>

        <!-- Objętość -->
        <span class="product-volume">0.0096 m³</span>
      </div>
      <!-- ... więcej product-row -->
    </div>

    <!-- ORDER ACTION -->
    <div class="order-action">
      <button class="btn-complete" data-action="complete-cutting" disabled>
        ZAKOŃCZ WYCIĘCIE
      </button>
    </div>
  </div>
</div>
```

### 3.3 Layout CSS - Masonry-style dla order cards

**Problem:** Karty mogą mieć różną wysokość (2 produkty vs 14 produktów)

**~~Rozwiązanie 1 - CSS Grid z auto-fit~~ (ODRZUCONE):**
```css
/* ODRZUCONE - pozostawia puste przestrzenie */
.orders-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(500px, 1fr));
    gap: 24px;
    align-items: start;
}
```

**✅ Rozwiązanie WYBRANE - Masonry layout (column-count):**
```css
.orders-list {
    column-count: 2;
    column-gap: 24px;
}

.order-card {
    break-inside: avoid;
    margin-bottom: 24px;
}

@media (min-width: 1600px) {
    .orders-list { column-count: 3; }
}
@media (max-width: 1200px) {
    .orders-list { column-count: 1; }
}
```

**Uzasadnienie:** Brak pustych przestrzeni, lepsze wykorzystanie ekranu.

### 3.4 Logika checkboxów

**localStorage key format:**
```
cutting_order_241118/2 = [342, 343, 344]  // array of checked product IDs
assembly_order_241118/2 = [342, 343, 344]
```

**Flow:**
1. **Load state** - przy renderze karty, załaduj stan z localStorage
2. **Checkbox change** - zapisz aktualny stan do localStorage
3. **Check if all checked** - sprawdź czy wszystkie produkty są zaznaczone
4. **Enable button** - jeśli tak, odblokuj przycisk "ZAKOŃCZ"
5. **Complete order** - wyślij request z listą product IDs
6. **Clear state** - usuń localStorage key po sukcesie

**Przykład kodu:**
```javascript
function loadCheckboxState(orderNumber) {
    const key = `${STORAGE_PREFIX}${orderNumber}`;
    const saved = localStorage.getItem(key);
    return saved ? JSON.parse(saved) : [];
}

function saveCheckboxState(orderNumber, checkedIds) {
    const key = `${STORAGE_PREFIX}${orderNumber}`;
    localStorage.setItem(key, JSON.stringify(checkedIds));
}

function updateOrderProgress(card) {
    const checkboxes = card.querySelectorAll('.product-check');
    const checkedCount = card.querySelectorAll('.product-check:checked').length;
    const totalCount = checkboxes.length;

    // Zaktualizuj licznik
    const counter = card.querySelector('.products-checked');
    counter.textContent = checkedCount;

    // Odblokuj przycisk jeśli wszystkie zaznaczone
    const btn = card.querySelector('.btn-complete');
    if (checkedCount === totalCount && totalCount > 0) {
        btn.disabled = false;
    } else {
        btn.disabled = true;
    }
}
```

### 3.5 Tracking started_at, assigned_worker_id, duration

**Problem:** Kiedy ustawiać `cutting_started_at` i `cutting_assigned_worker_id`?

**DECYZJA:**
- **NIE trackujemy** `started_at` ani `assigned_worker_id` na stanowiskach cutting/assembly
- **Powód:** Model order-based zakłada że pracownik robi całe zamówienie naraz, nie ma sensu trackować startu per stanowisko
- **Duration:** Również NIE jest obliczane - to pole pozostaje `NULL`

**Alternatywa (jeśli kiedyś będzie potrzebne):**
- `started_at` = moment kliknięcia "ZAKOŃCZ" (czyli = `completed_at`)
- `duration_minutes` = NULL (brak danych o czasie pracy)

**Uzasadnienie:**
- W pakowanie śledzenie czasu ma sens (produkty przychodzą stopniowo)
- W cutting/assembly cały proces jest atomic - pracownik bierze zamówienie, wykonuje, kończy

### 3.6 API Endpoint - Bulk completion

**Endpoint:**
```
POST /production/stations/complete-order
```

**Request body:**
```json
{
  "order_number": "241118/2",
  "product_ids": [342, 343, 344, 345],
  "station": "cutting",  // lub "assembly"
  "action": "complete"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "completed_count": 4,
    "order_number": "241118/2",
    "next_status": "czeka_na_montaz"  // dla cutting
  }
}
```

**Backend logic:**
```python
@bp.route('/stations/complete-order', methods=['POST'])
def complete_order():
    data = request.get_json()
    order_number = data.get('order_number')
    product_ids = data.get('product_ids', [])
    station = data.get('station')  # 'cutting' lub 'assembly'

    # Walidacja
    if not order_number or not product_ids:
        return jsonify({'success': False, 'error': 'Missing data'}), 400

    # Mapowanie station → next_status
    status_map = {
        'cutting': 'czeka_na_montaz',
        'assembly': 'czeka_na_pakowanie'
    }

    next_status = status_map.get(station)

    # Bulk update
    completed_count = 0
    for product_id in product_ids:
        product = ProductionProduct.query.get(product_id)
        if product and product.internal_order_number == order_number:
            product.current_status = next_status
            product.cutting_completed_at = datetime.now()  # dla cutting
            # lub product.assembly_completed_at dla assembly
            completed_count += 1

    db.session.commit()

    return jsonify({
        'success': True,
        'data': {
            'completed_count': completed_count,
            'order_number': order_number,
            'next_status': next_status
        }
    })
```

### 3.7 UX po ukończeniu zamówienia i obsługa błędów

**Co się dzieje po kliknięciu "ZAKOŃCZ WYCIĘCIE"?**

1. **Optimistic UI:**
   - Karta natychmiast znika z ekranu (nie czekamy na response)
   - Pokazujemy toast notification: "✅ Zamówienie 241118/2 ukończone"
   - localStorage dla tego zamówienia jest czyszczony

2. **Jeśli sukces (response 200 OK):**
   - Nic więcej - karta już zniknęła
   - Auto-refresh za 30s odświeży listę

3. **Jeśli błąd (response 4xx/5xx lub timeout):**
   - **Przywracamy kartę** na ekran
   - **Przywracamy stan checkboxów** z localStorage (backup przed usunięciem)
   - Pokazujemy error toast: "❌ Błąd: [treść błędu]"
   - Przycisk "ZAKOŃCZ" ponownie aktywny

**Implementacja JS:**
```javascript
async function completeOrder(orderNumber, productIds) {
    const card = document.querySelector(`[data-order-number="${orderNumber}"]`);

    // Backup przed usunięciem
    const cardBackup = card.cloneNode(true);
    const checkboxStateBackup = getCheckedProductIds(card);

    // Optimistic UI - usuń kartę
    card.remove();
    clearCheckboxState(orderNumber);
    showToast('success', `Zamówienie ${orderNumber} ukończone`);

    try {
        const response = await fetch('/production/stations/complete-order', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                order_number: orderNumber,
                product_ids: productIds,
                station: 'cutting',
                action: 'complete'
            })
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        // Sukces - nie rób nic
        console.log('[Cutting] Order completed successfully');

    } catch (error) {
        // Błąd - przywróć kartę
        console.error('[Cutting] Failed to complete order:', error);

        const ordersList = document.getElementById('orders-list');
        ordersList.appendChild(cardBackup);

        // Przywróć stan checkboxów
        saveCheckboxState(orderNumber, checkboxStateBackup);
        restoreCheckboxes(cardBackup, checkboxStateBackup);

        showToast('error', `Błąd ukończenia: ${error.message}`);
    }
}
```

**Timeout handling:**
- Request timeout: 10 sekund
- Jeśli timeout → traktuj jak błąd, przywróć kartę

### 3.8 Smart merge podczas auto-refresh

**Problem:** Auto-refresh może nadpisać stan checkboxów

**Rozwiązanie:** Smart merge (wzór z packaging):
```javascript
function smartMergeOrders(newOrders) {
    const ordersList = document.getElementById('orders-list');
    const existingCards = ordersList.querySelectorAll('.order-card');

    // Zbuduj mapę istniejących kart
    const existingMap = new Map();
    existingCards.forEach(card => {
        const orderNumber = card.dataset.orderNumber;
        existingMap.set(orderNumber, card);
    });

    // Dla każdego nowego zamówienia
    newOrders.forEach(order => {
        const existing = existingMap.get(order.order_number);

        if (existing) {
            // Zamówienie już istnieje - zachowaj stan checkboxów
            const checkedIds = getCheckedProductIds(existing);

            // Usuń stare produkty które już nie istnieją
            const newProductIds = new Set(order.products.map(p => p.id));
            const filtered = checkedIds.filter(id => newProductIds.has(id));

            // Zapisz odfiltrowany stan
            saveCheckboxState(order.order_number, filtered);

            // Usuń z mapy (zostały te które nie są w nowym fetch)
            existingMap.delete(order.order_number);
        } else {
            // Nowe zamówienie - renderuj od zera
            const newCard = renderOrderCard(order);
            ordersList.appendChild(newCard);
            attachOrderCardListeners(newCard);
        }
    });

    // Usuń karty które zniknęły z backendu
    existingMap.forEach((card, orderNumber) => {
        card.remove();
        clearCheckboxState(orderNumber);
    });
}
```

---

## 4. Szczegóły implementacji

### 4.1 Pliki do modyfikacji

**Backend:**
1. `modules/production/routers/station_routers.py`
   - Nowe endpointy:
     - `/ajax/orders/cutting`
     - `/ajax/orders/assembly`
     - `/stations/complete-order` (POST)
   - Logika grupowania produktów po `internal_order_number`

**Frontend HTML:**
2. `modules/production/templates/stations/cutting.html`
   - Całkowita zmiana struktury z product-cards → order-cards
   - Dodanie checkboxów, product-list, order-header

3. `modules/production/templates/stations/assembly.html`
   - Analogiczne zmiany jak cutting.html

**Frontend CSS:**
4. `modules/production/static/css/stations/station-cutting.css`
   - Nowe style dla order-card, product-list, checkboxów
   - Wzorować na `station-packaging.css`

5. `modules/production/static/css/stations/station-assembly.css`
   - Analogiczne zmiany

**Frontend JavaScript:**
6. `modules/production/static/js/stations/station-cutting.js`
   - Całkowita refaktoryzacja logiki
   - Dodanie obsługi checkboxów, localStorage, bulk completion
   - Smart merge podczas refresh

7. `modules/production/static/js/stations/station-assembly.js`
   - Analogiczne zmiany

**Shared:**
8. `modules/production/static/css/stations/station-shared.css`
   - Dodanie shared styles dla order-card layout (jeśli jeszcze nie ma)
   - Ekstrahowanie wspólnych stylów z packaging

### 4.2 Podejście do CSS - DRY Principle

**Problem:** Pakowanie, wycinanie i montaż będą miały niemal identyczny layout

**Rozwiązanie - Shared styles:**

`station-shared.css` - dodajemy:
```css
/* ============================================================================
   ORDER-BASED LAYOUT - Shared for cutting, assembly, packaging
   ============================================================================ */

.orders-list {
    column-count: 2;
    column-gap: 24px;
}

@media (min-width: 1600px) {
    .orders-list {
        column-count: 3;
    }
}

@media (max-width: 1200px) {
    .orders-list {
        column-count: 1;
    }
}

.order-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    overflow: hidden;
    box-shadow: var(--shadow-sm);
    display: flex;
    flex-direction: column;
    break-inside: avoid;
    margin-bottom: 24px;
}

.order-header {
    padding: 16px 20px;
    background: var(--bg-header);
    border-bottom: 1px solid var(--border-color);
}

.order-title {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
}

.order-number {
    font-size: 18px;
    font-weight: bold;
    color: var(--accent-orange);
}

.order-baselinker {
    font-size: 14px;
    color: var(--accent-blue);
    font-family: 'Courier New', monospace;
}

.order-summary {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 14px;
    color: var(--text-secondary);
}

/* Products list inside order */
.products-list {
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-height: 600px;
    overflow-y: auto;
}

.product-row {
    display: grid;
    grid-template-columns: 40px 80px 1fr 100px;
    gap: 12px;
    align-items: center;
    padding: 12px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    transition: all var(--transition-fast);
}

.product-row:hover {
    background: var(--bg-secondary);
    transform: translateX(2px);
}

/* Checkbox */
.product-checkbox {
    display: flex;
    align-items: center;
    justify-content: center;
}

.product-check {
    width: 24px;
    height: 24px;
    cursor: pointer;
}

/* Product ID + attachment icon */
.product-id-wrapper {
    display: flex;
    align-items: center;
    gap: 6px;
}

.product-id {
    font-family: 'Courier New', monospace;
    font-weight: bold;
    color: var(--accent-orange);
    font-size: 14px;
}

/* Product details with badges + name */
.product-details {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.product-badges {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}

.product-badges .badge {
    font-size: 11px;
    padding: 4px 8px;
}

.product-name {
    font-size: 13px;
    color: var(--text-primary);
    line-height: 1.3;
}

.product-volume {
    font-family: 'Courier New', monospace;
    font-weight: bold;
    color: var(--text-primary);
    text-align: right;
}

/* Order action button */
.order-action {
    padding: 16px;
    border-top: 1px solid var(--border-color);
}

/* Responsive */
@media (max-width: 768px) {
    .product-row {
        grid-template-columns: 40px 60px 1fr 80px;
        gap: 8px;
        padding: 8px;
        font-size: 12px;
    }

    .product-badges .badge {
        font-size: 10px;
        padding: 2px 6px;
    }

    .order-header {
        padding: 12px 16px;
    }

    .order-number {
        font-size: 16px;
    }

    .products-list {
        max-height: 400px;
    }
}
```

**Station-specific CSS:** Tylko overrides jeśli potrzebne

### 4.3 Migracja stopniowa - Etapy

**Etap 1: Backend (1-2h)**
- Nowe endpointy `/ajax/orders/cutting`, `/ajax/orders/assembly`
- Endpoint `/stations/complete-order` (POST)
- Testy w Postman/curl

**Etap 2: Cutting Station (3-4h)**
- Modyfikacja `cutting.html` - nowa struktura
- Modyfikacja `station-cutting.css` - layout order-card
- Modyfikacja `station-cutting.js` - logika checkboxów
- Testy manualne

**Etap 3: Assembly Station (2-3h)**
- Analogiczne zmiany jak Cutting
- Copy-paste większości kodu z adjustments

**Etap 4: Testy integracyjne (1h)**
- Testy flow: cutting → assembly → packaging
- Testy auto-refresh z zachowaniem stanu
- Testy offline mode

**Total estimate: 7-10h**

---

## 5. Edge cases i rozważania

### 5.1 Co z produktami które nie są ready?

**Problem:** W pakowaniiproduct może być w statusie innym niż `czeka_na_pakowanie` (np. błąd, cofnięty status)

**Rozwiązanie:**
- Produkt renderujemy z klasą `.product-not-ready`
- Checkbox jest `disabled`
- Tooltip wyjaśnia powód (np. "Produkt nie jest jeszcze w montażu")

**CSS:**
```css
.product-row.product-not-ready {
    opacity: 0.5;
    pointer-events: none;
}

.product-not-ready .product-check {
    cursor: not-allowed;
}
```

### 5.2 Co jeśli podczas refresh zamówienie zniknęło?

**Scenario:** Pracownik A zaznaczył 10/14 produktów, ale pracownik B skończył pozostałe 4 na innym urządzeniu

**Rozwiązanie:** Smart merge usuwa kartę i czyści localStorage:
```javascript
existingMap.forEach((card, orderNumber) => {
    card.remove();
    clearCheckboxState(orderNumber);
});
```

### 5.3 Co jeśli nowe produkty pojawiły się w zamówieniu?

**Scenario:** Admin dodał ręcznie nowy produkt do zamówienia

**Rozwiązanie:**
- Smart merge NIE renderuje całej karty od nowa
- Zamiast tego doda nowy product-row na końcu listy
- Stan checkboxów zostaje zachowany dla istniejących produktów

**Alternatywa (prostsza):** Full re-render karty z przywróceniem stanu z localStorage

### 5.4 Limity wysokości product-list

**Problem:** Zamówienie z 50 produktami będzie bardzo wysokie

**Rozwiązanie:** Scroll w `.products-list`:
```css
.products-list {
    max-height: 600px;
    overflow-y: auto;
}
```

### 5.5 Sortowanie produktów w ramach zamówienia

**Opcje:**
1. Po `product_sequence_in_order` (kolejność z Baselinker) ✅ **PREFEROWANE**
2. Po `id` (chronologicznie)
3. Po priorytet

**Decyzja:** Sortujemy po `product_sequence_in_order` - naturalna kolejność

---

## 6. Metryki sukcesu

### 6.1 KPIs

| Metryka | Przed | Cel po wdrożeniu |
|---------|-------|------------------|
| Średni czas na ukończenie zamówienia 10-produktowego | ~2 min | ~1 min |
| Liczba błędów (pominięte produkty) | 5% | <1% |
| Satysfakcja pracowników (survey 1-10) | ? | >8/10 |
| Czas szkolenia nowego pracownika | ~30 min | ~10 min |

### 6.2 Testy akceptacyjne

**User Story 1:** Pracownik wycina zamówienie z 14 produktami
- ✅ Widzi jedną kartę z listą 14 produktów
- ✅ Zaznacza checkboxy w miarę postępu
- ✅ Po zaznaczeniu wszystkich, przycisk staje się aktywny
- ✅ Klika raz "ZAKOŃCZ WYCIĘCIE" i wszystkie produkty przechodzą do montażu

**User Story 2:** Auto-refresh podczas pracy
- ✅ Pracownik zaznaczył 7/14 produktów
- ✅ Następuje auto-refresh (30s)
- ✅ Checkboxy pozostają zaznaczone
- ✅ Nowe produkty (jeśli były dodane) pojawiają się na liście

**User Story 3:** Produkt z załącznikiem
- ✅ Pracownik widzi ikonę spinacza przy ID produktu
- ✅ Po najechaniu myszką widzi podgląd PDF (tooltip)
- ✅ Po kliknięciu otwiera się modal pełnoekranowy

---

## 7. Decyzje projektowe ✅ ZATWIERDZONE

### 7.1 Layout - ✅ Masonry (column-count)

**WYBRANA OPCJA: Masonry CSS z column-count**
```css
.orders-list {
    column-count: 2;
    column-gap: 24px;
}

.order-card {
    break-inside: avoid;
    margin-bottom: 24px;
}

@media (min-width: 1600px) {
    .orders-list { column-count: 3; }
}
@media (max-width: 1200px) {
    .orders-list { column-count: 1; }
}
```

**Uzasadnienie:**
✅ Brak pustych przestrzeni - karty wypełniają wysokość równomiernie
✅ Elastyczny layout dla różnych wysokości (2 vs 14 produktów)
✅ Proste w implementacji - native CSS
✅ Dobra wydajność

### 7.2 JavaScript - ✅ Wspólny + dedykowane pliki

**WYBRANA OPCJA: Zachowanie obecnej struktury**
- `station-common.js` - funkcje współdzielone (już istnieje)
- `station-cutting.js` - dedykowana logika dla cutting
- `station-assembly.js` - dedykowana logika dla assembly
- `station-packaging.js` - dedykowana logika dla packaging (już istnieje)

**Uzasadnienie:**
✅ Clear separation of concerns
✅ Łatwe debugowanie - wiadomo gdzie szukać
✅ Możliwość specyficznych customizacji per stanowisko
✅ Zgodne z obecną architekturą

### 7.3 Status produktów - ✅ TYLKO dla pakowania

**DECYZJA:**
- **Cutting i Assembly:** Wszystkie produkty w zamówieniu muszą być zakończone razem. NIE pokazujemy statusów produktów. Checkboxy są zawsze aktywne.
- **Packaging:** Może mieć produkty not-ready (np. w montażu). Checkbox disabled + tooltip wyjaśnia dlaczego.

**Implementacja:**
```javascript
// Cutting/Assembly - wszystkie checkboxy aktywne
<input type="checkbox" class="product-check" id="check-342">

// Packaging - checkbox może być disabled
<input type="checkbox"
       class="product-check"
       id="check-342"
       {% if product.current_status != 'czeka_na_pakowanie' %}disabled{% endif %}>
```

**Uzasadnienie:**
- Cutting: Pracownik wycina wszystkie elementy z jednego drewna → logiczne zakończenie całego zamówienia naraz
- Assembly: Pracownik montuje wszystkie produkty z zamówienia → analogicznie
- Packaging: Produkty przychodzą stopniowo z montażu → potrzebny mechanizm disabled checkboxów

### 7.4 Bulk completion - ✅ Transakcyjne (All-or-nothing)

**WYBRANA OPCJA: Transakcyjne**
```python
try:
    for product_id in product_ids:
        product = ProductionProduct.query.get(product_id)
        product.current_status = next_status
        product.cutting_completed_at = datetime.now()

    db.session.commit()  # Wszystko naraz

    return {'success': True, 'completed_count': len(product_ids)}
except Exception as e:
    db.session.rollback()  # Cofnij wszystko
    return {'success': False, 'error': str(e)}
```

**Uzasadnienie:**
✅ Prostsze w implementacji
✅ Bardziej przewidywalne zachowanie
✅ Łatwiejsze debugowanie
✅ Zgodne z zasadą ACID dla transakcji bazodanowych

**Alternatywny scenariusz (rzadki):**
Jeśli wystąpi błąd (np. usunięty produkt), pracownik zobaczy komunikat błędu i musi:
1. Odświeżyć stronę (auto-refresh po 30s lub F5)
2. Sprawdzić co się stało (produkt usunięty? status zmieniony?)
3. Zaznaczyć checkboxy ponownie i spróbować jeszcze raz

---

## 8. Ryzyka i mitigation

### 8.1 Ryzyko: Regresja w performance

**Opis:** Zamówienia z 50+ produktami mogą obciążać render

**Mitigation:**
- Wirtualizacja listy produktów (opcjonalnie, tylko jeśli problem)
- Limit max-height + scroll
- Debouncing checkbox events

### 8.2 Ryzyko: Utrata danych w localStorage

**Opis:** Użytkownik czyści cookies/localStorage → traci stan checkboxów

**Mitigation:**
- Dodać backup stanu w backend (opcjonalnie)
- Lub komunikat: "Stan checkboxów jest przechowywany lokalnie. Nie czyść danych przeglądarki podczas pracy."

### 8.3 Ryzyko: Confusing UX przy disabled checkboxach

**Opis:** Użytkownik nie wie dlaczego checkbox jest disabled

**Mitigation:**
- Tooltip z wyjaśnieniem (np. "Produkt nie jest jeszcze gotowy")
- Wizualne oznaczenie (opacity 0.5, strikethrough name)

---

## 9. Rollout plan

### 9.1 Faza 1: Development (Week 1)
- Backend endpoints
- Cutting station refactor
- Assembly station refactor
- Unit tests

### 9.2 Faza 2: Testing (Week 2)
- QA testing
- User acceptance testing (2 pracowników)
- Bug fixes

### 9.3 Faza 3: Deployment (Week 2)
- Deploy na staging
- Szkolenie pracowników (15 min demo)
- Deploy na production
- Monitoring przez pierwszy tydzień

### 9.4 Faza 4: Evaluation (Week 3-4)
- Zbieranie feedbacku
- Analiza metryk
- Iteracje na podstawie feedbacku

---

## 10. Alternatywne podejścia (odrzucone)

### 10.1 Hybrid: Zachować product-cards + dodać grouping

**Opis:** Dodać header "Zamówienie 241118/2" nad grupą kart produktów

**Pros:** Mniej zmian, mniejsze ryzyko
**Cons:** Nadal wymaga wielokrotnych kliknięć, brak pełnego kontekstu

**Powód odrzucenia:** Nie rozwiązuje głównego problemu (wielokrotne kliknięcia)

### 10.2 "Select all" button zamiast checkboxów

**Opis:** Przycisk "Zaznacz wszystkie" na karcie zamówienia

**Pros:** Szybkie zaznaczanie
**Cons:** Brak elastyczności (co jeśli 1 produkt nie jest ready?)

**Powód odrzucenia:** Checkboxy dają pełną kontrolę i wizualny feedback

---

## 11. Appendix: Wireframes

### 11.1 Order Card - Desktop

```
┌─────────────────────────────────────────────────────────────┐
│ ORDER HEADER                                                 │
│ 241118/2  BL-123456                                         │
│ 📅 23.01.2025              2/14 produktów • 0.2345 m³       │
├─────────────────────────────────────────────────────────────┤
│ PRODUCTS LIST (scrollable)                                   │
│                                                              │
│ ┌─────────────────────────────────────────────────────────┐│
│ │ [✓] 342 📎 [BUK] [LITE] [A/B] [120×40×2]  0.0096 m³   ││
│ │           Buk Lite 120x40x2                             ││
│ └─────────────────────────────────────────────────────────┘│
│ ┌─────────────────────────────────────────────────────────┐│
│ │ [✓] 343 📎 [BUK] [LITE] [A/B] [120×40×2]  0.0096 m³   ││
│ │           Buk Lite 120x40x2                             ││
│ └─────────────────────────────────────────────────────────┘│
│ ┌─────────────────────────────────────────────────────────┐│
│ │ [ ] 344    [BUK] [LITE] [A/B] [120×40×2]  0.0096 m³   ││
│ │           Buk Lite 120x40x2                             ││
│ └─────────────────────────────────────────────────────────┘│
│ ... (11 more products)                                      │
├─────────────────────────────────────────────────────────────┤
│ ORDER ACTION                                                 │
│ [ ZAKOŃCZ WYCIĘCIE ] (disabled until all checked)          │
└─────────────────────────────────────────────────────────────┘
```

### 11.2 Product Row - Expanded View

```
┌───────────────────────────────────────────────────────────────┐
│ [✓]  342 📎    [BUK] [LITE] [A/B] [120×40×2]    0.0096 m³   │
│               Buk Lite 120x40x2 - powierzchnia gładka         │
└───────────────────────────────────────────────────────────────┘
 ↑    ↑   ↑     └──── Badges ────────┘           ↑
checkbox ID attach   └── Product Name ──┘        volume
```

### 11.3 Layout - 2 kolumny (Desktop)

```
┌─────────────────────┬─────────────────────┐
│ Order Card #1       │ Order Card #2       │
│ (2 products)        │ (14 products)       │
│                     │                     │
│                     │                     │
│                     │                     │
│                     │                     │
│                     │                     │
│                     │                     │
│                     │                     │
├─────────────────────┼─────────────────────┤
│ Order Card #3       │ Order Card #4       │
│ (5 products)        │ (3 products)        │
│                     │                     │
│                     │                     │
└─────────────────────┴─────────────────────┘
```

---

## 12. Checklist do zatwierdzenia

Przed rozpoczęciem implementacji, upewnij się że:

- [x] PRD został przeczytany i zrozumiany przez wszystkich stakeholders
- [x] Decyzje z sekcji 7 zostały podjęte i zatwierdzone
  - [x] Layout: Masonry (column-count)
  - [x] JavaScript: Wspólny + dedykowane pliki
  - [x] Status produktów: TYLKO dla pakowania
  - [x] Bulk completion: Transakcyjne
- [ ] Backend team potwierdza feasibility nowych endpointów
- [ ] Frontend team potwierdza feasibility zmian UI
- [ ] Pracownicy stanowisk zostali poinformowani o nadchodzącej zmianie
- [ ] Zaplanowano czas na testy użytkownika (UAT)
- [ ] Mamy plan rollback w razie krytycznych problemów

---

## 13. Podsumowanie decyzji ✅

### Kluczowe ustalenia:

1. **Layout:** Masonry CSS (column-count: 2/3) - brak pustych przestrzeni
2. **JavaScript:** Zachowanie struktury: common + dedykowane pliki per stanowisko
3. **Status produktów:**
   - Cutting/Assembly: wszystkie checkboxy aktywne (bulk completion całego zamówienia)
   - Packaging: checkboxy mogą być disabled (produkty not-ready)
4. **Bulk completion:** Transakcyjne (all-or-nothing) - rollback w razie błędu
5. **Sortowanie produktów:** Po `product_sequence_in_order` (kolejność z Baselinker)
6. **localStorage:** Stan checkboxów zapisywany per zamówienie (`cutting_order_<number>`)
7. **Badges:** Gatunek, technologia, klasa, wymiary - widoczne przy każdym produkcie
8. **Załączniki:** Ikona + tooltip + modal pełnoekranowy (już zaimplementowane)
9. **Tracking czasu:** NIE trackujemy `started_at`, `assigned_worker_id`, `duration` dla cutting/assembly (atomic process)
10. **UX po ukończeniu:** Optimistic UI - karta znika natychmiast, w razie błędu przywracamy z backupu
11. **Timeout:** 10 sekund na request bulk completion

### Estymacja czasu:
- **Backend:** 1-2h (endpointy + grupowanie)
- **Cutting:** 3-4h (HTML + CSS + JS)
- **Assembly:** 2-3h (copy-paste z Cutting + adjustments)
- **Testy:** 1h
- **TOTAL:** 7-10h

### Następne kroki:
1. ✅ PRD zatwierdzony - gotowe do implementacji
2. Rozpoczęcie od Backend (endpointy)
3. Następnie Cutting Station (pełna implementacja)
4. Potem Assembly Station (na bazie Cutting)
5. Testy integracyjne i UAT

---

**Kontakt:** Konrad Kmiecik
**Data zatwierdzenia:** 2025-01-24
**Status:** ✅ ZATWIERDZONY - Gotowy do implementacji
