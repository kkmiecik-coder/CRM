# Products Tab Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the products tab from flat per-product list to grouped per-order view with expandable product rows, in Industrial Light theme.

**Architecture:** Frontend-only grouping — the API still returns flat products, JS groups them by `internal_order_number`/`baselinker_order_id` into order objects. New HTML template renders order cards with expandable product rows. CSS rewritten from scratch in IL style. Existing modals (product details, bulk actions, baselinker compare) kept but restyled.

**Tech Stack:** Jinja2 templates, CSS (IL theme), vanilla JS (ProductsModule class rewrite), existing Flask API (no backend changes needed)

**Spec:** `docs/superpowers/specs/2026-03-26-products-tab-redesign.md`
**Visual Mockup:** `.superpowers/brainstorm/1400-1774526399/content/products-tab-mockup.html`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `modules/production/static/css/products-tab.css` | Rewrite | Full IL theme for products tab |
| `modules/production/templates/components/products-tab-content.html` | Rewrite | Order-grouped template with stats, filters, order cards, product rows, modals |
| `modules/production/static/js/modules/products-module.js` | Major modify | Add order grouping, new rendering, adapted filtering/sorting/selection |

No backend changes — API already returns all needed fields including `internal_order_number`, `baselinker_order_id`, `client_order_number`, `client_name`.

---

## Task 1: Rewrite Products Tab CSS — Industrial Light Theme

**Files:**
- Rewrite: `modules/production/static/css/products-tab.css`

- [ ] **Step 1: Replace entire CSS file**

Replace the full 4009-line `products-tab.css` with new IL-themed CSS. The file should contain:

1. **CSS Variables** — IL palette (same as dashboard: `--il-bg-base: #eef0f4`, etc.), plus product-specific status colors matching spec
2. **Stats bar** — `.il-stats-bar` flex row, `.il-stat-card` inline label+value
3. **Filters** — `.il-filters-bar`, `.il-filter-search`, `.il-filter-dropdown`, `.il-filter-badge`, `.il-active-filters`
4. **Column headers** — `.il-orders-header` with grid: `20px 24px 24px 20px 2fr 55px 80px 100px 120px 120px 130px`
5. **Order card** — `.il-order-card`, `.il-order-header` (same grid as headers), `.il-order-expand`, status left borders per station color using `data-station` attribute
6. **Product row** — `.il-product-row` (indented, light bg), spec tags, no status badge
7. **Bulk actions** — `.il-bulk-bar` fixed bottom
8. **Order action buttons** — `.il-order-action-btn`
9. **Star, checkbox, drag handle** styles
10. **Status badges** — all 10 statuses from spec (cutting through anulowane + mixed)
11. **Deadline urgency** — overdue (red), urgent (amber), normal (gray)
12. **Responsive** — 1200px, 900px, 600px breakpoints
13. **Multi-select dropdown** — `.il-multiselect` with search, options, open/close
14. **Modals** — IL-styled modals (product details, bulk actions)

Use the mockup HTML file as reference for exact classes and structure. Font: JetBrains Mono. Sizes: 1.5x of base mockup values (matching dashboard).

All classes prefixed with `il-` to avoid conflicts with old styles during transition.

- [ ] **Step 2: Commit**

```bash
git add modules/production/static/css/products-tab.css
git commit -m "feat(production): rewrite products-tab CSS in Industrial Light theme"
```

---

## Task 2: Rewrite Products Tab HTML Template

**Files:**
- Rewrite: `modules/production/templates/components/products-tab-content.html`

- [ ] **Step 1: Replace entire template**

The new template structure:

```
#products-module-container
├── Stats Bar (.il-stats-bar)
│   ├── Zamówienia (#il-stats-orders)
│   ├── Produkty (#il-stats-products)
│   ├── Objętość (#il-stats-volume)
│   ├── Wartość netto (#il-stats-value)
│   └── Pilne (#il-stats-urgent)
│
├── Filters (.il-filters-bar)
│   ├── Search input (#il-products-search)
│   ├── 5 multi-select dropdowns (same IDs as old: #filter-wood-species, etc.)
│   └── Active filters container (#il-active-filters)
│
├── Column Headers (.il-orders-header)
│   └── Grid: [drag] [checkbox (#il-select-all)] [star] [expand] [Klient/Zamówienie] [Pozycje] [Objętość] [Wartość netto] [Status] [Termin] [Akcje]
│
├── Orders List (#il-orders-list)
│   ├── Loading state (#il-products-loading)
│   ├── Empty state (#il-products-empty)
│   ├── Error state (#il-products-error)
│   └── Orders rendered here by JS
│
├── Bulk Actions Bar (#il-bulk-bar, hidden)
│   ├── Selection count
│   ├── Zmień status button
│   ├── Eksport button
│   └── Usuń button
│
├── Templates (hidden, used by JS cloneNode)
│   ├── #il-order-template — order card with header grid + products container
│   ├── #il-product-template — product row
│   ├── #il-filter-badge-template — active filter badge
│   └── Keep existing modal templates (product details, bulk actions, baselinker compare)
│
└── Modals (keep existing, restyle classes)
```

**Order template (`#il-order-template`):**
```html
<template id="il-order-template">
  <div class="il-order-card">
    <div class="il-order-header">
      <span class="il-drag-handle"><i class="fas fa-grip-vertical"></i></span>
      <input type="checkbox" class="il-order-checkbox">
      <span class="il-star-btn"><i class="far fa-star"></i></span>
      <span class="il-order-expand">▶</span>
      <div class="il-order-info">
        <span class="il-order-client"></span>
        <div class="il-order-ids"></div>
      </div>
      <span class="il-order-cell il-order-positions"></span>
      <span class="il-order-cell il-order-volume"></span>
      <span class="il-order-cell il-order-value"></span>
      <span class="il-order-status-badge"></span>
      <span class="il-order-deadline"></span>
      <div class="il-order-actions">
        <button class="il-order-action-btn" data-action="attachment"><i class="fas fa-paperclip"></i></button>
        <button class="il-order-action-btn" data-action="comment"><i class="fas fa-comment"></i></button>
        <button class="il-order-action-btn" data-action="details"><i class="fas fa-eye"></i></button>
        <button class="il-order-action-btn" data-action="baselinker"><i class="fas fa-external-link-alt"></i></button>
      </div>
    </div>
    <div class="il-order-products collapsed"></div>
  </div>
</template>
```

**Product template (`#il-product-template`):**
```html
<template id="il-product-template">
  <div class="il-product-row">
    <input type="checkbox" class="il-product-checkbox">
    <div class="il-product-name">
      <div class="il-product-name-text"></div>
      <div class="il-product-name-id"></div>
    </div>
    <div class="il-product-spec"></div>
    <span class="il-product-qty"></span>
    <span class="il-product-volume"></span>
  </div>
</template>
```

**Important:** Keep all existing modal templates at the bottom of the file:
- `#product-details-modal-template` (product details modal — lines 558-836 in old file)
- `#bulk-actions-modal-template` (bulk actions modal — lines 446-556 in old file)
- `#baselinker-compare-modal` (baselinker compare — lines 838-931 in old file)

These modals are complex and functional — don't rewrite their HTML, only update CSS classes where needed.

- [ ] **Step 2: Verify template renders**

Run the app and switch to "Lista produktów" tab. The tab should load without Jinja2 errors (content will be unstyled/empty since JS isn't updated yet).

- [ ] **Step 3: Commit**

```bash
git add modules/production/templates/components/products-tab-content.html
git commit -m "feat(production): rewrite products tab template with order-grouped layout"
```

---

## Task 3: Add Order Grouping Logic to ProductsModule

**Files:**
- Modify: `modules/production/static/js/modules/products-module.js`

This is the biggest task — adding order grouping and new rendering while preserving existing functionality.

- [ ] **Step 1: Add order grouping method**

Add a new method `groupProductsIntoOrders(products)` that takes the flat products array and returns an array of order objects:

```javascript
groupProductsIntoOrders(products) {
    const ordersMap = new Map();

    products.forEach(product => {
        const orderKey = product.internal_order_number || product.baselinker_order_id || `single-${product.id}`;

        if (!ordersMap.has(orderKey)) {
            ordersMap.set(orderKey, {
                orderKey: orderKey,
                clientName: product.client_name || 'Brak danych',
                baselinkerOrderId: product.baselinker_order_id,
                clientOrderNumber: product.client_order_number,
                internalOrderNumber: product.internal_order_number,
                products: [],
                totalVolume: 0,
                totalValue: 0,
                productCount: 0,
                status: null,
                deadline: null,
                isPriority: false,
                productionNotes: product.production_notes || '',
                attachmentUrl: null
            });
        }

        const order = ordersMap.get(orderKey);
        order.products.push(product);
        order.productCount++;
        order.totalVolume += (parseFloat(product.volume_m3) || 0) * (product.quantity || 1);
        order.totalValue += parseFloat(product.total_value_net) || 0;

        if (product.is_priority) order.isPriority = true;
        if (product.attachment_file_url) order.attachmentUrl = product.attachment_file_url;

        // Earliest deadline
        if (product.deadline_date) {
            if (!order.deadline || product.deadline_date < order.deadline) {
                order.deadline = product.deadline_date;
            }
        }
    });

    // Calculate order-level status
    ordersMap.forEach(order => {
        const statuses = [...new Set(order.products.map(p => p.current_status))];
        if (statuses.length === 1) {
            order.status = statuses[0];
            order.statusLabel = this.getStatusDisplayName(statuses[0]);
        } else {
            const completedCount = order.products.filter(p => p.current_status === 'spakowane').length;
            order.status = 'mixed';
            order.statusLabel = `Różne (${completedCount}/${order.productCount})`;
        }

        // Round totals
        order.totalVolume = Math.round(order.totalVolume * 1000) / 1000;
        order.totalValue = Math.round(order.totalValue * 100) / 100;
    });

    return Array.from(ordersMap.values());
}
```

- [ ] **Step 2: Add order state to constructor**

In the constructor's `this.state` block (around line 101), add:

```javascript
orders: [],           // Grouped orders
filteredOrders: [],   // After filtering
expandedOrders: new Set(),  // Track which orders are expanded
```

- [ ] **Step 3: Update `renderProductsList()` to render orders**

Replace the existing `renderProductsList()` method (line 1237) with a new `renderOrdersList()`:

```javascript
renderOrdersList() {
    const container = document.getElementById('il-orders-list');
    if (!container) return;

    // Clear existing content (keep loading/empty/error states)
    container.querySelectorAll('.il-order-card').forEach(el => el.remove());

    if (this.state.filteredOrders.length === 0) {
        this.showEmptyState();
        return;
    }

    this.hideEmptyState();

    const fragment = document.createDocumentFragment();

    this.state.filteredOrders.forEach(order => {
        const orderElement = this.createOrderCard(order);
        fragment.appendChild(orderElement);
    });

    container.appendChild(fragment);
    this.updateProductsCount();
    this.syncAllCheckboxes();
}
```

- [ ] **Step 4: Add `createOrderCard()` method**

```javascript
createOrderCard(order) {
    const template = document.getElementById('il-order-template');
    const clone = template.content.cloneNode(true);
    const card = clone.querySelector('.il-order-card');

    card.setAttribute('data-order-key', order.orderKey);

    // Populate header
    const header = card.querySelector('.il-order-header');
    this.populateOrderHeader(header, order);

    // Populate products
    const productsContainer = card.querySelector('.il-order-products');
    order.products.forEach(product => {
        const productRow = this.createProductRow(product);
        productsContainer.appendChild(productRow);
    });

    // Expand/collapse state
    if (this.state.expandedOrders.has(order.orderKey)) {
        productsContainer.classList.remove('collapsed');
        header.classList.add('expanded');
        header.querySelector('.il-order-expand').classList.add('open');
    }

    // Attach event listeners
    this.attachOrderEventListeners(card, order);

    return card;
}
```

- [ ] **Step 5: Add `populateOrderHeader()` method**

```javascript
populateOrderHeader(header, order) {
    // Status left border
    const stationClass = this.getStationClassFromStatus(order.status);
    header.classList.add(stationClass);

    // Star
    const star = header.querySelector('.il-star-btn');
    if (order.isPriority) {
        star.classList.add('active');
        star.querySelector('i').className = 'fas fa-star';
    }

    // Client info
    header.querySelector('.il-order-client').textContent = order.clientName;
    const idsContainer = header.querySelector('.il-order-ids');
    if (order.baselinkerOrderId) {
        idsContainer.innerHTML += `<span class="il-order-id-tag">BL-${order.baselinkerOrderId}</span>`;
    }
    if (order.clientOrderNumber) {
        idsContainer.innerHTML += `<span class="il-order-id-tag">${order.clientOrderNumber}</span>`;
    }

    // Metrics
    header.querySelector('.il-order-positions').textContent = order.productCount;
    header.querySelector('.il-order-volume').textContent = `${order.totalVolume.toFixed(3)} m³`;
    header.querySelector('.il-order-value').textContent = `${order.totalValue.toLocaleString('pl-PL')} zł`;

    // Status badge
    const badge = header.querySelector('.il-order-status-badge');
    badge.textContent = order.statusLabel;
    badge.className = `il-order-status-badge ${this.getStatusBadgeClass(order.status)}`;

    // Deadline
    const deadlineEl = header.querySelector('.il-order-deadline');
    if (order.deadline) {
        const days = this.calculateDaysUntilDeadline(order.deadline);
        const dateStr = new Date(order.deadline).toLocaleDateString('pl-PL', {day: '2-digit', month: '2-digit'});
        deadlineEl.textContent = `${days < 0 ? days : days} ${Math.abs(days) === 1 ? 'dzień' : 'dni'} (${dateStr})`;
        deadlineEl.className = `il-order-deadline ${days < 0 ? 'deadline-overdue' : days <= 1 ? 'deadline-urgent' : 'deadline-normal'}`;
    } else {
        deadlineEl.textContent = '—';
        deadlineEl.className = 'il-order-deadline deadline-normal';
    }
}
```

- [ ] **Step 6: Add `createProductRow()` for new template**

Replace existing `createProductRow()` with one that uses the new `#il-product-template`:

```javascript
createProductRow(product) {
    const template = document.getElementById('il-product-template');
    const clone = template.content.cloneNode(true);
    const row = clone.querySelector('.il-product-row');

    row.setAttribute('data-product-id', product.id || product.unique_id);

    // Dimmed state for filtered products
    if (product._dimmed) {
        row.classList.add('il-product-dimmed');
    }

    // Checkbox
    const checkbox = row.querySelector('.il-product-checkbox');
    checkbox.checked = this.state.selectedProducts.has(product.unique_id || String(product.id));

    // Name
    row.querySelector('.il-product-name-text').textContent = product.original_product_name || '—';
    row.querySelector('.il-product-name-id').textContent = product.short_product_id || '';

    // Spec tags
    const specContainer = row.querySelector('.il-product-spec');
    const specs = [
        product.parsed_wood_species,
        product.parsed_technology,
        product.parsed_wood_class,
        product.parsed_thickness_cm ? `${product.parsed_thickness_cm}mm` : null
    ].filter(Boolean);
    specContainer.innerHTML = specs.map(s => `<span class="il-product-spec-tag">${s}</span>`).join('');

    // Quantity
    row.querySelector('.il-product-qty').textContent = `${product.quantity || 1} szt.`;

    // Volume
    const vol = ((product.volume_m3 || 0) * (product.quantity || 1)).toFixed(4);
    row.querySelector('.il-product-volume').textContent = `${vol} m³`;

    return row;
}
```

- [ ] **Step 7: Add `attachOrderEventListeners()` method**

```javascript
attachOrderEventListeners(card, order) {
    const header = card.querySelector('.il-order-header');
    const productsContainer = card.querySelector('.il-order-products');

    // Expand/collapse on header click
    header.addEventListener('click', (e) => {
        if (e.target.closest('.il-order-checkbox') ||
            e.target.closest('.il-star-btn') ||
            e.target.closest('.il-order-actions') ||
            e.target.closest('.il-drag-handle')) return;

        const isExpanded = this.state.expandedOrders.has(order.orderKey);
        if (isExpanded) {
            this.state.expandedOrders.delete(order.orderKey);
            productsContainer.classList.add('collapsed');
            header.classList.remove('expanded');
            header.querySelector('.il-order-expand').classList.remove('open');
        } else {
            this.state.expandedOrders.add(order.orderKey);
            productsContainer.classList.remove('collapsed');
            header.classList.add('expanded');
            header.querySelector('.il-order-expand').classList.add('open');
        }
    });

    // Order checkbox — selects all products in order
    const orderCheckbox = header.querySelector('.il-order-checkbox');
    orderCheckbox.addEventListener('change', (e) => {
        e.stopPropagation();
        order.products.forEach(p => {
            const id = p.unique_id || String(p.id);
            if (orderCheckbox.checked) {
                this.state.selectedProducts.add(id);
            } else {
                this.state.selectedProducts.delete(id);
            }
        });
        // Sync product checkboxes in this card
        card.querySelectorAll('.il-product-checkbox').forEach((cb, i) => {
            cb.checked = orderCheckbox.checked;
        });
        this.toggleBulkActionsVisibility();
    });

    // Product checkboxes
    card.querySelectorAll('.il-product-checkbox').forEach((cb, i) => {
        cb.addEventListener('change', () => {
            const product = order.products[i];
            const id = product.unique_id || String(product.id);
            if (cb.checked) {
                this.state.selectedProducts.add(id);
            } else {
                this.state.selectedProducts.delete(id);
            }
            // Update order checkbox
            const allChecked = order.products.every(p =>
                this.state.selectedProducts.has(p.unique_id || String(p.id)));
            orderCheckbox.checked = allChecked;
            this.toggleBulkActionsVisibility();
        });
    });

    // Star button
    header.querySelector('.il-star-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        this.handleStarClick(order);
    });

    // Action buttons
    header.querySelectorAll('.il-order-action-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const action = btn.getAttribute('data-action');
            switch(action) {
                case 'details':
                    this.showProductDetails(order.products[0].id || order.products[0].unique_id);
                    break;
                case 'baselinker':
                    if (order.baselinkerOrderId) {
                        window.open(`https://panel.baselinker.com/orders/order/${order.baselinkerOrderId}`, '_blank');
                    }
                    break;
                case 'attachment':
                    this.showAttachment(order);
                    break;
                case 'comment':
                    this.showCommentTooltip(btn, order);
                    break;
            }
        });
    });

    // Drag handle
    const dragHandle = header.querySelector('.il-drag-handle');
    if (dragHandle) {
        card.setAttribute('draggable', 'true');
        card.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('text/plain', order.orderKey);
            card.classList.add('dragging');
        });
        card.addEventListener('dragend', () => {
            card.classList.remove('dragging');
        });
    }
}
```

- [ ] **Step 8: Add helper methods for comment tooltip and attachment**

```javascript
showCommentTooltip(btn, order) {
    // Remove existing tooltips
    document.querySelectorAll('.il-comment-tooltip').forEach(el => el.remove());

    if (!order.productionNotes) {
        // Show "Brak notatek" tooltip briefly
        const tooltip = document.createElement('div');
        tooltip.className = 'il-comment-tooltip';
        tooltip.textContent = 'Brak notatek';
        btn.style.position = 'relative';
        btn.appendChild(tooltip);
        setTimeout(() => tooltip.remove(), 2000);
        return;
    }

    const tooltip = document.createElement('div');
    tooltip.className = 'il-comment-tooltip';
    tooltip.textContent = order.productionNotes;
    btn.style.position = 'relative';
    btn.appendChild(tooltip);

    // Close on click outside
    const closeHandler = (e) => {
        if (!tooltip.contains(e.target)) {
            tooltip.remove();
            document.removeEventListener('click', closeHandler);
        }
    };
    setTimeout(() => document.addEventListener('click', closeHandler), 10);
}

showAttachment(order) {
    if (order.attachmentUrl) {
        // Use existing attachment modal if available
        if (typeof window.openAttachmentModalAdmin === 'function') {
            window.openAttachmentModalAdmin(order.attachmentUrl);
        } else {
            window.open(order.attachmentUrl, '_blank');
        }
    }
}
```

- [ ] **Step 9: Add status-to-station mapping helpers**

```javascript
getStationClassFromStatus(status) {
    const map = {
        'czeka_na_wyciecie': 'status-cutting',
        'czeka_na_skladanie': 'status-assembly',
        'czeka_na_sklejanie': 'status-gluing',
        'czeka_na_formatowanie': 'status-formatting',
        'czeka_na_wykanczanie': 'status-finishing',
        'czeka_na_pakowanie': 'status-packaging',
        'spakowane': 'status-completed',
        'w_realizacji': 'status-inprogress',
        'wstrzymane': 'status-paused',
        'anulowane': 'status-cancelled',
        'mixed': 'status-mixed'
    };
    return map[status] || 'status-completed';
}

getStatusBadgeClass(status) {
    const map = {
        'czeka_na_wyciecie': 'badge-cutting',
        'czeka_na_skladanie': 'badge-assembly',
        'czeka_na_sklejanie': 'badge-gluing',
        'czeka_na_formatowanie': 'badge-formatting',
        'czeka_na_wykanczanie': 'badge-finishing',
        'czeka_na_pakowanie': 'badge-packaging',
        'spakowane': 'badge-completed',
        'w_realizacji': 'badge-assembly',
        'wstrzymane': 'badge-paused',
        'anulowane': 'badge-cancelled',
        'mixed': 'badge-mixed'
    };
    return map[status] || 'badge-completed';
}
```

- [ ] **Step 10: Update `applyAllFilters()` to work with orders**

Modify the filtering pipeline:

```javascript
applyAllFilters() {
    // Step 1: Group ALL products into orders first
    const allOrders = this.groupProductsIntoOrders(this.state.products);

    // Step 2: Determine which products match filters
    let matchingProductIds = new Set();
    let productsToCheck = [...this.state.products];

    const textSearch = this.state.currentFilters.textSearch?.trim();
    if (textSearch && this.components.fuzzySearchEngine) {
        productsToCheck = this.components.fuzzySearchEngine.search(textSearch, productsToCheck, {
            fields: ['original_product_name', 'short_product_id', 'client_name', 'baselinker_order_id', 'client_order_number'],
            threshold: 2
        });
    }
    productsToCheck = this.applyMultiSelectFilters(productsToCheck);
    productsToCheck.forEach(p => matchingProductIds.add(p.unique_id || String(p.id)));

    // Step 3: Filter orders — show order if ANY product matches
    // Mark non-matching products with _dimmed flag for CSS dimming
    const hasFilters = this.hasActiveFilters();
    this.state.filteredOrders = allOrders.filter(order => {
        const hasMatch = order.products.some(p => matchingProductIds.has(p.unique_id || String(p.id)));
        if (!hasMatch && hasFilters) return false;

        // Mark products for dimming
        order.products.forEach(p => {
            p._dimmed = hasFilters && !matchingProductIds.has(p.unique_id || String(p.id));
        });
        return true;
    });

    // Step 4: Filtered products for stats = only matching products
    this.state.filteredProducts = productsToCheck;

    this.sortOrders();
    this.updateFilterBadges();
    this.updateStats();
    this.renderOrdersList();
}
```

- [ ] **Step 11: Add `sortOrders()` method**

```javascript
sortOrders() {
    const col = this.state.sortColumn;
    const dir = this.state.sortDirection === 'asc' ? 1 : -1;

    if (!col) {
        // Default: sort by deadline (most urgent first)
        this.state.filteredOrders.sort((a, b) => {
            if (!a.deadline) return 1;
            if (!b.deadline) return -1;
            return a.deadline.localeCompare(b.deadline);
        });
        return;
    }

    this.state.filteredOrders.sort((a, b) => {
        let valA, valB;
        switch(col) {
            case 'client': valA = a.clientName; valB = b.clientName; break;
            case 'positions': valA = a.productCount; valB = b.productCount; break;
            case 'volume': valA = a.totalVolume; valB = b.totalVolume; break;
            case 'value': valA = a.totalValue; valB = b.totalValue; break;
            case 'status':
                valA = a.statusLabel; valB = b.statusLabel; break;
            case 'deadline':
                valA = a.deadline || 'z'; valB = b.deadline || 'z'; break;
            default: return 0;
        }
        if (typeof valA === 'string') return valA.localeCompare(valB) * dir;
        return (valA - valB) * dir;
    });
}
```

- [ ] **Step 12: Update `updateStats()` for order-aware stats**

```javascript
updateStats() {
    const products = this.state.filteredProducts;
    const orders = this.state.filteredOrders;

    this.state.stats = {
        orderCount: orders.length,
        totalCount: products.length,
        filteredCount: products.length,
        totalVolume: orders.reduce((sum, o) => sum + o.totalVolume, 0),
        totalValue: orders.reduce((sum, o) => sum + o.totalValue, 0),
        urgentCount: orders.filter(o => {
            if (!o.deadline) return false;
            return this.calculateDaysUntilDeadline(o.deadline) <= 3;
        }).length,
        statusBreakdown: this.calculateStatusBreakdown(products)
    };

    this.updateStatsDisplay();
}

updateStatsDisplay() {
    const s = this.state.stats;
    this.updateElementText('il-stats-orders', s.orderCount);
    this.updateElementText('il-stats-products', s.totalCount);
    this.updateElementText('il-stats-volume', `${s.totalVolume.toFixed(3)} m³`);
    this.updateElementText('il-stats-value', `${s.totalValue.toLocaleString('pl-PL', {minimumFractionDigits: 2})} zł`);

    const urgentEl = document.getElementById('il-stats-urgent');
    if (urgentEl) {
        urgentEl.textContent = s.urgentCount;
        urgentEl.closest('.il-stat-card')?.classList.toggle('danger', s.urgentCount > 0);
    }
}

updateElementText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}
```

- [ ] **Step 13: Update load() lifecycle to use new rendering**

In the `load()` method, after products are loaded from API, add the grouping step:

Find where `this.state.products = data.products` is set, and after it add:
```javascript
this.state.orders = this.groupProductsIntoOrders(this.state.products);
```

Then ensure `applyAllFilters()` is called (which now calls `renderOrdersList()` instead of `renderProductsList()`).

Also update `initializeComponents()` to bind to new DOM element IDs (`#il-products-search` instead of `#products-text-search`, etc.).

Add select-all handler for `#il-select-all` checkbox in header:
```javascript
const selectAll = document.getElementById('il-select-all');
if (selectAll) {
    selectAll.addEventListener('change', () => {
        this.state.filteredOrders.forEach(order => {
            order.products.forEach(p => {
                const id = p.unique_id || String(p.id);
                if (selectAll.checked) {
                    this.state.selectedProducts.add(id);
                } else {
                    this.state.selectedProducts.delete(id);
                }
            });
        });
        // Sync all visible checkboxes
        document.querySelectorAll('.il-order-checkbox, .il-product-checkbox').forEach(cb => {
            cb.checked = selectAll.checked;
        });
        this.toggleBulkActionsVisibility();
    });
}
```

Add CSS class for dimmed products in the CSS file (Task 1):
```css
.il-product-dimmed { opacity: 0.4; }
```

Note: `calculateDaysUntilDeadline()` is an existing method in ProductsModule — reuse it as-is.

- [ ] **Step 14: Update bulk actions visibility**

```javascript
toggleBulkActionsVisibility() {
    const bar = document.getElementById('il-bulk-bar');
    if (!bar) return;

    if (this.state.selectedProducts.size > 0) {
        bar.style.display = 'flex';
        bar.querySelector('.il-bulk-count').textContent = `${this.state.selectedProducts.size} zaznaczone`;
    } else {
        bar.style.display = 'none';
    }
}
```

- [ ] **Step 15: Commit**

```bash
git add modules/production/static/js/modules/products-module.js
git commit -m "feat(production): add order grouping and new rendering to ProductsModule"
```

---

## Task 4: Integration Testing and Polish

- [ ] **Step 1: Run the app and test the products tab**

Open `http://127.0.0.1:5000/production/` and click "Lista produktów". Verify:
1. Products load and are grouped into orders
2. Order cards display: client, IDs, position count, volume, value, status, deadline
3. Click order → expands product rows
4. Product rows show: name, ID, spec tags, qty, volume
5. Filters work (text search, dropdowns)
6. Sorting works (click column headers)
7. Selection works (order checkbox selects all products, individual product checkboxes)
8. Bulk actions bar appears when items selected
9. Star priority toggles on order level
10. Action buttons: details opens modal, baselinker opens link, attachment opens modal, comment shows tooltip

- [ ] **Step 2: Fix any rendering issues**

Compare with mockup and fix CSS spacing, font sizes, colors as needed.

- [ ] **Step 3: Test responsive breakpoints**

Resize browser to 1200px, 900px, 600px and verify layout adapts.

- [ ] **Step 4: Commit final polish**

```bash
git add -A
git commit -m "feat(production): complete products tab redesign — order-grouped Industrial Light"
```
