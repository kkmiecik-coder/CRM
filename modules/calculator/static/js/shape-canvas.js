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
            gridLevels: [0.1, 1, 10, 20, 30, 50, 100],
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

        // ============================================
        // CANVAS SIZING
        // ============================================

        function resize() {
            var rect = canvasElement.parentElement.getBoundingClientRect();
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
            var minPx = 15, maxPx = 80;
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

            ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
            ctx.lineWidth = 0.5;
            _drawGridLines(cmLeft, cmRight, cmBottom, cmTop, minor);

            ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
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

        function _renderShape() {
            if (state.shapeType === 'circle' || state.shapeType === 'ellipse') {
                _renderEllipse();
                return;
            }
            var verts = state.vertices;
            if (!verts || verts.length < 2) return;

            ctx.beginPath();
            var start = cmToPixel(verts[0][0], verts[0][1]);
            ctx.moveTo(start[0], start[1]);
            for (var i = 1; i < verts.length; i++) {
                var pt = cmToPixel(verts[i][0], verts[i][1]);
                ctx.lineTo(pt[0], pt[1]);
            }
            ctx.closePath();
            ctx.fillStyle = 'rgba(230, 126, 34, 0.15)';
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
            ctx.fillStyle = 'rgba(230, 126, 34, 0.15)';
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
            var n = verts.length;
            for (var i = 0; i < n; i++) {
                var j = (i + 1) % n;
                var dx = verts[j][0] - verts[i][0];
                var dy = verts[j][1] - verts[i][1];
                var len = Math.sqrt(dx * dx + dy * dy);
                if (len < 0.1) continue;
                var label = (Math.round(len * 10) / 10) + ' cm';
                _renderSingleDimension(verts[i][0], verts[i][1], verts[j][0], verts[j][1], label);
            }
        }

        function _renderSingleDimension(x1, y1, x2, y2, label) {
            var p1 = cmToPixel(x1, y1);
            var p2 = cmToPixel(x2, y2);
            var mx = (p1[0] + p2[0]) / 2;
            var my = (p1[1] + p2[1]) / 2;

            ctx.save();
            ctx.font = '11px sans-serif';
            ctx.fillStyle = '#e67e22';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';

            var dx = p2[0] - p1[0], dy = p2[1] - p1[1];
            var len = Math.sqrt(dx * dx + dy * dy);
            if (len < 1) { ctx.restore(); return; }
            var nx = -dy / len * 14, ny = dx / len * 14;

            ctx.fillText(label, mx + nx, my + ny);
            ctx.restore();
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

            var margin = 0.1;
            var availW = state.width * (1 - 2 * margin);
            var availH = state.height * (1 - 2 * margin);

            state.scale = Math.min(availW / bbox.width, availH / bbox.height);
            state.scale = Math.max(0.1, Math.min(100, state.scale));

            var minX = 0, minY = 0;
            if (state.vertices) {
                minX = state.vertices.reduce(function(m, v) { return Math.min(m, v[0]); }, Infinity);
                minY = state.vertices.reduce(function(m, v) { return Math.min(m, v[1]); }, Infinity);
            }
            var shapePixelW = bbox.width * state.scale;
            var shapePixelH = bbox.height * state.scale;
            state.offsetX = (state.width - shapePixelW) / 2 - minX * state.scale;
            state.offsetY = (state.height - shapePixelH) / 2 - minY * state.scale;

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

        var resizeObserver = new ResizeObserver(function() { resize(); });
        resizeObserver.observe(canvasElement.parentElement);
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
