// shape-cutouts.js
// Wycięcia w blacie: elipsa (koło) i wielokąt (z narożnikami).
// Model: {id, type:'ellipse', cx, cy, rx, ry, angle} | {id, type:'polygon', points, corners}.
// Kolizje liczone na geometrii spłaszczonej (łuki i elipsy jako odcinki).
// Zależności: ShapeGeometry (pointInPolygon, ringsIntersect, rotateRing), ShapeCorners.

var ShapeCutouts = (function() {
    'use strict';

    var PUNKTY_ELIPSY = 72;
    var KAPPA = 0.5522847498;   // krzywa Béziera przybliżająca ćwiartkę elipsy
    var MAX_CUTOUTS = 5;
    var MIN_SIZE_CM = 1;
    // Wycięcie dotykające obrysu (albo innego wycięcia) na mniej niż tyle cm uznajemy za stykające się.
    // Samo ścisłe przecinanie odcinków (shape-geometry.js) pomija styk, a test punktu w wielokącie
    // rozstrzyga go zależnie od strony (lewa/dolna tak, prawa/górna nie) — stąd jawna tolerancja.
    var TOLERANCJA_STYKU_CM = 0.01;
    var _licznik = 0;

    function _round(v) { return Math.round(v * 10) / 10; }
    // Półosie elipsy zaokrąglamy do 0,05 cm, żeby średnice i osie leżały na siatce 0,1 cm:
    // Ø 3,5 cm to półoś 1,75 (zaokrąglona do 0,1 dawałaby Ø 3,4 albo 3,6)
    function _round05(v) { return Math.round(v * 20) / 20; }

    // Identyfikator wycięcia — po nim synchronizacja krawędzi poznaje,
    // które wycięcie usunięto (przenumerowanie liter H{n}.*)
    function newId() {
        _licznik += 1;
        return 'w' + Date.now().toString(36) + _licznik.toString(36);
    }

    function normalize(c) {
        if (!c || typeof c !== 'object') return null;
        if (c.type === 'ellipse') {
            var rx = Number(c.rx), ry = Number(c.ry), cx = Number(c.cx), cy = Number(c.cy);
            if (!(rx > 0) || !(ry > 0) || isNaN(cx) || isNaN(cy)) return null;
            return { id: c.id || newId(), type: 'ellipse', cx: cx, cy: cy, rx: rx, ry: ry, angle: Number(c.angle) || 0 };
        }
        if (c.type === 'polygon' && Array.isArray(c.points) && c.points.length >= 3) {
            var pts = c.points.map(function(p) { return [Number(p[0]), Number(p[1])]; });
            return { id: c.id || newId(), type: 'polygon', points: pts, corners: ShapeCorners.normalize(c.corners, pts.length) };
        }
        return null;
    }

    function fromHoles(holes) {
        var wynik = [];
        (holes || []).forEach(function(h) {
            if (Array.isArray(h) && h.length >= 3) {
                var c = normalize({ type: 'polygon', points: h });
                if (c) wynik.push(c);
            }
        });
        return wynik;
    }

    // Wycięcia z shape_data: pole `cutouts`, a dla starych danych — wielokąty z `holes`
    function fromShapeData(sd) {
        if (!sd) return [];
        if (Array.isArray(sd.cutouts)) {
            return sd.cutouts.map(normalize).filter(function(c) { return !!c; });
        }
        return fromHoles(sd.holes);
    }

    function clone(list) {
        return (list || []).map(function(c) {
            return normalize(JSON.parse(JSON.stringify(c)));
        }).filter(function(c) { return !!c; });
    }

    function ellipsePoints(c, n) {
        var ile = n || PUNKTY_ELIPSY;
        var a = (c.angle || 0) * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a), pts = [];
        for (var k = 0; k < ile; k++) {
            var t = 2 * Math.PI * k / ile, x = c.rx * Math.cos(t), y = c.ry * Math.sin(t);
            pts.push([c.cx + x * ca - y * sa, c.cy + x * sa + y * ca]);
        }
        return pts;
    }

    // Spłaszczony pierścień wycięcia (do kolizji, lameli i `holes`)
    function ring(c) {
        if (c.type === 'ellipse') return ellipsePoints(c);
        return ShapeCorners.flatten(ShapeCorners.contourSegments(c.points, c.corners));
    }

    function area(c) {
        if (c.type === 'ellipse') return Math.PI * c.rx * c.ry;
        return ShapeCorners.contourArea(c.points, c.corners);
    }

    // Obwód (cm): elipsa — Ramanujan jak calculateEllipsePerimeterCm w edges.js,
    // wielokąt — suma boków od wierzchołka do wierzchołka
    function perimeterCm(c) {
        if (c.type === 'ellipse') {
            var a = c.rx, b = c.ry;
            return Math.PI * (3 * (a + b) - Math.sqrt((3 * a + b) * (a + 3 * b)));
        }
        var s = 0, n = c.points.length;
        for (var i = 0; i < n; i++) {
            var p = c.points[i], q = c.points[(i + 1) % n];
            s += Math.hypot(q[0] - p[0], q[1] - p[1]);
        }
        return s;
    }

    function bounds(c) {
        if (c.type === 'ellipse') {
            var a = (c.angle || 0) * Math.PI / 180;
            var hw = Math.hypot(c.rx * Math.cos(a), c.ry * Math.sin(a));
            var hh = Math.hypot(c.rx * Math.sin(a), c.ry * Math.cos(a));
            return { minX: c.cx - hw, minY: c.cy - hh, maxX: c.cx + hw, maxY: c.cy + hh };
        }
        var b = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
        c.points.forEach(function(p) {
            b.minX = Math.min(b.minX, p[0]); b.minY = Math.min(b.minY, p[1]);
            b.maxX = Math.max(b.maxX, p[0]); b.maxY = Math.max(b.maxY, p[1]);
        });
        return b;
    }

    // Punkty do klamerek odległości: wierzchołki wielokąta albo 4 skrajne punkty elipsy
    function bracketPoints(c) {
        if (c.type === 'polygon') return c.points.map(function(p) { return [p[0], p[1]]; });
        var b = bounds(c);
        return [[b.minX, c.cy], [b.maxX, c.cy], [c.cx, b.minY], [c.cx, b.maxY]];
    }

    function translate(c, dx, dy) {
        var k = clone([c])[0];
        if (k.type === 'ellipse') { k.cx += dx; k.cy += dy; }
        else k.points = k.points.map(function(p) { return [p[0] + dx, p[1] + dy]; });
        return k;
    }

    function roundCoords(c) {
        var k = clone([c])[0];
        if (k.type === 'ellipse') {
            k.cx = _round(k.cx); k.cy = _round(k.cy); k.rx = _round05(k.rx); k.ry = _round05(k.ry);
            k.angle = Math.round(k.angle);
        } else {
            k.points = k.points.map(function(p) { return [_round(p[0]), _round(p[1])]; });
        }
        return k;
    }

    // Dopasowuje wycięcie do nowej ramki. Elipsa tylko z angle = 0 (wołający pilnuje).
    function scaleToBounds(c, nb) {
        var k = clone([c])[0];
        if (k.type === 'ellipse') {
            k.cx = (nb.minX + nb.maxX) / 2; k.cy = (nb.minY + nb.maxY) / 2;
            k.rx = (nb.maxX - nb.minX) / 2; k.ry = (nb.maxY - nb.minY) / 2;
            return k;
        }
        var ob = bounds(c);
        var sx = (ob.maxX - ob.minX) > 1e-9 ? (nb.maxX - nb.minX) / (ob.maxX - ob.minX) : 1;
        var sy = (ob.maxY - ob.minY) > 1e-9 ? (nb.maxY - nb.minY) / (ob.maxY - ob.minY) : 1;
        k.points = k.points.map(function(p) {
            return [nb.minX + (p[0] - ob.minX) * sx, nb.minY + (p[1] - ob.minY) * sy];
        });
        return k;
    }

    function rotate(c, deg, pivot) {
        var k = clone([c])[0];
        if (k.type === 'ellipse') {
            var r = ShapeGeometry.rotateRing([[k.cx, k.cy]], deg, pivot)[0];
            k.cx = r[0]; k.cy = r[1]; k.angle = (k.angle || 0) + deg;
        } else {
            k.points = ShapeGeometry.rotateRing(k.points, deg, pivot);
        }
        return k;
    }

    // Odległość (cm) punktu p od odcinka a-b
    function _odlegloscOdOdcinka(p, a, b) {
        var dx = b[0] - a[0], dy = b[1] - a[1];
        var len2 = dx * dx + dy * dy;
        var t = len2 > 1e-18 ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2 : 0;
        t = Math.max(0, Math.min(1, t));
        return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
    }

    // Czy jakikolwiek punkt pierścienia pts leży bliżej niż eps od któregokolwiek odcinka pierścienia seg
    function _punktyBlizejNizOdSegmentow(pts, seg, eps) {
        for (var i = 0; i < pts.length; i++) {
            for (var j = 0; j < seg.length; j++) {
                if (_odlegloscOdOdcinka(pts[i], seg[j], seg[(j + 1) % seg.length]) < eps) return true;
            }
        }
        return false;
    }

    // Czy pierścienie się stykają: wierzchołek jednego leży (z tolerancją eps) na boku drugiego.
    // Łapie styk w narożniku, na odcinku wspólnej ściany i w literze T.
    function _dotyka(ringA, ringB, eps) {
        return _punktyBlizejNizOdSegmentow(ringA, ringB, eps)
            || _punktyBlizejNizOdSegmentow(ringB, ringA, eps);
    }

    // Wycięcie w całości wewnątrz obrysu: wszystkie punkty w środku, krawędzie się nie przecinają
    // i nie dotykają obrysu (wycięcie stykające się z obrysem to w praktyce wcięcie, a tego nie ma).
    function containedIn(outerRing, c) {
        if (!outerRing || outerRing.length < 3) return false;
        var r = ring(c);
        for (var i = 0; i < r.length; i++) {
            if (!ShapeGeometry.pointInPolygon(r[i][0], r[i][1], outerRing)) return false;
        }
        if (ShapeGeometry.ringsIntersect(r, outerRing)) return false;
        return !_dotyka(r, outerRing, TOLERANCJA_STYKU_CM);
    }

    // Wycięcia nachodzą na siebie, gdy się przecinają, jedno leży w drugim albo dzielą ścianę/punkt
    function overlaps(a, b) {
        var ra = ring(a), rb = ring(b);
        if (ShapeGeometry.ringsIntersect(ra, rb)) return true;
        if (_dotyka(ra, rb, TOLERANCJA_STYKU_CM)) return true;
        return ShapeGeometry.pointInPolygon(ra[0][0], ra[0][1], rb)
            || ShapeGeometry.pointInPolygon(rb[0][0], rb[0][1], ra);
    }

    // Indeksy wycięć poza obrysem albo nachodzących na inne
    function invalidIndices(outerRing, list) {
        var zle = [];
        for (var i = 0; i < list.length; i++) {
            var ok = containedIn(outerRing, list[i]);
            for (var j = 0; ok && j < list.length; j++) {
                if (j !== i && overlaps(list[i], list[j])) ok = false;
            }
            if (!ok) zle.push(i);
        }
        return zle;
    }

    // Pochodne `holes` do shape_data (dla starych odbiorców: liczba wycięć, pole)
    function toHoles(list) {
        return (list || []).map(function(c) {
            return ring(c).map(function(p) { return [_round(p[0]), _round(p[1])]; });
        });
    }

    // Ścieżka do rysowania: wielokąt — odcinki/łuki, elipsa — 4 krzywe Béziera
    function pathSegments(c) {
        if (c.type === 'polygon') return ShapeCorners.contourSegments(c.points, c.corners);
        var a = (c.angle || 0) * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a);
        function pt(ux, uy) {
            var x = c.rx * ux, y = c.ry * uy;
            return [c.cx + x * ca - y * sa, c.cy + x * sa + y * ca];
        }
        var osie = [[1, 0], [0, 1], [-1, 0], [0, -1], [1, 0]];
        var segs = [];
        for (var q = 0; q < 4; q++) {
            var p0 = osie[q], p3 = osie[q + 1];
            segs.push({
                type: 'bezier',
                from: pt(p0[0], p0[1]),
                cp1: pt(p0[0] + KAPPA * p3[0], p0[1] + KAPPA * p3[1]),
                cp2: pt(p3[0] + KAPPA * p0[0], p3[1] + KAPPA * p0[1]),
                to: pt(p3[0], p3[1])
            });
        }
        return segs;
    }

    function makeEllipse(minX, minY, maxX, maxY) {
        return { id: newId(), type: 'ellipse', cx: (minX + maxX) / 2, cy: (minY + maxY) / 2,
                 rx: (maxX - minX) / 2, ry: (maxY - minY) / 2, angle: 0 };
    }

    function makeRect(minX, minY, maxX, maxY) {
        return { id: newId(), type: 'polygon',
                 points: [[minX, minY], [maxX, minY], [maxX, maxY], [minX, maxY]],
                 corners: [null, null, null, null] };
    }

    // Postać do zapisu w shape_data (zaokrąglona do 0,1 cm)
    function serialize(c) {
        var k = roundCoords(c);
        if (k.type === 'ellipse') {
            return { id: k.id, type: 'ellipse', cx: k.cx, cy: k.cy, rx: k.rx, ry: k.ry, angle: k.angle };
        }
        return { id: k.id, type: 'polygon', points: k.points, corners: k.corners };
    }

    return {
        MAX_CUTOUTS: MAX_CUTOUTS,
        MIN_SIZE_CM: MIN_SIZE_CM,
        newId: newId,
        normalize: normalize,
        fromHoles: fromHoles,
        fromShapeData: fromShapeData,
        clone: clone,
        ellipsePoints: ellipsePoints,
        ring: ring,
        area: area,
        perimeterCm: perimeterCm,
        bounds: bounds,
        bracketPoints: bracketPoints,
        translate: translate,
        roundCoords: roundCoords,
        scaleToBounds: scaleToBounds,
        rotate: rotate,
        containedIn: containedIn,
        overlaps: overlaps,
        invalidIndices: invalidIndices,
        toHoles: toHoles,
        pathSegments: pathSegments,
        makeEllipse: makeEllipse,
        makeRect: makeRect,
        serialize: serialize
    };
})();

window.ShapeCutouts = ShapeCutouts;
