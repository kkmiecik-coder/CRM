# DXF Import to Calculator - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Importuj DXF" button to the calculator that opens a modal for uploading DXF files, parses them server-side, and creates products in the calculator from extracted shapes and dimensions.

**Architecture:** Backend endpoint receives DXF file, uses ezdxf to extract closed polylines/circles, classifies shapes (rectangle/triangle/trapezoid/circle/polygon), returns JSON array of products. Frontend modal shows dropzone → loading → product cards with editable dimensions. On confirm, products are injected into the calculator via existing `addNewProduct()` + `ShapeEditor.restore()` API.

**Tech Stack:** Python (ezdxf, Flask), JavaScript (DOM manipulation, fetch API), CSS (modal, dropzone, product cards)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `modules/calculator/services/dxf_import_service.py` | Create | Parse DXF, classify shapes, return product data |
| `modules/calculator/routers/main_routers.py` | Modify | Add `POST /calculator/api/import-dxf` endpoint |
| `modules/calculator/templates/calculator.html` | Modify | Add import button + modal HTML |
| `modules/calculator/static/js/dxf-import.js` | Create | Modal logic, dropzone, product cards, injection into calculator |
| `modules/calculator/static/css/dxf_import.css` | Create | Modal and card styles |

---

### Task 1: DXF Import Service (Backend Parser)

**Files:**
- Create: `modules/calculator/services/dxf_import_service.py`

- [ ] **Step 1: Create the import service with shape classification**

```python
# modules/calculator/services/dxf_import_service.py
"""
DXF Import Service
Parsuje pliki DXF i wyodrębnia kształty produktów z wymiarami.
"""

import math
from io import BytesIO
import ezdxf
from ezdxf import path as ezdxf_path
from ezdxf import bbox as ezdxf_bbox


# Jednostki DXF → mnożnik do mm
UNIT_TO_MM = {
    0: None,   # nieokreślone
    1: 25.4,   # cale
    2: 304.8,  # stopy
    4: 1.0,    # mm
    5: 10.0,   # cm
    6: 1000.0, # m
}


def parse_dxf(file_bytes):
    """
    Parsuje plik DXF i zwraca listę wykrytych produktów.

    Args:
        file_bytes: bajty pliku DXF

    Returns:
        dict z kluczami:
          - products: lista produktów (shape, vertices, dimensions, etc.)
          - units: wykryta jednostka ('mm', 'cm', lub None)
          - layer_names: lista nazw warstw
    """
    doc = ezdxf.read(BytesIO(file_bytes))
    msp = doc.modelspace()

    # Wykryj jednostki
    raw_units = doc.header.get('$INSUNITS', 0)
    units_label = {4: 'mm', 5: 'cm', 6: 'm'}.get(raw_units)
    scale = UNIT_TO_MM.get(raw_units, 1.0) or 1.0  # fallback: traktuj jako mm

    # Zbierz nazwy warstw
    layer_names = [layer.dxf.name for layer in doc.layers]

    products = []

    # 1) Zamknięte polyline
    for entity in msp.query('LWPOLYLINE'):
        if not entity.is_closed:
            continue
        points_raw = list(entity.get_points(format='xy'))
        if len(points_raw) < 3:
            continue

        # Konwertuj do mm
        points_mm = [(x * scale, y * scale) for x, y in points_raw]
        product = _classify_polygon(points_mm, entity.dxf.layer)
        if product:
            products.append(product)

    # 2) Koła
    for entity in msp.query('CIRCLE'):
        radius_mm = entity.dxf.radius * scale
        diameter_mm = radius_mm * 2
        center = entity.dxf.center
        products.append({
            'shape_type': 'circle',
            'diameter_mm': round(diameter_mm, 1),
            'area_mm2': round(math.pi * radius_mm ** 2, 1),
            'bbox_width_mm': round(diameter_mm, 1),
            'bbox_height_mm': round(diameter_mm, 1),
            'layer': entity.dxf.layer,
            'vertices': None,
            'params': {'diameter': round(diameter_mm / 10, 2)},  # cm
        })

    return {
        'products': products,
        'units': units_label,
        'layer_names': layer_names,
    }


def _classify_polygon(points_mm, layer):
    """Klasyfikuje zamkniętą polyline na typ kształtu kalkulatora."""
    n = len(points_mm)

    # Normalizuj — przesuń do (0,0)
    min_x = min(p[0] for p in points_mm)
    min_y = min(p[1] for p in points_mm)
    pts = [(round(p[0] - min_x, 2), round(p[1] - min_y, 2)) for p in points_mm]

    bbox_w = max(p[0] for p in pts)
    bbox_h = max(p[1] for p in pts)
    area = abs(_shoelace(pts))

    # Konwertuj wierzchołki do cm
    vertices_cm = [(round(x / 10, 2), round(y / 10, 2)) for x, y in pts]
    bbox_w_cm = round(bbox_w / 10, 2)
    bbox_h_cm = round(bbox_h / 10, 2)

    base = {
        'bbox_width_mm': round(bbox_w, 1),
        'bbox_height_mm': round(bbox_h, 1),
        'area_mm2': round(area, 1),
        'layer': layer,
        'vertices_cm': vertices_cm,
    }

    if n == 3:
        return {**base, **_classify_triangle(pts, vertices_cm, bbox_w_cm, bbox_h_cm)}

    if n == 4:
        # Sprawdź prostokąt
        if _is_rectangle(pts, bbox_w, bbox_h, area):
            return {
                **base,
                'shape_type': 'rectangular',
                'params': {'length': bbox_w_cm, 'width': bbox_h_cm},
            }
        # Sprawdź równoległobok / trapez
        return {**base, **_classify_quadrilateral(pts, vertices_cm, bbox_w_cm, bbox_h_cm)}

    # Wielokąt
    return {
        **base,
        'shape_type': 'polygon',
        'params': {},
    }


def _is_rectangle(pts, bbox_w, bbox_h, area, tol=0.5):
    """Sprawdza czy 4-kąt jest prostokątem (pole ≈ bbox_w * bbox_h)."""
    expected_area = bbox_w * bbox_h
    return abs(area - expected_area) < tol * max(bbox_w, bbox_h)


def _classify_triangle(pts, vertices_cm, bbox_w_cm, bbox_h_cm):
    """Klasyfikuje trójkąt."""
    sides = []
    for i in range(3):
        j = (i + 1) % 3
        dx = pts[j][0] - pts[i][0]
        dy = pts[j][1] - pts[i][1]
        sides.append(math.sqrt(dx*dx + dy*dy))

    sides_sorted = sorted(sides)
    a, b, c = sides_sorted
    tol = 0.5  # mm

    sides_cm = [round(s / 10, 2) for s in sides]

    # Równoboczny
    if abs(a - c) < tol:
        return {
            'shape_type': 'triangle_equilateral',
            'params': {'side': round(a / 10, 2)},
        }

    # Prostokątny (a² + b² ≈ c²)
    if abs(a*a + b*b - c*c) < tol * c:
        return {
            'shape_type': 'triangle_right',
            'params': {'legA': round(a / 10, 2), 'legB': round(b / 10, 2)},
        }

    # Równoramienny
    if abs(a - b) < tol or abs(b - c) < tol:
        base_s = a if abs(b - c) < tol else c
        arm_s = b if abs(b - c) < tol else a
        return {
            'shape_type': 'triangle_isosceles',
            'params': {'base': round(base_s / 10, 2), 'arm': round(arm_s / 10, 2)},
        }

    # Dowolny
    return {
        'shape_type': 'triangle_custom',
        'params': {'sideA': sides_cm[0], 'sideB': sides_cm[1], 'sideC': sides_cm[2]},
    }


def _classify_quadrilateral(pts, vertices_cm, bbox_w_cm, bbox_h_cm):
    """Klasyfikuje czworokąt (trapez / równoległobok)."""
    # Sprawdź równoległe boki
    edges = []
    for i in range(4):
        j = (i + 1) % 4
        dx = pts[j][0] - pts[i][0]
        dy = pts[j][1] - pts[i][1]
        length = math.sqrt(dx*dx + dy*dy)
        angle = math.atan2(dy, dx)
        edges.append({'dx': dx, 'dy': dy, 'length': length, 'angle': angle})

    tol = 0.02  # rad tolerance

    # Sprawdź czy naprzeciwległe boki są równoległe
    pair_02 = abs(abs(edges[0]['angle'] - edges[2]['angle']) - math.pi) < tol or \
              abs(edges[0]['angle'] - edges[2]['angle']) < tol
    pair_13 = abs(abs(edges[1]['angle'] - edges[3]['angle']) - math.pi) < tol or \
              abs(edges[1]['angle'] - edges[3]['angle']) < tol

    if pair_02 and pair_13:
        # Równoległobok
        side_a_cm = round(edges[0]['length'] / 10, 2)
        side_b_cm = round(edges[1]['length'] / 10, 2)
        angle_deg = round(abs(edges[0]['angle'] - edges[1]['angle']) * 180 / math.pi, 1)
        if angle_deg > 90:
            angle_deg = 180 - angle_deg
        return {
            'shape_type': 'parallelogram',
            'params': {'sideA': side_a_cm, 'sideB': side_b_cm, 'angle': angle_deg},
        }

    if pair_02 or pair_13:
        # Trapez — jeden zestaw równoległych boków
        if pair_02:
            base_a = edges[0]['length']
            base_b = edges[2]['length']
        else:
            base_a = edges[1]['length']
            base_b = edges[3]['length']

        if base_a < base_b:
            base_a, base_b = base_b, base_a

        height = bbox_h_cm * 10  # mm — przybliżenie
        offset = abs(pts[3][0] - pts[0][0])

        return {
            'shape_type': 'trapezoid_asymmetric',
            'params': {
                'baseA': round(base_a / 10, 2),
                'baseB': round(base_b / 10, 2),
                'height': round(height / 10, 2),
                'offset': round(offset / 10, 2),
            },
        }

    # Dowolny czworokąt → polygon
    return {
        'shape_type': 'polygon',
        'params': {},
    }


def _shoelace(pts):
    """Pole wielokąta metodą sznurowadła."""
    n = len(pts)
    area = 0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return area / 2
```

- [ ] **Step 2: Test the service**

```bash
cd C:/Users/Grafik/Desktop/Github/CRM/CRM
source venv/Scripts/activate
python -c "
from modules.calculator.services.dxf_import_service import parse_dxf
import ezdxf
from io import BytesIO

# Utwórz testowy DXF z prostokątem i kołem
doc = ezdxf.new('R2010')
doc.header['\$INSUNITS'] = 4  # mm
msp = doc.modelspace()
msp.add_lwpolyline([(0,0),(1200,0),(1200,600),(0,600)], close=True)
msp.add_circle((2000, 400), 400)
msp.add_lwpolyline([(3000,0),(3800,0),(3000,600)], close=True)

from io import StringIO
buf = StringIO()
doc.write(buf, fmt='asc')
file_bytes = buf.getvalue().encode('utf-8')

result = parse_dxf(file_bytes)
for p in result['products']:
    print(f\"{p['shape_type']}: bbox={p['bbox_width_mm']}x{p['bbox_height_mm']}mm, params={p['params']}\")
print(f\"Units: {result['units']}\")
"
```

- [ ] **Step 3: Commit**

```bash
git add modules/calculator/services/dxf_import_service.py
git commit -m "feat(dxf-import): add DXF parsing service with shape classification"
```

---

### Task 2: Backend Endpoint

**Files:**
- Modify: `modules/calculator/routers/main_routers.py`

- [ ] **Step 1: Add import endpoint**

Add at the end of `main_routers.py`:

```python
@calculator_bp.route("/api/import-dxf", methods=["POST"])
def import_dxf():
    """Parsuje wgrany plik DXF i zwraca wykryte produkty."""
    from modules.calculator.services.dxf_import_service import parse_dxf

    if 'file' not in request.files:
        return jsonify({"error": "Brak pliku"}), 400

    file = request.files['file']
    if not file.filename or not file.filename.lower().endswith('.dxf'):
        return jsonify({"error": "Wymagany plik .dxf"}), 400

    # Max 10 MB
    file_bytes = file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        return jsonify({"error": "Plik za duży (max 10 MB)"}), 400

    try:
        result = parse_dxf(file_bytes)
        return jsonify(result)
    except Exception as e:
        import sys, traceback
        print(f"[DXF Import] Błąd parsowania: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": "Błąd parsowania pliku DXF", "details": str(e)}), 500
```

Ensure `request` and `jsonify` are imported (they should be already).

- [ ] **Step 2: Test the endpoint manually**

Run Flask app and test with curl or browser dev tools.

- [ ] **Step 3: Commit**

```bash
git add modules/calculator/routers/main_routers.py
git commit -m "feat(dxf-import): add POST /calculator/api/import-dxf endpoint"
```

---

### Task 3: CSS Styles for Modal

**Files:**
- Create: `modules/calculator/static/css/dxf_import.css`

- [ ] **Step 1: Create modal stylesheet**

```css
/* modules/calculator/static/css/dxf_import.css */

/* ============================================
   DXF IMPORT MODAL
   ============================================ */

.dxf-import-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.5);
    z-index: 9999;
    justify-content: center;
    align-items: center;
}

.dxf-import-overlay.active {
    display: flex;
}

.dxf-import-modal {
    background: #fff;
    border-radius: 12px;
    width: 90%;
    max-width: 720px;
    max-height: 85vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 8px 32px rgba(0,0,0,0.2);
}

.dxf-import-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid #eee;
}

.dxf-import-header h3 {
    margin: 0;
    font-size: 16px;
    font-family: 'Poppins', sans-serif;
    font-weight: 600;
}

.dxf-import-close {
    background: none;
    border: none;
    font-size: 22px;
    cursor: pointer;
    color: #999;
    padding: 0 4px;
}

.dxf-import-close:hover {
    color: #333;
}

.dxf-import-body {
    padding: 20px;
    overflow-y: auto;
    flex: 1;
}

.dxf-import-footer {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    padding: 14px 20px;
    border-top: 1px solid #eee;
}

/* ---- Dropzone ---- */

.dxf-dropzone {
    border: 2px dashed #ccc;
    border-radius: 10px;
    padding: 40px 20px;
    text-align: center;
    cursor: pointer;
    transition: all 0.2s;
}

.dxf-dropzone:hover,
.dxf-dropzone.dragover {
    border-color: #2196F3;
    background: #f0f7ff;
}

.dxf-dropzone-icon {
    font-size: 36px;
    margin-bottom: 8px;
    opacity: 0.5;
}

.dxf-dropzone-text {
    font-size: 14px;
    font-weight: 500;
    color: #333;
}

.dxf-dropzone-hint {
    font-size: 12px;
    color: #999;
    margin-top: 4px;
}

/* ---- Loading ---- */

.dxf-loading {
    display: none;
    text-align: center;
    padding: 40px 20px;
}

.dxf-loading.active {
    display: block;
}

.dxf-spinner {
    width: 36px;
    height: 36px;
    border: 3px solid #eee;
    border-top-color: #2196F3;
    border-radius: 50%;
    animation: dxf-spin 0.7s linear infinite;
    margin: 0 auto 12px;
}

@keyframes dxf-spin {
    to { transform: rotate(360deg); }
}

.dxf-loading-text {
    font-size: 14px;
    color: #666;
}

/* ---- Unit toggle ---- */

.dxf-unit-bar {
    display: none;
    align-items: center;
    gap: 10px;
    margin-bottom: 16px;
    font-size: 13px;
    font-family: 'Poppins', sans-serif;
}

.dxf-unit-bar.active {
    display: flex;
}

.dxf-unit-bar label {
    font-weight: 500;
    color: #555;
}

.dxf-unit-toggle {
    display: inline-flex;
    border: 1px solid #ddd;
    border-radius: 6px;
    overflow: hidden;
}

.dxf-unit-toggle button {
    padding: 5px 14px;
    border: none;
    background: #f5f5f5;
    font-size: 13px;
    font-family: 'Poppins', sans-serif;
    cursor: pointer;
    transition: all 0.15s;
    color: #555;
}

.dxf-unit-toggle button.active {
    background: #2196F3;
    color: #fff;
}

.dxf-unit-toggle button:hover:not(.active) {
    background: #e8e8e8;
}

/* ---- Product cards ---- */

.dxf-products-list {
    display: none;
    flex-direction: column;
    gap: 10px;
}

.dxf-products-list.active {
    display: flex;
}

.dxf-product-card {
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    padding: 14px 16px;
    display: flex;
    align-items: center;
    gap: 14px;
    transition: border-color 0.15s;
}

.dxf-product-card:hover {
    border-color: #2196F3;
}

.dxf-product-card.excluded {
    opacity: 0.4;
}

.dxf-product-check {
    flex-shrink: 0;
}

.dxf-product-check input[type="checkbox"] {
    width: 18px;
    height: 18px;
    cursor: pointer;
    accent-color: #2196F3;
}

.dxf-product-shape-badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    background: #e3f2fd;
    color: #1565c0;
    white-space: nowrap;
}

.dxf-product-dims {
    flex: 1;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
}

.dxf-product-dims .dxf-dim-field {
    display: flex;
    align-items: center;
    gap: 4px;
}

.dxf-product-dims .dxf-dim-field label {
    font-size: 11px;
    color: #888;
    white-space: nowrap;
}

.dxf-product-dims .dxf-dim-field input {
    width: 70px;
    padding: 4px 6px;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 13px;
    font-family: 'Poppins', sans-serif;
    text-align: right;
}

.dxf-product-dims .dxf-dim-field input:focus {
    border-color: #2196F3;
    outline: none;
}

.dxf-dim-unit {
    font-size: 11px;
    color: #999;
}

.dxf-product-layer {
    font-size: 11px;
    color: #aaa;
    white-space: nowrap;
}

/* ---- Footer buttons ---- */

.dxf-btn {
    padding: 8px 18px;
    border: none;
    border-radius: 6px;
    font-size: 13px;
    font-family: 'Poppins', sans-serif;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
}

.dxf-btn-cancel {
    background: #f5f5f5;
    color: #555;
}

.dxf-btn-cancel:hover {
    background: #e8e8e8;
}

.dxf-btn-import {
    background: #2196F3;
    color: #fff;
}

.dxf-btn-import:hover {
    background: #1976D2;
}

.dxf-btn-import:disabled {
    background: #ccc;
    cursor: not-allowed;
}

/* ---- Responsive ---- */

@media (max-width: 600px) {
    .dxf-import-modal {
        width: 95%;
        max-height: 90vh;
    }

    .dxf-product-card {
        flex-direction: column;
        align-items: flex-start;
    }

    .dxf-product-dims {
        width: 100%;
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add modules/calculator/static/css/dxf_import.css
git commit -m "feat(dxf-import): add modal CSS styles"
```

---

### Task 4: Modal HTML in Calculator Template

**Files:**
- Modify: `modules/calculator/templates/calculator.html`

- [ ] **Step 1: Add import button next to "Dodaj produkt"**

In `calculator.html`, after the existing add-product button (around line 95), add:

```html
<button type="button" class="add-product-btn" id="import-dxf-btn" style="border-color:#2196F3; color:#2196F3;">
    <span class="add-product-icon" style="font-weight:normal;">&#8679;</span>
    <span class="add-product-text">Importuj DXF</span>
</button>
```

- [ ] **Step 2: Add modal HTML at the bottom of body (before scripts)**

Before the `<script>` tags, add:

```html
<!-- DXF Import Modal -->
<div class="dxf-import-overlay" id="dxf-import-overlay">
    <div class="dxf-import-modal">
        <div class="dxf-import-header">
            <h3>Importuj plik DXF</h3>
            <button class="dxf-import-close" id="dxf-import-close">&times;</button>
        </div>
        <div class="dxf-import-body">
            <!-- Dropzone -->
            <div class="dxf-dropzone" id="dxf-dropzone">
                <input type="file" id="dxf-file-input" accept=".dxf" hidden>
                <div class="dxf-dropzone-icon">&#128194;</div>
                <div class="dxf-dropzone-text">Kliknij aby wybrać plik DXF</div>
                <div class="dxf-dropzone-hint">lub przeciągnij i upuść (max 10 MB)</div>
            </div>

            <!-- Loading -->
            <div class="dxf-loading" id="dxf-loading">
                <div class="dxf-spinner"></div>
                <div class="dxf-loading-text">Analizowanie pliku DXF...</div>
            </div>

            <!-- Unit toggle + products -->
            <div class="dxf-unit-bar" id="dxf-unit-bar">
                <label>Jednostka pliku:</label>
                <div class="dxf-unit-toggle" id="dxf-unit-toggle">
                    <button type="button" data-unit="mm">mm</button>
                    <button type="button" data-unit="cm" class="active">cm</button>
                </div>
                <span style="font-size:12px;color:#999;">(kalkulator pracuje w cm)</span>
            </div>
            <div class="dxf-products-list" id="dxf-products-list">
                <!-- dynamicznie generowane karty -->
            </div>
        </div>
        <div class="dxf-import-footer" id="dxf-import-footer" style="display:none;">
            <button type="button" class="dxf-btn dxf-btn-cancel" id="dxf-cancel-btn">Anuluj</button>
            <button type="button" class="dxf-btn dxf-btn-import" id="dxf-confirm-btn">Dodaj do kalkulatora</button>
        </div>
    </div>
</div>
```

- [ ] **Step 3: Add CSS and JS imports**

In the `<head>` CSS section add:
```html
<link rel="stylesheet" href="{{ url_for('calculator.static', filename='css/dxf_import.css') }}">
```

In the scripts section (after `edges.js`) add:
```html
<script src="{{ url_for('calculator.static', filename='js/dxf-import.js') }}"></script>
```

- [ ] **Step 4: Commit**

```bash
git add modules/calculator/templates/calculator.html
git commit -m "feat(dxf-import): add import button and modal HTML to calculator"
```

---

### Task 5: Frontend JavaScript (Modal Logic + Product Injection)

**Files:**
- Create: `modules/calculator/static/js/dxf-import.js`

- [ ] **Step 1: Create the full JS module**

```javascript
// dxf-import.js
// Modal obsługi importu DXF → tworzenie produktów w kalkulatorze

(function() {
    'use strict';

    // ============================================
    // SHAPE LABELS
    // ============================================

    const SHAPE_LABELS = {
        rectangular: 'Prostokąt',
        circle: 'Koło',
        triangle_right: 'Trójkąt prostokątny',
        triangle_equilateral: 'Trójkąt równoboczny',
        triangle_isosceles: 'Trójkąt równoramienny',
        triangle_custom: 'Trójkąt dowolny',
        trapezoid_symmetric: 'Trapez symetryczny',
        trapezoid_asymmetric: 'Trapez niesymetryczny',
        parallelogram: 'Równoległobok',
        polygon: 'Wielokąt',
    };

    // ============================================
    // STATE
    // ============================================

    let parsedProducts = [];
    let currentUnit = 'cm'; // 'mm' or 'cm'
    let detectedUnit = null; // from backend

    // ============================================
    // DOM REFS
    // ============================================

    const overlay = () => document.getElementById('dxf-import-overlay');
    const dropzone = () => document.getElementById('dxf-dropzone');
    const fileInput = () => document.getElementById('dxf-file-input');
    const loading = () => document.getElementById('dxf-loading');
    const unitBar = () => document.getElementById('dxf-unit-bar');
    const productsList = () => document.getElementById('dxf-products-list');
    const footer = () => document.getElementById('dxf-import-footer');

    // ============================================
    // MODAL OPEN / CLOSE
    // ============================================

    function openModal() {
        resetModal();
        overlay().classList.add('active');
    }

    function closeModal() {
        overlay().classList.remove('active');
        resetModal();
    }

    function resetModal() {
        parsedProducts = [];
        const dz = dropzone();
        const ld = loading();
        const ub = unitBar();
        const pl = productsList();
        const ft = footer();
        const fi = fileInput();

        if (dz) dz.style.display = '';
        if (ld) ld.classList.remove('active');
        if (ub) ub.classList.remove('active');
        if (pl) { pl.classList.remove('active'); pl.innerHTML = ''; }
        if (ft) ft.style.display = 'none';
        if (fi) fi.value = '';
    }

    // ============================================
    // FILE HANDLING
    // ============================================

    function handleFile(file) {
        if (!file) return;
        if (!file.name.toLowerCase().endsWith('.dxf')) {
            alert('Wymagany plik .dxf');
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            alert('Plik za duży (max 10 MB)');
            return;
        }

        // Show loading
        dropzone().style.display = 'none';
        loading().classList.add('active');

        const formData = new FormData();
        formData.append('file', file);

        fetch('/calculator/api/import-dxf', {
            method: 'POST',
            body: formData,
        })
        .then(res => {
            if (!res.ok) return res.json().then(d => { throw new Error(d.error || 'Błąd serwera'); });
            return res.json();
        })
        .then(data => {
            loading().classList.remove('active');

            if (!data.products || data.products.length === 0) {
                alert('Nie znaleziono kształtów w pliku DXF.\nUpewnij się, że plik zawiera zamknięte polyline lub koła.');
                dropzone().style.display = '';
                return;
            }

            parsedProducts = data.products;
            detectedUnit = data.units;

            // Set unit toggle based on detection
            if (detectedUnit === 'mm') {
                setUnit('mm');
            } else if (detectedUnit === 'cm') {
                setUnit('cm');
            } else {
                // Unknown — default mm (most DXF files from CNC are in mm)
                setUnit('mm');
            }

            renderProducts();
            unitBar().classList.add('active');
            productsList().classList.add('active');
            footer().style.display = 'flex';
        })
        .catch(err => {
            loading().classList.remove('active');
            dropzone().style.display = '';
            alert('Błąd importu: ' + err.message);
            console.error('[DXF Import]', err);
        });
    }

    // ============================================
    // UNIT TOGGLE
    // ============================================

    function setUnit(unit) {
        currentUnit = unit;
        document.querySelectorAll('#dxf-unit-toggle button').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.unit === unit);
        });
        // Re-render product cards with new unit conversion
        if (parsedProducts.length > 0) {
            renderProducts();
        }
    }

    // ============================================
    // RENDER PRODUCT CARDS
    // ============================================

    function renderProducts() {
        const container = productsList();
        container.innerHTML = '';

        parsedProducts.forEach((product, index) => {
            const card = document.createElement('div');
            card.className = 'dxf-product-card';
            card.dataset.index = index;

            // Wartości w cm (kalkulator pracuje w cm)
            let lengthCm, widthCm;
            if (currentUnit === 'mm') {
                lengthCm = round2(product.bbox_width_mm / 10);
                widthCm = round2(product.bbox_height_mm / 10);
            } else {
                lengthCm = round2(product.bbox_width_mm / 10);
                widthCm = round2(product.bbox_height_mm / 10);
            }
            // Note: bbox values from backend are always in mm
            // Conversion happens based on what user selected as the file unit
            // If file is in mm, backend already returns mm values — convert to cm
            // If file is in cm, backend scaled to mm — convert back

            const shapeLabel = SHAPE_LABELS[product.shape_type] || product.shape_type;
            const layerInfo = product.layer && product.layer !== '0' ? product.layer : '';

            card.innerHTML = `
                <div class="dxf-product-check">
                    <input type="checkbox" checked data-dxf-index="${index}">
                </div>
                <span class="dxf-product-shape-badge">${shapeLabel}</span>
                <div class="dxf-product-dims">
                    ${product.shape_type === 'circle' ? `
                        <div class="dxf-dim-field">
                            <label>Średnica</label>
                            <input type="number" step="0.1" value="${round2(product.diameter_mm / 10)}" data-dxf-field="diameter" data-dxf-index="${index}">
                            <span class="dxf-dim-unit">cm</span>
                        </div>
                    ` : `
                        <div class="dxf-dim-field">
                            <label>Dł.</label>
                            <input type="number" step="0.1" value="${lengthCm}" data-dxf-field="length" data-dxf-index="${index}">
                            <span class="dxf-dim-unit">cm</span>
                        </div>
                        <div class="dxf-dim-field">
                            <label>Szer.</label>
                            <input type="number" step="0.1" value="${widthCm}" data-dxf-field="width" data-dxf-index="${index}">
                            <span class="dxf-dim-unit">cm</span>
                        </div>
                    `}
                    <div class="dxf-dim-field">
                        <label>Grub.</label>
                        <input type="number" step="0.1" value="" placeholder="?" data-dxf-field="thickness" data-dxf-index="${index}">
                        <span class="dxf-dim-unit">cm</span>
                    </div>
                    <div class="dxf-dim-field">
                        <label>Ilość</label>
                        <input type="number" step="1" min="1" value="1" data-dxf-field="quantity" data-dxf-index="${index}" style="width:50px;">
                    </div>
                </div>
                ${layerInfo ? `<span class="dxf-product-layer">${layerInfo}</span>` : ''}
            `;

            // Checkbox toggle
            const checkbox = card.querySelector('input[type="checkbox"]');
            checkbox.addEventListener('change', () => {
                card.classList.toggle('excluded', !checkbox.checked);
            });

            container.appendChild(card);
        });
    }

    function round2(val) {
        return Math.round(val * 100) / 100;
    }

    // ============================================
    // INJECT PRODUCTS INTO CALCULATOR
    // ============================================

    function injectProducts() {
        const cards = productsList().querySelectorAll('.dxf-product-card');
        const toImport = [];

        cards.forEach(card => {
            const checkbox = card.querySelector('input[type="checkbox"]');
            if (!checkbox || !checkbox.checked) return;

            const idx = parseInt(card.dataset.index);
            const product = parsedProducts[idx];
            if (!product) return;

            const getVal = (field) => {
                const input = card.querySelector(`input[data-dxf-field="${field}"][data-dxf-index="${idx}"]`);
                return input ? parseFloat(input.value) || 0 : 0;
            };

            toImport.push({
                shapeType: product.shape_type,
                params: product.params,
                vertices_cm: product.vertices_cm || null,
                length: product.shape_type === 'circle' ? getVal('diameter') : getVal('length'),
                width: product.shape_type === 'circle' ? getVal('diameter') : getVal('width'),
                thickness: getVal('thickness'),
                quantity: Math.max(1, Math.round(getVal('quantity'))),
            });
        });

        if (toImport.length === 0) {
            alert('Zaznacz co najmniej jeden produkt do importu.');
            return;
        }

        // Sprawdź grubość
        const missingThickness = toImport.some(p => !p.thickness || p.thickness <= 0);
        if (missingThickness) {
            if (!confirm('Niektóre produkty nie mają uzupełnionej grubości. Kontynuować?')) {
                return;
            }
        }

        closeModal();

        // Inject sequentially with timeouts
        toImport.forEach((item, i) => {
            setTimeout(() => {
                _injectSingleProduct(item);
            }, i * 350);
        });
    }

    function _injectSingleProduct(item) {
        // 1. Dodaj nowy produkt
        if (typeof addNewProduct === 'function') {
            addNewProduct();
        } else {
            console.error('[DXF Import] addNewProduct() not found');
            return;
        }

        // 2. Poczekaj na DOM i ustaw dane
        setTimeout(() => {
            const forms = document.querySelectorAll('.quote-forms .quote-form');
            const form = forms[forms.length - 1];
            if (!form) return;

            const setField = (fieldName, value) => {
                const input = form.querySelector(`[data-field="${fieldName}"]`);
                if (input && value) {
                    input.value = value;
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                }
            };

            // Ustaw wymiary
            if (item.shapeType === 'circle') {
                setField('length', item.length);   // diameter → length field
                setField('width', item.width);
            } else {
                setField('length', item.length);
                setField('width', item.width);
            }
            setField('thickness', item.thickness);
            setField('quantity', item.quantity);

            // Ustaw kształt (jeśli nie prostokąt)
            if (item.shapeType && item.shapeType !== 'rectangular') {
                const shapeSelect = form.querySelector('[data-field="shapeSelect"]');
                if (shapeSelect) {
                    shapeSelect.value = item.shapeType;
                    shapeSelect.dispatchEvent(new Event('change', { bubbles: true }));

                    setTimeout(() => {
                        const editor = form._shapeEditor;
                        if (editor && editor.restore) {
                            editor.restore(item.shapeType, {
                                params: item.params,
                                vertices: item.vertices_cm,
                            });
                        }
                    }, 150);
                }
            }

            // Przelicz ceny
            if (typeof updatePrices === 'function') {
                setTimeout(() => updatePrices(), 200);
            }

        }, 200);
    }

    // ============================================
    // INIT
    // ============================================

    document.addEventListener('DOMContentLoaded', () => {
        // Open modal
        const importBtn = document.getElementById('import-dxf-btn');
        if (importBtn) {
            importBtn.addEventListener('click', openModal);
        }

        // Close modal
        const closeBtn = document.getElementById('dxf-import-close');
        if (closeBtn) closeBtn.addEventListener('click', closeModal);

        const cancelBtn = document.getElementById('dxf-cancel-btn');
        if (cancelBtn) cancelBtn.addEventListener('click', closeModal);

        // Close on overlay click
        const ov = overlay();
        if (ov) {
            ov.addEventListener('click', (e) => {
                if (e.target === ov) closeModal();
            });
        }

        // Dropzone click
        const dz = dropzone();
        const fi = fileInput();
        if (dz && fi) {
            dz.addEventListener('click', () => fi.click());

            fi.addEventListener('change', (e) => {
                if (e.target.files[0]) handleFile(e.target.files[0]);
            });

            // Drag & drop
            dz.addEventListener('dragover', (e) => {
                e.preventDefault();
                dz.classList.add('dragover');
            });
            dz.addEventListener('dragleave', () => {
                dz.classList.remove('dragover');
            });
            dz.addEventListener('drop', (e) => {
                e.preventDefault();
                dz.classList.remove('dragover');
                if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
            });
        }

        // Unit toggle
        document.querySelectorAll('#dxf-unit-toggle button').forEach(btn => {
            btn.addEventListener('click', () => setUnit(btn.dataset.unit));
        });

        // Confirm import
        const confirmBtn = document.getElementById('dxf-confirm-btn');
        if (confirmBtn) {
            confirmBtn.addEventListener('click', injectProducts);
        }
    });

})();
```

- [ ] **Step 2: Test full flow in browser**

1. Open calculator
2. Click "Importuj DXF"
3. Upload a test DXF file
4. Verify product cards appear
5. Toggle mm/cm
6. Adjust thickness
7. Click "Dodaj do kalkulatora"
8. Verify products appear in calculator with correct dimensions and shapes

- [ ] **Step 3: Commit**

```bash
git add modules/calculator/static/js/dxf-import.js
git commit -m "feat(dxf-import): add frontend modal with dropzone, product cards and calculator injection"
```

---

### Task 6: Integration Test & Polish

- [ ] **Step 1: Test with real-world DXF files**

Test various scenarios:
- DXF with only rectangles
- DXF with mixed shapes (rectangles + circles + triangles)
- DXF with units set to mm vs cm vs unspecified
- DXF with multiple layers
- Empty DXF (no closed shapes)
- Large DXF with many entities

- [ ] **Step 2: Final commit**

```bash
git add -A
git commit -m "feat(dxf-import): complete DXF import feature for calculator"
```
