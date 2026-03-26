# Production Dashboard Redesign — Design Spec

**Date:** 2026-03-26
**Module:** `modules/production`
**Mockup:** `.superpowers/brainstorm/1400-1774526399/content/final-design-v3.html`

## Overview

Redesign the production dashboard (`/production/`) from the current "candy" style to an **Industrial Light** aesthetic — monospaced font, white/gray palette, colors only where they carry functional meaning. Layout changes from flat grid to **Command Panels** (stations dominant left, support widgets stacked right).

## Visual Identity

### Typography
- **Font:** JetBrains Mono (monospace)
- **Casing:** Uppercase for all labels and headers, `letter-spacing: 1.5px`
- **Weights:** 700 for values/headers, 600 for labels, 400 for secondary text

### Color Palette
- **Background:** `#eef0f4` (base), `#ffffff` (cards)
- **Borders:** `#c8cdd5` (standard), `#e2e5ea` (light), `#d4d9e1` (inset shadow)
- **Text:** `#1a1a2e` (primary), `#7a8291` (secondary), `#9ba3b0` (muted)
- **Colors are functional only** — used for station identity, status, and alerts:
  - Station colors: CUT `#2d8a3e`, ASM `#2563eb`, GLU `#9333ea`, FMT `#d97706`, FIN `#0891b2`, PAK `#16a34a`
  - Status: OK `#16a34a`, Warning `#d97706`, Danger `#dc2626`, Info `#2563eb`, Inactive `#9ba3b0`

### Card Component
- White background, 1px border `#c8cdd5`, border-radius 3px
- Header: uppercase label, `font-size: 9px`, `letter-spacing: 1.5px`, separated by 2px bottom border in `#eef0f4`
- No shadows except subtle `inset 0 -2px 0 #d4d9e1` on KPI cards
- Hover: `box-shadow: 0 2px 8px rgba(0,0,0,0.06)` on station cards

## Layout

### Desktop (> 900px)
```
┌─────────────────────────────────────────────────┐
│ PRODUKCJA — DASHBOARD    [status] [sync] [odśw] │
├──────────────────────┬──────────────────────────┤
│                      │  [Zakończone] [Objętość] │
│   STANOWISKA (2x3)   │  [W produkcji teraz]     │
│   60% width          │  [Alerty terminów]       │
│                      │  [Status systemu]        │
├──────────────────────┴──────────────────────────┤
│  WYDAJNOŚĆ DZIENNA (full width chart)           │
└─────────────────────────────────────────────────┘
```

- Main grid: `grid-template-columns: 3fr 2fr`, gap 10px
- Stations grid: `grid-template-columns: 1fr 1fr` (2x3)
- Right stack: flexbox column, gap 10px

### Tablet (< 900px)
- Single column, order: KPI → W produkcji → Alerty → System → Stanowiska (2x3) → Wykres

### Mobile (< 600px)
- Single column, KPI stacks vertically, stations grid becomes 1 column

## Widgets

### 1. Header
- Title: "PRODUKCJA — DASHBOARD"
- Right side: system status dot (green), last sync time, refresh button
- Bottom border: 2px solid `#c8cdd5`

### 2. Station Cards (6x — Color Header style)
Each station card has:
- **Colored header bar** — station color background, white text
  - Station name (uppercase, `10px`, `letter-spacing: 1.5px`)
  - Status badge: "AKTYWNE" or "NIEDOSTĘPNE"
- **Stats grid** — 4 blocks in a row:
  - Oczekuje (pending count)
  - Ukończone (completed today at this station)
  - m³ dziś (volume processed today)
  - m³ oczekujące (pending volume)
- **Progress bar** — station color fill + percentage label

**Tablet heartbeat for status badge:**
- Each station tablet sends refresh requests every 30 seconds (existing behavior)
- Backend records `last_seen` timestamp per station on each refresh
- Dashboard checks `last_seen`:
  - < 60s ago → "Aktywne" badge (white text, semi-transparent white background)
  - ≥ 60s ago → "Niedostępne" badge (header turns gray `#9ba3b0`, progress bar also gray)

**Inactive station visual treatment:**
- Header background changes from station color to `#9ba3b0`
- Badge style: dark semi-transparent background
- Progress bar fill also becomes `#9ba3b0`

### 3. KPI Cards (2x)
- "Zakończone całkowicie dziś" — count of fully completed orders
- "Zakończona całkowicie objętość" — total m³ of fully completed orders
- Style: inset bottom shadow, uppercase multi-line label

### 4. W Produkcji Teraz (new widget)
- Blue left border (`4px solid #2563eb`)
- 3 stat blocks in a row:
  - Zamówień (orders count)
  - Produktów (products count)
  - m³ (total volume in production)
- Each stat: centered, gray background block

### 5. Alerty Terminów
- List of deadline alerts (max 5), sorted by urgency
- Each alert shows:
  - Status dot (danger/warning/info) with colored box-shadow ring
  - Client name (bold)
  - Order ID + current station
  - Days remaining (colored, uppercase) + deadline date below (gray, `DD.MM.YYYY`)
- Dot colors: overdue = red `#dc2626`, critical = orange `#d97706`, normal = blue `#2563eb`

### 6. Status Systemu
- 4 items: Sync BaseLinker, Baza danych, API BaseLinker, Błędy 24h
- Each: status dot (green/yellow/red) + label + value (time/OK/count)

### 7. Wydajność Dzienna (Chart)
- Full width below main grid
- Period selector buttons: 7D, 14D, **30D** (default), 90D, 180D, 365D
- Bar chart (Chart.js) — gray bars for past, blue for today
- Date labels below bars (every 3rd day shown)
- Chart height: 100px

## Files to Modify

### Templates
- `modules/production/templates/components/dashboard-tab-content.html` — main widget restructure
- `modules/production/templates/panel/dashboard.html` — header changes (minimal)

### CSS
- `modules/production/static/css/production-panel.css` — full style overhaul for dashboard section

### JavaScript
- `modules/production/static/js/modules/dashboard-module.js` — update widget rendering, add "W produkcji teraz" data loading, add station heartbeat status logic

### Backend
- `modules/production/routers/api_routers.py` — add `last_seen` to station stats response, add "in production now" stats endpoint
- `modules/production/routers/main_routers.py` — update initial `dashboard_stats` to include new data
- `modules/production/routers/station_routers.py` — record `last_seen` timestamp on each refresh request

## Data Requirements

### New data points needed:
1. **Per station:** `completed_today` (count), `pending_m3` (volume of pending items), `last_seen` (timestamp of last tablet heartbeat — stored in-memory dict on app process, acceptable to lose on restart since tablets re-heartbeat within 30s)
2. **Global:** `in_production_orders` (count), `in_production_products` (count), `in_production_m3` (total volume)
3. **Alerts:** `deadline_date` (absolute date, not just days remaining)

### Existing data to keep:
- Per station: `pending_count`, `today_m3`
- Global: `completed_orders`, `total_m3`, `avg_deadline_distance`
- Alerts: `client_name`, `days_remaining`, `order_id`, `current_station`
- System health: `last_sync`, `sync_status`, `database_status`, `errors_24h`

## Responsive Breakpoints

| Breakpoint | Layout | Station Grid |
|---|---|---|
| > 900px | 2-column (3fr 2fr) | 2x3 |
| 600-900px | 1-column, KPI on top | 2x3 |
| < 600px | 1-column, stacked KPIs | 1x6 |

## Notes

- **Chart.js** is already loaded in the project (used by the existing performance chart widget)
- **Alert urgency thresholds** are defined in existing code: overdue (< 0 days), critical (≤ 1 day), warning (≤ 2 days), normal (> 2 days) — keep existing logic
- **Source of truth:** When spec and mockup conflict, the spec takes precedence. Mockup at `.superpowers/brainstorm/1400-1774526399/content/final-design-v3.html` is for visual reference only
