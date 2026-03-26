# Products Tab Redesign — Design Spec

**Date:** 2026-03-26
**Module:** `modules/production`
**Mockup:** `.superpowers/brainstorm/1400-1774526399/content/products-tab-mockup.html`

## Overview

Redesign the products tab (`/production/` → "Lista produktów" tab) from flat per-product list to **grouped per-order** view with expandable product rows. Apply Industrial Light theme (JetBrains Mono, white/gray, functional colors). This is a fundamental change in data presentation — orders become the primary grouping unit.

## Key Change: Per-Product → Per-Order Grouping

**Current:** Flat list of individual products (ProductionItem rows), each with its own status, priority, actions.

**New:** Orders (grouped by `baselinker_order_id` or `internal_order_number`) as primary rows, with expandable product list underneath.

### Order Row shows:
- Drag handle (for priority reordering)
- Checkbox (select order)
- Star (priority marking — on order level)
- Expand/collapse arrow
- Client name + order IDs (BL number, client order number)
- Position count (number of products in order)
- Total volume (m³) with unit
- Total value (netto, zł) with unit
- Status badge (order-level status, or "Różne (X/Y)" if products have mixed statuses)
- Deadline with urgency coloring
- Action buttons: attachment (modal), comment (tooltip), details (modal), baselinker (external link)

### Product Row shows (when expanded):
- Checkbox
- Product name + product ID
- Spec tags (wood species, technology, class, thickness)
- Quantity (szt.)
- Volume (m³) with unit
- No status badge displayed (each product still has `current_status` in the data model, but it is only shown aggregated at the order level)
- No action buttons (actions are on order level)

## Visual Identity

Same Industrial Light theme as dashboard — see `docs/superpowers/specs/2026-03-26-production-dashboard-redesign.md` for full color/font spec.

### Order-Level Status Colors (left border + badge)
Maps to `current_status` values in ProductionItem model:
- `czeka_na_wyciecie` (Wycinanie): `#2d8a3e` (green)
- `czeka_na_skladanie` (Składanie): `#2563eb` (blue)
- `czeka_na_sklejanie` (Sklejanie): `#9333ea` (purple)
- `czeka_na_formatowanie` (Formatowanie): `#d97706` (amber)
- `czeka_na_wykanczanie` (Wykańczanie): `#0891b2` (cyan)
- `czeka_na_pakowanie` (Pakowanie): `#16a34a` (green)
- `spakowane` (Spakowane): `#9ba3b0` (gray)
- `w_realizacji` (W realizacji): `#2563eb` (blue, same as assembly)
- `wstrzymane` (Wstrzymane): `#d97706` (amber)
- `anulowane` (Anulowane): `#dc2626` (red)
- Mixed: `#9333ea` (purple) — when products have different statuses, show "Różne (X/Y)" where X = count of products with `spakowane` status, Y = total products

### Deadline Urgency Colors
- Overdue (< 0 days): `#dc2626` (red)
- Urgent (0-1 days): `#d97706` (amber)
- Normal (> 1 day): `#7a8291` (gray)

## Layout

### Stats Bar (top)
5 stat cards in a row, inline flex (label left, value right):
- Zamówienia (order count)
- Produkty (product count)
- Objętość (total m³)
- Wartość netto (total value)
- Pilne (urgent count, red if > 0)

### Filters
- Text search input: "Szukaj: nr zamówienia, klient, produkt..."
- 5 multi-select dropdown filters: Gatunek, Technologia, Klasa, Grubość, Status
- Active filter badges with remove (x) and "Wyczyść filtry" button
- Filters apply to orders — an order is shown if ANY of its products match the filter

### Column Headers
Fixed grid header row with columns:
`[drag 20px] [checkbox 24px] [star 24px] [expand 20px] [klient 2fr] [pozycje 55px] [objętość 80px] [wartość netto 100px] [status 120px] [termin 120px] [akcje 130px]`

### Order Card
- White background, 1px border, 3px radius
- 4px colored left border (status color)
- Grid layout matching column headers
- Hover: light background
- Expanded: bottom border separator before products

### Product Rows (expanded)
- Light gray background (`#f8f9fb`)
- Left padding (indented under order)
- Each product: checkbox, name+ID, spec tags, qty, volume
- Separator lines between products

### Bulk Actions Bar
- Fixed bottom center, dark background
- Shows when items selected
- Buttons: Zmień status, Eksport, Usuń

## Interactions

### Expand/Collapse
- Click anywhere on order row (except checkbox, star, actions) toggles product list
- Arrow rotates 90° when expanded
- Products slide in/out

### Selection
- Order checkbox: selects/deselects all products in order
- Product checkbox: individual product selection
- "Select all" in header: selects all visible orders + their products

### Star Priority
- On order level only
- Click toggles priority for entire order

### Drag & Drop
- Drag handle on order level only
- Reorders orders (priority)

### Actions (order level)
- **Attachment (paperclip):** Opens modal with file preview (existing attachment modal)
- **Comment (speech bubble):** Tooltip/popover showing production notes for the order
- **Details (eye):** Opens product details modal (existing modal, adapted for order context)
- **Baselinker (external link):** Opens Baselinker order in new tab

### Filtering
- Text search: fuzzy match against order ID, client name, product names, product IDs
- Multi-select filters: filter by product attributes (species, technology, class, thickness, status)
- An order is visible if ANY of its products match active filters
- When filtered, non-matching products within a visible order are dimmed (opacity 0.4) but still visible — this preserves order context

### Sorting
- Column headers clickable for sort
- Sort by: client name, position count, volume, value, status, deadline
- Default sort: by deadline (most urgent first)

## Data Requirements

### Backend: Order Grouping
Products need to be grouped by order. The API currently returns flat product list. Options:
1. **Backend grouping** — API returns orders with nested products (preferred)
2. **Frontend grouping** — JS groups products by `baselinker_order_id` / `internal_order_number`

**Recommended: Frontend grouping** — less API change, existing product data already has order identifiers. Group by `internal_order_number` (primary) or `baselinker_order_id` (fallback).

### Order-Level Computed Fields
Computed in frontend from grouped products:
- `product_count`: number of products in order
- `total_volume`: sum of (volume_m3 * quantity) for all products
- `total_value`: sum of product values
- `order_status`: if all products same status → that status; if mixed → "Różne (X/Y)" where X = completed count
- `order_deadline`: earliest deadline among products
- `is_priority`: true if any product is marked priority

### Existing Data Used
From `ProductionItem` model (already available):
- `baselinker_order_id`, `internal_order_number`, `client_order_number`
- `client_name`, `client_email`, `client_phone`
- `original_product_name`, `short_product_id`
- `wood_species`, `technology`, `wood_class`, `thickness`
- `quantity`, `volume_m3`, `unit_price`, `total_value`
- `current_status`, `deadline_date`
- `priority_score`, `is_priority`
- `production_notes`

## Files to Modify

### Templates
- `modules/production/templates/components/products-tab-content.html` — complete rewrite

### CSS
- `modules/production/static/css/products-tab.css` — complete rewrite in IL style

### JavaScript
- `modules/production/static/js/modules/products-module.js` — major rewrite:
  - Add order grouping logic
  - New rendering (order cards + product rows)
  - Update filtering to work on order level
  - Update selection (order + product checkboxes)
  - Update bulk actions
  - Keep: fuzzy search, export, keyboard shortcuts, details modal
  - Keep: drag & drop (adapt to order level)

### Backend (minimal changes)
- API endpoints stay the same — products are grouped in frontend
- Ensure all product fields listed above are returned by the API

## Responsive Breakpoints

| Breakpoint | Changes |
|---|---|
| > 1200px | Full grid, all columns |
| 900-1200px | Hide value column |
| 600-900px | Hide volume + value, compact layout |
| < 600px | Single column, card-style orders, stacked product info |

## Notes

- Existing modals (product details, baselinker compare, bulk actions) should be restyled to IL theme but keep their functionality
- The product details modal should show order context (which order the product belongs to)
- Virtual scroll is NOT needed for orders — order count is much smaller than flat product count, standard DOM rendering is sufficient
- Keyboard shortcuts preserved: Ctrl+A (select all), Ctrl+E (export), ESC (clear/close)
