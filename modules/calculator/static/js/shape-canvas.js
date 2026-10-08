// shape-canvas.js
// Interactive canvas editor for shape geometry
// Zależności: ShapeGeometry (shape-geometry.js), ShapeCorners (shape-corners.js),
// ShapeCutouts (shape-cutouts.js), ShapeTools (shape-tools.js) — ładowane przed tym plikiem.

var ShapeCanvas = (function() {
    'use strict';

    function create(canvasElement, options) {
        var ctx = canvasElement.getContext('2d');
        var realCtx = ctx;
        // Palety kolorów: normalny (pomarańczowy) i błędny (czerwony)
        var COLOR_THEMES = {
            normal: {
                shapeFill: 'rgba(230, 126, 34, 0.35)',
                shapeStroke: '#e67e22',
                dimLabel: '#e67e22',
                dimLabelAlpha: 'rgba(230, 126, 34, 0.6)'
            },
            error: {
                shapeFill: 'rgba(220, 38, 38, 0.30)',
                shapeStroke: '#dc2626',
                dimLabel: '#dc2626',
                dimLabelAlpha: 'rgba(220, 38, 38, 0.6)'
            }
        };

        var state = {
            shapeType: options.shapeType || 'rectangular',
            vertices: null,
            params: {},
            offsetX: 0,
            offsetY: 0,
            scale: 3,
            gridLevels: [0.1, 0.5, 1, 5, 10, 20, 30, 50, 100],
            currentGridCm: 1,
            dragVertex: -1,
            isPanning: false,
            panStartX: 0,
            panStartY: 0,
            hoverVertex: -1,
            undoStack: [],
            redoStack: [],
            maxUndo: 50,
            onParamsChange: options.onParamsChange || function() {},
            onShapeTypeChange: options.onShapeTypeChange || function() {},
            dpr: window.devicePixelRatio || 1,
            width: 0,
            height: 0,
            colorTheme: 'normal',
            outOfRangeDims: { length: false, width: false },  // które wymiary bbox na czerwono
            activeTool: 'select',  // patrz ShapeTools.IDS (V domyślne)
            rotation: 0,           // łączny kąt obrotu kształtu (0-359)
            rotateDrag: null,      // stan gestu obrotu, null gdy nie obracamy
            corners: [],           // narożniki obrysu, równoległe do vertices
            cutouts: [],           // wycięcia (model ShapeCutouts)
            activeHole: null,      // wycięcie rysowane punkt po punkcie (narzędzie +)
            hoverHoleStart: false,
            selection: null,       // {kind:'cutout', index} | {kind:'outer'} — zaznaczenie w V; L i M zaznaczają nowe wycięcie
            cornerType: 'round',   // typ z przełącznika narzędzia N
            cornerLimitHit: null,  // {ring:'outer'|indeks wycięcia} — obrys na czerwono przy limicie
            invalidCutouts: [],    // indeksy wycięć poza obrysem albo nachodzących na inne
            _hintTimeout: null,
            _hintSaved: null,      // tekst podpowiedzi sprzed serii komunikatów (_showHint)
            visibility: { dimensions: true, brackets: true, guides: true, angles: true, lamellas: true, corners: true }
        };

        // Load visibility z localStorage (per-przeglądarka)
        try {
            var savedVis = JSON.parse(localStorage.getItem('wp.canvas.visibility') || 'null');
            if (savedVis && typeof savedVis === 'object') {
                state.visibility = Object.assign(state.visibility, savedVis);
            }
        } catch (e) { /* ignore */ }

        // Wszystkie nasłuchy na <canvas> rejestrujemy tutaj, żeby destroy() mógł je zdjąć.
        // Bez tego każde ponowne utworzenie Canvy (suwak „Rysunek”, zmiana kształtu)
        // dokładało kolejny komplet obsługi myszy na tym samym elemencie.
        var _nasluchy = [];
        function _on(target, type, fn, opts) {
            target.addEventListener(type, fn, opts);
            _nasluchy.push([target, type, fn, opts]);
        }

        var tools = null;   // ShapeTools.create(api) — tworzone przed pierwszym render()

        // Pozycje wymiarów do obsługi dblclick
        var dimensionHitAreas = []; // [{x, y, edgeIndex, labelX, labelY}]

        // === Czytelność wymiarów (2026-05-18) ===
        var COLLISION_RADIUS = 32;         // px — promień detekcji kolizji label krawędzi ↔ bbox
        var ANGLE_COLLISION_RADIUS = 28;   // px — promień detekcji kolizji kąt ↔ bbox
        var SVG_SCALE = 1.5;               // mnożnik fontów i offsetów w trybie eksportu SVG
        var LAMELLA_SPACING_CM = 4;        // odstęp linii lameli (Task 8)

        function _mul() { return state._svgExportMode ? SVG_SCALE : 1; }
        function _scaled(v) { return Math.round(v * _mul()); }

        // ============================================
        // CANVAS SIZING
        // ============================================

        function resize() {
            var rect = canvasElement.parentElement.getBoundingClientRect();
            state.width = rect.width;

            var inFullscreen = !!canvasElement.closest('.fullscreen-canvas-modal__main');

            if (inFullscreen) {
                state.height = Math.max(rect.height, 200);
            } else {
                var viewW = window.innerWidth;
                var viewH = window.innerHeight;
                var targetH = 400;
                var maxH = 600;

                if (viewW > 768) {
                    targetH = viewH * 0.7;
                    maxH = viewH * 0.7;
                }

                state.height = Math.min(Math.max(targetH, 200), maxH);
            }

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
        // MODEL: narożniki i wycięcia
        // ============================================

        // Spłaszczony obrys z narożnikami — do kolizji wycięć, lameli, „mieści się”
        function _outerRing() {
            return ShapeGeometry.outerRing(state.shapeType, state.params, state.vertices, state.corners);
        }

        function _cutoutRings() {
            return state.cutouts.map(function(c) { return ShapeCutouts.ring(c); });
        }

        // Granice formatki (cm): z wierzchołków obrysu, dla koła — kwadrat średnicy
        function _outerBounds() {
            if (state.shapeType === 'circle') {
                var d = state.params.diameter || 0;
                return d > 0 ? { minX: 0, minY: 0, maxX: d, maxY: d } : null;
            }
            var verts = state.vertices;
            if (!verts || verts.length < 3) return null;
            var b = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
            verts.forEach(function(v) {
                b.minX = Math.min(b.minX, v[0]); b.minY = Math.min(b.minY, v[1]);
                b.maxX = Math.max(b.maxX, v[0]); b.maxY = Math.max(b.maxY, v[1]);
            });
            return b;
        }

        // Po każdej zmianie geometrii: narożniki przycięte do limitów, złe wycięcia oznaczone
        function _afterGeometryEdit() {
            state.corners = (state.vertices && state.vertices.length >= 3 && state.shapeType !== 'circle')
                ? ShapeCorners.clampCorners(state.vertices, state.corners)
                : [];
            state.cutouts = state.cutouts.map(function(c) {
                if (c.type !== 'polygon') return c;
                c.corners = ShapeCorners.clampCorners(c.points, c.corners);
                return c;
            });
            state.invalidCutouts = ShapeCutouts.invalidIndices(_outerRing(), state.cutouts);
        }

        // Po obrocie kontur wraca do początku układu, wycięcia jadą tym samym wektorem
        // (eksport SVG i klamerki zakładają kształt zaczynający się w (0,0))
        function _normalizeAfterRotate() {
            if (!state.vertices || !state.vertices.length) return;
            var minX = Infinity, minY = Infinity;
            state.vertices.forEach(function(v) { minX = Math.min(minX, v[0]); minY = Math.min(minY, v[1]); });
            state.vertices = state.vertices.map(function(v) { return [_round(v[0] - minX), _round(v[1] - minY)]; });
            state.cutouts = state.cutouts.map(function(c) {
                return ShapeCutouts.roundCoords(ShapeCutouts.translate(c, -minX, -minY));
            });
        }

        // ============================================
        // GRID RENDERING
        // ============================================

        function _selectGridSpacing() {
            var minPx = 4, maxPx = 80;
            for (var g = 0; g < state.gridLevels.length; g++) {
                var cm = state.gridLevels[g];
                var px = cm * state.scale;
                if (px >= minPx && px <= maxPx) {
                    state.currentGridCm = cm;
                    return;
                }
            }
            for (var g2 = 0; g2 < state.gridLevels.length; g2++) {
                if (state.gridLevels[g2] * state.scale >= minPx) {
                    state.currentGridCm = state.gridLevels[g2];
                    return;
                }
            }
            state.currentGridCm = 1;
        }

        function _renderGrid() {
            _selectGridSpacing();
            var minor = state.currentGridCm;
            var major = minor * 10;

            var cmLeftBottom = pixelToCm(0, state.height);
            var cmRightTop = pixelToCm(state.width, 0);
            var cmLeft = cmLeftBottom[0], cmBottom = cmLeftBottom[1];
            var cmRight = cmRightTop[0], cmTop = cmRightTop[1];

            ctx.strokeStyle = 'rgba(255, 255, 255, 0.22)';
            ctx.lineWidth = 0.5;
            _drawGridLines(cmLeft, cmRight, cmBottom, cmTop, minor);

            ctx.strokeStyle = 'rgba(255, 255, 255, 0.4)';
            ctx.lineWidth = 0.5;
            _drawGridLines(cmLeft, cmRight, cmBottom, cmTop, major);
        }

        function _drawGridLines(cmLeft, cmRight, cmBottom, cmTop, spacing) {
            var startX = Math.floor(cmLeft / spacing) * spacing;
            var startY = Math.floor(cmBottom / spacing) * spacing;

            ctx.beginPath();
            for (var x = startX; x <= cmRight; x += spacing) {
                var pxArr = cmToPixel(x, 0);
                ctx.moveTo(pxArr[0], 0);
                ctx.lineTo(pxArr[0], state.height);
            }
            for (var y = startY; y <= cmTop; y += spacing) {
                var pyArr = cmToPixel(0, y);
                ctx.moveTo(0, pyArr[1]);
                ctx.lineTo(state.width, pyArr[1]);
            }
            ctx.stroke();
        }

        // ============================================
        // SHAPE RENDERING
        // ============================================

        // Punkty do klamerek: wierzchołki obrysu (kształty nietypowe) + punkty wycięć
        function _bracketPointsAll() {
            var isSimple = (state.shapeType === 'rectangular' || state.shapeType === 'circle');
            var pts = (!isSimple && state.vertices) ? state.vertices.slice() : [];
            state.cutouts.forEach(function(c) { pts = pts.concat(ShapeCutouts.bracketPoints(c)); });
            return pts;
        }

        // Dopisuje pozycję klamerki, jeśli jeszcze jej nie ma; zwraca true, gdy dopisała.
        // Mikro-epsilon na drgania float; NIE chowamy klamerek różniących się o 1 mm.
        // Wspólne dla rysowania klamerek (_renderBbox) i liczenia marginesu (_bracketCounts).
        function _pushUnique(arr, v) {
            for (var k = 0; k < arr.length; k++) if (Math.abs(arr[k] - v) < 0.001) return false;
            arr.push(v);
            return true;
        }

        // Ile klamerek stanie nad i obok formatki — tyle miejsca zostawiamy przy dopasowaniu.
        // Wierzchołki obrysu liczymy jak dotąd, każdy osobno, żeby marginesy (i eksport SVG)
        // istniejących wielokątów zostały bez zmian. Punkty wycięć liczymy UNIKALNIE, tak jak
        // _renderBbox rysuje klamerki (jeden poziom na pozycję), z pominięciem pozycji już
        // zajętych przez obrys — prostokątne wycięcie ma każdą współrzędną dwa razy, elipsa
        // cx/cy dwa razy, a liczone wprost zgniatały widok przy kilku wycięciach.
        function _bracketCounts(b) {
            var tol = 0.3, cx = 0, cy = 0;
            var xs = [], ys = [];
            var isSimple = (state.shapeType === 'rectangular' || state.shapeType === 'circle');
            var obrys = (!isSimple && state.vertices) ? state.vertices : [];
            obrys.forEach(function(p) {
                if (Math.abs(p[0] - b.minX) > tol && Math.abs(p[0] - b.maxX) > tol) { cx++; _pushUnique(xs, p[0]); }
                if (Math.abs(p[1] - b.minY) > tol && Math.abs(p[1] - b.maxY) > tol) { cy++; _pushUnique(ys, p[1]); }
            });
            state.cutouts.forEach(function(c) {
                ShapeCutouts.bracketPoints(c).forEach(function(p) {
                    if (Math.abs(p[0] - b.minX) > tol && Math.abs(p[0] - b.maxX) > tol && _pushUnique(xs, p[0])) cx++;
                    if (Math.abs(p[1] - b.minY) > tol && Math.abs(p[1] - b.maxY) > tol && _pushUnique(ys, p[1])) cy++;
                });
            });
            return { x: cx, y: cy };
        }

        function _renderBbox() {
            var isSimple = (state.shapeType === 'rectangular' || state.shapeType === 'circle');
            var b = _outerBounds();
            if (!b) return;
            var bMinX = b.minX, bMinY = b.minY, bMaxX = b.maxX, bMaxY = b.maxY;
            var tolerance = 0.05;

            // Prostokąt i koło: formatka to sam kształt — bez przerywanej ramki
            // i bez wymiarów formatki. Klamerki dostają tylko punkty wycięć.
            if (!isSimple) {
                var verts = state.vertices;
                var p1 = cmToPixel(bMinX, bMinY);
                var p2 = cmToPixel(bMaxX, bMinY);
                var p3 = cmToPixel(bMaxX, bMaxY);
                var p4 = cmToPixel(bMinX, bMaxY);

                ctx.beginPath();
                ctx.moveTo(p1[0], p1[1]);
                ctx.lineTo(p2[0], p2[1]);
                ctx.lineTo(p3[0], p3[1]);
                ctx.lineTo(p4[0], p4[1]);
                ctx.closePath();
                if (!state._svgExportMode) {
                    ctx.fillStyle = 'rgba(230, 126, 34, 0.15)';
                    ctx.fill();
                }
                ctx.strokeStyle = 'rgba(230, 126, 34, 0.7)';
                ctx.lineWidth = 1;
                ctx.setLineDash([4, 4]);
                ctx.stroke();
                ctx.setLineDash([]);

                // Wymiary formatki — pomijaj, jeśli bok formatki pokrywa się z bokiem kształtu
                var bboxW = Math.round((bMaxX - bMinX) * 10) / 10;
                var bboxH = Math.round((bMaxY - bMinY) * 10) / 10;
                var bottomEdgeOverlaps = false;
                var leftEdgeOverlaps = false;
                for (var ei = 0; ei < verts.length; ei++) {
                    var v1 = verts[ei], v2 = verts[(ei + 1) % verts.length];
                    if (Math.abs(v1[1] - bMinY) < tolerance && Math.abs(v2[1] - bMinY) < tolerance
                            && Math.abs(Math.min(v1[0], v2[0]) - bMinX) < tolerance
                            && Math.abs(Math.max(v1[0], v2[0]) - bMaxX) < tolerance) {
                        bottomEdgeOverlaps = true;
                    }
                    if (Math.abs(v1[0] - bMinX) < tolerance && Math.abs(v2[0] - bMinX) < tolerance
                            && Math.abs(Math.min(v1[1], v2[1]) - bMinY) < tolerance
                            && Math.abs(Math.max(v1[1], v2[1]) - bMaxY) < tolerance) {
                        leftEdgeOverlaps = true;
                    }
                }
                if (!bottomEdgeOverlaps) {
                    var bboxWColor = state.outOfRangeDims.length ? '#dc2626' : null;
                    _renderSingleDimension(bMinX, bMinY, bMaxX, bMinY, bboxW + ' cm', 'Formatka', undefined, bboxWColor);
                }
                if (!leftEdgeOverlaps) {
                    var bboxHColor = state.outOfRangeDims.width ? '#dc2626' : null;
                    // Od góry do dołu (w cm), żeby normalna wskazywała w LEWO
                    _renderSingleDimension(bMinX, bMaxY, bMinX, bMinY, bboxH + ' cm', 'Formatka', 40, bboxHColor);
                }
            }

            var allBracketVerts = _bracketPointsAll();
            if (!allBracketVerts.length) return;

            // Linie prowadzące: od punktów (obrys + wycięcia) do krawędzi formatki
            if (state.visibility.guides) {
                ctx.save();
                ctx.strokeStyle = state._svgExportMode ? 'rgba(120, 120, 120, 0.55)' : 'rgba(255, 255, 255, 0.5)';
                ctx.lineWidth = 1.5;
                ctx.setLineDash([6, 6]);
                for (var gi = 0; gi < allBracketVerts.length; gi++) {
                    var gvx = allBracketVerts[gi][0], gvy = allBracketVerts[gi][1];
                    var isOnBboxCorner = (Math.abs(gvx - bMinX) < tolerance || Math.abs(gvx - bMaxX) < tolerance)
                        && (Math.abs(gvy - bMinY) < tolerance || Math.abs(gvy - bMaxY) < tolerance);
                    if (isOnBboxCorner) continue;
                    // Pionowa w górę — gdy punkt NIE leży na lewym/prawym boku formatki
                    var onLeftOrRight = Math.abs(gvx - bMinX) < tolerance || Math.abs(gvx - bMaxX) < tolerance;
                    if (!onLeftOrRight && Math.abs(gvy - bMaxY) > tolerance) {
                        var gp1 = cmToPixel(gvx, gvy);
                        var gp2 = cmToPixel(gvx, bMaxY);
                        ctx.beginPath(); ctx.moveTo(gp1[0], gp1[1]); ctx.lineTo(gp2[0], gp2[1]); ctx.stroke();
                    }
                    // Pozioma w prawo — gdy punkt NIE leży na dolnym/górnym boku formatki
                    var onTopOrBottom = Math.abs(gvy - bMinY) < tolerance || Math.abs(gvy - bMaxY) < tolerance;
                    if (!onTopOrBottom && Math.abs(gvx - bMaxX) > tolerance) {
                        var gp3 = cmToPixel(gvx, gvy);
                        var gp4 = cmToPixel(bMaxX, gvy);
                        ctx.beginPath(); ctx.moveTo(gp3[0], gp3[1]); ctx.lineTo(gp4[0], gp4[1]); ctx.stroke();
                    }
                }
                ctx.restore();
            }

            // Unikalne rzuty X (na górny bok) i Y (na prawy bok) — _pushUnique wspólne z _bracketCounts
            var xPositions = [];
            var yPositions = [];
            for (var bi = 0; bi < allBracketVerts.length; bi++) {
                var vx = allBracketVerts[bi][0], vy = allBracketVerts[bi][1];
                if (Math.abs(vx - bMinX) > tolerance && Math.abs(vx - bMaxX) > tolerance) _pushUnique(xPositions, vx);
                if (Math.abs(vy - bMinY) > tolerance && Math.abs(vy - bMaxY) > tolerance) _pushUnique(yPositions, vy);
            }
            xPositions.sort(function(a, c) { return a - c; });
            yPositions.sort(function(a, c) { return a - c; });

            if (!state.visibility.brackets) return;

            // Klamerki nad górnym bokiem — każda kolejna wyżej
            for (var xi = 0; xi < xPositions.length; xi++) {
                var xDist = xPositions[xi] - bMinX;
                if (xDist > tolerance) _renderBracket(bMinX, bMaxY, xPositions[xi], bMaxY, 'top', xDist, xi);
            }
            // Klamerki przy prawym boku — każda kolejna bardziej w prawo
            for (var yi = 0; yi < yPositions.length; yi++) {
                var yDist = yPositions[yi] - bMinY;
                if (yDist > tolerance) _renderBracket(bMaxX, bMinY, bMaxX, yPositions[yi], 'right', yDist, yi);
            }
        }

        // Rysuje klamerkę wymiarową |----wymiar----|
        function _renderBracket(x1cm, y1cm, x2cm, y2cm, side, distCm, level) {
            var p1 = cmToPixel(x1cm, y1cm);
            var p2 = cmToPixel(x2cm, y2cm);
            var baseOffset = _scaled(14);
            var levelSpacing = _scaled(28); // px odstęp między kolejnymi klamerkami
            var offset = baseOffset + (level || 0) * levelSpacing;
            var tick = _scaled(6);    // px kreski |

            var ox = 0, oy = 0;
            if (side === 'bottom') oy = offset;
            else if (side === 'top') oy = -offset;
            else if (side === 'left') ox = -offset;
            else if (side === 'right') ox = offset;

            var tx = 0, ty = 0;
            if (side === 'bottom' || side === 'top') { ty = tick; }
            else { tx = tick; }

            var sx = p1[0] + ox, sy = p1[1] + oy;
            var ex = p2[0] + ox, ey = p2[1] + oy;

            ctx.save();
            ctx.strokeStyle = '#e67e22';
            ctx.lineWidth = 2;
            ctx.setLineDash([]);

            ctx.beginPath();
            ctx.moveTo(sx, sy);
            ctx.lineTo(ex, ey);
            ctx.stroke();

            ctx.beginPath();
            ctx.moveTo(sx - tx, sy - ty);
            ctx.lineTo(sx + tx, sy + ty);
            ctx.stroke();

            ctx.beginPath();
            ctx.moveTo(ex - tx, ey - ty);
            ctx.lineTo(ex + tx, ey + ty);
            ctx.stroke();

            var label = (Math.round(distCm * 10) / 10) + ' cm';
            var mx = (sx + ex) / 2;
            var my = (sy + ey) / 2;
            ctx.font = 'bold ' + _scaled(15) + 'px sans-serif';
            ctx.fillStyle = '#e67e22';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';

            // Capture pozycji label dla detekcji kolizji z label krawędzi/kątów
            var _hOff = _scaled(14);
            var _vOff = _scaled(12);
            var labelCenterX, labelCenterY;
            if (side === 'right') { labelCenterX = mx + _hOff; labelCenterY = my; }
            else if (side === 'left') { labelCenterX = mx - _hOff; labelCenterY = my; }
            else if (side === 'bottom') { labelCenterX = mx; labelCenterY = my + _vOff; }
            else { labelCenterX = mx; labelCenterY = my - _vOff; } // top
            if (state._bboxLabelBoxes) state._bboxLabelBoxes.push({ x: labelCenterX, y: labelCenterY });

            if (side === 'right' || side === 'left') {
                // Pionowe klamerki — tekst obrócony o 90° w prawo
                var rotOx = (side === 'right' ? _hOff : -_hOff);
                ctx.translate(mx + rotOx, my);
                ctx.rotate(Math.PI / 2);
                ctx.fillText(label, 0, 0);
            } else {
                var labelOy = (side === 'bottom' ? _vOff : -_vOff);
                ctx.fillText(label, mx, my + labelOy);
            }
            ctx.restore();
        }

        // Rysuje listę segmentów (cm) jako zamknięty podkontur bieżącej ścieżki
        function _traceSegments(segs) {
            if (!segs || !segs.length) return;
            var p0 = cmToPixel(segs[0].from[0], segs[0].from[1]);
            ctx.moveTo(p0[0], p0[1]);
            for (var i = 0; i < segs.length; i++) {
                var s = segs[i];
                if (s.type === 'line') {
                    var p = cmToPixel(s.to[0], s.to[1]);
                    ctx.lineTo(p[0], p[1]);
                } else if (s.type === 'arc') {
                    var c = cmToPixel(s.center[0], s.center[1]);
                    var a0 = Math.atan2(s.from[1] - s.center[1], s.from[0] - s.center[0]);
                    var a1 = Math.atan2(s.to[1] - s.center[1], s.to[0] - s.center[0]);
                    // Oś Y odwrócona: kąt na ekranie = −kąt w cm, a łuk CCW w cm
                    // idzie na ekranie przeciwnie do wskazówek zegara (anticlockwise = true)
                    ctx.arc(c[0], c[1], s.radius * state.scale, -a0, -a1, s.ccw);
                } else if (s.type === 'bezier') {
                    var c1 = cmToPixel(s.cp1[0], s.cp1[1]);
                    var c2 = cmToPixel(s.cp2[0], s.cp2[1]);
                    var e = cmToPixel(s.to[0], s.to[1]);
                    ctx.bezierCurveTo(c1[0], c1[1], c2[0], c2[1], e[0], e[1]);
                }
            }
            ctx.closePath();
        }

        function _traceOuter() {
            if (state.shapeType === 'circle') {
                var r = (state.params.diameter || 0) / 2;
                _traceSegments(ShapeCutouts.pathSegments({ type: 'ellipse', cx: r, cy: r, rx: r, ry: r, angle: 0 }));
                return;
            }
            _traceSegments(ShapeCorners.contourSegments(state.vertices, state.corners));
        }

        function _toolShowsHandles() {
            var t = tools && tools[state.activeTool];
            return !!(t && t.showsHandles);
        }

        function _renderShape() {
            state._bboxLabelBoxes = [];
            dimensionHitAreas = [];
            var isCircle = state.shapeType === 'circle';
            if (isCircle) {
                if (!(state.params.diameter > 0)) return;
            } else if (!state.vertices || state.vertices.length < 3) {
                return;
            }
            var theme = COLOR_THEMES[state.colorTheme] || COLOR_THEMES.normal;
            var bladTheme = COLOR_THEMES.error;

            _renderBbox();

            // Obrys + wycięcia jedną ścieżką z evenodd (wycięcia wycinają)
            ctx.beginPath();
            _traceOuter();
            for (var ci = 0; ci < state.cutouts.length; ci++) {
                _traceSegments(ShapeCutouts.pathSegments(state.cutouts[ci]));
            }
            ctx.fillStyle = theme.shapeFill;
            ctx.fill('evenodd');

            if (state.visibility.lamellas) _renderLamellas();

            // Obrys (2px); czerwony, gdy narzędzie N doszło do limitu na obrysie
            ctx.beginPath();
            _traceOuter();
            var limitObrys = state.cornerLimitHit && state.cornerLimitHit.ring === 'outer';
            ctx.strokeStyle = limitObrys ? bladTheme.shapeStroke : theme.shapeStroke;
            ctx.lineWidth = 2;
            ctx.stroke();

            // Wycięcia (1.5px); złe (poza obrysem / nachodzące) albo na limicie — czerwone
            for (var cj = 0; cj < state.cutouts.length; cj++) {
                var zle = state.invalidCutouts.indexOf(cj) >= 0
                    || (state.cornerLimitHit && state.cornerLimitHit.ring === cj);
                ctx.beginPath();
                _traceSegments(ShapeCutouts.pathSegments(state.cutouts[cj]));
                ctx.strokeStyle = zle ? bladTheme.shapeStroke : theme.shapeStroke;
                ctx.lineWidth = zle ? 2.5 : 1.5;
                ctx.stroke();
            }

            _renderActiveHole(theme);

            if (isCircle) {
                _renderCircleDimension();
            } else {
                _renderDimensionLines(state.vertices);
                _renderAngles();
            }
            _renderCutoutDimensions();
            _renderCornerLabels();

            // Uchwyty punktów: w eksporcie zawsze (rysunek produkcji jak dotąd),
            // na żywo tylko w narzędziach pracujących na punktach (A, +, −)
            var uchwyty = state._svgExportMode || _toolShowsHandles();
            if (!isCircle && uchwyty) _renderVertexHandles(state.vertices);
            if (isCircle && !state._svgExportMode && _toolShowsHandles()) _renderCircleHandle();
            if (uchwyty) _renderCutoutHandles();
        }

        // Lamele — poziome linie co LAMELLA_SPACING_CM, przycięte geometrycznie do
        // obrysu z narożnikami i wycięciami (canvas2svg nie przenosi clip z evenodd)
        function _renderLamellas() {
            var outer = _outerRing();
            if (outer.length < 3) return;
            var lamele = ShapeGeometry.horizontalScanSegments(outer, _cutoutRings(), LAMELLA_SPACING_CM);
            if (!lamele.length) return;
            ctx.save();
            ctx.strokeStyle = 'rgba(138, 138, 138, 0.55)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            for (var li = 0; li < lamele.length; li++) {
                var lp1 = cmToPixel(lamele[li][0], lamele[li][2]);
                var lp2 = cmToPixel(lamele[li][1], lamele[li][2]);
                ctx.moveTo(lp1[0], lp1[1]);
                ctx.lineTo(lp2[0], lp2[1]);
            }
            ctx.stroke();
            ctx.restore();
        }

        // Wycięcie rysowane punkt po punkcie (narzędzie +) — linia przerywana
        function _renderActiveHole(theme) {
            if (!state.activeHole || !state.activeHole.length) return;
            ctx.save();
            ctx.strokeStyle = theme.shapeStroke;
            ctx.lineWidth = 1.5;
            ctx.setLineDash([6, 4]);
            ctx.beginPath();
            var as = cmToPixel(state.activeHole[0][0], state.activeHole[0][1]);
            ctx.moveTo(as[0], as[1]);
            for (var ai = 1; ai < state.activeHole.length; ai++) {
                var ap = cmToPixel(state.activeHole[ai][0], state.activeHole[ai][1]);
                ctx.lineTo(ap[0], ap[1]);
            }
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.beginPath();
            ctx.arc(as[0], as[1], state.hoverHoleStart ? 9 : 6, 0, Math.PI * 2);
            ctx.fillStyle = state.hoverHoleStart ? theme.shapeStroke : '#fff';
            ctx.fill();
            ctx.strokeStyle = theme.shapeStroke;
            ctx.lineWidth = 2;
            ctx.stroke();
            for (var ai2 = 1; ai2 < state.activeHole.length; ai2++) {
                var aap = cmToPixel(state.activeHole[ai2][0], state.activeHole[ai2][1]);
                ctx.beginPath();
                ctx.arc(aap[0], aap[1], 4, 0, Math.PI * 2);
                ctx.fillStyle = '#fff';
                ctx.fill();
                ctx.stroke();
            }
            ctx.restore();
        }

        // Stałe etykiety narożników („R50”, „20×45°”) — trafiają też do SVG dla produkcji
        function _renderCornerLabels() {
            if (!state.visibility.corners) return;
            var pierscienie = [];
            if (state.vertices && state.shapeType !== 'circle') {
                pierscienie.push({ pts: state.vertices, corners: state.corners });
            }
            state.cutouts.forEach(function(c) {
                if (c.type === 'polygon') pierscienie.push({ pts: c.points, corners: c.corners });
            });
            // Przy aktywnym N kropka do przeciągania leży tuż za środkiem łuku, czyli tam, gdzie
            // etykieta — wtedy etykieta idzie dalej wzdłuż dwusiecznej. Eksport SVG (rysunek dla
            // produkcji) i pozostałe narzędzia: pozycja jak dotąd.
            var narzedzieN = (!state._svgExportMode && state.activeTool === 'corner') ? _activeToolObj() : null;
            var rozmiarFontu = _scaled(13);
            ctx.save();
            ctx.font = 'bold ' + rozmiarFontu + 'px sans-serif';
            ctx.fillStyle = '#e67e22';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            pierscienie.forEach(function(r) {
                var n = r.pts.length;
                for (var i = 0; i < n; i++) {
                    var corner = r.corners && r.corners[i];
                    if (!corner) continue;
                    var ang = ShapeCorners.cornerAngle(r.pts[(i - 1 + n) % n], r.pts[i], r.pts[(i + 1) % n]);
                    if (!ang) continue;
                    var tekst = ShapeCorners.label(corner, ang.theta);
                    var distPx = ShapeCorners.midpointDistance(ang.theta, corner) * state.scale + _scaled(18);
                    var kropka = (narzedzieN && narzedzieN.dotPlacement) ? narzedzieN.dotPlacement(ang.theta, corner) : null;
                    if (kropka) {
                        // Prostokąt tekstu (środek na dwusiecznej) sięga w stronę kropki o swój rzut
                        // na dwusieczną: pół szerokości·|bx| + pół wysokości·|by|. Środek etykiety
                        // odsuwamy od środka kropki o ten rzut + zasięg koła + odstęp 3 px — wtedy
                        // cały prostokąt leży za kołem i na nie nie nachodzi.
                        var rzutTekstu = ctx.measureText(tekst).width / 2 * Math.abs(ang.bisector[0])
                            + rozmiarFontu / 2 * Math.abs(ang.bisector[1]);
                        distPx = kropka.dist + kropka.radius + 3 + rzutTekstu;
                    }
                    var v = cmToPixel(r.pts[i][0], r.pts[i][1]);
                    // Dwusieczna w pikselach: oś Y odwrócona
                    ctx.fillText(tekst, v[0] + ang.bisector[0] * distPx, v[1] - ang.bisector[1] * distPx);
                }
            });
            ctx.restore();
        }

        // Etykiety kątów wewnętrznych (tylko nie-90° ±1°)
        function _renderAngles() {
            if (!state.visibility.angles) return;

            function _renderRing(ring) {
                if (!ring || ring.length < 3) return;
                var n = ring.length;
                for (var i = 0; i < n; i++) {
                    var prev = ring[(i - 1 + n) % n];
                    var curr = ring[i];
                    var next = ring[(i + 1) % n];

                    var inDx = curr[0] - prev[0], inDy = curr[1] - prev[1];
                    var outDx = next[0] - curr[0], outDy = next[1] - curr[1];
                    var inLen = Math.sqrt(inDx * inDx + inDy * inDy);
                    var outLen = Math.sqrt(outDx * outDx + outDy * outDy);
                    if (inLen < 0.01 || outLen < 0.01) continue;

                    var nInDx = inDx / inLen, nInDy = inDy / inLen;
                    var nOutDx = outDx / outLen, nOutDy = outDy / outLen;
                    // Kąt wewnętrzny: między -inVec i outVec
                    var dot = (-nInDx) * nOutDx + (-nInDy) * nOutDy;
                    if (dot > 1) dot = 1; if (dot < -1) dot = -1;
                    var angleDeg = Math.round(Math.acos(dot) * 180 / Math.PI);
                    if (Math.abs(angleDeg - 90) <= 1) continue;

                    // Bisektor (cm) → wnętrze rogu = uśredniony kierunek od curr w stronę "do środka"
                    var bx = (-nInDx) + nOutDx;
                    var by = (-nInDy) + nOutDy;
                    var bLen = Math.sqrt(bx * bx + by * by);
                    if (bLen < 0.001) continue;
                    bx /= bLen; by /= bLen;

                    // Pozycje w pixelach
                    var cPx = cmToPixel(curr[0], curr[1]);
                    // Wektory in/out w układzie ekranowym (Y odwrócone w cmToPixel)
                    var pPx = cmToPixel(prev[0], prev[1]);
                    var nPx = cmToPixel(next[0], next[1]);
                    var scrInX = cPx[0] - pPx[0], scrInY = cPx[1] - pPx[1];
                    var scrOutX = nPx[0] - cPx[0], scrOutY = nPx[1] - cPx[1];
                    var scrInLen = Math.sqrt(scrInX * scrInX + scrInY * scrInY);
                    var scrOutLen = Math.sqrt(scrOutX * scrOutX + scrOutY * scrOutY);
                    if (scrInLen < 1 || scrOutLen < 1) continue;

                    // Łuk: od kierunku -in do +out. Dla ostrych kątów zwiększamy promień,
                    // żeby łuk miał sensowną długość (przy 13° na r=14 to ~3px ledwo widoczna kreseczka).
                    var startAng = Math.atan2(-scrInY, -scrInX); // wektor od curr w stronę prev (na ekranie)
                    var endAng = Math.atan2(scrOutY, scrOutX);   // wektor od curr w stronę next (na ekranie)
                    var _safeAngForArc = Math.max(2, angleDeg);
                    var r = Math.min(72, Math.max(36, 8 / Math.sin(_safeAngForArc / 2 * Math.PI / 180))) * _mul();

                    // Wybierz kierunek łuku po krótszej stronie (ta będzie po stronie wnętrza)
                    var diff = endAng - startAng;
                    while (diff > Math.PI) diff -= 2 * Math.PI;
                    while (diff < -Math.PI) diff += 2 * Math.PI;
                    var ccw = diff < 0;

                    ctx.save();
                    ctx.strokeStyle = 'rgba(230, 126, 34, 0.7)';
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.arc(cPx[0], cPx[1], r, startAng, endAng, ccw);
                    ctx.stroke();

                    // Tekst na bisektorze ekranowym (w stronę środka łuku)
                    var midAng = startAng + (ccw ? -Math.abs(diff) / 2 : Math.abs(diff) / 2);
                    // Promień bazowy + dynamiczne odsunięcie dla ostrych kątów,
                    // żeby tekst nie wpadł między krawędzie tworzące klin.
                    // Odległość perpendykularna do krawędzi = angleRadius * sin(kąt/2).
                    // Aby tekst (~wys. 14px) zmieścił się obok krawędzi, potrzebujemy
                    // sin(kąt/2) * angleRadius > ~12px → angleRadius > 12 / sin(kąt/2).
                    var safeAngle = Math.max(2, angleDeg);
                    var edgeClearance = (20 / Math.sin(safeAngle / 2 * Math.PI / 180)) * _mul();
                    var angleRadius = Math.min(110 * _mul(), Math.max(r + _scaled(14), edgeClearance));
                    var tx = cPx[0] + Math.cos(midAng) * angleRadius;
                    var ty = cPx[1] + Math.sin(midAng) * angleRadius;

                    // Detekcja kolizji z label bbox/Formatka — zwiększ promień jeśli kolizja
                    if (state._bboxLabelBoxes && state._bboxLabelBoxes.length > 0) {
                        for (var abi = 0; abi < state._bboxLabelBoxes.length; abi++) {
                            var ab = state._bboxLabelBoxes[abi];
                            if (Math.abs(tx - ab.x) < ANGLE_COLLISION_RADIUS * _mul() &&
                                Math.abs(ty - ab.y) < ANGLE_COLLISION_RADIUS * _mul()) {
                                angleRadius = r + _scaled(40);
                                tx = cPx[0] + Math.cos(midAng) * angleRadius;
                                ty = cPx[1] + Math.sin(midAng) * angleRadius;
                                break;
                            }
                        }
                    }

                    ctx.font = 'bold ' + _scaled(14) + 'px sans-serif';
                    ctx.fillStyle = 'rgba(230, 126, 34, 0.9)';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(angleDeg + '°', tx, ty);
                    ctx.restore();
                }
            }

            _renderRing(state.vertices);
            for (var ci = 0; ci < state.cutouts.length; ci++) {
                if (state.cutouts[ci].type === 'polygon') _renderRing(state.cutouts[ci].points);
            }
        }

        function _renderCutoutHandles() {
            for (var ci = 0; ci < state.cutouts.length; ci++) {
                var c = state.cutouts[ci];
                if (c.type !== 'polygon') continue;
                for (var pj = 0; pj < c.points.length; pj++) {
                    var pt = cmToPixel(c.points[pj][0], c.points[pj][1]);
                    var hov = state.hoverVertex && state.hoverVertex.kind === 'cutout'
                        && state.hoverVertex.ci === ci && state.hoverVertex.pj === pj;
                    _drawHandle(pt[0], pt[1], hov);
                }
            }
        }

        function _renderCutoutDimensions() {
            if (!state.visibility.dimensions) return;
            for (var ci = 0; ci < state.cutouts.length; ci++) {
                var c = state.cutouts[ci];
                if (c.type === 'ellipse') {
                    // Koło: „Ø 20 cm”, elipsa: „30 × 20 cm” w środku wycięcia
                    var kolo = ShapeTools._jestKolem(c);   // jedna definicja koła z narzędziem V
                    var tekst = kolo
                        ? 'Ø ' + (Math.round(c.rx * 20) / 10) + ' cm'
                        : (Math.round(c.rx * 20) / 10) + ' × ' + (Math.round(c.ry * 20) / 10) + ' cm';
                    var p = cmToPixel(c.cx, c.cy);
                    ctx.save();
                    ctx.font = _scaled(14) + 'px sans-serif';
                    ctx.fillStyle = '#e67e22';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(tekst, p[0], p[1]);
                    ctx.restore();
                    continue;
                }
                var h = c.points, n = h.length;
                for (var i = 0; i < n; i++) {
                    var j = (i + 1) % n;
                    var len = Math.hypot(h[j][0] - h[i][0], h[j][1] - h[i][1]);
                    if (len < 0.1) continue;
                    // Bez oznaczeń Gx — mniej szumu na wycięciach
                    _renderSingleDimension(h[i][0], h[i][1], h[j][0], h[j][1], (Math.round(len * 10) / 10) + ' cm', null, -16);
                }
            }
        }

        // Wymiar średnicy koła (obrys)
        function _renderCircleDimension() {
            var d = state.params.diameter || 0;
            _renderSingleDimension(0, d / 2, d, d / 2, d + ' cm');
        }

        // Uchwyt średnicy koła (narzędzie A)
        function _renderCircleHandle() {
            var d = state.params.diameter || 0;
            var handle = cmToPixel(d, d / 2);
            _drawHandle(handle[0], handle[1], state.hoverVertex === 0);
        }

        function _renderVertexHandles(verts) {
            for (var i = 0; i < verts.length; i++) {
                var pt = cmToPixel(verts[i][0], verts[i][1]);
                _drawHandle(pt[0], pt[1], state.hoverVertex === i || state.dragVertex === i);
            }
        }

        function _drawHandle(px, py, isHovered) {
            var r = isHovered ? 7 : 5;
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
            dimensionHitAreas = [];
            if (!state.visibility.dimensions) return;
            var n = verts.length;
            for (var i = 0; i < n; i++) {
                var j = (i + 1) % n;
                var dx = verts[j][0] - verts[i][0];
                var dy = verts[j][1] - verts[i][1];
                var len = Math.sqrt(dx * dx + dy * dy);
                if (len < 0.1) continue;
                var dimLabel = (Math.round(len * 10) / 10) + ' cm';
                var edgeId = 'G' + (i + 1);
                var labelPos = _renderSingleDimension(verts[i][0], verts[i][1], verts[j][0], verts[j][1], dimLabel, edgeId);
                if (labelPos) {
                    dimensionHitAreas.push({ x: labelPos.x, y: labelPos.y, edgeIndex: i, length: len });
                }
            }
        }

        function _renderSingleDimension(x1, y1, x2, y2, label, edgeId, offsetOverride, colorOverride) {
            var p1 = cmToPixel(x1, y1);
            var p2 = cmToPixel(x2, y2);

            ctx.save();

            var dx = p2[0] - p1[0], dy = p2[1] - p1[1];
            var len = Math.sqrt(dx * dx + dy * dy);
            if (len < 1) { ctx.restore(); return; }
            var dist = (offsetOverride !== undefined ? offsetOverride : 22) * _mul();
            var nx = -dy / len * dist, ny = dx / len * dist;

            // Pozycja wymiaru: domyślnie środek krawędzi
            var mx = (p1[0] + p2[0]) / 2;
            var my = (p1[1] + p2[1]) / 2;

            // Sticky: przytrzymaj wymiar w widocznym obszarze canvasu
            // Jeśli środek krawędzi wychodzi poza canvas, przesuń wymiar wzdłuż krawędzi
            var pad = 15; // margines od krawędzi canvasu
            var labelX = mx + nx;
            var labelY = my + ny;

            // Clamp pozycji wzdłuż krawędzi (parametr t: 0=p1, 1=p2)
            // Oblicz t dla którego label jest w widocznym obszarze
            var bestT = 0.5;
            if (edgeId && len > 10) {
                // Znajdź zakres t dla którego punkt na krawędzi + offset mieści się w canvasie
                var candidateX = p1[0] + bestT * dx + nx;
                var candidateY = p1[1] + bestT * dy + ny;

                // Sprawdź czy środek jest w widocznym obszarze
                var inBounds = candidateX > pad && candidateX < state.width - pad
                            && candidateY > pad && candidateY < state.height - pad;

                if (!inBounds) {
                    // Szukaj najlepszego t żeby label był w canvasie
                    // Próbkuj wzdłuż krawędzi
                    var found = false;
                    for (var st = 0.02; st <= 0.98; st += 0.02) {
                        var cx = p1[0] + st * dx + nx;
                        var cy = p1[1] + st * dy + ny;
                        if (cx > pad && cx < state.width - pad && cy > pad && cy < state.height - pad) {
                            bestT = st;
                            found = true;
                            // Preferuj punkt bliżej środka
                            if (st >= 0.45) break;
                        }
                    }
                    if (!found) {
                        // Krawędź całkowicie poza ekranem — nie rysuj
                        ctx.restore();
                        return;
                    }
                }

                labelX = p1[0] + bestT * dx + nx;
                labelY = p1[1] + bestT * dy + ny;

                // Finalny clamp do granic canvasu
                labelX = Math.max(pad, Math.min(state.width - pad, labelX));
                labelY = Math.max(pad, Math.min(state.height - pad, labelY));
            }

            // Detekcja kolizji label krawędzi outer ring z label bbox/Formatka
            // (flip TYLKO dla outer ring — edgeId zaczyna się od 'G', np. G1, G2, G3)
            var isOuterRingLabel = edgeId && edgeId.charAt(0) === 'G';
            if (isOuterRingLabel && state._bboxLabelBoxes && state._bboxLabelBoxes.length > 0) {
                var collides = false;
                for (var bi = 0; bi < state._bboxLabelBoxes.length; bi++) {
                    var b = state._bboxLabelBoxes[bi];
                    if (Math.abs(labelX - b.x) < COLLISION_RADIUS * _mul() &&
                        Math.abs(labelY - b.y) < COLLISION_RADIUS * _mul()) {
                        collides = true;
                        break;
                    }
                }
                if (collides) {
                    // Flip na wewnętrzną stronę krawędzi: zamień znak normalnej (nx, ny)
                    labelX = p1[0] + bestT * dx - nx;
                    labelY = p1[1] + bestT * dy - ny;
                    labelX = Math.max(pad, Math.min(state.width - pad, labelX));
                    labelY = Math.max(pad, Math.min(state.height - pad, labelY));
                }
            }

            // Jeśli to label bbox (Formatka), zapisz pozycję do detekcji kolizji
            if (edgeId === 'Formatka' && state._bboxLabelBoxes) {
                state._bboxLabelBoxes.push({ x: labelX, y: labelY });
            }

            // Wymiar
            ctx.font = _scaled(15) + 'px sans-serif';
            ctx.fillStyle = colorOverride || '#e67e22';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            ctx.fillText(label, labelX, labelY);

            // Oznaczenie boku (G1, G2...) — pod wymiarem. Prostokąt bez liter: moduł krawędzi
            // opisuje jego boki literami A–H, więc G1–G4 na rysunku (i w SVG produkcji) myliłyby.
            // edgeId zostaje (pozycja etykiety, odsuwanie od wymiarów formatki).
            if (edgeId && state.shapeType !== 'rectangular') {
                ctx.font = 'bold ' + _scaled(13) + 'px sans-serif';
                ctx.fillStyle = colorOverride ? colorOverride : 'rgba(230, 126, 34, 0.6)';
                ctx.textBaseline = 'top';
                ctx.fillText(edgeId, labelX, labelY + _scaled(2));
            }

            ctx.restore();
            return { x: labelX, y: labelY };
        }

        // ============================================
        // SCALE INDICATOR
        // ============================================

        function getScaleLabel() {
            var cm = state.currentGridCm;
            if (cm < 1) return '1 kratka = ' + (cm * 10) + ' mm';
            return '1 kratka = ' + cm + ' cm';
        }

        // ============================================
        // MAIN RENDER
        // ============================================

        function render() {
            ctx.clearRect(0, 0, state.width, state.height);
            ctx.fillStyle = '#1a1a2e';
            ctx.fillRect(0, 0, state.width, state.height);
            _renderGrid();
            _renderShape();
            // Nakładka narzędzia (dymki, ramki, kropki) — NIE trafia do eksportu SVG,
            // bo exportSVG woła tylko _renderShape()
            var tool = tools && tools[state.activeTool];
            if (tool && tool.renderOverlay) tool.renderOverlay();
            if (options.scaleIndicator) {
                options.scaleIndicator.textContent = getScaleLabel();
            }
        }

        // ============================================
        // INTERACTIONS: ZOOM
        // ============================================

        _on(canvasElement, 'wheel', function(e) {
            e.preventDefault();
            var zoomFactor = e.deltaY > 0 ? 0.85 : 1.15;
            var rect = canvasElement.getBoundingClientRect();
            var mouseX = e.clientX - rect.left;
            var mouseY = e.clientY - rect.top;

            var cmPt = pixelToCm(mouseX, mouseY);
            state.scale *= zoomFactor;
            state.scale = Math.max(0.1, Math.min(100, state.scale));
            state.offsetX = mouseX - cmPt[0] * state.scale;
            state.offsetY = (state.height - mouseY) - cmPt[1] * state.scale;

            render();
        }, { passive: false });

        // ============================================
        // INTERAKCJE: dyspozytor narzędzi + przesuwanie widoku
        // ============================================

        function _pointer(e) {
            var rect = canvasElement.getBoundingClientRect();
            var px = e.clientX - rect.left, py = e.clientY - rect.top;
            return { px: px, py: py, cm: pixelToCm(px, py), shift: e.shiftKey, alt: e.altKey, button: e.button, event: e };
        }

        function _activeToolObj() {
            return tools ? tools[state.activeTool] : null;
        }

        function _startPan(p) {
            state.isPanning = true;
            state.panStartX = p.px - state.offsetX;
            state.panStartY = (state.height - p.py) - state.offsetY;
            canvasElement.style.cursor = 'grabbing';
        }

        _on(canvasElement, 'mousedown', function(e) {
            canvasElement.focus();   // skróty klawiszowe działają po kliknięciu w canvas
            var p = _pointer(e);
            var tool = _activeToolObj();
            if (tool && tool.onDown && tool.onDown(p) === true) return;
            if (e.button !== 0) return;
            _startPan(p);
        });

        // Podświetlenie punktu pod kursorem (obrys, wycięcia, uchwyt średnicy koła).
        // Wspólne dla narzędzi z uchwytami (A, +, −) — w „−” widać, który punkt zniknie.
        // _findVertexAt zwraca -1, gdy nic nie trafiono; obiekt trafienia w wycięcie
        // porównujemy przez JSON, bo to za każdym razem nowy obiekt.
        function _updateHover(p) {
            var hov = _findVertexAt(p.px, p.py);
            if (JSON.stringify(hov) === JSON.stringify(state.hoverVertex)) return;
            state.hoverVertex = hov;
            canvasElement.classList.toggle('hovering-vertex', hov !== -1);
            render();
        }

        _on(canvasElement, 'mousemove', function(e) {
            var p = _pointer(e);
            if (state.isPanning) {
                state.offsetX = p.px - state.panStartX;
                state.offsetY = (state.height - p.py) - state.panStartY;
                render();
                return;
            }
            var tool = _activeToolObj();
            var obsluzone = !!(tool && tool.onMove && tool.onMove(p) === true);
            // Gdy narzędzie samo obsłużyło ruch (np. przeciąganie w A), podświetlenia nie ruszamy
            if (!obsluzone && tool && tool.showsHandles) _updateHover(p);
        });

        _on(canvasElement, 'mouseup', function(e) {
            var tool = _activeToolObj();
            if (tool && tool.onUp) tool.onUp(_pointer(e));
            state.isPanning = false;
            canvasElement.style.cursor = '';
        });

        _on(canvasElement, 'mouseleave', function() {
            var tool = _activeToolObj();
            if (tool && tool.onLeave) tool.onLeave();
            state.isPanning = false;
            canvasElement.style.cursor = '';
        });

        _on(canvasElement, 'contextmenu', function(e) { e.preventDefault(); });

        _on(canvasElement, 'dblclick', function(e) {
            var p = _pointer(e);
            var tool = _activeToolObj();
            if (tool && tool.onDblClick && tool.onDblClick(p) === true) return;
            _editDimensionAt(p.px, p.py);
        });

        canvasElement.setAttribute('tabindex', '0');
        canvasElement.style.outline = 'none';
        _on(canvasElement, 'keydown', function(e) {
            var tool = _activeToolObj();
            if (tool && tool.onKey && tool.onKey(e) === true) {
                // Obsłużone przez narzędzie (np. Esc) — nie zamykaj trybu pełnoekranowego
                e.preventDefault();
                e.stopPropagation();
                return;
            }
            var isCtrl = e.ctrlKey || e.metaKey;
            var z = (e.key === 'z' || e.key === 'Z');
            if (isCtrl && z && !e.shiftKey) { e.preventDefault(); undo(); }
            else if (isCtrl && z && e.shiftKey) { e.preventDefault(); redo(); }
        });

        // Pole do wpisania wartości nad canvasem (wymiar boku, odległość, wymiar narożnika)
        function _openInlineInput(px, py, value, onApply, opts) {
            var o = opts || {};
            var wrapper = canvasElement.parentElement;
            var input = document.createElement('input');
            input.type = 'number';
            input.step = o.step || '0.1';
            input.min = (o.min != null) ? String(o.min) : '0.1';
            if (o.max != null) input.max = String(o.max);
            input.value = value;
            input.style.cssText = 'position:absolute;left:' + (px - 35) + 'px;top:' + (py - 12) + 'px;' +
                'width:70px;height:24px;font-size:12px;text-align:center;border:2px solid #e67e22;' +
                'border-radius:4px;background:#1a1a2e;color:#e67e22;outline:none;z-index:10;font-weight:bold;';
            wrapper.appendChild(input);
            input.focus();
            input.select();
            var zamkniete = false;
            // oddajFokus: tylko przy zamknięciu klawiszem (Enter/Esc) wracamy fokusem na canvas,
            // żeby skróty działały dalej. Przy blur NIE — użytkownik kliknął gdzie indziej
            // (np. w inne pole formularza) i tam ma zostać fokus.
            function zamknij(zastosuj, oddajFokus) {
                if (zamkniete) return;
                zamkniete = true;
                var v = parseFloat(input.value);
                if (input.parentNode) input.parentNode.removeChild(input);
                if (zastosuj && !isNaN(v)) onApply(v);
                if (oddajFokus) canvasElement.focus();
            }
            input.addEventListener('blur', function() { zamknij(true, false); });
            input.addEventListener('keydown', function(ev) {
                ev.stopPropagation();   // Esc nie zamyka trybu pełnoekranowego, litery nie przełączają narzędzi
                if (ev.key === 'Enter') { ev.preventDefault(); zamknij(true, true); }
                if (ev.key === 'Escape') { ev.preventDefault(); zamknij(false, true); }
            });
        }

        // Dwuklik na wymiarze boku obrysu — wpisanie nowej długości.
        // Prostokąt zostaje prostokątem: bok poziomy zmienia długość, pionowy szerokość, a nowy
        // wymiar idzie przez setOuterParams i emisję do pól formularza (jak zmiana pola wymiaru).
        // Wielokąt: przesuwamy drugi koniec boku, wierzchołek zaokrąglony do 0,1 cm przed walidacją.
        // Ta sama wartość co na etykiecie nic nie zmienia (bez wpisu historii).
        function _editDimensionAt(mx, my) {
            var hit = null;
            for (var di = 0; di < dimensionHitAreas.length; di++) {
                var d = dimensionHitAreas[di];
                if (Math.hypot(mx - d.x, my - d.y) < 25) { hit = d; break; }
            }
            if (!hit) return;
            var edgeIdx = hit.edgeIndex;
            var pokazana = Math.round(hit.length * 10) / 10;
            _openInlineInput(hit.x, hit.y, pokazana, function(newLen) {
                if (!(newLen > 0) || !state.vertices) return;
                if (Math.abs(newLen - pokazana) < 1e-9) return;
                var vi = edgeIdx, vj = (edgeIdx + 1) % state.vertices.length;
                var oldDx = state.vertices[vj][0] - state.vertices[vi][0];
                var oldDy = state.vertices[vj][1] - state.vertices[vi][1];
                var oldLen = Math.sqrt(oldDx * oldDx + oldDy * oldDy);
                if (oldLen <= 0.01) return;
                if (state.shapeType === 'rectangular') {
                    var b = _outerBounds();
                    if (!b) return;
                    var wymiary = { length: b.maxX - b.minX, width: b.maxY - b.minY };
                    wymiary[Math.abs(oldDx) >= Math.abs(oldDy) ? 'length' : 'width'] = newLen;
                    _pushUndo();
                    setOuterParams(wymiary);
                    _emitChange();
                    render();
                    return;
                }
                var skala = newLen / oldLen;
                var nowy = [_round(state.vertices[vi][0] + oldDx * skala), _round(state.vertices[vi][1] + oldDy * skala)];
                if (nowy[0] === state.vertices[vj][0] && nowy[1] === state.vertices[vj][1]) return;
                _pushUndo();
                state.vertices[vj] = nowy;
                _convertToPolygonIfNeeded();
                _emitChange();
                render();
            });
        }

        // ============================================
        // TRAFIENIA (punkty, boki, wycięcia)
        // ============================================

        function _findVertexAt(px, py) {
            var hitR = 12;
            if (state.shapeType === 'circle') {
                var d = state.params.diameter || 0;
                var hPt = cmToPixel(d, d / 2);
                if (d > 0 && Math.hypot(px - hPt[0], py - hPt[1]) < hitR) return 0;
            } else if (state.vertices) {
                for (var i = 0; i < state.vertices.length; i++) {
                    var vPt = cmToPixel(state.vertices[i][0], state.vertices[i][1]);
                    if (Math.hypot(px - vPt[0], py - vPt[1]) < hitR) return i;
                }
            }
            for (var ci = 0; ci < state.cutouts.length; ci++) {
                var c = state.cutouts[ci];
                if (c.type !== 'polygon') continue;
                for (var pj = 0; pj < c.points.length; pj++) {
                    var p = cmToPixel(c.points[pj][0], c.points[pj][1]);
                    if (Math.hypot(px - p[0], py - p[1]) < hitR) return { kind: 'cutout', ci: ci, pj: pj };
                }
            }
            return -1;
        }

        function _findCutoutEdgeAt(px, py) {
            for (var ci = 0; ci < state.cutouts.length; ci++) {
                var c = state.cutouts[ci];
                if (c.type !== 'polygon') continue;
                var n = c.points.length;
                for (var i = 0; i < n; i++) {
                    var a = cmToPixel(c.points[i][0], c.points[i][1]);
                    var b = cmToPixel(c.points[(i + 1) % n][0], c.points[(i + 1) % n][1]);
                    if (_pointToSegmentDist(px, py, a[0], a[1], b[0], b[1]) < 8) return { ci: ci, edgeIdx: i };
                }
            }
            return null;
        }

        // Indeks wycięcia pod punktem (cm); ostatnio dodane leży „na wierzchu”
        function _findCutoutAt(cm) {
            for (var ci = state.cutouts.length - 1; ci >= 0; ci--) {
                if (ShapeGeometry.pointInPolygon(cm[0], cm[1], ShapeCutouts.ring(state.cutouts[ci]))) return ci;
            }
            return -1;
        }

        function _showHint(msg) {
            // Podpowiedź szukamy w edytorze kształtu, nie w formularzu: w trybie pełnoekranowym
            // cały edytor (z podpowiedzią) jest przeniesiony do okna poza .quote-form
            var editorEl = canvasElement.closest('[data-shape-editor]');
            var hintEl = editorEl ? editorEl.querySelector('[data-shape-hint]') : null;
            if (!hintEl) return;
            // Tekst sprzed PIERWSZEJ podpowiedzi z serii. Kolejna podpowiedź w ciągu 3 s
            // (np. przy przeciąganiu wycięcia poniżej 1 cm leci przy każdym ruchu myszy)
            // zapamiętałaby jako „poprzedni” sam czerwony komunikat i ten zostałby na stałe.
            if (!state._hintSaved) state._hintSaved = { el: hintEl, text: hintEl.textContent, color: hintEl.style.color };
            hintEl.textContent = msg;
            hintEl.style.color = '#dc2626';
            clearTimeout(state._hintTimeout);
            state._hintTimeout = setTimeout(_restoreHint, 3000);
        }

        // Przywraca tekst i kolor podpowiedzi sprzed serii czerwonych komunikatów
        // (po 3 s, a także przy destroy — inaczej czerwony komunikat zostałby na stałe)
        function _restoreHint() {
            var zapis = state._hintSaved;
            state._hintSaved = null;
            if (!zapis) return;
            zapis.el.textContent = zapis.text;
            zapis.el.style.color = zapis.color || '';
        }

        function _findEdgeAt(px, py) {
            if (!state.vertices || state.vertices.length < 2) return -1;
            var hitDist = 8;
            var n = state.vertices.length;
            for (var i = 0; i < n; i++) {
                var j = (i + 1) % n;
                var p1 = cmToPixel(state.vertices[i][0], state.vertices[i][1]);
                var p2 = cmToPixel(state.vertices[j][0], state.vertices[j][1]);
                var dist = _pointToSegmentDist(px, py, p1[0], p1[1], p2[0], p2[1]);
                if (dist < hitDist) return i;
            }
            return -1;
        }

        function _pointToSegmentDist(px, py, x1, y1, x2, y2) {
            var dx = x2 - x1, dy = y2 - y1;
            var lenSq = dx * dx + dy * dy;
            if (lenSq === 0) return Math.hypot(px - x1, py - y1);
            var t = ((px - x1) * dx + (py - y1) * dy) / lenSq;
            t = Math.max(0, Math.min(1, t));
            return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
        }

        // ============================================
        // UNDO / REDO
        // ============================================

        function _convertToPolygonIfNeeded() {
            // Pierwsza edycja punktu na nie-polygon nie-eliptycznym kształcie → konwersja typu
            if (state.shapeType === 'polygon' || state.shapeType === 'circle' || state.shapeType === 'oval') return;
            state.shapeType = 'polygon';
            state.onShapeTypeChange('polygon');
        }

        // Migawka niesie też typ kształtu: + i − na boku, A na wierzchołku i obrót zamieniają
        // prostokąt (trójkąt, trapez…) w wielokąt, a cofnięcie ma przywrócić także typ
        function _snapshot() {
            return JSON.stringify({
                vertices: state.vertices, corners: state.corners, cutouts: state.cutouts,
                rotation: state.rotation, params: state.params, shapeType: state.shapeType
            });
        }

        function _restoreSnapshot(json) {
            var s = JSON.parse(json);
            state.vertices = s.vertices;
            state.corners = s.corners || [];
            // Tolerancja na migawki sprzed wycięć-obiektów (holes jako pierścienie)
            state.cutouts = s.cutouts ? ShapeCutouts.clone(s.cutouts) : ShapeCutouts.fromHoles(s.holes);
            state.rotation = s.rotation || 0;
            if (s.params) state.params = s.params;
            state.selection = null;
            // Typ na końcu: edytor dostaje go z już przywróconą geometrią
            if (s.shapeType && s.shapeType !== state.shapeType) {
                state.shapeType = s.shapeType;
                state.onShapeTypeChange(s.shapeType);
            }
        }

        function _pushUndoSnapshot(json) {
            state.undoStack.push(json);
            if (state.undoStack.length > state.maxUndo) state.undoStack.shift();
            state.redoStack = [];
        }

        function _pushUndo() { _pushUndoSnapshot(_snapshot()); }
        function _popUndo() { state.undoStack.pop(); }

        // Czy aktywne narzędzie jest w trakcie gestu (przeciąganie punktu w A, obrót w R,
        // w zadaniu 6 przesuwanie/skalowanie wycięcia w V). Narzędzie zgłasza to metodą
        // inGesture(). W trakcie gestu nie cofamy ani nie ponawiamy: gest trzyma odwołania
        // do geometrii sprzed cofnięcia (indeks punktu, migawkę obrotu), więc drugi Ctrl+Z
        // dawał TypeError albo zapis poza listą punktów. Dotyczy też przycisków ↩/↪ —
        // edytor woła te same undo()/redo().
        function _gestureInProgress() {
            var t = _activeToolObj();
            return !!(t && t.inGesture && t.inGesture());
        }

        function undo() {
            if (state.undoStack.length === 0 || _gestureInProgress()) return;
            state.redoStack.push(_snapshot());
            _restoreSnapshot(state.undoStack.pop());
            _emitChange();
            render();
        }

        function redo() {
            if (state.redoStack.length === 0 || _gestureInProgress()) return;
            state.undoStack.push(_snapshot());
            _restoreSnapshot(state.redoStack.pop());
            _emitChange();
            render();
        }

        // ============================================
        // FIT TO VIEW
        // ============================================

        function fitToView() {
            var b = _outerBounds();
            if (!b) { render(); return; }
            var bw = b.maxX - b.minX, bh = b.maxY - b.minY;
            if (bw <= 0 || bh <= 0) return;
            var cnt = _bracketCounts(b);
            var bracketSpacing = 28;
            var prosty = (state.shapeType === 'rectangular' || state.shapeType === 'circle') && cnt.x === 0 && cnt.y === 0;
            var extraRight = prosty ? 30 : (cnt.y * bracketSpacing + 30);
            var extraTop = prosty ? 30 : (cnt.x * bracketSpacing + 40);
            var extraBottom = 60;   // margines na wymiar dolny formatki
            var extraLeft = 60;     // margines na wymiar lewy formatki
            var availW = state.width - extraLeft - extraRight;
            var availH = state.height - extraTop - extraBottom;
            state.scale = Math.max(0.1, Math.min(100, Math.min(availW / bw, availH / bh)));
            // Canvas Y odwrócony (cmToPixel: screenY = height - cmY*scale - offsetY)
            var totalW = bw * state.scale + extraRight;
            var totalH = bh * state.scale + extraTop;
            state.offsetX = (state.width - totalW) / 2 + extraLeft / 2 - b.minX * state.scale;
            state.offsetY = (state.height - totalH) / 2 + extraBottom / 2 - b.minY * state.scale;
            render();
        }

        // ============================================
        // PUBLIC API: SET SHAPE / PARAMS
        // ============================================

        function setShape(shapeType, params, vertices, cutouts, corners) {
            var t = _activeToolObj();
            if (t && t.reset) t.reset();   // bez dopisywania kąta ze starego gestu obrotu
            state.shapeType = shapeType;
            state.params = Object.assign({}, params);
            state.vertices = vertices ? vertices.map(function(v) { return [v[0], v[1]]; }) : null;
            state.cutouts = (cutouts && cutouts.length && Array.isArray(cutouts[0]))
                ? ShapeCutouts.fromHoles(cutouts)
                : ShapeCutouts.clone(cutouts || []);
            state.corners = state.vertices ? ShapeCorners.normalize(corners, state.vertices.length) : [];
            state.activeHole = null;
            state.selection = null;
            state.cornerLimitHit = null;
            state.rotation = 0;
            state.rotateDrag = null;
            canvasElement.classList.remove('rotating-shape');
            state.undoStack = [];
            state.redoStack = [];
            _afterGeometryEdit();
            fitToView();
        }

        // Prostokąt/koło: wymiary z pól formularza. Wycięcia zostają w miejscu (od lewego
        // dolnego rogu), narożniki są przycinane, złe wycięcia oznaczane. Bez emisji —
        // edytor sam przelicza pola i krawędzie.
        function setOuterParams(params) {
            state.params = Object.assign({}, state.params, params);
            if (state.shapeType === 'rectangular') {
                var l = state.params.length, w = state.params.width;
                state.vertices = (l > 0 && w > 0)
                    ? ShapeGeometry.generateVertices('rectangular', { length: l, width: w })
                    : null;
            }
            _afterGeometryEdit();
            fitToView();
        }

        function getCutouts() { return ShapeCutouts.clone(state.cutouts); }

        function setCutouts(list) {
            state.cutouts = ShapeCutouts.clone(list || []);
            state.activeHole = null;
            state.selection = null;
            _afterGeometryEdit();
            render();
        }

        // Zgodność wstecz: pierścienie wycięć (pochodne)
        function getHoles() { return ShapeCutouts.toHoles(state.cutouts); }
        function setHoles(holes) { setCutouts(ShapeCutouts.fromHoles(holes)); }

        function getCorners() { return state.corners.slice(); }

        // Równe narożniki całego pierścienia (każdy róg ten sam typ i r_mm — tak działa tryb
        // podstawowy krawędzi) przycinamy jednakowo do wspólnego limitu. Zwykłe przycinanie
        // rogu po rogu dawało różne wymiary zależnie od kolejności (R300 na kwadracie 40×40 →
        // 100/100/100/300 zamiast 4×200). Gdy rogi się różnią albo zażądano tylko części
        // rogów, zostaje zwykłe przycinanie w _afterGeometryEdit.
        function _wyrownajRowneNarozniki(pts, lista) {
            if (!pts || !lista.length || lista.length !== pts.length || !lista[0]) return lista;
            var wzor = lista[0];
            for (var i = 1; i < lista.length; i++) {
                if (!lista[i] || lista[i].type !== wzor.type || lista[i].r_mm !== wzor.r_mm) return lista;
            }
            var maks = ShapeCorners.maxUniformMm(pts, wzor.type);
            if (maks >= wzor.r_mm) return lista;
            return ShapeCorners.normalize(lista.map(function() { return { type: wzor.type, r_mm: maks }; }), lista.length);
        }

        // Narożniki z zewnątrz (moduł krawędzi): {outer: [...], cutouts: {indeks: [...]}}.
        // Zwraca {changed, clamped} — clamped = coś przycięto do limitu geometrii.
        function setAllCorners(spec) {
            function stan() {
                return JSON.stringify([state.corners, state.cutouts.map(function(c) { return c.corners || null; })]);
            }
            var przed = stan();
            if (spec.outer && state.vertices) state.corners = ShapeCorners.normalize(spec.outer, state.vertices.length);
            Object.keys(spec.cutouts || {}).forEach(function(k) {
                var c = state.cutouts[Number(k)];
                if (c && c.type === 'polygon') c.corners = ShapeCorners.normalize(spec.cutouts[k], c.points.length);
            });
            var zadane = stan();
            if (spec.outer && state.vertices && state.shapeType !== 'circle') {
                state.corners = _wyrownajRowneNarozniki(state.vertices, state.corners);
            }
            Object.keys(spec.cutouts || {}).forEach(function(k) {
                var c = state.cutouts[Number(k)];
                if (c && c.type === 'polygon') c.corners = _wyrownajRowneNarozniki(c.points, c.corners);
            });
            _afterGeometryEdit();
            var po = stan();
            render();
            return { changed: po !== przed, clamped: po !== zadane };
        }

        function hasFeatures() {
            return ShapeCorners.hasAny(state.corners) || state.cutouts.length > 0;
        }

        function getInvalidCutouts() { return state.invalidCutouts.slice(); }

        // Limit wymiaru narożnika z geometrii; ringKey: 'outer' albo indeks wycięcia
        function maxCornerMm(ringKey, index, type) {
            if (ringKey === 'outer') {
                return state.vertices ? ShapeCorners.maxCornerMm(state.vertices, state.corners, index, type) : 0;
            }
            var c = state.cutouts[ringKey];
            return (c && c.type === 'polygon') ? ShapeCorners.maxCornerMm(c.points, c.corners, index, type) : 0;
        }

        function updateFromParams(params) {
            state.params = Object.assign({}, params);
            var config = ShapeGeometry.SHAPE_CONFIG[state.shapeType];
            if (config && config.hasVertices) {
                state.vertices = ShapeGeometry.generateVertices(state.shapeType, params);
            }
            _afterGeometryEdit();
            render();
        }

        function getVertices() {
            return state.vertices ? state.vertices.map(function(v) { return [v[0], v[1]]; }) : null;
        }

        function getParams() {
            return Object.assign({}, state.params);
        }

        function canUndo() { return state.undoStack.length > 0; }
        function canRedo() { return state.redoStack.length > 0; }

        // ============================================
        // EMIT CHANGES TO INPUTS
        // ============================================

        function _emitChange() {
            _afterGeometryEdit();
            if (state.vertices) {
                var newParams = ShapeGeometry.extractParams(state.shapeType, state.vertices);
                state.params = Object.assign({}, state.params, newParams);
            }
            state.onParamsChange(state.params, state.vertices, ShapeCutouts.clone(state.cutouts), state.corners.slice());
        }

        function _round(val) {
            return Math.round(val * 10) / 10;
        }

        // ============================================
        // SVG EXPORT (for shape_svg persistence)
        // ============================================

        function exportSVG() {
            if (typeof C2S === 'undefined') {
                console.warn('canvas2svg (C2S) not loaded — SVG export unavailable');
                return '';
            }
            var b = _outerBounds();
            if (!b) return '';
            var bw = b.maxX - b.minX, bh = b.maxY - b.minY;
            if (bw <= 0 || bh <= 0) return '';

            // Snapshot stanu widoku + widoczności (SVG eksportujemy ZAWSZE w pełni)
            var saved = {
                scale: state.scale, offsetX: state.offsetX, offsetY: state.offsetY,
                width: state.width, height: state.height,
                visibility: Object.assign({}, state.visibility)
            };
            state.visibility = { dimensions: true, brackets: true, guides: true, angles: true, lamellas: true, corners: true };

            var cnt = _bracketCounts(b);
            var bracketSpacing = 28;
            var prosty = (state.shapeType === 'rectangular' || state.shapeType === 'circle') && cnt.x === 0 && cnt.y === 0;
            var extraRight = prosty ? 30 : (cnt.y * bracketSpacing + 30);
            var extraTop = prosty ? 30 : (cnt.x * bracketSpacing + 40);
            var extraBottom = 60;
            var extraLeft = 60;

            var MAX_W = 1200, MAX_H = 900;
            var scaleW = (MAX_W - extraLeft - extraRight) / bw;
            var scaleH = (MAX_H - extraTop - extraBottom) / bh;
            state.scale = Math.max(0.1, Math.min(100, Math.min(scaleW, scaleH)));

            var minX = b.minX, minY = b.minY;
            var SVG_W = Math.ceil(bw * state.scale + extraLeft + extraRight);
            var SVG_H = Math.ceil(bh * state.scale + extraTop + extraBottom);
            state.width = SVG_W;
            state.height = SVG_H;
            state.offsetX = extraLeft - minX * state.scale;
            state.offsetY = extraBottom - minY * state.scale;

            // Swap ctx → canvas2svg (bez DPR setTransform, bez tła, bez gridu)
            ctx = new C2S(SVG_W, SVG_H);
            state._svgExportMode = true;
            var svg = '';
            try {
                _renderShape();
                svg = ctx.getSerializedSvg(true);
            } catch (err) {
                console.error('exportSVG render failed', err);
                svg = '';
            }

            // Restore
            state._svgExportMode = false;
            ctx = realCtx;
            state.scale = saved.scale;
            state.offsetX = saved.offsetX;
            state.offsetY = saved.offsetY;
            state.width = saved.width;
            state.height = saved.height;
            state.visibility = saved.visibility;

            if (!svg) return '';

            // canvas2svg dodaje width/height ale NIE viewBox — wstrzyknij viewBox + preserveAspectRatio,
            // zostaw natural width/height (800×600). Skalowanie/maksymalne wymiary do CSS w miejscu osadzenia.
            if (svg.indexOf('viewBox') === -1) {
                svg = svg.replace(/<svg /,
                    '<svg viewBox="0 0 ' + SVG_W + ' ' + SVG_H + '" preserveAspectRatio="xMidYMid meet" ');
            }

            return svg;
        }


        // ============================================
        // NARZĘDZIA — wspólny kontekst dla shape-tools.js
        // ============================================
        var api = {
            state: state,
            canvas: canvasElement,
            ctx: function() { return ctx; },
            theme: function() { return COLOR_THEMES[state.colorTheme] || COLOR_THEMES.normal; },
            cmToPixel: cmToPixel,
            pixelToCm: pixelToCm,
            render: render,
            pushUndo: _pushUndo,
            pushUndoSnapshot: _pushUndoSnapshot,
            popUndo: _popUndo,
            snapshot: _snapshot,
            restoreSnapshot: _restoreSnapshot,   // gest, który wrócił do startu (A, R) — z typem kształtu
            gestureInProgress: _gestureInProgress,   // narzędzie zgłasza gest przez inGesture()
            emitChange: _emitChange,
            showHint: _showHint,
            round: _round,
            snap: function(v) { var g = state.currentGridCm; return Math.round(v / g) * g; },
            scaled: _scaled,
            findVertexAt: _findVertexAt,
            findEdgeAt: _findEdgeAt,
            findCutoutEdgeAt: _findCutoutEdgeAt,
            findCutoutAt: _findCutoutAt,
            outerRing: _outerRing,
            outerBounds: _outerBounds,
            convertToPolygonIfNeeded: _convertToPolygonIfNeeded,
            normalizeAfterRotate: _normalizeAfterRotate,
            afterGeometryEdit: _afterGeometryEdit,
            openInlineInput: _openInlineInput,
            renderSingleDimension: _renderSingleDimension,
            traceSegments: _traceSegments   // podkontur ze segmentów (cm) — podgląd wycięcia w L/M
        };
        tools = ShapeTools.create(api);
        canvasElement.classList.add('tool-' + state.activeTool);

        // ============================================
        // INIT
        // ============================================

        // W trakcie gestu (przeciąganie, obrót) nie dopasowujemy widoku: zmiana skali i przesunięcia
        // pod ręką zmieniłaby przeliczanie kursora na cm i punkt odskoczyłby od myszy
        var resizeObserver = new ResizeObserver(function() {
            resize();
            if (!_gestureInProgress()) fitToView();
        });
        resizeObserver.observe(canvasElement.parentElement);
        // Obserwuj też sekcję Produkt — zmiana inputów zmienia jej wysokość
        var form = canvasElement.closest('.quote-form');
        var productSection = form ? form.querySelector('.product-data') : null;
        if (productSection) resizeObserver.observe(productSection);
        resize();

        function setColorTheme(theme) {
            if (theme !== state.colorTheme && COLOR_THEMES[theme]) {
                state.colorTheme = theme;
                render();
            }
        }

        function setOutOfRangeDims(dims) {
            state.outOfRangeDims = {
                length: !!(dims && dims.length),
                width: !!(dims && dims.width)
            };
            render();
        }

        function setActiveTool(tool) {
            if (tool === 'cursor') tool = 'direct';   // stara nazwa kursora punktów
            if (!tools || !tools[tool]) return;
            // Wybór narzędzia, które już jest aktywne, nic nie zmienia: onDeactivate wyczyściłby
            // zaznaczenie V (ramka znikałaby po kliknięciu własnego przycisku albo skrótu)
            if (tool === state.activeTool) return;
            var stary = tools[state.activeTool];
            if (stary && stary.onDeactivate) stary.onDeactivate();
            state.activeTool = tool;
            // Podświetlenie punktu nie przechodzi na nowe narzędzie (R nie ma uchwytów,
            // a w +/− odświeży się przy pierwszym ruchu myszy)
            state.hoverVertex = -1;
            ShapeTools.IDS.concat(['cursor']).forEach(function(id) { canvasElement.classList.remove('tool-' + id); });
            canvasElement.classList.remove('rotating-shape', 'dragging-vertex', 'hovering-vertex');
            canvasElement.classList.add('tool-' + tool);
            if (tools[tool].onActivate) tools[tool].onActivate();
            render();
        }

        function setCornerType(type) {
            if (type !== 'round' && type !== 'chamfer') return;
            state.cornerType = type;
            render();
        }

        function getActiveTool() {
            return state.activeTool;
        }

        function setVisibility(key, value) {
            if (!(key in state.visibility)) return;
            state.visibility[key] = !!value;
            try { localStorage.setItem('wp.canvas.visibility', JSON.stringify(state.visibility)); } catch (e) { /* ignore */ }
            render();
        }

        function getVisibility() {
            return Object.assign({}, state.visibility);
        }

        return {
            setShape: setShape,
            setOuterParams: setOuterParams,
            updateFromParams: updateFromParams,
            getVertices: getVertices,
            getParams: getParams,
            getCutouts: getCutouts,
            setCutouts: setCutouts,
            getHoles: getHoles,
            setHoles: setHoles,
            getCorners: getCorners,
            setAllCorners: setAllCorners,
            hasFeatures: hasFeatures,
            getInvalidCutouts: getInvalidCutouts,
            maxCornerMm: maxCornerMm,
            showHint: _showHint,
            fitToView: fitToView,
            undo: undo,
            redo: redo,
            canUndo: canUndo,
            canRedo: canRedo,
            exportSVG: exportSVG,
            render: render,
            resize: resize,
            setColorTheme: setColorTheme,
            setOutOfRangeDims: setOutOfRangeDims,
            setActiveTool: setActiveTool,
            getActiveTool: getActiveTool,
            setCornerType: setCornerType,
            getCornerType: function() { return state.cornerType; },
            setVisibility: setVisibility,
            getVisibility: getVisibility,
            getRotation: function() { return state.rotation; },
            setRotation: function(deg) {
                var v = parseInt(deg, 10);
                state.rotation = isNaN(v) ? 0 : ((v % 360) + 360) % 360;
            },
            destroy: function() {
                resizeObserver.disconnect();
                clearTimeout(state._hintTimeout);
                _restoreHint();
                _nasluchy.forEach(function(n) { n[0].removeEventListener(n[1], n[2], n[3]); });
                _nasluchy = [];
                ShapeTools.IDS.concat(['cursor']).forEach(function(id) { canvasElement.classList.remove('tool-' + id); });
            }
        };
    }

    return { create: create };
})();

window.ShapeCanvas = ShapeCanvas;
