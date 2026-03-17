// shape-canvas.js
// Interactive canvas editor for shape geometry
// Dependencies: ShapeGeometry (shape-geometry.js)

var ShapeCanvas = (function() {
    'use strict';

    function create(canvasElement, options) {
        var ctx = canvasElement.getContext('2d');
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
            height: 0
        };

        // Pozycje wymiarów do obsługi dblclick
        var dimensionHitAreas = []; // [{x, y, edgeIndex, labelX, labelY}]

        // ============================================
        // CANVAS SIZING
        // ============================================

        function resize() {
            var rect = canvasElement.parentElement.getBoundingClientRect();
            state.width = rect.width;
            // Dopasuj wysokość do sekcji Produkt
            var form = canvasElement.closest('.quote-form');
            var productSection = form ? form.querySelector('.product-data') : null;
            var productH = productSection ? productSection.offsetHeight : 0;
            state.height = productH > 50 ? productH : 400;
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
            var minPx = 8, maxPx = 80;
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

        function _renderBbox() {
            if (state.shapeType === 'rectangular' || state.shapeType === 'circle') return;
            var verts = state.vertices;
            if (!verts || verts.length < 3) return;

            var bbox = ShapeGeometry.calculateBbox(state.shapeType, state.params, verts);
            if (bbox.width <= 0 || bbox.height <= 0) return;

            var bMinX = Infinity, bMinY = Infinity;
            for (var i = 0; i < verts.length; i++) {
                if (verts[i][0] < bMinX) bMinX = verts[i][0];
                if (verts[i][1] < bMinY) bMinY = verts[i][1];
            }

            var p1 = cmToPixel(bMinX, bMinY);
            var p2 = cmToPixel(bMinX + bbox.width, bMinY);
            var p3 = cmToPixel(bMinX + bbox.width, bMinY + bbox.height);
            var p4 = cmToPixel(bMinX, bMinY + bbox.height);

            ctx.beginPath();
            ctx.moveTo(p1[0], p1[1]);
            ctx.lineTo(p2[0], p2[1]);
            ctx.lineTo(p3[0], p3[1]);
            ctx.lineTo(p4[0], p4[1]);
            ctx.closePath();
            ctx.fillStyle = 'rgba(230, 126, 34, 0.15)';
            ctx.fill();
            ctx.strokeStyle = 'rgba(230, 126, 34, 0.7)';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.stroke();
            ctx.setLineDash([]);

            // Wymiary bounding boxa — pomijaj jeśli krawędź bbox pokrywa się z krawędzią kształtu
            var bboxW = Math.round(bbox.width * 10) / 10;
            var bboxH = Math.round(bbox.height * 10) / 10;
            var bMaxX = bMinX + bbox.width;
            var bMaxY = bMinY + bbox.height;
            var tolerance = 0.05;

            // Sprawdź czy dolna krawędź bbox pokrywa się z krawędzią kształtu
            var bottomEdgeOverlaps = false;
            var rightEdgeOverlaps = false;
            for (var ei = 0; ei < verts.length; ei++) {
                var ej = (ei + 1) % verts.length;
                var v1 = verts[ei], v2 = verts[ej];
                // Dolna: oba wierzchołki na Y=bMinY i rozciągają się na całą szerokość bbox
                if (Math.abs(v1[1] - bMinY) < tolerance && Math.abs(v2[1] - bMinY) < tolerance) {
                    var edgeMinX = Math.min(v1[0], v2[0]);
                    var edgeMaxX = Math.max(v1[0], v2[0]);
                    if (Math.abs(edgeMinX - bMinX) < tolerance && Math.abs(edgeMaxX - bMaxX) < tolerance) {
                        bottomEdgeOverlaps = true;
                    }
                }
                // Prawa: oba wierzchołki na X=bMaxX i rozciągają się na całą wysokość bbox
                if (Math.abs(v1[0] - bMaxX) < tolerance && Math.abs(v2[0] - bMaxX) < tolerance) {
                    var edgeMinY = Math.min(v1[1], v2[1]);
                    var edgeMaxY = Math.max(v1[1], v2[1]);
                    if (Math.abs(edgeMinY - bMinY) < tolerance && Math.abs(edgeMaxY - bMaxY) < tolerance) {
                        rightEdgeOverlaps = true;
                    }
                }
            }

            if (!bottomEdgeOverlaps) {
                _renderSingleDimension(bMinX, bMinY, bMaxX, bMinY, bboxW + ' cm', 'Formatka');
            }
            if (!rightEdgeOverlaps) {
                _renderSingleDimension(bMaxX, bMinY, bMaxX, bMaxY, bboxH + ' cm', 'Formatka', 40);
            }

            // Klamerki: dla każdego wierzchołka rzutujemy na krawędzie bbox
            // i rysujemy klamerkę od rogu bbox do rzutu wierzchołka

            // Linie prowadzące: od wierzchołków kształtu do krawędzi bbox
            ctx.save();
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.5)';
            ctx.lineWidth = 1.5;
            ctx.setLineDash([6, 6]);
            for (var gi = 0; gi < verts.length; gi++) {
                var gvx = verts[gi][0], gvy = verts[gi][1];
                var isOnBboxCorner = (Math.abs(gvx - bMinX) < tolerance || Math.abs(gvx - bMaxX) < tolerance)
                    && (Math.abs(gvy - bMinY) < tolerance || Math.abs(gvy - bMaxY) < tolerance);
                if (isOnBboxCorner) continue;

                // Linia pionowa w górę — tylko jeśli wierzchołek NIE leży na lewej/prawej krawędzi bbox
                var onLeftOrRight = Math.abs(gvx - bMinX) < tolerance || Math.abs(gvx - bMaxX) < tolerance;
                if (!onLeftOrRight && Math.abs(gvy - bMaxY) > tolerance) {
                    var gp1 = cmToPixel(gvx, gvy);
                    var gp2 = cmToPixel(gvx, bMaxY);
                    ctx.beginPath(); ctx.moveTo(gp1[0], gp1[1]); ctx.lineTo(gp2[0], gp2[1]); ctx.stroke();
                }
                // Linia pozioma w prawo — tylko jeśli wierzchołek NIE leży na dolnej/górnej krawędzi bbox
                var onTopOrBottom = Math.abs(gvy - bMinY) < tolerance || Math.abs(gvy - bMaxY) < tolerance;
                if (!onTopOrBottom && Math.abs(gvx - bMaxX) > tolerance) {
                    var gp3 = cmToPixel(gvx, gvy);
                    var gp4 = cmToPixel(bMaxX, gvy);
                    ctx.beginPath(); ctx.moveTo(gp3[0], gp3[1]); ctx.lineTo(gp4[0], gp4[1]); ctx.stroke();
                }
            }
            ctx.restore();

            // Zbierz unikalne pozycje X i Y wierzchołków (rzuty na krawędzie)
            var xPositions = []; // rzuty na dolną/górną krawędź
            var yPositions = []; // rzuty na lewą/prawą krawędź

            for (var bi = 0; bi < verts.length; bi++) {
                var vx = verts[bi][0], vy = verts[bi][1];
                // Rzut X na dolną krawędź — pomijaj jeśli w rogu bbox
                if (Math.abs(vx - bMinX) > tolerance && Math.abs(vx - bMaxX) > tolerance) {
                    xPositions.push(vx);
                }
                // Rzut Y na lewą krawędź — pomijaj jeśli w rogu bbox
                if (Math.abs(vy - bMinY) > tolerance && Math.abs(vy - bMaxY) > tolerance) {
                    yPositions.push(vy);
                }
            }

            // Sortuj i usuń duplikaty
            xPositions.sort(function(a, b) { return a - b; });
            yPositions.sort(function(a, b) { return a - b; });

            // Klamerki na górnej krawędzi bbox (poziome) — każda kolejna wyżej
            for (var xi = 0; xi < xPositions.length; xi++) {
                var xDist = xPositions[xi] - bMinX;
                if (xDist > tolerance) {
                    _renderBracket(bMinX, bMaxY, xPositions[xi], bMaxY, 'top', xDist, xi);
                }
            }

            // Klamerki na prawej krawędzi bbox (pionowe) — każda kolejna bardziej w prawo
            for (var yi = 0; yi < yPositions.length; yi++) {
                var yDist = yPositions[yi] - bMinY;
                if (yDist > tolerance) {
                    _renderBracket(bMaxX, bMinY, bMaxX, yPositions[yi], 'right', yDist, yi);
                }
            }
        }

        // Rysuje klamerkę wymiarową |----wymiar----|
        function _renderBracket(x1cm, y1cm, x2cm, y2cm, side, distCm, level) {
            var p1 = cmToPixel(x1cm, y1cm);
            var p2 = cmToPixel(x2cm, y2cm);
            var baseOffset = 14;
            var levelSpacing = 28; // px odstęp między kolejnymi klamerkami
            var offset = baseOffset + (level || 0) * levelSpacing;
            var tick = 6;    // px kreski |

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
            ctx.font = 'bold 11px sans-serif';
            ctx.fillStyle = '#e67e22';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';

            if (side === 'right' || side === 'left') {
                // Pionowe klamerki — tekst obrócony o 90° w prawo
                var rotOx = (side === 'right' ? 14 : -14);
                ctx.translate(mx + rotOx, my);
                ctx.rotate(Math.PI / 2);
                ctx.fillText(label, 0, 0);
            } else {
                var labelOy = (side === 'bottom' ? 12 : -12);
                ctx.fillText(label, mx, my + labelOy);
            }
            ctx.restore();
        }

        function _renderShape() {
            if (state.shapeType === 'circle' || state.shapeType === 'ellipse') {
                _renderEllipse();
                return;
            }
            var verts = state.vertices;
            if (!verts || verts.length < 2) return;

            // Bounding box (pod kształtem)
            _renderBbox();

            ctx.beginPath();
            var start = cmToPixel(verts[0][0], verts[0][1]);
            ctx.moveTo(start[0], start[1]);
            for (var i = 1; i < verts.length; i++) {
                var pt = cmToPixel(verts[i][0], verts[i][1]);
                ctx.lineTo(pt[0], pt[1]);
            }
            ctx.closePath();
            ctx.fillStyle = 'rgba(230, 126, 34, 0.35)';
            ctx.fill();

            ctx.strokeStyle = '#e67e22';
            ctx.lineWidth = 2;
            ctx.stroke();

            _renderDimensionLines(verts);
            _renderVertexHandles(verts);
        }

        function _renderEllipse() {
            var p = state.params;
            var a = (state.shapeType === 'circle' ? (p.diameter || 0) : (p.axisA || 0)) / 2;
            var b = (state.shapeType === 'circle' ? (p.diameter || 0) : (p.axisB || 0)) / 2;
            if (a <= 0 || b <= 0) return;

            var center = cmToPixel(a, b);
            var rx = a * state.scale;
            var ry = b * state.scale;

            ctx.beginPath();
            ctx.ellipse(center[0], center[1], rx, ry, 0, 0, 2 * Math.PI);
            ctx.fillStyle = 'rgba(230, 126, 34, 0.35)';
            ctx.fill();
            ctx.strokeStyle = '#e67e22';
            ctx.lineWidth = 2;
            ctx.stroke();

            if (state.shapeType === 'circle') {
                _renderSingleDimension(0, b, p.diameter, b, p.diameter + ' cm');
            } else {
                _renderSingleDimension(0, b, p.axisA, b, p.axisA + ' cm');
                _renderSingleDimension(a, 0, a, p.axisB, p.axisB + ' cm');
            }

            var handle = cmToPixel(a * 2, b);
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

        function _renderSingleDimension(x1, y1, x2, y2, label, edgeId, offsetOverride) {
            var p1 = cmToPixel(x1, y1);
            var p2 = cmToPixel(x2, y2);

            ctx.save();

            var dx = p2[0] - p1[0], dy = p2[1] - p1[1];
            var len = Math.sqrt(dx * dx + dy * dy);
            if (len < 1) { ctx.restore(); return; }
            var dist = offsetOverride || 22;
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
            if (edgeId && len > 10) {
                // Znajdź zakres t dla którego punkt na krawędzi + offset mieści się w canvasie
                var bestT = 0.5; // domyślnie środek
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

            // Wymiar
            ctx.font = '11px sans-serif';
            ctx.fillStyle = '#e67e22';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            ctx.fillText(label, labelX, labelY);

            // Oznaczenie boku (G1, G2...) — pod wymiarem
            if (edgeId) {
                ctx.font = 'bold 10px sans-serif';
                ctx.fillStyle = 'rgba(230, 126, 34, 0.6)';
                ctx.textBaseline = 'top';
                ctx.fillText(edgeId, labelX, labelY + 2);
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

            if (options.scaleIndicator) {
                options.scaleIndicator.textContent = getScaleLabel();
            }
        }

        // ============================================
        // INTERACTIONS: ZOOM
        // ============================================

        canvasElement.addEventListener('wheel', function(e) {
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
        // INTERACTIONS: PAN & VERTEX DRAG
        // ============================================

        canvasElement.addEventListener('mousedown', function(e) {
            var rect = canvasElement.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;

            if (e.button === 2) {
                _handleRightClick(mx, my);
                return;
            }

            var vi = _findVertexAt(mx, my);
            if (vi >= 0) {
                state.dragVertex = vi;
                _pushUndo();
                canvasElement.classList.add('dragging-vertex');
                return;
            }

            if (state.shapeType === 'polygon') {
                var edgeIdx = _findEdgeAt(mx, my);
                if (edgeIdx >= 0 && state.vertices && state.vertices.length < 20) {
                    var cmPt = pixelToCm(mx, my);
                    _pushUndo();
                    state.vertices.splice(edgeIdx + 1, 0, [_round(cmPt[0]), _round(cmPt[1])]);
                    _emitChange();
                    render();
                    return;
                }
            }

            state.isPanning = true;
            state.panStartX = mx - state.offsetX;
            state.panStartY = (state.height - my) - state.offsetY;
            canvasElement.style.cursor = 'grabbing';
        });

        canvasElement.addEventListener('mousemove', function(e) {
            var rect = canvasElement.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;

            if (state.dragVertex >= 0) {
                var cmPt = pixelToCm(mx, my);
                var snap = state.currentGridCm;
                var sx = Math.round(cmPt[0] / snap) * snap;
                var sy = Math.round(cmPt[1] / snap) * snap;

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

            var vi = _findVertexAt(mx, my);
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

        canvasElement.addEventListener('contextmenu', function(e) {
            e.preventDefault();
        });

        // ============================================
        // DBLCLICK: INLINE EDIT WYMIARU
        // ============================================

        canvasElement.addEventListener('dblclick', function(e) {
            var rect = canvasElement.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;

            // Szukaj wymiaru w pobliżu kliknięcia
            var hitRadius = 25;
            var hit = null;
            for (var di = 0; di < dimensionHitAreas.length; di++) {
                var d = dimensionHitAreas[di];
                if (Math.hypot(mx - d.x, my - d.y) < hitRadius) {
                    hit = d;
                    break;
                }
            }
            if (!hit) return;

            // Utwórz inline input nad canvasem
            var wrapper = canvasElement.parentElement;
            var input = document.createElement('input');
            input.type = 'number';
            input.step = '0.1';
            input.min = '0.1';
            input.value = Math.round(hit.length * 10) / 10;
            input.style.cssText = 'position:absolute;left:' + (hit.x - 35) + 'px;top:' + (hit.y - 12) + 'px;' +
                'width:70px;height:24px;font-size:12px;text-align:center;border:2px solid #e67e22;' +
                'border-radius:4px;background:#1a1a2e;color:#e67e22;outline:none;z-index:10;font-weight:bold;';
            wrapper.appendChild(input);
            input.focus();
            input.select();

            var edgeIdx = hit.edgeIndex;

            function applyValue() {
                var newLen = parseFloat(input.value);
                if (!isNaN(newLen) && newLen > 0 && state.vertices) {
                    var vi = edgeIdx;
                    var vj = (edgeIdx + 1) % state.vertices.length;
                    var oldDx = state.vertices[vj][0] - state.vertices[vi][0];
                    var oldDy = state.vertices[vj][1] - state.vertices[vi][1];
                    var oldLen = Math.sqrt(oldDx * oldDx + oldDy * oldDy);
                    if (oldLen > 0.01) {
                        _pushUndo();
                        var scale = newLen / oldLen;
                        state.vertices[vj][0] = state.vertices[vi][0] + oldDx * scale;
                        state.vertices[vj][1] = state.vertices[vi][1] + oldDy * scale;
                        _emitChange();
                        render();
                    }
                }
                if (input.parentNode) input.parentNode.removeChild(input);
            }

            input.addEventListener('blur', applyValue);
            input.addEventListener('keydown', function(ev) {
                if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
                if (ev.key === 'Escape') { if (input.parentNode) input.parentNode.removeChild(input); }
            });
        });

        // ============================================
        // SKRÓTY KLAWISZOWE (Ctrl+Z, Ctrl+Shift+Z)
        // ============================================

        canvasElement.setAttribute('tabindex', '0');
        canvasElement.style.outline = 'none';
        canvasElement.addEventListener('keydown', function(e) {
            var isCtrl = e.ctrlKey || e.metaKey;
            if (isCtrl && e.key === 'z' && !e.shiftKey) {
                e.preventDefault();
                undo();
            } else if (isCtrl && e.key === 'z' && e.shiftKey) {
                e.preventDefault();
                redo();
            }
        });

        // Focus canvas po kliknięciu żeby skróty działały
        canvasElement.addEventListener('mousedown', function() {
            canvasElement.focus();
        }, true);

        // ============================================
        // VERTEX / EDGE HIT TESTING
        // ============================================

        function _findVertexAt(px, py) {
            var hitR = 12;
            if (state.shapeType === 'circle' || state.shapeType === 'ellipse') {
                var p = state.params;
                var a = (state.shapeType === 'circle' ? p.diameter : p.axisA) || 0;
                var b = (state.shapeType === 'circle' ? p.diameter : p.axisB) || 0;
                var hPt = cmToPixel(a, b / 2);
                if (Math.hypot(px - hPt[0], py - hPt[1]) < hitR) return 0;
                return -1;
            }
            if (!state.vertices) return -1;
            for (var i = 0; i < state.vertices.length; i++) {
                var vPt = cmToPixel(state.vertices[i][0], state.vertices[i][1]);
                if (Math.hypot(px - vPt[0], py - vPt[1]) < hitR) return i;
            }
            return -1;
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
            var vi = _findVertexAt(mx, my);
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
            var isVariantShape = state.shapeType.indexOf('trapezoid') === 0 || state.shapeType.indexOf('triangle') === 0;
            if (!isVariantShape || state.shapeType === 'trapezoid_custom' || state.shapeType === 'triangle_custom') return;
            var detected = ShapeGeometry.detectVariant(state.shapeType, state.vertices);
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
            var bbox = ShapeGeometry.calculateBbox(state.shapeType, state.params, state.vertices);
            if (bbox.width <= 0 || bbox.height <= 0) return;

            // Policz klamerki (wierzchołki nie w rogach bbox)
            var bracketCountX = 0, bracketCountY = 0;
            var isSimple = (state.shapeType === 'rectangular' || state.shapeType === 'circle');
            if (!isSimple && state.vertices) {
                var bMinXc = state.vertices.reduce(function(m, v) { return Math.min(m, v[0]); }, Infinity);
                var bMinYc = state.vertices.reduce(function(m, v) { return Math.min(m, v[1]); }, Infinity);
                var bMaxXc = bMinXc + bbox.width;
                var bMaxYc = bMinYc + bbox.height;
                var tol = 0.3;
                for (var fi = 0; fi < state.vertices.length; fi++) {
                    var fvx = state.vertices[fi][0], fvy = state.vertices[fi][1];
                    if (Math.abs(fvx - bMinXc) > tol && Math.abs(fvx - bMaxXc) > tol) bracketCountX++;
                    if (Math.abs(fvy - bMinYc) > tol && Math.abs(fvy - bMaxYc) > tol) bracketCountY++;
                }
            }

            // Dodatkowy margines na klamerki i wymiary (px)
            var bracketSpacing = 28;
            var extraRight = isSimple ? 30 : (bracketCountY * bracketSpacing + 60);
            var extraTop = isSimple ? 30 : (bracketCountX * bracketSpacing + 40);
            var extraBottom = 60; // margines na wymiar dolny formatki
            var extraLeft = 30;

            // Oblicz skalę żeby kształt + marginesy zmieścił się w canvasie
            var availW = state.width - extraLeft - extraRight;
            var availH = state.height - extraTop - extraBottom;

            state.scale = Math.min(availW / bbox.width, availH / bbox.height);
            state.scale = Math.max(0.1, Math.min(100, state.scale));

            var minX = 0, minY = 0;
            if (state.vertices) {
                minX = state.vertices.reduce(function(m, v) { return Math.min(m, v[0]); }, Infinity);
                minY = state.vertices.reduce(function(m, v) { return Math.min(m, v[1]); }, Infinity);
            }
            var shapePixelW = bbox.width * state.scale;
            var shapePixelH = bbox.height * state.scale;

            // Centruj: kształt + klamerki jako całość
            // Canvas Y jest odwrócony (cmToPixel: screenY = height - cmY*scale - offsetY)
            // offsetX: pozycja lewej krawędzi kształtu
            // offsetY: pozycja dolnej krawędzi kształtu (w odwróconym Y)
            var totalW = shapePixelW + extraRight;
            var totalH = shapePixelH + extraTop;
            state.offsetX = (state.width - totalW) / 2 + extraLeft / 2 - minX * state.scale;
            state.offsetY = (state.height - totalH) / 2 + extraBottom / 2 - minY * state.scale;

            render();
        }

        // ============================================
        // PUBLIC API: SET SHAPE / PARAMS
        // ============================================

        function setShape(shapeType, params, vertices) {
            state.shapeType = shapeType;
            state.params = Object.assign({}, params);
            state.vertices = vertices ? vertices.map(function(v) { return [v[0], v[1]]; }) : null;
            state.undoStack = [];
            state.redoStack = [];
            fitToView();
        }

        function updateFromParams(params) {
            state.params = Object.assign({}, params);
            var config = ShapeGeometry.SHAPE_CONFIG[state.shapeType];
            if (config && config.hasVertices) {
                state.vertices = ShapeGeometry.generateVertices(state.shapeType, params);
            }
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
            if (state.vertices) {
                var newParams = ShapeGeometry.extractParams(state.shapeType, state.vertices);
                state.params = Object.assign({}, state.params, newParams);
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
            var bbox = ShapeGeometry.calculateBbox(state.shapeType, state.params, state.vertices);
            if (bbox.width <= 0 || bbox.height <= 0) return '';

            var pad = 5;
            var w = bbox.width + 2 * pad;
            var h = bbox.height + 2 * pad;

            if (state.shapeType === 'circle') {
                var r = (state.params.diameter || 0) / 2;
                return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + w + ' ' + h + '" width="80" height="' + (80 * h / w) + '"><circle cx="' + (r + pad) + '" cy="' + (r + pad) + '" r="' + r + '" fill="rgba(230,126,34,0.2)" stroke="#e67e22" stroke-width="1.5"/></svg>';
            }
            if (state.shapeType === 'ellipse') {
                var rx = (state.params.axisA || 0) / 2;
                var ry = (state.params.axisB || 0) / 2;
                return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + w + ' ' + h + '" width="80" height="' + (80 * h / w) + '"><ellipse cx="' + (rx + pad) + '" cy="' + (ry + pad) + '" rx="' + rx + '" ry="' + ry + '" fill="rgba(230,126,34,0.2)" stroke="#e67e22" stroke-width="1.5"/></svg>';
            }

            if (!state.vertices || state.vertices.length < 3) return '';
            var minX = state.vertices.reduce(function(m, v) { return Math.min(m, v[0]); }, Infinity);
            var minY = state.vertices.reduce(function(m, v) { return Math.min(m, v[1]); }, Infinity);
            var maxY = state.vertices.reduce(function(m, v) { return Math.max(m, v[1]); }, -Infinity);
            // Flip Y axis for SVG (SVG Y goes down, canvas Y goes up)
            var pts = state.vertices.map(function(v) {
                return (v[0] - minX + pad) + ',' + (maxY - v[1] + pad);
            }).join(' ');
            return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + w + ' ' + h + '" width="80" height="' + (80 * h / w) + '"><polygon points="' + pts + '" fill="rgba(230,126,34,0.2)" stroke="#e67e22" stroke-width="1.5"/></svg>';
        }

        // ============================================
        // INIT
        // ============================================

        var resizeObserver = new ResizeObserver(function() { resize(); fitToView(); });
        resizeObserver.observe(canvasElement.parentElement);
        // Obserwuj też sekcję Produkt — zmiana inputów zmienia jej wysokość
        var form = canvasElement.closest('.quote-form');
        var productSection = form ? form.querySelector('.product-data') : null;
        if (productSection) resizeObserver.observe(productSection);
        resize();

        return {
            setShape: setShape,
            updateFromParams: updateFromParams,
            getVertices: getVertices,
            getParams: getParams,
            fitToView: fitToView,
            undo: undo,
            redo: redo,
            canUndo: canUndo,
            canRedo: canRedo,
            exportSVG: exportSVG,
            render: render,
            resize: resize,
            destroy: function() { resizeObserver.disconnect(); }
        };
    }

    return { create: create };
})();

window.ShapeCanvas = ShapeCanvas;
