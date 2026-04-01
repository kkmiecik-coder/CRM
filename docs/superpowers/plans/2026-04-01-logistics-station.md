# Logistics Station Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Logistyka" station between production (finishing/formatting) and packaging that decides transport method for non-personal-pickup orders.

**Architecture:** New status `czeka_na_logistyke` in model, intercept `complete_task()` to route non-pickup orders to logistics. New API endpoints for listing/approving logistics orders. Dashboard card + dedicated page accessible to logged-in users.

**Tech Stack:** Flask/Jinja2, SQLAlchemy, vanilla JS, CSS (IL design system)

---

## File Structure

### New Files
- `modules/production/templates/logistics/logistics.html` — Full-page logistics station view
- `modules/production/routers/api/logistics_api.py` — API endpoints (list orders, approve transport)

### Modified Files
- `modules/production/models.py` — New columns + status + intercept in complete_task()
- `modules/production/routers/api/__init__.py` — Import logistics_api
- `modules/production/routers/api/dashboard_api.py` — Logistics stats for dashboard card
- `modules/production/routers/main_routers.py` — Route for logistics page
- `modules/production/templates/components/dashboard-tab-content.html` — Logistics card on dashboard
- `modules/production/static/js/modules/products-module.js` — STATUS_CONFIG, getStatusConfig, timeline
- `modules/production/static/css/production-panel.css` — Logistics station color

---

### Task 1: Add new columns and status to ProductionItem model

**Files:**
- Modify: `modules/production/models.py`

- [ ] **Step 1: Add `czeka_na_logistyke` to current_status enum**

In `models.py` at line 167, the current_status column uses a list of string values. Add `'czeka_na_logistyke'` after `'czeka_na_wykanczanie'`:

```python
# Line 167-179: Add 'czeka_na_logistyke' to the enum values
current_status = Column(String(50), default='czeka_na_wyciecie', index=True)
# Valid values: czeka_na_wyciecie, czeka_na_skladanie, czeka_na_sklejanie,
# czeka_na_formatowanie, czeka_na_wykanczanie, czeka_na_logistyke,
# czeka_na_pakowanie, spakowane, anulowane, wstrzymane, w_realizacji
```

- [ ] **Step 2: Add new columns after the existing station timestamp columns (after line 242)**

```python
    # Logistyka - decyzja o transporcie
    override_delivery_method = Column(String(255), nullable=True, comment='Nadpisanie metody dostawy (kurier_baselinker / transport_woodpower)')
    logistics_completed_at = Column(DateTime, nullable=True, index=True, comment='Timestamp zatwierdzenia decyzji logistycznej')
```

- [ ] **Step 3: Modify `complete_task()` to intercept transition to packaging**

In `models.py` at line 602, the `next_status_map` defines transitions. Modify the method to route non-pickup orders through logistics:

```python
    def complete_task(self, station_code):
        # ... existing docstring ...
        now = get_local_now()
        skipped_cutting = False

        # Mapowanie stanowisko -> następny status
        next_status_map = {
            'cutting': 'czeka_na_skladanie',
            'assembly': 'czeka_na_sklejanie',
            'gluing': 'czeka_na_formatowanie',
            'formatting': 'czeka_na_wykanczanie',
            'finishing': 'czeka_na_logistyke',   # CHANGED: finishing -> logistics (not packaging)
            'packaging': 'spakowane'
        }

        if station_code in next_status_map:
            next_status = next_status_map[station_code]

            # ... existing assembly skip logic (unchanged) ...

            # Specjalna logika: produkty "Surowe" pomijają stanowisko wykańczania
            skipped_finishing = False
            if station_code == 'formatting' and self.should_skip_finishing():
                next_status = 'czeka_na_logistyke'  # CHANGED: was czeka_na_pakowanie
                skipped_finishing = True
                self.quantity_done_finishing = self.quantity
                if self.finishing_completed_at is None:
                    self.finishing_completed_at = now
                # ... existing logging ...

            # NEW: Logistyka — odbiór osobisty omija stanowisko logistyki
            if next_status == 'czeka_na_logistyke' and self.is_personal_pickup:
                next_status = 'czeka_na_pakowanie'
                self.logistics_completed_at = now  # Mark as auto-completed
                logger.info("Odbiór osobisty - pomijam logistykę", extra={
                    'product_id': self.short_product_id
                })

            self.current_status = next_status
            # ... rest unchanged ...
```

The key changes:
1. Line 607: `'finishing': 'czeka_na_logistyke'` (was `czeka_na_pakowanie`)
2. Line 629: `next_status = 'czeka_na_logistyke'` (was `czeka_na_pakowanie`)
3. New block: if `next_status == 'czeka_na_logistyke'` and `is_personal_pickup`, skip to `czeka_na_pakowanie`

- [ ] **Step 4: Commit**

```bash
git add modules/production/models.py
git commit -m "feat: add logistics station — new columns, status, and routing in complete_task()"
```

---

### Task 2: Create logistics API endpoints

**Files:**
- Create: `modules/production/routers/api/logistics_api.py`
- Modify: `modules/production/routers/api/__init__.py`

- [ ] **Step 1: Create logistics_api.py**

```python
# modules/production/routers/api/logistics_api.py
"""
Logistics station API endpoints.
Lists orders awaiting transport decision and handles approval.
"""
from datetime import datetime
from flask import request, jsonify
from flask_login import login_required, current_user
from extensions import db
from sqlalchemy import func
from modules.logging import get_structured_logger

from . import api_bp
from ...models import ProductionItem, get_local_now

logger = get_structured_logger('production.api.logistics')


@api_bp.route('/logistics/orders', methods=['GET'])
@login_required
def logistics_orders():
    """GET /production/api/logistics/orders — list orders awaiting logistics decision"""
    try:
        items = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_logistyke'
        ).order_by(ProductionItem.deadline_date.asc()).all()

        # Group by order
        orders_map = {}
        for item in items:
            key = item.internal_order_number or str(item.id)
            if key not in orders_map:
                orders_map[key] = {
                    'order_number': item.internal_order_number,
                    'baselinker_order_id': item.baselinker_order_id,
                    'client_name': item.client_name or 'Brak danych',
                    'delivery_method': item.delivery_method or 'Nieokreślony',
                    'delivery_address': item.delivery_address or '',
                    'delivery_city': item.delivery_city or '',
                    'delivery_postcode': item.delivery_postcode or '',
                    'delivery_country_code': item.delivery_country_code or 'PL',
                    'production_notes': item.production_notes or '',
                    'products': [],
                    'total_volume': 0.0,
                    'total_products': 0,
                    'deadline': None,
                }
            orders_map[key]['products'].append({
                'id': item.id,
                'short_product_id': item.short_product_id,
                'original_product_name': item.original_product_name or '',
                'volume_m3': float(item.volume_m3 or 0),
                'quantity': item.quantity or 1,
            })
            orders_map[key]['total_volume'] += float(item.volume_m3 or 0)
            orders_map[key]['total_products'] += 1
            if item.deadline_date:
                current_deadline = orders_map[key]['deadline']
                iso = item.deadline_date.isoformat()
                if current_deadline is None or iso < current_deadline:
                    orders_map[key]['deadline'] = iso

        orders = sorted(orders_map.values(), key=lambda x: x.get('deadline') or '9999')

        return jsonify({
            'success': True,
            'orders': orders,
            'total_orders': len(orders)
        })

    except Exception as e:
        logger.error(f"Błąd logistics/orders: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/logistics/approve', methods=['POST'])
@login_required
def logistics_approve():
    """POST /production/api/logistics/approve — approve transport method for an order"""
    try:
        data = request.get_json()
        order_number = data.get('order_number')
        transport_method = data.get('transport_method')

        if not order_number or not transport_method:
            return jsonify({'success': False, 'error': 'Brak wymaganych pól'}), 400

        if transport_method not in ('kurier_baselinker', 'transport_woodpower'):
            return jsonify({'success': False, 'error': 'Nieprawidłowa metoda transportu'}), 400

        items = ProductionItem.query.filter(
            ProductionItem.internal_order_number == order_number,
            ProductionItem.current_status == 'czeka_na_logistyke'
        ).all()

        if not items:
            return jsonify({'success': False, 'error': 'Nie znaleziono produktów do zatwierdzenia'}), 404

        now = get_local_now()
        for item in items:
            item.override_delivery_method = transport_method
            item.logistics_completed_at = now
            item.current_status = 'czeka_na_pakowanie'

        db.session.commit()

        logger.info("Zatwierdzono logistykę", extra={
            'order_number': order_number,
            'transport_method': transport_method,
            'products_count': len(items),
            'user': current_user.username
        })

        return jsonify({
            'success': True,
            'message': f'Zatwierdzono {len(items)} produktów',
            'transport_method': transport_method
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Błąd logistics/approve: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/logistics/update-notes', methods=['POST'])
@login_required
def logistics_update_notes():
    """POST /production/api/logistics/update-notes — update production notes for order"""
    try:
        data = request.get_json()
        order_number = data.get('order_number')
        notes = data.get('notes', '')

        items = ProductionItem.query.filter(
            ProductionItem.internal_order_number == order_number
        ).all()

        if not items:
            return jsonify({'success': False, 'error': 'Zamówienie nie znalezione'}), 404

        for item in items:
            item.production_notes = notes

        db.session.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
```

- [ ] **Step 2: Register in api/__init__.py**

Add after the last import line in `modules/production/routers/api/__init__.py`:

```python
from . import logistics_api
```

- [ ] **Step 3: Commit**

```bash
git add modules/production/routers/api/logistics_api.py modules/production/routers/api/__init__.py
git commit -m "feat: logistics API — list orders, approve transport, update notes"
```

---

### Task 3: Add logistics page route and template

**Files:**
- Modify: `modules/production/routers/main_routers.py`
- Create: `modules/production/templates/logistics/logistics.html`

- [ ] **Step 1: Add route in main_routers.py**

Add a new route for the logistics page:

```python
@main_bp.route('/logistics')
@login_required
def logistics():
    """Strona stanowiska Logistyka — decyzja o transporcie"""
    return render_template('logistics/logistics.html')
```

- [ ] **Step 2: Create logistics.html template**

Create `modules/production/templates/logistics/logistics.html` — a standalone page using IL design system. The page fetches data from `/production/api/logistics/orders` via JS and renders order cards. Each card shows client info, address, delivery method, products list, volume, notes (editable), and a transport method select with approve button.

The template should:
- Extend the sidebar layout (include sidebar.html)
- Load production-panel.css for IL styling
- Fetch orders on page load via fetch()
- Render cards dynamically
- Handle approve button click → POST to /production/api/logistics/approve
- Handle notes editing → POST to /production/api/logistics/update-notes
- Show empty state when no orders pending
- Auto-refresh every 60s

- [ ] **Step 3: Commit**

```bash
git add modules/production/routers/main_routers.py modules/production/templates/logistics/logistics.html
git commit -m "feat: logistics page — route and template with IL design"
```

---

### Task 4: Add logistics card to dashboard

**Files:**
- Modify: `modules/production/templates/components/dashboard-tab-content.html`
- Modify: `modules/production/routers/api/dashboard_api.py`
- Modify: `modules/production/static/css/production-panel.css`

- [ ] **Step 1: Add logistics stats to dashboard API**

In `dashboard_api.py`, in the section where station stats are built (around line 55-75), add a case for `czeka_na_logistyke`:

```python
            elif status == 'czeka_na_logistyke':
                stations_stats['logistics'] = {
                    'waiting_count': count,
                    'avg_priority': round(avg_priority or 0, 1)
                }
```

Also add logistics pending count query where other station pending counts are computed (around line 960):

```python
        # Logistics stats
        logistics_pending = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_logistyke'
        ).count()
        dashboard_stats['logistics'] = {
            'pending_count': logistics_pending
        }
```

- [ ] **Step 2: Add logistics card to dashboard template**

In `dashboard-tab-content.html`, after the packaging station card (line 242) and before the grid closing `</div>` (line 244), insert a lighter logistics card:

```html
        {# LOGISTICS — light card, not a full station #}
        <div class="il-logistics-card">
          <div class="il-logistics-header">
            <span class="il-logistics-name"><i class="fas fa-truck me-2"></i>Logistyka</span>
            <div class="il-station-actions">
              <span class="il-logistics-count" id="logistics-pending-count">{{ dashboard_stats.logistics.pending_count|default(0) }}</span>
              <a href="{{ url_for('production.production_main.logistics') }}" class="il-station-link" title="Otwórz stanowisko"><i class="fas fa-external-link-alt"></i></a>
            </div>
          </div>
          <div class="il-logistics-body">
            <span class="il-logistics-label">zamówień oczekuje na decyzję transportową</span>
          </div>
        </div>
```

- [ ] **Step 3: Add CSS for logistics card**

In `production-panel.css`, add after the station styles:

```css
/* ─── Logistics Card (lighter than full station) ─── */
--il-station-log: #6366f1;

.il-logistics-card {
  border: 1px solid var(--il-border);
  border-radius: var(--il-radius, 3px);
  overflow: hidden;
  grid-column: 1 / -1;
}

.il-logistics-header {
  padding: 7px 12px;
  display: flex;
  align-items: center;
  background: var(--il-station-log, #6366f1);
}

.il-logistics-name {
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: #fff;
}

.il-logistics-count {
  font-family: 'JetBrains Mono', monospace;
  font-size: 16px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
  background: rgba(255, 255, 255, 0.2);
  padding: 2px 10px;
  border-radius: var(--il-radius, 3px);
}

.il-logistics-body {
  padding: 10px 12px;
  background: var(--il-bg-card);
}

.il-logistics-label {
  font-size: 12px;
  color: var(--il-text-secondary);
}
```

- [ ] **Step 4: Commit**

```bash
git add modules/production/templates/components/dashboard-tab-content.html modules/production/routers/api/dashboard_api.py modules/production/static/css/production-panel.css
git commit -m "feat: logistics card on dashboard with pending count"
```

---

### Task 5: Update JS — status config, timeline, progress

**Files:**
- Modify: `modules/production/static/js/modules/products-module.js`

- [ ] **Step 1: Add logistics to STATUS_CONFIG (around line 51)**

Add after `czeka_na_wykanczanie` entries:

```javascript
'czeka_na_logistyke': { icon: 'fa-truck', displayName: 'Logistyka', color: 'logistics-theme', badgeClass: 'badge-logistics' },
```

- [ ] **Step 2: Add logistics to getStatusConfig() (around line 3956)**

Add entries in the configs object:

```javascript
'czeka_na_logistyke': {
    icon: 'fa-truck',
    displayName: 'Logistyka',
    color: 'logistics-theme',
    cssClass: 'logistics'
},
```

- [ ] **Step 3: Add logistics to STATUS_TRANSLATIONS (around line 31)**

```javascript
'czeka_na_logistyke': 'Logistyka',
```

- [ ] **Step 4: Add logistics step to timeline (generateProductionTimeline stations array)**

Insert between finishing and packaging:

```javascript
{
    code: 'logistics',
    name: 'Logistyka',
    status: 'czeka_na_logistyke',
    icon: 'fas fa-truck',
    color: 'logistics-theme',
    startField: null,
    endField: 'logistics_completed_at',
    durationField: null
},
```

- [ ] **Step 5: Update getTimelineState for logistics**

In the `stationOrder` array and `endFields`/`statusMap` maps, add logistics between finishing and packaging:

```javascript
const stationOrder = ['cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'logistics', 'packaging'];
const endFields = {
    // ... existing ...
    'logistics': 'logistics_completed_at',
};
const statusMap = {
    // ... existing ...
    'logistics': 'czeka_na_logistyke',
};
```

Also add special skip logic: if `is_personal_pickup` is true on the product, logistics shows as "Pominięto".

- [ ] **Step 6: Update generateQuantityProgress stations array**

Add 'logistics' to the stations array (now 7 stations instead of 6):

```javascript
const stations = ['cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'logistics', 'packaging'];
```

And add logistics to endFields and statusMap in that function.

- [ ] **Step 7: Commit**

```bash
git add modules/production/static/js/modules/products-module.js
git commit -m "feat: logistics in JS — status config, timeline step, progress calculation"
```

---

### Task 6: Add logistics_completed_at to API product responses

**Files:**
- Modify: `modules/production/routers/api/products_api.py`

- [ ] **Step 1: Add logistics fields to products-tab-content response**

In the product_dict construction (around line 643), add after packaging fields:

```python
'logistics_completed_at': get_attr(product, 'logistics_completed_at').isoformat() if get_attr(product, 'logistics_completed_at') else None,
'override_delivery_method': get_attr(product, 'override_delivery_method', None),
'is_personal_pickup': product.is_personal_pickup,
```

- [ ] **Step 2: Also add to products-filtered response**

Find the similar product_dict in the products-filtered endpoint and add the same fields.

- [ ] **Step 3: Update packaging station to show override_delivery_method**

In the packaging station's AJAX data (stations/ajax.py), if `override_delivery_method` is set on a product, use it instead of `delivery_method` for display.

- [ ] **Step 4: Commit**

```bash
git add modules/production/routers/api/products_api.py
git commit -m "feat: add logistics fields to product API responses"
```

---

### Task 7: Database migration

- [ ] **Step 1: Run the app to trigger auto-migration or create columns manually**

Since this project uses `flask setup-db` or auto-setup, add the columns to the database:

```sql
ALTER TABLE production_items ADD COLUMN override_delivery_method VARCHAR(255) NULL;
ALTER TABLE production_items ADD COLUMN logistics_completed_at DATETIME NULL;
CREATE INDEX ix_production_items_logistics_completed_at ON production_items (logistics_completed_at);
```

Or if using Flask-SQLAlchemy auto-create, just restart the app.

- [ ] **Step 2: Verify columns exist**

```bash
python -c "from modules.production.models import ProductionItem; print([c.name for c in ProductionItem.__table__.columns if 'logistics' in c.name or 'override' in c.name])"
```

Expected: `['override_delivery_method', 'logistics_completed_at']`

- [ ] **Step 3: Commit any migration files if generated**

```bash
git add -A
git commit -m "feat: database migration for logistics columns"
```

---

### Task 8: Manual testing

- [ ] **Step 1: Verify flow for non-pickup order**

Complete a non-pickup order through finishing → should land on `czeka_na_logistyke` (not `czeka_na_pakowanie`)

- [ ] **Step 2: Verify flow for pickup order**

Complete a pickup order through finishing → should skip logistics and go to `czeka_na_pakowanie`

- [ ] **Step 3: Test logistics page**

Navigate to `/production/logistics` → should show pending orders with delivery info, empty select, approve button disabled

- [ ] **Step 4: Test approval**

Select transport method, click approve → order should move to `czeka_na_pakowanie` with `override_delivery_method` set

- [ ] **Step 5: Verify dashboard card**

Check dashboard → logistics card shows correct pending count with link

- [ ] **Step 6: Verify timeline**

Open product detail modal → timeline shows "Logistyka" step between finishing and packaging with correct state
