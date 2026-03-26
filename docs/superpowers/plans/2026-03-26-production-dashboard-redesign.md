# Production Dashboard Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the production dashboard from the current "candy" style to Industrial Light aesthetic with Command Panels layout, new station heartbeat status, and "W produkcji teraz" widget.

**Architecture:** Replace dashboard CSS variables and widget styles with Industrial Light theme (JetBrains Mono, white/gray, functional colors only). Restructure HTML template from flat grid to Command Panels layout (stations 60% left, support widgets stacked right). Add in-memory heartbeat tracking for station tablet status. Add new "in production now" stats aggregation.

**Tech Stack:** Jinja2 templates, CSS (custom properties), vanilla JS (existing DashboardModule), Chart.js (existing), SQLAlchemy queries, Python Flask

**Spec:** `docs/superpowers/specs/2026-03-26-production-dashboard-redesign.md`
**Visual Mockup:** `.superpowers/brainstorm/1400-1774526399/content/final-design-v3.html`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `modules/production/static/css/production-panel.css` | Modify | Replace dashboard CSS section with Industrial Light theme |
| `modules/production/templates/components/dashboard-tab-content.html` | Modify | New HTML structure: Command Panels layout, station cards type C, new widgets |
| `modules/production/templates/panel/dashboard.html` | Modify | Update header to Industrial Light style |
| `modules/production/static/js/modules/dashboard-module.js` | Modify | Update widget rendering, add heartbeat status, add "W produkcji teraz" |
| `modules/production/routers/api_routers.py` | Modify | Add heartbeat data, in-production stats, new data fields to dashboard endpoints |
| `modules/production/routers/main_routers.py` | Modify | Update initial dashboard_stats with new fields |
| `modules/production/routers/station_routers.py` | Modify | Record last_seen timestamp on tablet refresh |
| `modules/production/services/station_heartbeat.py` | Create | In-memory heartbeat store for station tablet status |

---

## Task 1: Create Station Heartbeat Service

**Files:**
- Create: `modules/production/services/station_heartbeat.py`

This is a simple in-memory store — no database, no migration. Tablets re-heartbeat within 30s so data loss on restart is acceptable.

- [ ] **Step 1: Create the heartbeat service**

```python
"""In-memory heartbeat tracking for station tablets."""
from datetime import datetime, timedelta

# In-memory store: { station_name: last_seen_datetime }
_station_heartbeats = {}

HEARTBEAT_TIMEOUT_SECONDS = 60


def record_heartbeat(station_name: str):
    """Record that a station tablet just checked in."""
    _station_heartbeats[station_name] = datetime.now()


def is_station_active(station_name: str) -> bool:
    """Check if station tablet has heartbeated within timeout."""
    last_seen = _station_heartbeats.get(station_name)
    if last_seen is None:
        return False
    return (datetime.now() - last_seen).total_seconds() < HEARTBEAT_TIMEOUT_SECONDS


def get_station_status(station_name: str) -> dict:
    """Get station heartbeat status for dashboard display."""
    last_seen = _station_heartbeats.get(station_name)
    active = is_station_active(station_name)
    return {
        'active': active,
        'last_seen': last_seen.isoformat() if last_seen else None,
        'status_label': 'Aktywne' if active else 'Niedostępne'
    }


def get_all_statuses() -> dict:
    """Get heartbeat status for all known stations."""
    station_names = ['cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging']
    return {name: get_station_status(name) for name in station_names}
```

- [ ] **Step 2: Commit**

```bash
git add modules/production/services/station_heartbeat.py
git commit -m "feat(production): add in-memory station heartbeat service"
```

---

## Task 2: Wire Heartbeat into Station Tablet Routes

**Files:**
- Modify: `modules/production/routers/station_routers.py`

Find the station panel refresh endpoint(s) — the routes that tablets call every 30 seconds. Add a `record_heartbeat()` call.

- [ ] **Step 1: Find the tablet refresh endpoints**

Search `station_routers.py` for routes that serve station data or station panel pages. Look for endpoints like `/station/<name>`, `/api/station-data`, or any route with refresh/poll semantics. The station names are: `cutting`, `assembly`, `gluing`, `formatting`, `finishing`, `packaging`.

- [ ] **Step 2: Add heartbeat import and call**

At the top of `station_routers.py`, add:
```python
from modules.production.services.station_heartbeat import record_heartbeat
```

In each station refresh/data endpoint, add at the start of the handler:
```python
record_heartbeat(station_name)  # station_name from route param or determined by endpoint
```

If there's a single endpoint like `GET /api/station/<station_name>/data`, add it once. If there are separate endpoints per station, add to each.

- [ ] **Step 3: Commit**

```bash
git add modules/production/routers/station_routers.py
git commit -m "feat(production): record heartbeat on station tablet refresh"
```

---

## Task 3: Update Backend API — Dashboard Data Endpoints

**Files:**
- Modify: `modules/production/routers/api_routers.py`
- Modify: `modules/production/routers/main_routers.py`

Add new data fields to dashboard stats: per-station `completed_today`, `pending_m3`, heartbeat status; global "in production now" stats; alert `deadline_date`.

- [ ] **Step 1: Update `api_routers.py` — dashboard-tab-content endpoint (around line 2511)**

In the `dashboard_tab_content()` function, find where `dashboard_stats['stations']` is built (around lines 2623-2751). For each station, add these fields:

```python
from modules.production.services.station_heartbeat import get_all_statuses

# Inside dashboard_tab_content(), after building station stats:
heartbeat_statuses = get_all_statuses()

# For each station in dashboard_stats['stations']:
# Add to each station dict:
station_data['completed_today'] = ProductionItem.query.filter(
    ProductionItem.current_status != 'czeka_na_wyciecie',  # adjust per station
    # Filter: items that completed THIS station today
).count()
station_data['pending_m3'] = float(pending_m3_value or 0)
station_data['tablet_status'] = heartbeat_statuses.get(station_key, {})
```

The exact query for `completed_today` per station depends on the station:
- cutting: count where `cutting_completed_at >= today_start`
- assembly: count where `assembly_completed_at >= today_start`
- etc.

For `pending_m3`: sum `volume_m3` of items waiting at that station.

- [ ] **Step 2: Add "in production now" stats to dashboard data**

In the same endpoint, add a new section to `dashboard_stats`:

```python
# "In production now" — orders/products/m3 currently being processed
in_production_items = ProductionItem.query.filter(
    ProductionItem.current_status.notin_(['spakowane', 'anulowane'])
).all()

# Count unique orders (by baselinker_order_id or order grouping)
in_production_order_ids = set(item.baselinker_order_id for item in in_production_items if item.baselinker_order_id)

dashboard_stats['in_production'] = {
    'orders': len(in_production_order_ids),
    'products': len(in_production_items),
    'm3': round(sum(float(item.volume_m3 or 0) for item in in_production_items), 2)
}
```

- [ ] **Step 3: Add `deadline_date` to alerts**

In the alerts section of the endpoint, ensure each alert includes the raw date:

```python
# In the alerts loop, add:
alert_data['deadline_date_formatted'] = item.deadline_date.strftime('%d.%m.%Y') if item.deadline_date else ''
```

- [ ] **Step 4: Update `dashboard-data` endpoint (around line 6057)**

Apply the same changes to the `/dashboard-data` endpoint so that data refreshes also return the new fields (heartbeat statuses, in_production stats, deadline dates).

- [ ] **Step 5: Update `main_routers.py` — initial dashboard_stats**

In `main_routers.py` `dashboard()` function (around line 49), add the same new data fields to the initial `dashboard_stats` dict so the template has them on first render:

```python
from modules.production.services.station_heartbeat import get_all_statuses

# Add to dashboard_stats:
heartbeat_statuses = get_all_statuses()
# Add heartbeat to each station
# Add 'in_production' dict
# Add 'deadline_date_formatted' to each alert
```

- [ ] **Step 6: Commit**

```bash
git add modules/production/routers/api_routers.py modules/production/routers/main_routers.py
git commit -m "feat(production): add heartbeat, in-production stats, deadline dates to dashboard API"
```

---

## Task 4: Rewrite Dashboard CSS — Industrial Light Theme

**Files:**
- Modify: `modules/production/static/css/production-panel.css`

Replace the dashboard-specific CSS sections. Keep non-dashboard styles (station panels, product list, etc.) intact.

- [ ] **Step 1: Identify dashboard CSS boundaries**

The dashboard styles are in these sections of `production-panel.css`:
- Lines ~1-30: CSS variables (`:root`)
- Lines ~78-88: `.production-dashboard-grid`
- Lines ~100-131: `.widget`, `.widget-header`, `.widget-content`
- Lines ~215-371: Stations grid and station cards
- Lines ~375-424: Summary stats
- Lines ~429-591: Alerts
- Lines ~596-650+: System health

- [ ] **Step 2: Replace `:root` CSS variables**

Find the existing `:root` block and replace/add the Industrial Light variables. Keep any non-dashboard variables intact.

```css
/* ─── Industrial Light Dashboard Theme ─── */
--il-bg-base: #eef0f4;
--il-bg-card: #ffffff;
--il-border: #c8cdd5;
--il-border-light: #e2e5ea;
--il-inset-shadow: #d4d9e1;
--il-text-primary: #1a1a2e;
--il-text-secondary: #7a8291;
--il-text-muted: #9ba3b0;
--il-radius: 3px;

--il-station-cut: #2d8a3e;
--il-station-asm: #2563eb;
--il-station-glu: #9333ea;
--il-station-fmt: #d97706;
--il-station-fin: #0891b2;
--il-station-pak: #16a34a;

--il-status-ok: #16a34a;
--il-status-warn: #d97706;
--il-status-danger: #dc2626;
--il-status-info: #2563eb;
--il-status-inactive: #9ba3b0;
```

- [ ] **Step 3: Replace dashboard grid and widget base styles**

Replace `.production-dashboard-grid` with the new Command Panels layout:

```css
/* ─── Dashboard Layout ─── */
.production-dashboard-grid {
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 10px;
  margin-bottom: 10px;
  font-family: 'JetBrains Mono', 'Courier New', monospace;
}

/* ─── Card Base ─── */
.dashboard-card {
  background: var(--il-bg-card);
  border: 1px solid var(--il-border);
  border-radius: var(--il-radius);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.dashboard-card-header {
  color: var(--il-text-secondary);
  text-transform: uppercase;
  letter-spacing: 1.5px;
  font-size: 9px;
  font-weight: 600;
  padding: 12px 14px 8px;
  border-bottom: 2px solid var(--il-bg-base);
  flex-shrink: 0;
}
.dashboard-card-body {
  padding: 12px 14px 14px;
  flex: 1;
}
```

- [ ] **Step 4: Add station card styles (Color Header type)**

```css
/* ─── Station Cards ─── */
.il-stations-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  flex: 1;
}
.il-station {
  border: 1px solid var(--il-border-light);
  border-radius: var(--il-radius);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: box-shadow 0.15s ease;
}
.il-station:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.il-station-header {
  padding: 7px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.il-station-name {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: #fff;
}
.il-station-badge {
  font-size: 7px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  padding: 2px 7px;
  border-radius: 2px;
}
.il-station-badge.active {
  color: rgba(255,255,255,0.9);
  background: rgba(255,255,255,0.2);
}
.il-station-badge.inactive {
  color: rgba(255,255,255,0.7);
  background: rgba(0,0,0,0.2);
}
.il-station-body {
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
}
.il-station-stats {
  display: flex;
  gap: 3px;
  flex: 1;
}
.il-station-stat {
  flex: 1;
  text-align: center;
  padding: 8px 4px;
  background: var(--il-bg-base);
  border-radius: 2px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.il-station-stat-value {
  font-size: 15px;
  font-weight: 700;
  color: var(--il-text-primary);
  line-height: 1;
}
.il-station-stat-label {
  font-size: 7px;
  color: var(--il-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-top: 4px;
  line-height: 1.2;
}
.il-station-progress {
  display: flex;
  align-items: center;
  gap: 8px;
}
.il-station-bar {
  flex: 1;
  height: 4px;
  background: var(--il-bg-base);
  border-radius: 2px;
  overflow: hidden;
}
.il-station-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.4s ease;
}
.il-station-bar-pct {
  font-size: 9px;
  font-weight: 600;
  color: var(--il-text-secondary);
  width: 28px;
  text-align: right;
}

/* Station header colors */
.il-station[data-station="cutting"] .il-station-header { background: var(--il-station-cut); }
.il-station[data-station="cutting"] .il-station-bar-fill { background: var(--il-station-cut); }
.il-station[data-station="assembly"] .il-station-header { background: var(--il-station-asm); }
.il-station[data-station="assembly"] .il-station-bar-fill { background: var(--il-station-asm); }
.il-station[data-station="gluing"] .il-station-header { background: var(--il-station-glu); }
.il-station[data-station="gluing"] .il-station-bar-fill { background: var(--il-station-glu); }
.il-station[data-station="formatting"] .il-station-header { background: var(--il-station-fmt); }
.il-station[data-station="formatting"] .il-station-bar-fill { background: var(--il-station-fmt); }
.il-station[data-station="finishing"] .il-station-header { background: var(--il-station-fin); }
.il-station[data-station="finishing"] .il-station-bar-fill { background: var(--il-station-fin); }
.il-station[data-station="packaging"] .il-station-header { background: var(--il-station-pak); }
.il-station[data-station="packaging"] .il-station-bar-fill { background: var(--il-station-pak); }

/* Inactive station */
.il-station.station-inactive .il-station-header { background: var(--il-status-inactive) !important; }
.il-station.station-inactive .il-station-bar-fill { background: var(--il-status-inactive) !important; }
```

- [ ] **Step 5: Add right stack styles (KPI, In Production, Alerts, System, Chart)**

```css
/* ─── Right Stack ─── */
.il-right-stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* ─── KPI Cards ─── */
.il-kpi-row { display: flex; gap: 8px; }
.il-kpi {
  flex: 1;
  background: var(--il-bg-card);
  border: 1px solid var(--il-border);
  border-radius: var(--il-radius);
  padding: 12px 14px;
  box-shadow: inset 0 -2px 0 var(--il-inset-shadow);
}
.il-kpi-label {
  color: var(--il-text-secondary);
  text-transform: uppercase;
  letter-spacing: 1px;
  font-size: 8px;
  font-weight: 600;
  line-height: 1.3;
}
.il-kpi-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--il-text-primary);
  margin-top: 4px;
  line-height: 1;
}
.il-kpi-unit {
  font-size: 11px;
  color: var(--il-text-secondary);
  font-weight: 500;
}

/* ─── In Production Now ─── */
.il-in-production {
  background: var(--il-bg-card);
  border: 1px solid var(--il-border);
  border-radius: var(--il-radius);
  padding: 12px 14px;
  border-left: 4px solid var(--il-status-info);
}
.il-in-production-header {
  color: var(--il-text-secondary);
  text-transform: uppercase;
  letter-spacing: 1.5px;
  font-size: 8px;
  font-weight: 600;
  margin-bottom: 8px;
}
.il-in-production-stats { display: flex; gap: 8px; }
.il-in-production-stat {
  flex: 1;
  text-align: center;
  padding: 8px 4px;
  background: var(--il-bg-base);
  border-radius: var(--il-radius);
}
.il-in-production-stat-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--il-text-primary);
  line-height: 1;
}
.il-in-production-stat-label {
  font-size: 8px;
  color: var(--il-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-top: 4px;
}

/* ─── Alerts ─── */
.il-alert-list { display: flex; flex-direction: column; gap: 8px; }
.il-alert-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--il-bg-base);
}
.il-alert-item:last-child { border-bottom: none; }
.il-alert-dot {
  width: 8px; height: 8px; border-radius: 50%;
  flex-shrink: 0; margin-top: 3px;
}
.il-alert-dot.danger { background: var(--il-status-danger); box-shadow: 0 0 0 3px rgba(220,38,38,0.15); }
.il-alert-dot.warn { background: var(--il-status-warn); box-shadow: 0 0 0 3px rgba(217,119,6,0.15); }
.il-alert-dot.info { background: var(--il-status-info); }
.il-alert-info { flex: 1; }
.il-alert-client { font-size: 11px; font-weight: 600; color: var(--il-text-primary); }
.il-alert-order { font-size: 9px; color: var(--il-text-secondary); margin-top: 1px; }
.il-alert-right { text-align: right; flex-shrink: 0; }
.il-alert-days { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
.il-alert-date { font-size: 9px; color: var(--il-text-secondary); margin-top: 2px; }

/* ─── System Status ─── */
.il-system-list { display: flex; flex-direction: column; gap: 6px; }
.il-system-item { display: flex; align-items: center; justify-content: space-between; }
.il-system-item-left { display: flex; align-items: center; gap: 8px; }
.il-system-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.il-system-label { font-size: 10px; color: var(--il-text-primary); }
.il-system-value { font-size: 9px; color: var(--il-text-secondary); font-weight: 500; }

/* ─── Chart ─── */
.il-chart-header { display: flex; justify-content: space-between; align-items: center; }
.il-chart-periods { display: flex; gap: 4px; }
.il-chart-period {
  font-size: 9px; padding: 3px 10px; border-radius: 2px;
  cursor: pointer; font-weight: 600; letter-spacing: 0.5px;
  font-family: 'JetBrains Mono', monospace; border: none;
  transition: all 0.15s ease;
}
.il-chart-period.inactive { background: var(--il-bg-base); color: var(--il-text-secondary); }
.il-chart-period.active { background: var(--il-text-primary); color: #fff; }

/* ─── Dashboard Header ─── */
.il-dashboard-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 2px solid var(--il-border);
  font-family: 'JetBrains Mono', monospace;
}
.il-dashboard-header h1 {
  font-size: 16px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 2px;
  color: var(--il-text-primary);
  margin: 0;
}
.il-header-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 10px;
  color: var(--il-text-secondary);
  text-transform: uppercase;
  letter-spacing: 1px;
}
.il-btn-refresh {
  background: var(--il-bg-card);
  border: 1px solid var(--il-border);
  border-radius: var(--il-radius);
  padding: 6px 12px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--il-text-secondary);
  cursor: pointer;
  box-shadow: inset 0 -2px 0 var(--il-inset-shadow);
  transition: all 0.15s ease;
}
.il-btn-refresh:hover { color: var(--il-text-primary); border-color: var(--il-text-secondary); }

/* ─── Responsive ─── */
@media (max-width: 900px) {
  .production-dashboard-grid { grid-template-columns: 1fr; }
  .il-right-stack { order: -1; }
}
@media (max-width: 600px) {
  .il-dashboard-header { flex-direction: column; align-items: flex-start; gap: 8px; }
  .il-header-meta { flex-wrap: wrap; }
  .il-kpi-row { flex-direction: column; gap: 6px; }
  .il-in-production-stats { gap: 4px; }
  .il-stations-grid { grid-template-columns: 1fr; }
  .il-kpi-value { font-size: 20px; }
}
```

- [ ] **Step 6: Remove old dashboard widget styles**

Delete or comment out the old `.widget`, `.widget-header`, `.widget-content`, `.stations-grid`, `.station-card`, `.summary-stats`, `.summary-card`, `.alerts-list` (old version), `.health-indicator`, `.health-item` styles. Keep all non-dashboard styles (station panel, product list, config, etc.) intact.

- [ ] **Step 7: Add JetBrains Mono font import**

In `modules/production/templates/panel/dashboard.html`, add in the `<head>`:
```html
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
```

- [ ] **Step 8: Commit**

```bash
git add modules/production/static/css/production-panel.css modules/production/templates/panel/dashboard.html
git commit -m "feat(production): Industrial Light CSS theme for dashboard"
```

---

## Task 5: Rewrite Dashboard HTML Template

**Files:**
- Modify: `modules/production/templates/components/dashboard-tab-content.html`

Replace the entire content of this template with the new Command Panels structure. Keep the same Jinja2 variable names (`dashboard_stats`) so backend compatibility is maintained.

- [ ] **Step 1: Replace template content**

Replace the full content of `dashboard-tab-content.html` with the new Industrial Light structure. The template must:

1. **Header** — title "PRODUKCJA — DASHBOARD", system status dot, last sync time, refresh button
2. **Main grid** (`production-dashboard-grid`) with 2 children:
   - Left: `.dashboard-card.stations-card` containing `.il-stations-grid` with 6 station cards (type C: colored header + 4 stats + progress bar)
   - Right: `.il-right-stack` containing KPIs, In Production Now, Alerts, System Status
3. **Chart** — full width below grid, with period selector (7D/14D/30D/90D/180D/365D, default 30D)

Key Jinja2 bindings to preserve:
- `{{ dashboard_stats.stations.cutting.pending_count }}` → station pending count
- `{{ dashboard_stats.stations.cutting.today_m3 }}` → station m³ today
- `{{ dashboard_stats.today_totals.completed_orders }}` → KPI completed
- `{{ dashboard_stats.today_totals.total_m3 }}` → KPI volume
- New: `{{ dashboard_stats.in_production.orders }}`, `.products`, `.m3`
- New: `{{ dashboard_stats.stations.cutting.tablet_status.status_label }}`
- New: `{{ dashboard_stats.stations.cutting.tablet_status.active }}`
- Alerts: `{{ alert.deadline_date_formatted }}`

Element IDs to preserve (used by JS for data refresh):
- `#cutting-pending`, `#cutting-today-m3` (and same for all 6 stations)
- `#today-completed`, `#today-total-m3`
- `#alerts-list`, `#alerts-count`
- `#performance-chart-canvas`, `#chart-period-select`

New element IDs to add:
- `#in-production-orders`, `#in-production-products`, `#in-production-m3`
- `#cutting-completed-today`, `#cutting-pending-m3` (and same for all stations)
- `#cutting-tablet-badge` (and same for all stations)
- Per station: `.il-station-bar-fill` for progress width, `.il-station-bar-pct` for percentage text

Station card HTML structure for each station (use cutting as example):
```html
<div class="il-station {% if not dashboard_stats.stations.cutting.tablet_status.active %}station-inactive{% endif %}" data-station="cutting" data-station-url="{{ url_for('production.station_cutting') }}">
  <div class="il-station-header">
    <span class="il-station-name">Wycinanie</span>
    <span class="il-station-badge {% if dashboard_stats.stations.cutting.tablet_status.active %}active{% else %}inactive{% endif %}" id="cutting-tablet-badge">
      {{ dashboard_stats.stations.cutting.tablet_status.status_label }}
    </span>
  </div>
  <div class="il-station-body">
    <div class="il-station-stats">
      <div class="il-station-stat">
        <div class="il-station-stat-value" id="cutting-pending">{{ dashboard_stats.stations.cutting.pending_count }}</div>
        <div class="il-station-stat-label">Oczekuje</div>
      </div>
      <div class="il-station-stat">
        <div class="il-station-stat-value" id="cutting-completed-today">{{ dashboard_stats.stations.cutting.completed_today }}</div>
        <div class="il-station-stat-label">Ukończ.</div>
      </div>
      <div class="il-station-stat">
        <div class="il-station-stat-value" id="cutting-today-m3">{{ dashboard_stats.stations.cutting.today_m3 }}</div>
        <div class="il-station-stat-label">m³ dziś</div>
      </div>
      <div class="il-station-stat">
        <div class="il-station-stat-value" id="cutting-pending-m3">{{ dashboard_stats.stations.cutting.pending_m3 }}</div>
        <div class="il-station-stat-label">m³ ocz.</div>
      </div>
    </div>
    <div class="il-station-progress">
      <div class="il-station-bar">
        <div class="il-station-bar-fill" id="cutting-bar-fill"></div>
      </div>
      <span class="il-station-bar-pct" id="cutting-bar-pct"></span>
    </div>
  </div>
</div>
```

Repeat for: assembly (Składanie), gluing (Sklejanie), formatting (Formatowanie), finishing (Wykańczanie), packaging (Pakowanie).

- [ ] **Step 2: Verify template renders**

Run the app locally and visit `http://127.0.0.1:5000/production/`. Check that:
- All widgets render with correct data
- Layout is 2-column (stations left, support right)
- Station cards show colored headers and stats
- No Jinja2 errors in console

- [ ] **Step 3: Commit**

```bash
git add modules/production/templates/components/dashboard-tab-content.html
git commit -m "feat(production): Industrial Light dashboard template with Command Panels layout"
```

---

## Task 6: Update JavaScript — Widget Rendering and Data Refresh

**Files:**
- Modify: `modules/production/static/js/modules/dashboard-module.js`

Update the DashboardModule to handle new element IDs, render new widgets, and process heartbeat data on refresh.

- [ ] **Step 1: Update `updateWidgetsWithInitialData()` method**

Add handling for new data fields:

```javascript
// In updateWidgetsWithInitialData(), add:

// Update "In Production Now" widget
if (data.in_production) {
    this.updateElementText('in-production-orders', data.in_production.orders);
    this.updateElementText('in-production-products', data.in_production.products);
    this.updateElementText('in-production-m3', data.in_production.m3);
}

// Update station completed_today, pending_m3, and tablet status
const stations = ['cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging'];
stations.forEach(station => {
    const stationData = data.stations?.[station];
    if (stationData) {
        this.updateElementText(`${station}-completed-today`, stationData.completed_today || 0);
        this.updateElementText(`${station}-pending-m3`, stationData.pending_m3 || 0);

        // Update tablet heartbeat badge
        const badge = document.getElementById(`${station}-tablet-badge`);
        const card = badge?.closest('.il-station');
        if (badge && stationData.tablet_status) {
            badge.textContent = stationData.tablet_status.status_label;
            badge.className = 'il-station-badge ' + (stationData.tablet_status.active ? 'active' : 'inactive');
            if (card) {
                card.classList.toggle('station-inactive', !stationData.tablet_status.active);
            }
        }

        // Update progress bar
        this.updateStationProgress(station, stationData);
    }
});
```

- [ ] **Step 2: Add `updateStationProgress()` helper method**

```javascript
updateStationProgress(station, data) {
    const barFill = document.getElementById(`${station}-bar-fill`);
    const barPct = document.getElementById(`${station}-bar-pct`);
    if (!barFill || !barPct) return;

    // Calculate percentage: pending / (pending + completed) * 100
    const pending = parseInt(data.pending_count) || 0;
    const completed = parseInt(data.completed_today) || 0;
    const total = pending + completed;
    const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

    barFill.style.width = pct + '%';
    barPct.textContent = pct + '%';
}
```

- [ ] **Step 3: Update the `updateStationsWidget()` method**

Extend the existing station update logic to also update the new fields (completed_today, pending_m3, tablet_status, progress bar) when data refreshes happen.

- [ ] **Step 4: Add "in production" to data refresh handlers**

In `setupDataRefreshHandlers()`, add the in_production data update to the existing handlers or register a new one:

```javascript
// In the 'stations' or 'totals' refresh handler callback, add:
if (data.in_production) {
    this.updateElementText('in-production-orders', data.in_production.orders);
    this.updateElementText('in-production-products', data.in_production.products);
    this.updateElementText('in-production-m3', data.in_production.m3);
}
```

- [ ] **Step 5: Update alert rendering for deadline dates**

In the alerts update method (where alert HTML is rebuilt), add the deadline date:

```javascript
// In alert item rendering, change the days display to include date:
alertHtml += `
  <div class="il-alert-right">
    <div class="il-alert-days" style="color: ${daysColor};">${daysText}</div>
    <div class="il-alert-date">${alert.deadline_date_formatted || ''}</div>
  </div>
`;
```

- [ ] **Step 6: Update chart default period**

Find where the chart period selector is initialized and change the default from 14D to 30D:

```javascript
// Change default period
const defaultPeriod = 30;
```

- [ ] **Step 7: Test full cycle**

Run the app locally. Verify:
1. Dashboard loads with all widgets populated
2. Auto-refresh (60s) updates all values including new fields
3. Station tablet status badges update on refresh
4. "W produkcji teraz" widget shows correct numbers
5. Alert deadline dates display below days remaining
6. Chart defaults to 30D
7. Responsive: resize browser to < 900px (single column, KPI on top) and < 600px (stacked)

- [ ] **Step 8: Commit**

```bash
git add modules/production/static/js/modules/dashboard-module.js
git commit -m "feat(production): update dashboard JS for Industrial Light widgets and heartbeat"
```

---

## Task 7: Final Integration Test and Cleanup

- [ ] **Step 1: Full visual comparison with mockup**

Open both the mockup (`.superpowers/brainstorm/1400-1774526399/content/final-design-v3.html`) and the live dashboard (`http://127.0.0.1:5000/production/`) side by side. Check:
- Font: JetBrains Mono everywhere in dashboard area
- Colors: white/gray base, functional colors only on stations, alerts, statuses
- Layout: stations 60% left, right stack 40%
- Station cards: colored header, 4 stats, progress bar with percentage
- KPI labels: "Zakończone całkowicie dziś" and "Zakończona całkowicie objętość"
- Alerts: days + date below
- Chart: 30D default, 6 period options

- [ ] **Step 2: Test responsive breakpoints**

- Desktop (> 900px): 2-column layout
- Tablet (600-900px): single column, KPI/support widgets on top, stations below (2x3)
- Mobile (< 600px): single column, KPIs stacked vertically, stations 1-column

- [ ] **Step 3: Remove old unused CSS classes**

If any old widget classes are no longer referenced in templates or JS, remove them from `production-panel.css`.

- [ ] **Step 4: Commit final cleanup**

```bash
git add -A
git commit -m "feat(production): complete dashboard redesign — Industrial Light theme"
```
