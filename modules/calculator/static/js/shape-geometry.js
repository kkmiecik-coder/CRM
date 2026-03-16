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
            inputs: [],
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
                return null;
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
        if (isNaN(h) || h <= 0) return null;
        return [[0, 0], [base, 0], [base / 2, h]];
    }

    function _triangleCustomVertices(p) {
        const a = p.sideA || 80, b = p.sideB || 70, c = p.sideC || 60;
        if (a + b <= c || a + c <= b || b + c <= a) return null;
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
            edges.push({ id: 'G' + (i + 1), type: 'top', length_cm: length });
        }
        return edges;
    }

    // ============================================
    // VALIDATION
    // ============================================

    function validate(shapeType, params) {
        const errors = [];

        const config = SHAPE_CONFIG[shapeType];
        if (!config) return ['Nieznany typ kształtu'];

        for (const input of config.inputs) {
            const val = params[input.key];
            if (val === undefined || val === null || val === '') {
                errors.push(input.label + ' jest wymagane');
            } else if (isNaN(val) || Number(val) <= 0) {
                errors.push(input.label + ' musi być > 0');
            }
        }
        if (errors.length > 0) return errors;

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
            const sides = [a, b, c].sort(function(x, y) { return x - y; });

            if (Math.abs(sides[0] - sides[2]) < TOLERANCE) {
                return 'triangle_equilateral';
            }
            if (Math.abs(sides[0] - sides[1]) < TOLERANCE || Math.abs(sides[1] - sides[2]) < TOLERANCE) {
                return 'triangle_isosceles';
            }
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
        return Math.round(val * 10) / 10;
    }

    // ============================================
    // BUILD shape_data OBJECT FOR PERSISTENCE
    // ============================================

    function buildShapeData(shapeType, params, vertices) {
        var area = calculateArea(shapeType, params, vertices);
        var bbox = calculateBbox(shapeType, params, vertices);
        return {
            params: Object.assign({}, params),
            vertices: vertices ? vertices.map(function(v) { return [_round(v[0]), _round(v[1])]; }) : null,
            real_area_cm2: _round(area),
            bbox: bbox
        };
    }

    // ============================================
    // PUBLIC API
    // ============================================

    return {
        SHAPE_CONFIG: SHAPE_CONFIG,
        generateVertices: generateVertices,
        calculateArea: calculateArea,
        calculateBbox: calculateBbox,
        calculateEdgeLengths: calculateEdgeLengths,
        validate: validate,
        detectVariant: detectVariant,
        extractParams: extractParams,
        buildShapeData: buildShapeData
    };
})();

window.ShapeGeometry = ShapeGeometry;
