# Calculator Advanced Shapes — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add support for 12 shape types (trapezoids, triangles, parallelograms, polygons) with an interactive canvas editor to the internal calculator, replacing the current rectangular/round radio toggle.

**Architecture:** The feature adds a shape geometry engine (JS module for area/bbox/vertex calculations), a canvas renderer/editor (HTML5 Canvas with hierarchical grid, zoom/pan, vertex drag), replaces the shape radio toggle with a `<select>` dropdown, and extends the quote persistence layer (`shape_data` JSON, `shape_svg`, dynamic edges). Pricing uses bounding box for wood cost and real area for finishing/volume. The existing rectangular/round flow is preserved for backward compatibility.

**Tech Stack:** HTML5 Canvas API, vanilla JavaScript (ES6 modules pattern matching existing codebase), Python/Flask/SQLAlchemy (backend), MySQL (database), Jinja2 templates.

**Spec:** `docs/superpowers/specs/2026-03-16-calculator-advanced-shapes-design.md`

---

## Chunk 1: Database Migration & Shape Geometry Engine

### Task 1: Database Migration — Extend QuoteItemDetails

**Files:**
- Modify: `modules/calculator/models.py` (lines 697-754, QuoteItemDetails class)
- Create: `migrations/010_advanced_shapes.sql` (follows existing `NNN_name.sql` convention)

- [ ] **Step 1: Add new columns to QuoteItemDetails model**

In `modules/calculator/models.py`, find the `QuoteItemDetails` class (around line 697). Make these changes:

1. Change `shape` column from `String(20)` to `String(50)`:
```python
shape = db.Column(db.String(50), default='rectangular')
```

2. Add new columns after `round_surcharge_brutto`:
```python
shape_data = db.Column(db.Text, nullable=True)  # JSON: params, vertices, real_area_cm2, bbox
shape_svg = db.Column(db.Text, nullable=True)    # SVG string for display in quotes/PDF
```

3. Update the `to_dict()` method to include new fields:
```python
'shape_data': self.shape_data,
'shape_svg': self.shape_svg,
```

- [ ] **Step 2: Create database migration script**

Create `migrations/010_advanced_shapes.sql` following the existing `NNN_name.sql` convention:

```sql
ALTER TABLE quote_items_details MODIFY COLUMN shape VARCHAR(50) DEFAULT 'rectangular';
ALTER TABLE quote_items_details ADD COLUMN shape_data TEXT NULL AFTER round_surcharge_brutto;
ALTER TABLE quote_items_details ADD COLUMN shape_svg TEXT NULL AFTER shape_data;
```

- [ ] **Step 3: Test migration locally**

Run the migration against local MySQL (XAMPP). Verify:
- Existing rows retain `shape = 'rectangular'` or `'round'`
- New columns are NULL for existing rows
- Insert a test row with `shape = 'triangle_equilateral'` (21 chars) — must succeed

- [ ] **Step 4: Commit**

```bash
git add modules/calculator/models.py migrations/
git commit -m "feat(calculator): extend QuoteItemDetails for advanced shapes — add shape_data, shape_svg columns, widen shape to String(50)"
```

---

### Task 2: Shape Geometry Engine — Core Module

**Files:**
- Create: `modules/calculator/static/js/shape-geometry.js`

This module provides pure geometry functions: vertex generation from parameters, area calculation, bounding box, and parameter extraction from vertices. No DOM or Canvas dependency — purely mathematical.

- [ ] **Step 1: Create shape-geometry.js with shape configuration registry**

```javascript
// shape-geometry.js
// Pure geometry engine — no DOM/Canvas dependencies
// Provides: vertex generation, area calculation, bounding box, param extraction

const ShapeGeometry = (function() {
    'use strict';

    // ============================================
    // SHAPE REGISTRY
    // ============================================

    const SHAPE_CONFIG = {
        rectangular: {
            label: 'Prostokąt',
            inputs: [
                { key: 'length', label: 'Długość', unit: 'cm' },
                { key: 'width', label: 'Szerokość', unit: 'cm' }
            ],
            defaults: { length: 100, width: 50 },
            hasVertices: true
        },
        circle: {
            label: 'Koło',
            inputs: [
                { key: 'diameter', label: 'Średnica', unit: 'cm' }
            ],
            defaults: { diameter: 80 },
            hasVertices: false
        },
        ellipse: {
            label: 'Elipsa',
            inputs: [
                { key: 'axisA', label: 'Oś A', unit: 'cm' },
                { key: 'axisB', label: 'Oś B', unit: 'cm' }
            ],
            defaults: { axisA: 100, axisB: 60 },
            hasVertices: false
        },
        triangle_right: {
            label: 'Trójkąt prostokątny',
            group: 'Trójkąt',
            inputs: [
                { key: 'legA', label: 'Przyprostokątna A', unit: 'cm' },
                { key: 'legB', label: 'Przyprostokątna B', unit: 'cm' }
            ],
            defaults: { legA: 80, legB: 60 },
            hasVertices: true
        },
        triangle_equilateral: {
            label: 'Trójkąt równoboczny',
            group: 'Trójkąt',
            inputs: [
                { key: 'side', label: 'Bok', unit: 'cm' }
            ],
            defaults: { side: 80 },
            hasVertices: true
        },
        triangle_isosceles: {
            label: 'Trójkąt równoramienny',
            group: 'Trójkąt',
            inputs: [
                { key: 'base', label: 'Podstawa', unit: 'cm' },
                { key: 'arm', label: 'Ramię', unit: 'cm' }
            ],
            defaults: { base: 80, arm: 60 },
            hasVertices: true
        },
        triangle_custom: {
            label: 'Trójkąt dowolny',
            group: 'Trójkąt',
            inputs: [
                { key: 'sideA', label: 'Bok A', unit: 'cm' },
                { key: 'sideB', label: 'Bok B', unit: 'cm' },
                { key: 'sideC', label: 'Bok C', unit: 'cm' }
            ],
            defaults: { sideA: 80, sideB: 70, sideC: 60 },
            hasVertices: true
        },
        trapezoid_symmetric: {
            label: 'Trapez symetryczny',
            group: 'Trapez',
            inputs: [
                { key: 'baseA', label: 'Podstawa A (dłuższa)', unit: 'cm' },
                { key: 'baseB', label: 'Podstawa B (krótsza)', unit: 'cm' },
                { key: 'height', label: 'Wysokość', unit: 'cm' }
            ],
            defaults: { baseA: 120, baseB: 80, height: 40 },
            hasVertices: true
        },
        trapezoid_asymmetric: {
            label: 'Trapez niesymetryczny',
            group: 'Trapez',
            inputs: [
                { key: 'baseA', label: 'Podstawa A (dłuższa)', unit: 'cm' },
                { key: 'baseB', label: 'Podstawa B (krótsza)', unit: 'cm' },
                { key: 'height', label: 'Wysokość', unit: 'cm' },
                { key: 'offset', label: 'Przesunięcie', unit: 'cm' }
            ],
            defaults: { baseA: 120, baseB: 80, height: 40, offset: 10 },
            hasVertices: true
        },
        trapezoid_custom: {
            label: 'Trapez dowolny',
            group: 'Trapez',
            inputs: [
                { key: 'baseA', label: 'Podstawa A (dłuższa)', unit: 'cm' },
                { key: 'baseB', label: 'Podstawa B (krótsza)', unit: 'cm' },
                { key: 'height', label: 'Wysokość', unit: 'cm' },
                { key: 'offset', label: 'Przesunięcie', unit: 'cm' }
            ],
            defaults: { baseA: 120, baseB: 80, height: 40, offset: 15 },
            hasVertices: true
        },
        parallelogram: {
            label: 'Równoległobok',
            inputs: [
                { key: 'sideA', label: 'Bok A', unit: 'cm' },
                { key: 'sideB', label: 'Bok B', unit: 'cm' },
                { key: 'angle', label: 'Kąt', unit: '°' }
            ],
            defaults: { sideA: 100, sideB: 60, angle: 60 },
            hasVertices: true
        },
        polygon: {
            label: 'Wielokąt niestandardowy',
            inputs: [],  // No parameter inputs — canvas only
            defaults: {},
            hasVertices: true,
            maxVertices: 20
        }
    };

    // ============================================
    // VERTEX GENERATION FROM PARAMS
    // ============================================

    function generateVertices(shapeType, params) {
        switch (shapeType) {
            case 'rectangular':
                return _rectVertices(params);
            case 'triangle_right':
                return _triangleRightVertices(params);
            case 'triangle_equilateral':
                return _triangleEquilateralVertices(params);
            case 'triangle_isosceles':
                return _triangleIsoscelesVertices(params);
            case 'triangle_custom':
                return _triangleCustomVertices(params);
            case 'trapezoid_symmetric':
                return _trapezoidSymmetricVertices(params);
            case 'trapezoid_asymmetric':
            case 'trapezoid_custom':
                return _trapezoidAsymmetricVertices(params);
            case 'parallelogram':
                return _parallelogramVertices(params);
            case 'polygon':
                return _defaultPolygonVertices(params);
            case 'circle':
            case 'ellipse':
                return null; // No vertices — parametric curves
            default:
                return null;
        }
    }

    function _rectVertices(p) {
        const l = p.length || 100, w = p.width || 50;
        return [[0, 0], [l, 0], [l, w], [0, w]];
    }

    function _triangleRightVertices(p) {
        const a = p.legA || 80, b = p.legB || 60;
        return [[0, 0], [a, 0], [0, b]];
    }

    function _triangleEquilateralVertices(p) {
        const s = p.side || 80;
        const h = s * Math.sqrt(3) / 2;
        return [[0, 0], [s, 0], [s / 2, h]];
    }

    function _triangleIsoscelesVertices(p) {
        const base = p.base || 80, arm = p.arm || 60;
        const h = Math.sqrt(arm * arm - (base / 2) * (base / 2));
        if (isNaN(h) || h <= 0) return null; // Invalid triangle
        return [[0, 0], [base, 0], [base / 2, h]];
    }

    function _triangleCustomVertices(p) {
        const a = p.sideA || 80, b = p.sideB || 70, c = p.sideC || 60;
        // Validate triangle inequality
        if (a + b <= c || a + c <= b || b + c <= a) return null;
        // Place side A along X axis, compute third vertex
        const cosB = (a * a + c * c - b * b) / (2 * a * c);
        const sinB = Math.sqrt(1 - cosB * cosB);
        return [[0, 0], [a, 0], [c * cosB, c * sinB]];
    }

    function _trapezoidSymmetricVertices(p) {
        const a = p.baseA || 120, b = p.baseB || 80, h = p.height || 40;
        const offset = (a - b) / 2;
        return [[0, 0], [a, 0], [a - offset, h], [offset, h]];
    }

    function _trapezoidAsymmetricVertices(p) {
        const a = p.baseA || 120, b = p.baseB || 80, h = p.height || 40;
        const off = p.offset || 0;
        return [[0, 0], [a, 0], [off + b, h], [off, h]];
    }

    function _parallelogramVertices(p) {
        const a = p.sideA || 100, b = p.sideB || 60;
        const angleRad = (p.angle || 60) * Math.PI / 180;
        const dx = b * Math.cos(angleRad);
        const dy = b * Math.sin(angleRad);
        return [[0, 0], [a, 0], [a + dx, dy], [dx, dy]];
    }

    function _defaultPolygonVertices() {
        // Regular pentagon, radius 50cm
        const n = 5, r = 50, cx = 50, cy = 50;
        const verts = [];
        for (let i = 0; i < n; i++) {
            const angle = (2 * Math.PI * i / n) - Math.PI / 2;
            verts.push([cx + r * Math.cos(angle), cy + r * Math.sin(angle)]);
        }
        return verts;
    }

    // ============================================
    // AREA CALCULATIONS
    // ============================================

    function calculateArea(shapeType, params, vertices) {
        if (shapeType === 'circle') {
            const d = params.diameter || 0;
            return Math.PI * (d / 2) * (d / 2);
        }
        if (shapeType === 'ellipse') {
            const a = params.axisA || 0, b = params.axisB || 0;
            return Math.PI * (a / 2) * (b / 2);
        }
        if (!vertices || vertices.length < 3) return 0;
        return _shoelaceArea(vertices);
    }

    function _shoelaceArea(vertices) {
        let area = 0;
        const n = vertices.length;
        for (let i = 0; i < n; i++) {
            const j = (i + 1) % n;
            area += vertices[i][0] * vertices[j][1];
            area -= vertices[j][0] * vertices[i][1];
        }
        return Math.abs(area) / 2;
    }

    // ============================================
    // BOUNDING BOX
    // ============================================

    function calculateBbox(shapeType, params, vertices) {
        if (shapeType === 'circle') {
            const d = params.diameter || 0;
            return { width: d, height: d };
        }
        if (shapeType === 'ellipse') {
            return { width: params.axisA || 0, height: params.axisB || 0 };
        }
        if (!vertices || vertices.length < 2) return { width: 0, height: 0 };

        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (const [x, y] of vertices) {
            if (x < minX) minX = x;
            if (y < minY) minY = y;
            if (x > maxX) maxX = x;
            if (y > maxY) maxY = y;
        }
        return { width: maxX - minX, height: maxY - minY };
    }

    // ============================================
    // EDGE LENGTHS (for edge pricing)
    // ============================================

    function calculateEdgeLengths(shapeType, params, vertices) {
        if (shapeType === 'circle') {
            const d = params.diameter || 0;
            return [{ id: 'G1', type: 'top', length_cm: Math.PI * d }];
        }
        if (shapeType === 'ellipse') {
            const a = (params.axisA || 0) / 2, b = (params.axisB || 0) / 2;
            // Ramanujan approximation
            const perimeter = Math.PI * (3 * (a + b) - Math.sqrt((3 * a + b) * (a + 3 * b)));
            return [{ id: 'G1', type: 'top', length_cm: perimeter }];
        }
        if (!vertices || vertices.length < 3) return [];

        const edges = [];
        const n = vertices.length;
        for (let i = 0; i < n; i++) {
            const j = (i + 1) % n;
            const dx = vertices[j][0] - vertices[i][0];
            const dy = vertices[j][1] - vertices[i][1];
            const length = Math.sqrt(dx * dx + dy * dy);
            edges.push({ id: `G${i + 1}`, type: 'top', length_cm: length });
        }
        return edges;
    }

    // ============================================
    // VALIDATION
    // ============================================

    function validate(shapeType, params) {
        const errors = [];

        // Common: all numeric params must be > 0
        const config = SHAPE_CONFIG[shapeType];
        if (!config) return ['Nieznany typ kształtu'];

        for (const input of config.inputs) {
            const val = params[input.key];
            if (val === undefined || val === null || val === '') {
                errors.push(`${input.label} jest wymagane`);
            } else if (isNaN(val) || Number(val) <= 0) {
                errors.push(`${input.label} musi być > 0`);
            }
        }
        if (errors.length > 0) return errors;

        // Shape-specific validation
        switch (shapeType) {
            case 'triangle_custom': {
                const a = Number(params.sideA), b = Number(params.sideB), c = Number(params.sideC);
                if (a + b <= c || a + c <= b || b + c <= a) {
                    errors.push('Nieprawidłowe wymiary trójkąta (nierówność trójkąta)');
                }
                break;
            }
            case 'triangle_isosceles': {
                const base = Number(params.base), arm = Number(params.arm);
                if (base >= 2 * arm) {
                    errors.push('Podstawa zbyt długa (musi być < 2 × ramię)');
                }
                break;
            }
            case 'trapezoid_symmetric':
            case 'trapezoid_asymmetric':
            case 'trapezoid_custom': {
                const a = Number(params.baseA), b = Number(params.baseB);
                if (a < b) errors.push('Podstawa A musi być ≥ podstawa B');
                if (params.offset !== undefined) {
                    const off = Number(params.offset);
                    if (off < 0) errors.push('Przesunięcie musi być ≥ 0');
                    if (off > a - b) errors.push('Przesunięcie zbyt duże (max: A - B)');
                }
                break;
            }
            case 'parallelogram': {
                const angle = Number(params.angle);
                if (angle <= 0 || angle >= 180) {
                    errors.push('Kąt musi być między 1° a 179°');
                }
                break;
            }
        }

        return errors;
    }

    // ============================================
    // DETECT SHAPE VARIANT FROM VERTICES
    // ============================================

    const TOLERANCE = 0.5; // cm

    function detectVariant(shapeType, vertices) {
        if (!vertices) return shapeType;

        // Trapezoid variant detection
        if (vertices.length === 4 && shapeType.startsWith('trapezoid')) {
            const bottomLeft = vertices[0][0];
            const bottomRight = vertices[1][0];
            const topRight = vertices[2][0];
            const topLeft = vertices[3][0];
            const leftOffset = topLeft - bottomLeft;
            const rightOffset = bottomRight - topRight;
            if (Math.abs(leftOffset - rightOffset) < TOLERANCE) {
                return 'trapezoid_symmetric';
            }
            return 'trapezoid_asymmetric';
        }

        // Triangle variant detection
        if (vertices.length === 3 && shapeType.startsWith('triangle')) {
            const a = _dist(vertices[0], vertices[1]);
            const b = _dist(vertices[1], vertices[2]);
            const c = _dist(vertices[2], vertices[0]);
            const sides = [a, b, c].sort((x, y) => x - y);

            // Check equilateral: all sides equal
            if (Math.abs(sides[0] - sides[2]) < TOLERANCE) {
                return 'triangle_equilateral';
            }
            // Check isosceles: two sides equal
            if (Math.abs(sides[0] - sides[1]) < TOLERANCE || Math.abs(sides[1] - sides[2]) < TOLERANCE) {
                return 'triangle_isosceles';
            }
            // Check right: Pythagorean theorem (a² + b² ≈ c²)
            if (Math.abs(sides[0]*sides[0] + sides[1]*sides[1] - sides[2]*sides[2]) < TOLERANCE * sides[2]) {
                return 'triangle_right';
            }
            return 'triangle_custom';
        }

        return shapeType;
    }

    // ============================================
    // EXTRACT PARAMS FROM VERTICES
    // ============================================

    function extractParams(shapeType, vertices) {
        if (!vertices) return {};

        switch (shapeType) {
            case 'rectangular': {
                const w = Math.abs(vertices[1][0] - vertices[0][0]);
                const h = Math.abs(vertices[2][1] - vertices[1][1]);
                return { length: _round(w), width: _round(h) };
            }
            case 'triangle_right': {
                const a = _dist(vertices[0], vertices[1]);
                const b = _dist(vertices[0], vertices[2]);
                return { legA: _round(a), legB: _round(b) };
            }
            case 'triangle_equilateral': {
                const s = _dist(vertices[0], vertices[1]);
                return { side: _round(s) };
            }
            case 'triangle_isosceles': {
                const base = _dist(vertices[0], vertices[1]);
                const arm = _dist(vertices[0], vertices[2]);
                return { base: _round(base), arm: _round(arm) };
            }
            case 'triangle_custom': {
                const a = _dist(vertices[0], vertices[1]);
                const b = _dist(vertices[1], vertices[2]);
                const c = _dist(vertices[2], vertices[0]);
                return { sideA: _round(a), sideB: _round(b), sideC: _round(c) };
            }
            case 'trapezoid_symmetric':
            case 'trapezoid_asymmetric':
            case 'trapezoid_custom': {
                const baseA = _dist(vertices[0], vertices[1]);
                const baseB = _dist(vertices[3], vertices[2]);
                const height = Math.abs(vertices[2][1] - vertices[0][1]);
                const offset = vertices[3][0] - vertices[0][0];
                return { baseA: _round(baseA), baseB: _round(baseB), height: _round(height), offset: _round(offset) };
            }
            case 'parallelogram': {
                const a = _dist(vertices[0], vertices[1]);
                const b = _dist(vertices[0], vertices[3]);
                const dx = vertices[3][0] - vertices[0][0];
                const dy = vertices[3][1] - vertices[0][1];
                const angle = Math.atan2(dy, dx) * 180 / Math.PI;
                return { sideA: _round(a), sideB: _round(b), angle: _round(angle) };
            }
            default:
                return {};
        }
    }

    function _dist(p1, p2) {
        const dx = p2[0] - p1[0], dy = p2[1] - p1[1];
        return Math.sqrt(dx * dx + dy * dy);
    }

    function _round(val) {
        return Math.round(val * 10) / 10; // Round to 1 decimal
    }

    // ============================================
    // BUILD shape_data OBJECT FOR PERSISTENCE
    // ============================================

    function buildShapeData(shapeType, params, vertices) {
        const area = calculateArea(shapeType, params, vertices);
        const bbox = calculateBbox(shapeType, params, vertices);
        return {
            params: { ...params },
            vertices: vertices ? vertices.map(v => [_round(v[0]), _round(v[1])]) : null,
            real_area_cm2: _round(area),
            bbox: bbox
        };
    }

    // ============================================
    // PUBLIC API
    // ============================================

    return {
        SHAPE_CONFIG,
        generateVertices,
        calculateArea,
        calculateBbox,
        calculateEdgeLengths,
        validate,
        detectVariant,
        extractParams,
        buildShapeData
    };
})();

// Make globally available (matches existing codebase pattern)
window.ShapeGeometry = ShapeGeometry;
```

- [ ] **Step 2: Verify module loads without errors**

Add `<script src="{{ url_for('calculator.static', filename='js/shape-geometry.js') }}"></script>` to `calculator.html` before `calculator-core.js`. Open the calculator in browser, check console for errors. Verify `window.ShapeGeometry.SHAPE_CONFIG` is accessible.

- [ ] **Step 3: Commit**

```bash
git add modules/calculator/static/js/shape-geometry.js
git commit -m "feat(calculator): add shape geometry engine — vertex generation, area/bbox calculation, validation for 12 shape types"
```

---

## Chunk 2: Canvas Renderer & Editor

### Task 3: Shape Canvas — Grid, Rendering, Interactions

**Files:**
- Create: `modules/calculator/static/js/shape-canvas.js`
- Create: `modules/calculator/static/css/shape_canvas.css`

This module handles all Canvas rendering and user interactions: hierarchical grid, shape drawing, vertex editing, zoom/pan, undo/redo, fit-to-view.

- [ ] **Step 1: Create shape_canvas.css**

```css
/* shape_canvas.css — Canvas editor styles */

.shape-editor-container {
    display: flex;
    gap: 12px;
    margin-bottom: 10px;
}

.shape-inputs-column {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 180px;
    max-width: 200px;
}

.shape-canvas-column {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 280px;
}

.shape-canvas-wrapper {
    position: relative;
    border: 1px solid #ddd;
    border-radius: 6px;
    overflow: hidden;
    background: #1a1a2e;
}

.shape-canvas-wrapper canvas {
    display: block;
    width: 100%;
    cursor: grab;
}

.shape-canvas-wrapper canvas.dragging-vertex {
    cursor: grabbing;
}

.shape-canvas-wrapper canvas.hovering-vertex {
    cursor: pointer;
}

.shape-canvas-scale-indicator {
    position: absolute;
    bottom: 6px;
    left: 8px;
    background: rgba(0, 0, 0, 0.6);
    color: #ccc;
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 3px;
    pointer-events: none;
    font-family: monospace;
}

.shape-canvas-controls {
    display: flex;
    gap: 4px;
}

.shape-canvas-controls button {
    padding: 4px 10px;
    font-size: 12px;
    border: 1px solid #ccc;
    border-radius: 4px;
    background: #fff;
    cursor: pointer;
    color: #333;
}

.shape-canvas-controls button:hover {
    background: #f0f0f0;
    border-color: #999;
}

.shape-canvas-controls button:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}

.shape-input-row {
    display: flex;
    align-items: center;
    gap: 6px;
}

.shape-input-row label {
    font-size: 12px;
    color: #555;
    min-width: 100px;
    white-space: nowrap;
}

.shape-input-row input {
    width: 70px;
    padding: 4px 6px;
    border: 1px solid #ccc;
    border-radius: 4px;
    font-size: 12px;
    text-align: right;
}

.shape-input-row input.error-outline {
    border-color: #e74c3c;
    background: #fef0ef;
}

.shape-input-row .unit {
    font-size: 11px;
    color: #888;
    min-width: 20px;
}

.shape-bbox-info {
    font-size: 11px;
    color: #888;
    margin-top: 4px;
    padding: 4px 6px;
    background: #f8f8f8;
    border-radius: 4px;
}

.shape-validation-error {
    font-size: 11px;
    color: #e74c3c;
    margin-top: 2px;
}

/* Hide canvas column when shape is rectangular and canvas not expanded */
.shape-editor-container.collapsed-canvas .shape-canvas-column {
    display: none;
}

.shape-editor-container.collapsed-canvas .shape-inputs-column {
    max-width: none;
}

/* Polygon: add/remove point hint */
.shape-canvas-hint {
    font-size: 10px;
    color: #888;
    font-style: italic;
    margin-top: 2px;
}
```

- [ ] **Step 2: Create shape-canvas.js — Canvas renderer with grid, shape drawing, interactions**

This is the largest single file. Create `modules/calculator/static/js/shape-canvas.js`:

```javascript
// shape-canvas.js
// Interactive canvas editor for shape geometry
// Dependencies: ShapeGeometry (shape-geometry.js)

const ShapeCanvas = (function() {
    'use strict';

    // ============================================
    // CANVAS INSTANCE FACTORY
    // ============================================

    function create(canvasElement, options) {
        const ctx = canvasElement.getContext('2d');
        const state = {
            // Shape data
            shapeType: options.shapeType || 'rectangular',
            vertices: null,      // [[x,y], ...] in cm
            params: {},          // Current input params

            // View transform
            offsetX: 0,          // Pan offset in pixels
            offsetY: 0,
            scale: 3,            // Pixels per cm (zoom level)

            // Grid
            gridLevels: [0.1, 1, 10, 20, 30, 50, 100], // cm per grid line
            currentGridCm: 1,    // Current minor grid spacing in cm

            // Interaction state
            dragVertex: -1,      // Index of vertex being dragged, -1 = none
            isPanning: false,
            panStartX: 0,
            panStartY: 0,
            hoverVertex: -1,

            // Undo/redo
            undoStack: [],
            redoStack: [],
            maxUndo: 50,

            // Callbacks
            onParamsChange: options.onParamsChange || function() {},
            onShapeTypeChange: options.onShapeTypeChange || function() {},

            // Canvas sizing
            dpr: window.devicePixelRatio || 1,
            width: 0,
            height: 0
        };

        // ============================================
        // CANVAS SIZING
        // ============================================

        function resize() {
            const rect = canvasElement.parentElement.getBoundingClientRect();
            state.width = rect.width;
            state.height = Math.max(200, Math.min(rect.width * 0.6, 350));
            canvasElement.width = state.width * state.dpr;
            canvasElement.height = state.height * state.dpr;
            canvasElement.style.height = state.height + 'px';
            ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
            render();
        }

        // ============================================
        // COORDINATE TRANSFORMS
        // ============================================

        function cmToPixel(cx, cy) {
            return [cx * state.scale + state.offsetX, state.height - (cy * state.scale + state.offsetY)];
        }

        function pixelToCm(px, py) {
            return [(px - state.offsetX) / state.scale, (state.height - py - state.offsetY) / state.scale];
        }

        // ============================================
        // GRID RENDERING
        // ============================================

        function _selectGridSpacing() {
            // Choose grid spacing so minor lines are 15-80px apart
            const minPx = 15, maxPx = 80;
            for (const cm of state.gridLevels) {
                const px = cm * state.scale;
                if (px >= minPx && px <= maxPx) {
                    state.currentGridCm = cm;
                    return;
                }
            }
            // Fallback: pick closest
            state.currentGridCm = state.gridLevels.find(cm => cm * state.scale >= minPx) || 1;
        }

        function _renderGrid() {
            _selectGridSpacing();
            const minor = state.currentGridCm;
            const major = minor * 10;

            // Visible range in cm
            const [cmLeft, cmBottom] = pixelToCm(0, state.height);
            const [cmRight, cmTop] = pixelToCm(state.width, 0);

            // Minor grid lines (darker)
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
            ctx.lineWidth = 0.5;
            _drawGridLines(cmLeft, cmRight, cmBottom, cmTop, minor);

            // Major grid lines (lighter)
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
            ctx.lineWidth = 0.5;
            _drawGridLines(cmLeft, cmRight, cmBottom, cmTop, major);
        }

        function _drawGridLines(cmLeft, cmRight, cmBottom, cmTop, spacing) {
            const startX = Math.floor(cmLeft / spacing) * spacing;
            const startY = Math.floor(cmBottom / spacing) * spacing;

            ctx.beginPath();
            for (let x = startX; x <= cmRight; x += spacing) {
                const [px] = cmToPixel(x, 0);
                ctx.moveTo(px, 0);
                ctx.lineTo(px, state.height);
            }
            for (let y = startY; y <= cmTop; y += spacing) {
                const [, py] = cmToPixel(0, y);
                ctx.moveTo(0, py);
                ctx.lineTo(state.width, py);
            }
            ctx.stroke();
        }

        // ============================================
        // SHAPE RENDERING
        // ============================================

        function _renderShape() {
            if (state.shapeType === 'circle' || state.shapeType === 'ellipse') {
                _renderEllipse();
                return;
            }
            const verts = state.vertices;
            if (!verts || verts.length < 2) return;

            // Fill
            ctx.beginPath();
            const [sx, sy] = cmToPixel(verts[0][0], verts[0][1]);
            ctx.moveTo(sx, sy);
            for (let i = 1; i < verts.length; i++) {
                const [px, py] = cmToPixel(verts[i][0], verts[i][1]);
                ctx.lineTo(px, py);
            }
            ctx.closePath();
            ctx.fillStyle = 'rgba(230, 126, 34, 0.15)';
            ctx.fill();

            // Outline
            ctx.strokeStyle = '#e67e22';
            ctx.lineWidth = 2;
            ctx.stroke();

            // Dimension lines
            _renderDimensionLines(verts);

            // Vertex handles
            _renderVertexHandles(verts);
        }

        function _renderEllipse() {
            const p = state.params;
            const a = (state.shapeType === 'circle' ? (p.diameter || 0) : (p.axisA || 0)) / 2;
            const b = (state.shapeType === 'circle' ? (p.diameter || 0) : (p.axisB || 0)) / 2;
            if (a <= 0 || b <= 0) return;

            const [cx, cy] = cmToPixel(a, b);
            const rx = a * state.scale;
            const ry = b * state.scale;

            ctx.beginPath();
            ctx.ellipse(cx, cy, rx, ry, 0, 0, 2 * Math.PI);
            ctx.fillStyle = 'rgba(230, 126, 34, 0.15)';
            ctx.fill();
            ctx.strokeStyle = '#e67e22';
            ctx.lineWidth = 2;
            ctx.stroke();

            // Dimension: diameter / axes
            if (state.shapeType === 'circle') {
                _renderSingleDimension(0, b, p.diameter, b, p.diameter + ' cm');
            } else {
                _renderSingleDimension(0, b, p.axisA, b, p.axisA + ' cm');
                _renderSingleDimension(a, 0, a, p.axisB, p.axisB + ' cm');
            }

            // Radius handle
            const [hx, hy] = cmToPixel(a * 2, b);
            _drawHandle(hx, hy, state.hoverVertex === 0);
        }

        function _renderVertexHandles(verts) {
            for (let i = 0; i < verts.length; i++) {
                const [px, py] = cmToPixel(verts[i][0], verts[i][1]);
                _drawHandle(px, py, state.hoverVertex === i || state.dragVertex === i);
            }
        }

        function _drawHandle(px, py, isHovered) {
            const r = isHovered ? 7 : 5;
            ctx.beginPath();
            ctx.arc(px, py, r, 0, 2 * Math.PI);
            ctx.fillStyle = isHovered ? '#e67e22' : '#fff';
            ctx.fill();
            ctx.strokeStyle = '#e67e22';
            ctx.lineWidth = 2;
            ctx.stroke();
        }

        // ============================================
        // DIMENSION LINES
        // ============================================

        function _renderDimensionLines(verts) {
            const n = verts.length;
            for (let i = 0; i < n; i++) {
                const j = (i + 1) % n;
                const dx = verts[j][0] - verts[i][0];
                const dy = verts[j][1] - verts[i][1];
                const len = Math.sqrt(dx * dx + dy * dy);
                if (len < 0.1) continue;
                const label = Math.round(len * 10) / 10 + ' cm';
                _renderSingleDimension(verts[i][0], verts[i][1], verts[j][0], verts[j][1], label);
            }
        }

        function _renderSingleDimension(x1, y1, x2, y2, label) {
            const [px1, py1] = cmToPixel(x1, y1);
            const [px2, py2] = cmToPixel(x2, y2);
            const mx = (px1 + px2) / 2;
            const my = (py1 + py2) / 2;

            ctx.save();
            ctx.font = '11px sans-serif';
            ctx.fillStyle = '#e67e22';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';

            // Offset label perpendicular to edge
            const dx = px2 - px1, dy = py2 - py1;
            const len = Math.sqrt(dx * dx + dy * dy);
            if (len < 1) { ctx.restore(); return; }
            const nx = -dy / len * 14, ny = dx / len * 14;

            ctx.fillText(label, mx + nx, my + ny);
            ctx.restore();
        }

        // ============================================
        // SCALE INDICATOR
        // ============================================

        function getScaleLabel() {
            const cm = state.currentGridCm;
            if (cm < 1) return `1 kratka = ${cm * 10} mm`;
            return `1 kratka = ${cm} cm`;
        }

        // ============================================
        // MAIN RENDER
        // ============================================

        function render() {
            ctx.clearRect(0, 0, state.width, state.height);

            // Background
            ctx.fillStyle = '#1a1a2e';
            ctx.fillRect(0, 0, state.width, state.height);

            _renderGrid();
            _renderShape();

            // Update scale indicator
            if (options.scaleIndicator) {
                options.scaleIndicator.textContent = getScaleLabel();
            }
        }

        // ============================================
        // INTERACTIONS: ZOOM
        // ============================================

        canvasElement.addEventListener('wheel', function(e) {
            e.preventDefault();
            const zoomFactor = e.deltaY > 0 ? 0.85 : 1.15;
            const rect = canvasElement.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            // Zoom toward mouse position
            const [cmX, cmY] = pixelToCm(mouseX, mouseY);
            state.scale *= zoomFactor;
            state.scale = Math.max(0.1, Math.min(100, state.scale));
            // Adjust offset to keep mouse point stable
            state.offsetX = mouseX - cmX * state.scale;
            state.offsetY = (state.height - mouseY) - cmY * state.scale;

            render();
        }, { passive: false });

        // ============================================
        // INTERACTIONS: PAN & VERTEX DRAG
        // ============================================

        canvasElement.addEventListener('mousedown', function(e) {
            const rect = canvasElement.getBoundingClientRect();
            const mx = e.clientX - rect.left;
            const my = e.clientY - rect.top;

            if (e.button === 2) {
                // Right click: remove vertex (polygon only)
                _handleRightClick(mx, my);
                return;
            }

            // Check vertex hit
            const vi = _findVertexAt(mx, my);
            if (vi >= 0) {
                state.dragVertex = vi;
                _pushUndo();
                canvasElement.classList.add('dragging-vertex');
                return;
            }

            // Check edge hit for adding point (polygon only)
            if (state.shapeType === 'polygon') {
                const edgeIdx = _findEdgeAt(mx, my);
                if (edgeIdx >= 0 && state.vertices.length < 20) {
                    const [cx, cy] = pixelToCm(mx, my);
                    _pushUndo();
                    state.vertices.splice(edgeIdx + 1, 0, [_round(cx), _round(cy)]);
                    _emitChange();
                    render();
                    return;
                }
            }

            // Pan
            state.isPanning = true;
            state.panStartX = mx - state.offsetX;
            state.panStartY = (state.height - my) - state.offsetY;
            canvasElement.style.cursor = 'grabbing';
        });

        canvasElement.addEventListener('mousemove', function(e) {
            const rect = canvasElement.getBoundingClientRect();
            const mx = e.clientX - rect.left;
            const my = e.clientY - rect.top;

            if (state.dragVertex >= 0) {
                const [cx, cy] = pixelToCm(mx, my);
                // Snap to grid
                const snap = state.currentGridCm;
                const sx = Math.round(cx / snap) * snap;
                const sy = Math.round(cy / snap) * snap;

                if (state.shapeType === 'circle' || state.shapeType === 'ellipse') {
                    _handleEllipseVertexDrag(sx, sy);
                } else {
                    state.vertices[state.dragVertex] = [_round(sx), _round(sy)];
                }
                _emitChange();
                render();
                return;
            }

            if (state.isPanning) {
                state.offsetX = mx - state.panStartX;
                state.offsetY = (state.height - my) - state.panStartY;
                render();
                return;
            }

            // Hover detection
            const vi = _findVertexAt(mx, my);
            if (vi !== state.hoverVertex) {
                state.hoverVertex = vi;
                canvasElement.classList.toggle('hovering-vertex', vi >= 0);
                render();
            }
        });

        canvasElement.addEventListener('mouseup', function() {
            if (state.dragVertex >= 0) {
                state.dragVertex = -1;
                canvasElement.classList.remove('dragging-vertex');
                _detectAndSwitchVariant();
            }
            state.isPanning = false;
            canvasElement.style.cursor = '';
        });

        canvasElement.addEventListener('mouseleave', function() {
            state.isPanning = false;
            state.dragVertex = -1;
            canvasElement.classList.remove('dragging-vertex');
            canvasElement.style.cursor = '';
        });

        // Prevent context menu on right-click
        canvasElement.addEventListener('contextmenu', function(e) {
            e.preventDefault();
        });

        // ============================================
        // VERTEX / EDGE HIT TESTING
        // ============================================

        function _findVertexAt(px, py) {
            const hitR = 12; // pixels
            if (state.shapeType === 'circle' || state.shapeType === 'ellipse') {
                // Single handle on the right edge
                const p = state.params;
                const a = (state.shapeType === 'circle' ? p.diameter : p.axisA) || 0;
                const b = (state.shapeType === 'circle' ? p.diameter : p.axisB) || 0;
                const [hx, hy] = cmToPixel(a, b / 2);
                if (Math.hypot(px - hx, py - hy) < hitR) return 0;
                return -1;
            }
            if (!state.vertices) return -1;
            for (let i = 0; i < state.vertices.length; i++) {
                const [vx, vy] = cmToPixel(state.vertices[i][0], state.vertices[i][1]);
                if (Math.hypot(px - vx, py - vy) < hitR) return i;
            }
            return -1;
        }

        function _findEdgeAt(px, py) {
            if (!state.vertices || state.vertices.length < 2) return -1;
            const hitDist = 8;
            const n = state.vertices.length;
            for (let i = 0; i < n; i++) {
                const j = (i + 1) % n;
                const [x1, y1] = cmToPixel(state.vertices[i][0], state.vertices[i][1]);
                const [x2, y2] = cmToPixel(state.vertices[j][0], state.vertices[j][1]);
                const dist = _pointToSegmentDist(px, py, x1, y1, x2, y2);
                if (dist < hitDist) return i;
            }
            return -1;
        }

        function _pointToSegmentDist(px, py, x1, y1, x2, y2) {
            const dx = x2 - x1, dy = y2 - y1;
            const lenSq = dx * dx + dy * dy;
            if (lenSq === 0) return Math.hypot(px - x1, py - y1);
            let t = ((px - x1) * dx + (py - y1) * dy) / lenSq;
            t = Math.max(0, Math.min(1, t));
            return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
        }

        // ============================================
        // ELLIPSE DRAG
        // ============================================

        function _handleEllipseVertexDrag(cx, cy) {
            if (state.shapeType === 'circle') {
                state.params.diameter = Math.max(1, _round(cx));
            } else {
                state.params.axisA = Math.max(1, _round(cx));
            }
        }

        // ============================================
        // RIGHT CLICK: REMOVE VERTEX
        // ============================================

        function _handleRightClick(mx, my) {
            if (state.shapeType !== 'polygon') return;
            if (!state.vertices || state.vertices.length <= 3) return;
            const vi = _findVertexAt(mx, my);
            if (vi < 0) return;
            _pushUndo();
            state.vertices.splice(vi, 1);
            _emitChange();
            render();
        }

        // ============================================
        // AUTO-DETECT VARIANT CHANGE
        // ============================================

        function _detectAndSwitchVariant() {
            // Only auto-detect for shapes with variants (trapezoids and triangles), skip "custom" variants
            const isVariantShape = state.shapeType.startsWith('trapezoid') || state.shapeType.startsWith('triangle');
            if (!isVariantShape || state.shapeType === 'trapezoid_custom' || state.shapeType === 'triangle_custom') return;
            const detected = ShapeGeometry.detectVariant(state.shapeType, state.vertices);
            if (detected !== state.shapeType) {
                state.shapeType = detected;
                state.onShapeTypeChange(detected);
            }
        }

        // ============================================
        // UNDO / REDO
        // ============================================

        function _pushUndo() {
            state.undoStack.push(JSON.stringify(state.vertices));
            if (state.undoStack.length > state.maxUndo) state.undoStack.shift();
            state.redoStack = [];
        }

        function undo() {
            if (state.undoStack.length === 0) return;
            state.redoStack.push(JSON.stringify(state.vertices));
            state.vertices = JSON.parse(state.undoStack.pop());
            _emitChange();
            render();
        }

        function redo() {
            if (state.redoStack.length === 0) return;
            state.undoStack.push(JSON.stringify(state.vertices));
            state.vertices = JSON.parse(state.redoStack.pop());
            _emitChange();
            render();
        }

        // ============================================
        // FIT TO VIEW
        // ============================================

        function fitToView() {
            const bbox = ShapeGeometry.calculateBbox(state.shapeType, state.params, state.vertices);
            if (bbox.width <= 0 || bbox.height <= 0) return;

            const margin = 0.1; // 10%
            const availW = state.width * (1 - 2 * margin);
            const availH = state.height * (1 - 2 * margin);

            state.scale = Math.min(availW / bbox.width, availH / bbox.height);
            state.scale = Math.max(0.1, Math.min(100, state.scale));

            // Center the shape
            let minX = 0, minY = 0;
            if (state.vertices) {
                minX = Math.min(...state.vertices.map(v => v[0]));
                minY = Math.min(...state.vertices.map(v => v[1]));
            }
            const shapePixelW = bbox.width * state.scale;
            const shapePixelH = bbox.height * state.scale;
            state.offsetX = (state.width - shapePixelW) / 2 - minX * state.scale;
            state.offsetY = (state.height - shapePixelH) / 2 - minY * state.scale;

            render();
        }

        // ============================================
        // PUBLIC API: SET SHAPE / PARAMS
        // ============================================

        function setShape(shapeType, params, vertices) {
            state.shapeType = shapeType;
            state.params = { ...params };
            state.vertices = vertices ? vertices.map(v => [...v]) : null;
            state.undoStack = [];
            state.redoStack = [];
            fitToView();
        }

        function updateFromParams(params) {
            state.params = { ...params };
            const config = ShapeGeometry.SHAPE_CONFIG[state.shapeType];
            if (config && config.hasVertices) {
                state.vertices = ShapeGeometry.generateVertices(state.shapeType, params);
            }
            render();
        }

        function getVertices() {
            return state.vertices ? state.vertices.map(v => [...v]) : null;
        }

        function getParams() {
            return { ...state.params };
        }

        function canUndo() { return state.undoStack.length > 0; }
        function canRedo() { return state.redoStack.length > 0; }

        // ============================================
        // EMIT CHANGES TO INPUTS
        // ============================================

        function _emitChange() {
            if (state.vertices) {
                const newParams = ShapeGeometry.extractParams(state.shapeType, state.vertices);
                state.params = { ...state.params, ...newParams };
            }
            state.onParamsChange(state.params, state.vertices);
        }

        function _round(val) {
            return Math.round(val * 10) / 10;
        }

        // ============================================
        // SVG EXPORT (for shape_svg persistence)
        // ============================================

        function exportSVG() {
            const bbox = ShapeGeometry.calculateBbox(state.shapeType, state.params, state.vertices);
            if (bbox.width <= 0 || bbox.height <= 0) return '';

            const pad = 5;
            const w = bbox.width + 2 * pad;
            const h = bbox.height + 2 * pad;

            let pathD = '';
            if (state.shapeType === 'circle') {
                const r = (state.params.diameter || 0) / 2;
                return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="80" height="${80 * h / w}"><circle cx="${r + pad}" cy="${r + pad}" r="${r}" fill="rgba(230,126,34,0.2)" stroke="#e67e22" stroke-width="1.5"/></svg>`;
            }
            if (state.shapeType === 'ellipse') {
                const rx = (state.params.axisA || 0) / 2;
                const ry = (state.params.axisB || 0) / 2;
                return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="80" height="${80 * h / w}"><ellipse cx="${rx + pad}" cy="${ry + pad}" rx="${rx}" ry="${ry}" fill="rgba(230,126,34,0.2)" stroke="#e67e22" stroke-width="1.5"/></svg>`;
            }

            if (!state.vertices || state.vertices.length < 3) return '';
            const minX = Math.min(...state.vertices.map(v => v[0]));
            const minY = Math.min(...state.vertices.map(v => v[1]));
            const pts = state.vertices.map(v => `${v[0] - minX + pad},${v[1] - minY + pad}`).join(' ');
            return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="80" height="${80 * h / w}"><polygon points="${pts}" fill="rgba(230,126,34,0.2)" stroke="#e67e22" stroke-width="1.5"/></svg>`;
        }

        // ============================================
        // INIT
        // ============================================

        // Observe resize
        const resizeObserver = new ResizeObserver(() => resize());
        resizeObserver.observe(canvasElement.parentElement);
        resize();

        // Return public API
        return {
            setShape,
            updateFromParams,
            getVertices,
            getParams,
            fitToView,
            undo,
            redo,
            canUndo,
            canRedo,
            exportSVG,
            render,
            resize,
            destroy: function() { resizeObserver.disconnect(); }
        };
    }

    return { create };
})();

window.ShapeCanvas = ShapeCanvas;
```

- [ ] **Step 3: Add CSS and JS to calculator.html**

In `calculator.html`, add the CSS link in the `<head>`:
```html
<link rel="stylesheet" href="{{ url_for('calculator.static', filename='css/shape_canvas.css') }}">
```

Add JS before `calculator-core.js`:
```html
<script src="{{ url_for('calculator.static', filename='js/shape-geometry.js') }}"></script>
<script src="{{ url_for('calculator.static', filename='js/shape-canvas.js') }}"></script>
```

- [ ] **Step 4: Verify canvas renders in browser**

Temporarily instantiate a canvas in the console to test:
```javascript
// In browser console
const c = document.createElement('canvas');
document.body.appendChild(c);
const editor = ShapeCanvas.create(c, { shapeType: 'trapezoid_symmetric' });
editor.setShape('trapezoid_symmetric', { baseA: 120, baseB: 80, height: 40 }, ShapeGeometry.generateVertices('trapezoid_symmetric', { baseA: 120, baseB: 80, height: 40 }));
```

- [ ] **Step 5: Commit**

```bash
git add modules/calculator/static/js/shape-canvas.js modules/calculator/static/css/shape_canvas.css
git commit -m "feat(calculator): add interactive shape canvas — grid rendering, vertex editing, zoom/pan, undo/redo, SVG export"
```

---

## Chunk 3: UI Integration — Dropdown, Dynamic Inputs, Canvas Binding

### Task 4: Replace Shape Radio Toggle with Dropdown + Dynamic Inputs + Canvas

**Files:**
- Modify: `modules/calculator/templates/calculator.html` (lines 123-141, shape toggle section)
- Create: `modules/calculator/static/js/shape-editor.js` (orchestrator: binds dropdown, inputs, canvas)
- Modify: `modules/calculator/static/js/calculator-ui.js` (replace `initShapeToggle`)
- Modify: `modules/calculator/static/js/calculator-events.js` (update shape field exclusions)
- Modify: `modules/calculator/static/js/calculator-products.js` (update product cloning for new shape system)
- Modify: `modules/calculator/static/css/calculator_layout.css` (replace shape toggle styles)

- [ ] **Step 1: Replace HTML shape toggle with dropdown + editor container**

In `calculator.html`, replace lines 123-141 (the `.product-shape` div) with:

```html
<!-- Kształt produktu -->
<div class="product-shape">
    <label class="input-txt">Kształt:</label>
    <select class="shape-select" data-field="shapeSelect">
        <option value="rectangular">Prostokąt</option>
        <option value="circle">Koło</option>
        <option value="ellipse">Elipsa</option>
        <optgroup label="Trójkąt">
            <option value="triangle_right">Trójkąt prostokątny</option>
            <option value="triangle_equilateral">Trójkąt równoboczny</option>
            <option value="triangle_isosceles">Trójkąt równoramienny</option>
            <option value="triangle_custom">Trójkąt dowolny</option>
        </optgroup>
        <optgroup label="Trapez">
            <option value="trapezoid_symmetric">Trapez symetryczny</option>
            <option value="trapezoid_asymmetric">Trapez niesymetryczny</option>
            <option value="trapezoid_custom">Trapez dowolny</option>
        </optgroup>
        <option value="parallelogram">Równoległobok</option>
        <option value="polygon">Wielokąt niestandardowy</option>
    </select>
</div>
```

Also, in the workspace row (after the dimensions section, before finishing), add the shape editor container:

```html
<!-- Shape Editor: inputs + canvas (two-column) -->
<div class="shape-editor-container collapsed-canvas" data-shape-editor>
    <div class="shape-inputs-column" data-shape-inputs></div>
    <div class="shape-canvas-column">
        <div class="shape-canvas-wrapper">
            <canvas data-shape-canvas></canvas>
            <div class="shape-canvas-scale-indicator" data-shape-scale></div>
        </div>
        <div class="shape-canvas-controls">
            <button type="button" data-shape-undo title="Cofnij" disabled>↩</button>
            <button type="button" data-shape-redo title="Ponów" disabled>↪</button>
            <button type="button" data-shape-fit title="Dopasuj do widoku">⊡</button>
        </div>
        <div class="shape-canvas-hint" data-shape-hint style="display:none">
            Klik na krawędzi = dodaj punkt | PPM na punkcie = usuń punkt
        </div>
    </div>
</div>
```

- [ ] **Step 2: Create shape-editor.js — orchestrator binding dropdown, inputs, canvas**

```javascript
// shape-editor.js
// Orchestrates: shape dropdown ↔ dynamic inputs ↔ canvas
// Dependencies: ShapeGeometry, ShapeCanvas

const ShapeEditor = (function() {
    'use strict';

    function init(form) {
        const select = form.querySelector('[data-field="shapeSelect"]');
        const editorContainer = form.querySelector('[data-shape-editor]');
        const inputsColumn = form.querySelector('[data-shape-inputs]');
        const canvasEl = form.querySelector('[data-shape-canvas]');
        const scaleIndicator = form.querySelector('[data-shape-scale]');
        const undoBtn = form.querySelector('[data-shape-undo]');
        const redoBtn = form.querySelector('[data-shape-redo]');
        const fitBtn = form.querySelector('[data-shape-fit]');
        const hintEl = form.querySelector('[data-shape-hint]');

        if (!select || !editorContainer) return null;

        let canvas = null;
        let currentShape = select.value || 'rectangular';
        let currentParams = {};
        let isUpdating = false; // Prevent circular updates

        // ============================================
        // CANVAS INIT (lazy — created on first non-rectangular shape)
        // ============================================

        function _ensureCanvas() {
            if (canvas) return;
            canvas = ShapeCanvas.create(canvasEl, {
                shapeType: currentShape,
                scaleIndicator: scaleIndicator,
                onParamsChange: _onCanvasParamsChange,
                onShapeTypeChange: _onCanvasShapeTypeChange
            });
        }

        // ============================================
        // DROPDOWN CHANGE
        // ============================================

        select.addEventListener('change', function() {
            const newShape = this.value;
            _switchShape(newShape);
        });

        function _switchShape(shapeType) {
            currentShape = shapeType;
            form.dataset.productShape = shapeType;

            const config = ShapeGeometry.SHAPE_CONFIG[shapeType];
            if (!config) return;

            // Update visibility
            const isSimpleRect = (shapeType === 'rectangular');
            editorContainer.classList.toggle('collapsed-canvas', isSimpleRect);

            // Show/hide hint for polygon
            if (hintEl) {
                hintEl.style.display = shapeType === 'polygon' ? '' : 'none';
            }

            // Generate default params
            currentParams = { ...config.defaults };

            // Render dynamic inputs
            _renderInputs(config);

            // Update canvas
            if (!isSimpleRect) {
                _ensureCanvas();
                const vertices = ShapeGeometry.generateVertices(shapeType, currentParams);
                canvas.setShape(shapeType, currentParams, vertices);
            }

            // Sync with existing dimension fields
            _syncToMainDimensions();

            // Update pricing
            if (typeof updatePrices === 'function') updatePrices();
        }

        // ============================================
        // RENDER DYNAMIC INPUTS
        // ============================================

        function _renderInputs(config) {
            inputsColumn.innerHTML = '';

            for (const input of config.inputs) {
                const row = document.createElement('div');
                row.className = 'shape-input-row';
                row.innerHTML = `
                    <label>${input.label}:</label>
                    <input type="number" step="0.1" min="0.1"
                           data-shape-param="${input.key}"
                           value="${currentParams[input.key] || ''}">
                    <span class="unit">${input.unit}</span>
                `;
                inputsColumn.appendChild(row);
            }

            // Bbox info
            const bboxDiv = document.createElement('div');
            bboxDiv.className = 'shape-bbox-info';
            bboxDiv.setAttribute('data-shape-bbox', '');
            inputsColumn.appendChild(bboxDiv);

            // Validation area
            const validDiv = document.createElement('div');
            validDiv.className = 'shape-validation-error';
            validDiv.setAttribute('data-shape-validation', '');
            inputsColumn.appendChild(validDiv);

            // Attach input listeners
            inputsColumn.querySelectorAll('input[data-shape-param]').forEach(inp => {
                inp.addEventListener('input', _onInputChange);
            });

            _updateBboxDisplay();
        }

        // ============================================
        // INPUT → CANVAS SYNC
        // ============================================

        function _onInputChange() {
            if (isUpdating) return;
            isUpdating = true;

            // Collect params from inputs
            inputsColumn.querySelectorAll('input[data-shape-param]').forEach(inp => {
                currentParams[inp.dataset.shapeParam] = parseFloat(inp.value) || 0;
            });

            // Validate
            const errors = ShapeGeometry.validate(currentShape, currentParams);
            const validDiv = inputsColumn.querySelector('[data-shape-validation]');
            if (validDiv) validDiv.textContent = errors.length > 0 ? errors[0] : '';

            // Update canvas
            if (canvas && errors.length === 0) {
                canvas.updateFromParams(currentParams);
            }

            _syncToMainDimensions();
            _updateBboxDisplay();
            _updateUndoRedoButtons();

            if (errors.length === 0 && typeof updatePrices === 'function') {
                updatePrices();
            }

            isUpdating = false;
        }

        // ============================================
        // CANVAS → INPUT SYNC
        // ============================================

        function _onCanvasParamsChange(params, vertices) {
            if (isUpdating) return;
            isUpdating = true;

            currentParams = { ...params };

            // Update input fields
            inputsColumn.querySelectorAll('input[data-shape-param]').forEach(inp => {
                const key = inp.dataset.shapeParam;
                if (params[key] !== undefined) {
                    inp.value = params[key];
                }
            });

            _syncToMainDimensions();
            _updateBboxDisplay();
            _updateUndoRedoButtons();

            if (typeof updatePrices === 'function') updatePrices();

            isUpdating = false;
        }

        function _onCanvasShapeTypeChange(newType) {
            currentShape = newType;
            select.value = newType;
            form.dataset.productShape = newType;
        }

        // ============================================
        // SYNC TO MAIN DIMENSION FIELDS (length, width for pricing)
        // ============================================

        function _syncToMainDimensions() {
            const vertices = canvas ? canvas.getVertices() : null;
            const bbox = ShapeGeometry.calculateBbox(currentShape, currentParams, vertices);

            // Set length/width to bbox dimensions for price lookup
            const lengthInput = form.querySelector('input[data-field="length"]');
            const widthInput = form.querySelector('input[data-field="width"]');

            if (currentShape === 'rectangular') {
                // Rectangular: normal behavior, inputs are primary
                if (widthInput) {
                    widthInput.readOnly = false;
                    widthInput.style.opacity = '';
                    widthInput.style.cursor = '';
                }
                return;
            }

            // Non-rectangular: set length/width to bbox, make read-only
            if (lengthInput) {
                lengthInput.value = Math.round(bbox.width * 10) / 10;
                lengthInput.readOnly = true;
                lengthInput.style.opacity = '0.5';
                lengthInput.style.cursor = 'not-allowed';
            }
            if (widthInput) {
                widthInput.value = Math.round(bbox.height * 10) / 10;
                widthInput.readOnly = true;
                widthInput.style.opacity = '0.5';
                widthInput.style.cursor = 'not-allowed';
            }

            // Store real area in dataset for pricing
            const area = ShapeGeometry.calculateArea(currentShape, currentParams, vertices);
            form.dataset.shapeRealAreaCm2 = area;
        }

        // ============================================
        // BBOX DISPLAY
        // ============================================

        function _updateBboxDisplay() {
            const bboxDiv = inputsColumn.querySelector('[data-shape-bbox]');
            if (!bboxDiv) return;
            if (currentShape === 'rectangular') {
                bboxDiv.textContent = '';
                return;
            }
            const vertices = canvas ? canvas.getVertices() : null;
            const bbox = ShapeGeometry.calculateBbox(currentShape, currentParams, vertices);
            bboxDiv.textContent = `Bbox: ${Math.round(bbox.width * 10) / 10} × ${Math.round(bbox.height * 10) / 10} cm`;
        }

        // ============================================
        // UNDO/REDO BUTTONS
        // ============================================

        if (undoBtn) undoBtn.addEventListener('click', () => { if (canvas) { canvas.undo(); _updateUndoRedoButtons(); } });
        if (redoBtn) redoBtn.addEventListener('click', () => { if (canvas) { canvas.redo(); _updateUndoRedoButtons(); } });
        if (fitBtn) fitBtn.addEventListener('click', () => { if (canvas) canvas.fitToView(); });

        function _updateUndoRedoButtons() {
            if (undoBtn) undoBtn.disabled = !canvas || !canvas.canUndo();
            if (redoBtn) redoBtn.disabled = !canvas || !canvas.canRedo();
        }

        // ============================================
        // PUBLIC API
        // ============================================

        return {
            setShape: _switchShape,

            getShapeData: function() {
                const vertices = canvas ? canvas.getVertices() : (currentShape === 'rectangular' ?
                    ShapeGeometry.generateVertices('rectangular', {
                        length: parseFloat(form.querySelector('input[data-field="length"]')?.value) || 0,
                        width: parseFloat(form.querySelector('input[data-field="width"]')?.value) || 0
                    }) : null);
                return ShapeGeometry.buildShapeData(currentShape, currentParams, vertices);
            },

            getShapeSvg: function() {
                if (!canvas) return '';
                return canvas.exportSVG();
            },

            getShapeType: function() {
                return currentShape;
            },

            restore: function(shapeType, shapeData) {
                currentShape = shapeType;
                form.dataset.productShape = shapeType;
                select.value = shapeType;

                const config = ShapeGeometry.SHAPE_CONFIG[shapeType];
                if (!config) return;

                // Use saved params or defaults
                currentParams = (shapeData && shapeData.params) ? { ...shapeData.params } : { ...config.defaults };

                // Show/hide canvas
                const isSimpleRect = (shapeType === 'rectangular');
                editorContainer.classList.toggle('collapsed-canvas', isSimpleRect);
                if (hintEl) hintEl.style.display = shapeType === 'polygon' ? '' : 'none';

                // Render inputs with restored values
                _renderInputs(config);
                inputsColumn.querySelectorAll('input[data-shape-param]').forEach(inp => {
                    const key = inp.dataset.shapeParam;
                    if (currentParams[key] !== undefined) inp.value = currentParams[key];
                });

                // Restore canvas with saved vertices (not regenerated from defaults)
                if (!isSimpleRect) {
                    _ensureCanvas();
                    const vertices = (shapeData && shapeData.vertices)
                        ? shapeData.vertices
                        : ShapeGeometry.generateVertices(shapeType, currentParams);
                    canvas.setShape(shapeType, currentParams, vertices);
                }

                _syncToMainDimensions();
                _updateBboxDisplay();
                if (typeof updatePrices === 'function') updatePrices();
            },

            destroy: function() {
                if (canvas) canvas.destroy();
            }
        };
    }

    return { init };
})();

window.ShapeEditor = ShapeEditor;
```

- [ ] **Step 3: Update initShapeToggle in calculator-ui.js**

Replace the existing `initShapeToggle(form)` function (lines 7-83 of `calculator-ui.js`) with:

```javascript
function initShapeToggle(form) {
    // New system: ShapeEditor handles dropdown + canvas
    if (form.dataset.shapeEditorInit) return;
    form.dataset.shapeEditorInit = 'true';

    const editor = ShapeEditor.init(form);
    if (editor) {
        form._shapeEditor = editor; // Store reference for later access
    }

    // Legacy compatibility: set default shape
    if (!form.dataset.productShape) {
        form.dataset.productShape = 'rectangular';
    }
}
```

- [ ] **Step 4: Update calculator-events.js — remove old shape radio exclusions**

In `calculator-events.js`, find all references to `shapeRect` and `shapeRound` (lines ~597-599, ~609-610, ~636, ~652, ~778-780, ~793-795). Replace the shape radio skip conditions:

Change all instances of:
```javascript
if (input.dataset.field === 'shapeRect' || input.dataset.field === 'shapeRound') return;
```
to:
```javascript
if (input.dataset.field === 'shapeSelect') return;
```

And for radio skip:
```javascript
if (radio.dataset.field === 'shapeRect' || radio.dataset.field === 'shapeRound') return;
```
remove these lines entirely (no more shape radios to skip).

- [ ] **Step 5: Update calculator-products.js — product cloning**

In `prepareNewProductForm()`, update shape handling for cloned products:
- Instead of updating radio button names (`productShape-N`), update the select's dataset
- Call `initShapeToggle(form)` to initialize the ShapeEditor for the new form
- Ensure shape defaults to `rectangular` for new products

- [ ] **Step 6: Update calculator_layout.css**

Replace the old `.shape-toggle`, `.shape-option`, `.shape-label` styles (lines 236-284) with new dropdown styles:

```css
.product-shape {
    display: flex;
    flex-direction: column;
    gap: 3px;
}

.shape-select {
    width: 100%;
    padding: 6px 8px;
    border: 1px solid #ccc;
    border-radius: 4px;
    font-size: 12px;
    background: #fff;
    cursor: pointer;
}

.shape-select:focus {
    border-color: #e67e22;
    outline: none;
}
```

- [ ] **Step 7: Test in browser**

1. Open calculator, verify dropdown appears instead of radio toggle
2. Select "Trapez symetryczny" — verify two-column layout appears with canvas
3. Change input values — verify canvas updates
4. Drag vertices on canvas — verify inputs update
5. Switch back to "Prostokąt" — verify canvas hides
6. Add new product — verify shape defaults to rectangular

- [ ] **Step 8: Commit**

```bash
git add modules/calculator/static/js/shape-editor.js modules/calculator/templates/calculator.html modules/calculator/static/js/calculator-ui.js modules/calculator/static/js/calculator-events.js modules/calculator/static/js/calculator-products.js modules/calculator/static/css/calculator_layout.css
git commit -m "feat(calculator): replace shape radio toggle with dropdown + interactive canvas editor — two-column layout with dynamic inputs"
```

---

## Chunk 4: Pricing Integration & Volume Calculations

### Task 5: Update Pricing Logic for Advanced Shapes

**Files:**
- Modify: `modules/calculator/static/js/calculator-core.js` (volume calculation, shape surcharge, weight)
- Modify: `modules/calculator/static/js/save_quote.js` (include shape_data, shape_svg in save payload)

- [ ] **Step 1: Update volume calculation in calculator-core.js**

Find the volume calculation section (around lines 820-828 in `computeAggregatedData` and lines 502-505 in `updatePrices`).

Replace the current shape volume logic with:

```javascript
// Volume calculation using shape data
function calculateProductVolume(form, lengthVal, widthVal, thicknessVal) {
    const productShape = form.dataset.productShape || 'rectangular';

    // Non-rectangular shapes: use real area from shape editor (stored in dataset)
    if (productShape !== 'rectangular') {
        const realAreaCm2 = parseFloat(form.dataset.shapeRealAreaCm2);
        if (!isNaN(realAreaCm2) && realAreaCm2 > 0) {
            return (realAreaCm2 / 10000) * (thicknessVal / 100); // cm² → m², cm → m
        }
    }
    // Rectangular or fallback: bbox volume
    return (lengthVal / 100) * (widthVal / 100) * (thicknessVal / 100);
}
```

Update `updatePrices()` — the wood price uses bbox volume (length × width × thickness), but displayed volume and weight use real volume:

```javascript
// Bbox volume for wood pricing
const bboxVolume = (lengthVal / 100) * (widthVal / 100) * (thicknessVal / 100);
// Real volume for display and shipping
const realVolume = calculateProductVolume(form, lengthVal, widthVal, thicknessVal);

// Price per unit (uses bbox)
const unitNetto = bboxVolume * pricePerM3 * multiplier;
// ...but store real volume for display
radio.dataset.realVolumeM3 = realVolume.toFixed(6);
```

- [ ] **Step 2: Update surcharge logic in updatePrices()**

Remove the current round-only surcharge check (lines ~502-505). Replace with:

```javascript
// Shape surcharge (currently only round/circle/ellipse)
const productShape = activeQuoteForm.dataset.productShape || 'rectangular';
if ((productShape === 'circle' || productShape === 'round' || productShape === 'ellipse') && window._roundShapeSurchargeNetto) {
    unitNetto += window._roundShapeSurchargeNetto;
}
// Other shapes: no surcharge (per spec — to be extended later)
```

- [ ] **Step 3: Update weight calculation**

Find weight calculation (uses `volume * 800 * quantity`). Ensure it uses real volume:

```javascript
const weight = realVolume * 800 * quantity; // kg, using real volume
```

- [ ] **Step 4: Update save_quote.js — include shape_data and shape_svg**

Find where the product data payload is built (around line 1068-1126). Add shape data:

```javascript
// Shape data
const shapeEditor = form._shapeEditor;
let shapeData = null;
let shapeSvg = '';
let productShape = form.dataset.productShape || 'rectangular';

if (shapeEditor) {
    shapeData = shapeEditor.getShapeData();
    shapeSvg = shapeEditor.getShapeSvg();
    productShape = shapeEditor.getShapeType();
}

// In the product object:
{
    // ... existing fields ...
    shape: productShape,
    shape_data: shapeData ? JSON.stringify(shapeData) : null,
    shape_svg: shapeSvg || null,
    real_volume_m3: realVolume
}
```

- [ ] **Step 5: Test pricing**

1. Create a trapezoidal product (a=120, b=80, h=40, thickness=3)
2. Verify bbox is 120×40 → volume for pricing = 0.0144 m³
3. Verify real area = 4000 cm² → real volume = 0.0120 m³
4. Verify price uses bbox volume (higher), but displayed volume shows real volume (lower)

- [ ] **Step 6: Commit**

```bash
git add modules/calculator/static/js/calculator-core.js modules/calculator/static/js/save_quote.js
git commit -m "feat(calculator): update pricing for advanced shapes — bbox for wood price, real area for finishing/volume/weight"
```

---

## Chunk 5: Backend Persistence & Edit Restoration

### Task 6: Update Backend — Save/Load Shape Data

**Files:**
- Modify: `modules/calculator/services/quote_service.py` (save shape_data/shape_svg, load for edit)
- Modify: `modules/calculator/routers/quote_routers.py` (if API changes needed)

- [ ] **Step 1: Update _update_or_create_product in quote_service.py**

Find the shape handling section (around line 250). Extend it:

```python
# Shape data (advanced shapes)
shape = product_data.get('shape', 'rectangular')
shape_data_json = product_data.get('shape_data')  # Already JSON string from frontend
shape_svg = product_data.get('shape_svg')

# Surcharge (currently only for circle/ellipse)
round_surcharge_netto = 0
round_surcharge_brutto = 0
if shape in ('round', 'circle', 'ellipse'):
    surcharge_per_unit = _to_decimal(
        CalculatorSetting.get_value('round_shape_surcharge_netto', '50.00')
    )
    round_surcharge_netto = _round_price(surcharge_per_unit * Decimal(quantity))
    round_surcharge_brutto = _round_price(
        _to_decimal(round_surcharge_netto) * Decimal('1.23')
    )
```

Update the QuoteItemDetails creation/update to include new fields:

```python
detail.shape_data = shape_data_json
detail.shape_svg = shape_svg
```

And in `create_quote()` (around line 577-597):
```python
item_details = QuoteItemDetails(
    # ... existing fields ...
    shape=product_shape,
    shape_data=product_data.get('shape_data'),
    shape_svg=product_data.get('shape_svg'),
    round_surcharge_netto=round_surcharge_netto,
    round_surcharge_brutto=round_surcharge_brutto,
)
```

- [ ] **Step 2: Update load_quote_for_edit in quote_service.py**

Find the product loading section (around line 88-93). Add shape_data to the returned dict:

```python
"shape": detail.shape if detail else "rectangular",
"shape_data": detail.shape_data if detail else None,
"shape_svg": detail.shape_svg if detail else None,
"round_surcharge_netto": float(detail.round_surcharge_netto) if detail and detail.round_surcharge_netto else 0,
"round_surcharge_brutto": float(detail.round_surcharge_brutto) if detail and detail.round_surcharge_brutto else 0,
```

- [ ] **Step 3: Update QuoteItem volume — use real volume**

In the quote service, when creating QuoteItem records, calculate and store real volume:

```python
# Real volume from shape_data if available
real_volume_m3 = None
if shape_data_json:
    import json
    try:
        sd = json.loads(shape_data_json)
        real_area_cm2 = sd.get('real_area_cm2', 0)
        if real_area_cm2 > 0:
            thickness_cm = float(product_data.get('thickness', 0))
            real_volume_m3 = (real_area_cm2 / 10000) * (thickness_cm / 100)
    except (json.JSONDecodeError, TypeError):
        pass

# When creating QuoteItem:
item.volume_m3 = real_volume_m3 if real_volume_m3 else volume_m3  # Use real if available
```

- [ ] **Step 4: Commit**

```bash
git add modules/calculator/services/quote_service.py
git commit -m "feat(calculator): backend persistence for advanced shapes — save/load shape_data, shape_svg, real volume"
```

---

### Task 7: Update Edit Mode Restoration

**Files:**
- Modify: `modules/calculator/static/js/quote_edit_loader.js` (restore shape from shape_data)

- [ ] **Step 1: Update restoreShape in quote_edit_loader.js**

Replace the existing `restoreShape` function (lines 228-256):

```javascript
async restoreShape(form, shape, shapeData) {
    const editor = form._shapeEditor;

    if (!shape || shape === 'rectangular') {
        // Default rectangular
        if (editor) editor.setShape('rectangular');
        form.dataset.productShape = 'rectangular';
        return;
    }

    // Legacy: 'round' maps to 'circle' in new system
    const mappedShape = shape === 'round' ? 'circle' : shape;

    if (editor) {
        // Parse shape_data if it's a string
        let parsedData = shapeData;
        if (typeof shapeData === 'string') {
            try { parsedData = JSON.parse(shapeData); } catch(e) { parsedData = null; }
        }

        editor.restore(mappedShape, parsedData);
    } else {
        // Fallback: set dropdown directly
        const select = form.querySelector('[data-field="shapeSelect"]');
        if (select) {
            select.value = mappedShape;
            select.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    form.dataset.productShape = mappedShape;
}
```

- [ ] **Step 2: Update restoreProduct to pass shape_data**

Find `restoreProduct` (around line 172). Update the shape restore call:

```javascript
// Shape (before dimensions — shape affects which fields are editable)
await this.restoreShape(form, product.shape, product.shape_data);
```

- [ ] **Step 3: Update restoreShapesSecondPass**

Find `restoreShapesSecondPass` (around line 262). Update to work with new shape system — instead of checking radio buttons, verify the dropdown and editor state:

```javascript
// Second pass: verify shape dropdown matches loaded data
const forms = document.querySelectorAll('.quote-form');
for (let i = 0; i < products.length; i++) {
    const form = forms[i];
    if (!form || !products[i]) continue;

    const shape = products[i].shape || 'rectangular';
    const mappedShape = shape === 'round' ? 'circle' : shape;
    form.dataset.productShape = mappedShape;

    const select = form.querySelector('[data-field="shapeSelect"]');
    if (select && select.value !== mappedShape) {
        select.value = mappedShape;
    }

    // Lock length/width for non-rectangular shapes
    if (mappedShape !== 'rectangular') {
        const lengthInput = form.querySelector('input[data-field="length"]');
        const widthInput = form.querySelector('input[data-field="width"]');
        if (lengthInput) { lengthInput.readOnly = true; lengthInput.style.opacity = '0.5'; lengthInput.style.cursor = 'not-allowed'; }
        if (widthInput) { widthInput.readOnly = true; widthInput.style.opacity = '0.5'; widthInput.style.cursor = 'not-allowed'; }
    }
}
```

- [ ] **Step 4: Update change detection MutationObserver**

In the change detection setup (around line 585), add `data-shape-real-area-cm2` to the observed attributes:

```javascript
this.datasetObserver.observe(form, {
    attributes: true,
    attributeFilter: [
        'data-finishing-type', 'data-finishing-variant', 'data-finishing-color',
        'data-finishing-gloss', 'data-edges-type', 'data-edges-r-value',
        'data-edges-angle-value', 'data-edges-brutto', 'data-edges-data',
        'data-product-shape', 'data-shape-real-area-cm2'
    ]
});
```

- [ ] **Step 5: Test edit mode round-trip**

1. Create a quote with a trapezoid product, save it
2. Open the quote for editing
3. Verify: dropdown shows "Trapez symetryczny", canvas shows the trapezoid with correct dimensions
4. Modify dimensions, save again
5. Reload — verify changes persisted

- [ ] **Step 6: Commit**

```bash
git add modules/calculator/static/js/quote_edit_loader.js
git commit -m "feat(calculator): update edit mode restoration for advanced shapes — restore dropdown, canvas, shape_data"
```

---

## Chunk 6: Dynamic Edge System for Non-Rectangular Shapes

### Task 8: Extend Edge System for Advanced Shapes

**Files:**
- Modify: `modules/calculator/services/edge_calculator.py` (add dynamic edge calculation)
- Modify: `modules/calculator/static/js/edges.js` (update edge modal for dynamic edges)
- Modify: `modules/calculator/routers/edge_routers.py` (update API to accept shape_data)

- [ ] **Step 1: Add dynamic edge calculation to edge_calculator.py**

Verify `import math` is at the top of `edge_calculator.py` (add if missing). Verify `_round_price` and `Decimal` imports are available. Then add a new function for non-rectangular shapes:

```python
def calculate_dynamic_edges(shape_type, shape_data_json, thickness_cm, edges_config, prices=None):
    """
    Calculate edges for non-rectangular shapes.
    Returns edge details with G (top), D (bottom), P (vertical) edges.

    edges_config format:
    [
        {"id": "G1", "type": "chamfer", "r_value": 3},
        {"id": "P2", "type": "round", "r_value": 5},
        ...
    ]
    """
    import json

    if not shape_data_json:
        return {"details": [], "total_netto": 0, "total_brutto": 0}

    shape_data = json.loads(shape_data_json) if isinstance(shape_data_json, str) else shape_data_json
    vertices = shape_data.get('vertices')

    # Generate edge definitions
    edge_defs = _generate_edge_definitions(shape_type, shape_data, thickness_cm)

    if not prices:
        prices = _load_edge_prices()

    total_netto = Decimal('0')
    total_brutto = Decimal('0')
    details = []

    for edge_cfg in (edges_config or []):
        edge_id = edge_cfg.get('id', '')
        edge_type = edge_cfg.get('type', 'sharp')
        r_value = edge_cfg.get('r_value')

        if edge_type == 'sharp':
            details.append({
                'id': edge_id, 'type': edge_type,
                'price_netto': 0, 'price_brutto': 0, 'length_mm': 0
            })
            continue

        # Find edge definition
        edge_def = next((e for e in edge_defs if e['id'] == edge_id), None)
        if not edge_def:
            continue

        length_mm = edge_def['length_cm'] * 10
        price_info = prices.get(edge_type, {})
        per_mb = Decimal(str(price_info.get('per_mb', 0)))

        if edge_def.get('is_corner'):
            price_netto = Decimal(str(price_info.get('per_corner', 0)))
        else:
            price_netto = _round_price(Decimal(str(length_mm)) / Decimal('1000') * per_mb)

        price_brutto = _round_price(price_netto * Decimal('1.23'))
        total_netto += price_netto
        total_brutto += price_brutto

        details.append({
            'id': edge_id,
            'type': edge_type,
            'edge_type_label': edge_def.get('type_label', ''),
            'length_mm': float(length_mm),
            'price_netto': float(price_netto),
            'price_brutto': float(price_brutto)
        })

    return {
        'details': details,
        'total_netto': float(total_netto),
        'total_brutto': float(total_brutto),
        'edge_definitions': edge_defs
    }


def _generate_edge_definitions(shape_type, shape_data, thickness_cm):
    """Generate G (top), D (bottom), P (vertical) edge definitions."""
    edges = []
    vertices = shape_data.get('vertices')
    params = shape_data.get('params', {})

    if shape_type in ('circle', 'ellipse'):
        # Single perimeter edge
        if shape_type == 'circle':
            d = params.get('diameter', 0)
            perimeter = math.pi * d
        else:
            a, b = params.get('axisA', 0) / 2, params.get('axisB', 0) / 2
            perimeter = math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))

        edges.append({'id': 'G1', 'type_label': 'top', 'length_cm': perimeter, 'name': 'Obwód (góra)'})
        edges.append({'id': 'D1', 'type_label': 'bottom', 'length_cm': perimeter, 'name': 'Obwód (dół)'})
        edges.append({'id': 'P1', 'type_label': 'vertical', 'length_cm': perimeter, 'name': 'Krawędź boczna (obwód)'})
        return edges

    if not vertices or len(vertices) < 3:
        return edges

    n = len(vertices)
    for i in range(n):
        j = (i + 1) % n
        dx = vertices[j][0] - vertices[i][0]
        dy = vertices[j][1] - vertices[i][1]
        length = math.sqrt(dx * dx + dy * dy)
        edges.append({'id': f'G{i+1}', 'type_label': 'top', 'length_cm': length, 'name': f'Góra {i+1}'})
        edges.append({'id': f'D{i+1}', 'type_label': 'bottom', 'length_cm': length, 'name': f'Dół {i+1}'})

    # Vertical edges (one per vertex, height = thickness)
    for i in range(n):
        edges.append({'id': f'P{i+1}', 'type_label': 'vertical', 'length_cm': thickness_cm, 'name': f'Pion {i+1}'})

    return edges
```

- [ ] **Step 2: Update edge API endpoint**

In `edge_routers.py`, update the `/api/calculate-edges` endpoint to accept shape_data:

```python
@calculator_bp.route('/api/calculate-edges', methods=['POST'])
def api_calculate_edges():
    data = request.get_json()
    shape = data.get('shape', 'rectangular')
    shape_data = data.get('shape_data')

    if shape not in ('rectangular', 'round') and shape_data:
        # Use dynamic edge system
        result = calculate_dynamic_edges(
            shape_type=shape,
            shape_data_json=shape_data,
            thickness_cm=float(data.get('thickness', 0)),
            edges_config=data.get('edges', [])
        )
        return jsonify(result)

    # Existing rectangular edge calculation
    # ... (keep existing code)
```

- [ ] **Step 3: Update edges.js — edge modal for dynamic edges**

The edge modal (`edges_modal.html` / `edges.js`) needs to show dynamic edges (G1-GN, D1-DN, P1-PN) instead of fixed A-H / N1-N4 when the shape is non-rectangular. This is the most complex UI change in the edge system.

In `edges.js`, add a function to render dynamic edge selectors:

```javascript
function renderDynamicEdges(edgeDefinitions, form) {
    // Build edge selection UI from dynamic definitions
    // Group by type_label: top, bottom, vertical
    const groups = { top: [], bottom: [], vertical: [] };
    for (const edge of edgeDefinitions) {
        groups[edge.type_label].push(edge);
    }

    // Render groups in the edge modal
    // Each edge gets: label, type selector (sharp/chamfer/round), r_value input
    // ... (detailed DOM generation matching existing edge modal structure)
}
```

Note: The full edge modal UI refactor is significant. The core logic for edge pricing remains the same — just the edge definitions become dynamic. The existing 3D preview in `edges.js` (2083 lines) works with rectangular edges. For non-rectangular shapes, show a 2D top-down view of the shape with labeled edges instead.

- [ ] **Step 4: Test edge calculation**

1. Create a triangle (3 edges) — verify G1-G3, D1-D3, P1-P3 appear
2. Set chamfer on G1 — verify price calculated correctly
3. Create a trapezoid — verify 4 edges per group
4. Verify rectangular shapes still use the old A-H / N1-N4 system

- [ ] **Step 5: Commit**

```bash
git add modules/calculator/services/edge_calculator.py modules/calculator/routers/edge_routers.py modules/calculator/static/js/edges.js
git commit -m "feat(calculator): dynamic edge system for advanced shapes — G/D/P edges, per-edge finishing selection"
```

---

## Chunk 7: Display Integration — Quotes List, PDF, Drafts

### Task 9: Update Quote Display — Badges, SVG Preview, PDF

**Files:**
- Modify: `modules/quotes/static/js/quotes.js` (shape badge + SVG preview)
- Modify: `modules/quotes/templates/offer_pdf.html` (shape name + SVG in PDF)

- [ ] **Step 1: Update quotes.js — shape badge**

Find the shape badge section (around line 2562). Replace:

```javascript
// Shape badge — support all shape types
const shapeLabels = {
    'rectangular': null, // No badge for default
    'circle': 'Koło',
    'ellipse': 'Elipsa',
    'round': 'Okrągły', // Legacy
    'triangle_right': 'Trójkąt prostokątny',
    'triangle_equilateral': 'Trójkąt równoboczny',
    'triangle_isosceles': 'Trójkąt równoramienny',
    'triangle_custom': 'Trójkąt dowolny',
    'trapezoid_symmetric': 'Trapez symetryczny',
    'trapezoid_asymmetric': 'Trapez niesymetryczny',
    'trapezoid_custom': 'Trapez dowolny',
    'parallelogram': 'Równoległobok',
    'polygon': 'Wielokąt'
};
const shapeLabel = finishing && finishing.shape ? shapeLabels[finishing.shape] : null;
const shapeDisplay = shapeLabel
    ? ` <span style="background:#e67e22;color:#fff;padding:1px 6px;border-radius:4px;font-size:11px;margin-left:4px;">${shapeLabel}</span>`
    : '';

// Shape SVG preview
const shapeSvgHtml = finishing && finishing.shape_svg
    ? `<div class="shape-svg-preview" style="margin-top:4px">${finishing.shape_svg}</div>`
    : '';
```

Add `${shapeSvgHtml}` to the product column HTML.

- [ ] **Step 2: Update offer_pdf.html — shape in PDF**

Find the shape display section (around line 527). Replace:

```html
{% set shape_labels = {
    'circle': 'Koło',
    'ellipse': 'Elipsa',
    'round': 'Okrągły/owalny',
    'triangle_right': 'Trójkąt prostokątny',
    'triangle_equilateral': 'Trójkąt równoboczny',
    'triangle_isosceles': 'Trójkąt równoramienny',
    'triangle_custom': 'Trójkąt dowolny',
    'trapezoid_symmetric': 'Trapez symetryczny',
    'trapezoid_asymmetric': 'Trapez niesymetryczny',
    'trapezoid_custom': 'Trapez dowolny',
    'parallelogram': 'Równoległobok',
    'polygon': 'Wielokąt'
} %}
{% if finishing_detail and finishing_detail.shape in shape_labels %}
<br><span class="finishing-details" style="color: #e67e22; font-weight: bold;">
    Kształt: {{ shape_labels[finishing_detail.shape] }}
</span>
{% if finishing_detail.shape_svg %}
<div style="margin-top: 4px;">{{ finishing_detail.shape_svg|safe }}</div>
{% endif %}
{% endif %}
```

- [ ] **Step 3: Commit**

```bash
git add modules/quotes/static/js/quotes.js modules/quotes/templates/offer_pdf.html
git commit -m "feat(quotes): display advanced shape badges and SVG previews in quote lists and PDF"
```

---

### Task 10: Update Draft System

**Files:**
- Modify: `modules/calculator/static/js/qdraft_backup.js` (save/restore shape_data)

- [ ] **Step 1: Update draft backup to include shape_data**

In `qdraft_backup.js`, find where product data is collected for backup (around line 255). Add:

```javascript
const shapeEditor = form._shapeEditor;
const shape = form.dataset.productShape || 'rectangular';
const shapeData = shapeEditor ? shapeEditor.getShapeData() : null;

// In the product backup object:
{
    // ... existing fields ...
    shape: shape,
    shape_data: shapeData
}
```

- [ ] **Step 2: Update draft restore to restore shape_data**

In the restore section (around line 543), update to use the ShapeEditor:

```javascript
// Restore shape
const editor = form._shapeEditor;
if (editor && product.shape_data) {
    editor.restore(product.shape || 'rectangular', product.shape_data);
} else if (product.shape && product.shape !== 'rectangular') {
    const select = form.querySelector('[data-field="shapeSelect"]');
    if (select) {
        select.value = product.shape;
        select.dispatchEvent(new Event('change', { bubbles: true }));
    }
}
```

- [ ] **Step 3: Test draft round-trip**

1. Create a trapezoid product, wait for auto-draft save
2. Navigate away and back — verify shape and canvas restore correctly
3. Verify rectangular products still restore normally

- [ ] **Step 4: Commit**

```bash
git add modules/calculator/static/js/qdraft_backup.js
git commit -m "feat(calculator): draft backup/restore for advanced shape data"
```

---

## Chunk 8: Final Integration & Testing

### Task 11: End-to-End Testing & Polish

- [ ] **Step 1: Test complete flow — create quote with advanced shape**

1. Open calculator
2. Select "Trapez symetryczny" from dropdown
3. Enter: a=120, b=80, h=40, grubość=3, ilość=5
4. Verify canvas shows trapezoid with correct dimensions
5. Verify bbox shows 120×40
6. Select wood variant — verify price uses bbox volume (0.0144 m³)
7. Add finishing — verify price uses real area (4000 cm²)
8. Configure edges (G1-G4 chamfer) — verify edge prices calculated
9. Save quote — verify all data persists
10. Load quote for edit — verify shape, canvas, inputs restore correctly

- [ ] **Step 2: Test backward compatibility**

1. Open an existing quote with `shape=rectangular` — verify it loads normally
2. Open an existing quote with `shape=round` — verify it maps to "Koło" dropdown
3. Create a new rectangular product — verify no canvas shown, normal flow
4. Open public calculator (`/kalkulator`) — verify NO shape dropdown, NO canvas, NO new JS files loaded
5. Open public B2B calculator (`/kalkulatorb2b`) — same verification as above

- [ ] **Step 3: Test all shape types**

For each of the 12 shapes:
1. Select from dropdown
2. Verify correct inputs appear
3. Verify canvas renders correctly
4. Drag a vertex — verify inputs update
5. Change an input — verify canvas updates
6. Save and reload — verify round-trip

- [ ] **Step 4: Test edge cases**

1. Invalid triangle (sides 1, 1, 100) — verify validation error shown
2. Polygon: add points up to 20, verify 21st is blocked
3. Trapez: drag to break symmetry — verify auto-switch to "niesymetryczny"
4. Canvas: zoom in/out — verify grid scale changes correctly
5. Canvas: undo/redo — verify vertex changes reverse
6. Fit-to-view after zoom — verify shape re-centered

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(calculator): complete advanced shapes integration — end-to-end tested"
```
