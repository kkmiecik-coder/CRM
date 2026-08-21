// shape-editor.js
// Orchestrates: shape dropdown <-> static inputs (show/hide) <-> canvas
// Dependencies: ShapeGeometry, ShapeCanvas

var ShapeEditor = (function() {
    'use strict';

    function init(form) {
        var select = form.querySelector('[data-field="shapeSelect"]');
        var editorContainer = form.querySelector('[data-shape-editor]');
        var canvasEl = form.querySelector('[data-shape-canvas]');
        var scaleIndicator = form.querySelector('[data-shape-scale]');
        var undoBtn = form.querySelector('[data-shape-undo]');
        var redoBtn = form.querySelector('[data-shape-redo]');
        var fitBtn = form.querySelector('[data-shape-fit]');
        var hintEl = form.querySelector('[data-shape-hint]');
        var toolbarEl = form.querySelector('[data-shape-toolbar]');
        var toolButtons = toolbarEl ? toolbarEl.querySelectorAll('[data-shape-tool]') : [];
        var viewToggleEl = form.querySelector('[data-shape-view-toggle]');
        var visibilityCheckboxes = viewToggleEl ? viewToggleEl.querySelectorAll('input[data-visibility-key]') : [];

        function _syncVisibilityCheckboxes() {
            if (!canvas || !visibilityCheckboxes.length) return;
            var vis = canvas.getVisibility();
            for (var vi = 0; vi < visibilityCheckboxes.length; vi++) {
                var cb = visibilityCheckboxes[vi];
                cb.checked = !!vis[cb.dataset.visibilityKey];
            }
        }

        for (var vci = 0; vci < visibilityCheckboxes.length; vci++) {
            (function(cb) {
                cb.addEventListener('change', function() {
                    if (canvas) canvas.setVisibility(cb.dataset.visibilityKey, cb.checked);
                });
            })(visibilityCheckboxes[vci]);
        }

        var TOOL_HINTS = {
            cursor: 'Przeciągnij wierzchołek lub tło canvasu',
            add: 'Klik krawędź = dodaj punkt. Klik wnętrze = nowa dziura. Prawy klik = zakończ dziurę.',
            remove: 'Klik wierzchołek = usuń (min 3 punkty)',
            rotate: 'Chwyć wierzchołek lub wnętrze i obracaj. Shift = co 15°. Obrót zmienia formatkę.'
        };

        function _setActiveToolButton(tool) {
            for (var i = 0; i < toolButtons.length; i++) {
                toolButtons[i].classList.toggle('active', toolButtons[i].dataset.shapeTool === tool);
            }
            if (hintEl && currentShape !== 'rectangular' && currentShape !== 'circle' && currentShape !== 'oval') {
                hintEl.textContent = TOOL_HINTS[tool] || TOOL_HINTS.cursor;
                hintEl.style.display = '';
            }
        }
        var lengthWrapper = form.querySelector('[data-dim-field="length-wrapper"]');
        var widthWrapper = form.querySelector('[data-dim-field="width-wrapper"]');
        var validDiv = form.querySelector('[data-shape-validation]');

        if (!select || !editorContainer) return null;

        var canvas = null;
        var currentShape = select.value || 'rectangular';
        var currentParams = {};
        var isUpdating = false;

        // Wszystkie wrappery inputów kształtów (statyczne w HTML)
        var allParamWrappers = form.querySelectorAll('[data-shape-param-wrapper]');

        // Podepnij listenery na inputy kształtów — raz, nie na każdą zmianę
        var allParamInputs = form.querySelectorAll('[data-shape-param-wrapper] input[data-shape-param]');
        for (var i = 0; i < allParamInputs.length; i++) {
            allParamInputs[i].addEventListener('input', _onInputChange);
        }

        // ============================================
        // CANVAS INIT (lazy)
        // ============================================

        function _ensureCanvas() {
            if (canvas) return;
            canvas = ShapeCanvas.create(canvasEl, {
                shapeType: currentShape,
                scaleIndicator: scaleIndicator,
                onParamsChange: _onCanvasParamsChange,
                onShapeTypeChange: _onCanvasShapeTypeChange
            });
            _syncVisibilityCheckboxes();
        }

        for (var ti = 0; ti < toolButtons.length; ti++) {
            (function(btn) {
                btn.addEventListener('click', function() {
                    if (btn.classList.contains('disabled')) return;
                    var tool = btn.dataset.shapeTool;
                    if (canvas) canvas.setActiveTool(tool);
                    _setActiveToolButton(tool);
                });
            })(toolButtons[ti]);
        }

        // Skróty V/A/D — tylko gdy canvas aktywny i fokus poza inputami
        document.addEventListener('keydown', function(e) {
            if (!canvas) return;
            if (!form.classList.contains('shape-canvas-active')) return;
            var tag = (document.activeElement && document.activeElement.tagName) || '';
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            var key = e.key.toLowerCase();
            var tool = null;
            if (key === 'v') tool = 'cursor';
            else if (key === 'a') tool = 'add';
            else if (key === 'd') tool = 'remove';
            else if (key === 'r') tool = 'rotate';
            if (!tool || !toolbarEl) return;
            var btn = toolbarEl.querySelector('[data-shape-tool="' + tool + '"]');
            if (!btn || btn.classList.contains('disabled')) return;
            e.preventDefault();
            canvas.setActiveTool(tool);
            _setActiveToolButton(tool);
        });

        // ============================================
        // DROPDOWN CHANGE
        // ============================================

        select.addEventListener('change', function() {
            var newShape = this.value;
            _switchShape(newShape);
        });

        function _switchShape(shapeType) {
            var prevShape = currentShape;
            currentShape = shapeType;
            form.dataset.productShape = shapeType;

            var config = ShapeGeometry.SHAPE_CONFIG[shapeType];
            if (!config) return;

            var hideCanvas = (shapeType === 'rectangular' || shapeType === 'circle');
            var usesOriginalInputs = (shapeType === 'rectangular' || shapeType === 'circle');
            editorContainer.classList.toggle('collapsed-canvas', hideCanvas);
            form.classList.toggle('shape-canvas-active', !hideCanvas);

            if (toolbarEl) {
                toolbarEl.style.display = hideCanvas ? 'none' : 'flex';
                var isCircleLike = (shapeType === 'circle' || shapeType === 'oval');
                for (var bi = 0; bi < toolButtons.length; bi++) {
                    toolButtons[bi].classList.toggle('disabled', isCircleLike);
                }
                _setActiveToolButton('cursor');
                if (canvas) canvas.setActiveTool('cursor');
            }

            // Pokaż/ukryj oryginalne inputy length/width (prostokąt i koło ich używają)
            if (lengthWrapper) {
                lengthWrapper.style.display = usesOriginalInputs ? '' : 'none';
                var lengthLabel = lengthWrapper.querySelector('label');
                if (lengthLabel) lengthLabel.textContent = (shapeType === 'circle') ? 'Średnica (cm)' : 'Długość (cm)';
            }
            if (widthWrapper) widthWrapper.style.display = (shapeType === 'rectangular') ? '' : 'none';

            // Wyczyść width gdy przełączamy z koła (gdzie width = średnica) na prostokąt
            if (prevShape === 'circle' && shapeType === 'rectangular') {
                var widthInput = form.querySelector('input[data-field="width"]');
                if (widthInput) widthInput.value = '';
            }

            if (hintEl) {
                var showHint = !(shapeType === 'rectangular' || shapeType === 'circle' || shapeType === 'oval');
                hintEl.style.display = showHint ? '' : 'none';
                if (showHint) hintEl.textContent = TOOL_HINTS.cursor;
            }

            currentParams = Object.assign({}, config.defaults);

            _showShapeInputs(config);

            if (!hideCanvas) {
                _ensureCanvas();
                var vertices = ShapeGeometry.generateVertices(shapeType, currentParams);
                canvas.setShape(shapeType, currentParams, vertices, []);
            } else if (canvas) {
                // Zniszcz canvas przy przełączeniu na prostokąt/koło,
                // żeby getShapeSvg() nie zwracał starego kształtu
                canvas.destroy();
                canvas = null;
            }

            _syncToMainDimensions();

            // Koło: listener na input length — kopiuje wartość na width
            _setupCircleSync();

            if (typeof updatePrices === 'function') updatePrices();
        }

        function _setupCircleSync() {
            var lengthInput = form.querySelector('input[data-field="length"]');
            var widthInput = form.querySelector('input[data-field="width"]');
            if (!lengthInput || !widthInput) return;

            // Usuń stary listener jeśli istnieje
            if (form._circleInputHandler) {
                lengthInput.removeEventListener('input', form._circleInputHandler);
                form._circleInputHandler = null;
            }

            if (currentShape === 'circle') {
                form._circleInputHandler = function() {
                    widthInput.value = this.value;
                    // Wymuszenie dispatcha żeby walidacja się odpaliła
                    widthInput.dispatchEvent(new Event('input', { bubbles: true }));
                };
                lengthInput.addEventListener('input', form._circleInputHandler);
                // Synchronizuj od razu
                if (lengthInput.value) {
                    widthInput.value = lengthInput.value;
                }
            }
        }

        // ============================================
        // SHOW/HIDE SHAPE INPUTS (zamiast innerHTML)
        // ============================================

        function _showShapeInputs(config) {
            // Ukryj wszystkie wrappery inputów kształtów
            for (var i = 0; i < allParamWrappers.length; i++) {
                allParamWrappers[i].style.display = 'none';
            }

            // Prostokąt i koło używają natywnych inputów length/width
            if (currentShape === 'rectangular' || currentShape === 'circle') {
                if (validDiv) validDiv.style.display = 'none';
                return;
            }

            // Pozostałe (trapez, trójkąt, polygon, oval...) — edycja TYLKO na canvasie.
            // Nie pokazujemy inputów parametrycznych — wszystko przez toolbar.
            if (validDiv) {
                validDiv.style.display = 'none';
                validDiv.textContent = '';
            }

            _updateBboxDisplay();
        }

        // ============================================
        // INPUT -> CANVAS SYNC
        // ============================================

        function _onInputChange() {
            if (isUpdating) return;
            isUpdating = true;

            var config = ShapeGeometry.SHAPE_CONFIG[currentShape];
            if (config) {
                for (var i = 0; i < config.inputs.length; i++) {
                    var key = config.inputs[i].key;
                    var inputEl = form.querySelector('[data-shape-param-wrapper="' + key + '"] input');
                    if (inputEl) currentParams[key] = parseFloat(inputEl.value) || 0;
                }
            }

            var errors = ShapeGeometry.validate(currentShape, currentParams);
            if (validDiv) validDiv.textContent = errors.length > 0 ? errors[0] : '';

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
        // CANVAS -> INPUT SYNC
        // ============================================

        function _onCanvasParamsChange(params, vertices, holes) {
            if (isUpdating) return;
            isUpdating = true;

            currentParams = Object.assign({}, params);

            var config = ShapeGeometry.SHAPE_CONFIG[currentShape];
            if (config) {
                for (var i = 0; i < config.inputs.length; i++) {
                    var key = config.inputs[i].key;
                    var inputEl = form.querySelector('[data-shape-param-wrapper="' + key + '"] input');
                    if (inputEl && params[key] !== undefined) {
                        inputEl.value = params[key];
                    }
                }
            }

            _syncToMainDimensions();
            _updateBboxDisplay();
            _updateUndoRedoButtons();

            if (typeof updatePrices === 'function') updatePrices();

            // Powiadom system backupu o zmianie z canvasu
            _notifyBackup();

            // Trigger re-build listy edges w modalu (gdy otwarty) po zmianie holes/wierzchołków
            if (typeof window.EdgesModule !== 'undefined' && typeof window.EdgesModule.refresh === 'function') {
                try {
                    var shapeData = ShapeGeometry.buildShapeData(currentShape, currentParams, vertices, holes);
                    var thicknessInput = form.querySelector('input[data-field="thickness"]');
                    var thicknessVal = thicknessInput ? (parseFloat(thicknessInput.value) || 0) : 0;
                    window.EdgesModule.refresh(shapeData, thicknessVal);
                } catch (e) {
                    console.warn('[ShapeEditor] EdgesModule.refresh failed:', e);
                }
            }

            isUpdating = false;
        }

        function _onCanvasShapeTypeChange(newType) {
            currentShape = newType;
            select.value = newType;
            form.dataset.productShape = newType;
        }

        // ============================================
        // SYNC TO MAIN DIMENSION FIELDS
        // ============================================

        function _syncToMainDimensions() {
            var lengthInput = form.querySelector('input[data-field="length"]');
            var widthInput = form.querySelector('input[data-field="width"]');

            if (currentShape === 'rectangular') {
                return;
            }

            if (currentShape === 'circle') {
                // Koło: width = length (średnica)
                if (lengthInput && widthInput) {
                    widthInput.value = lengthInput.value;
                }
                return;
            }

            // Nie-prostokątne: length/width z bbox
            var vertices = canvas ? canvas.getVertices() : null;
            var bbox = ShapeGeometry.calculateBbox(currentShape, currentParams, vertices);

            if (lengthInput) {
                lengthInput.value = Math.round(bbox.width * 10) / 10;
            }
            if (widthInput) {
                widthInput.value = Math.round(bbox.height * 10) / 10;
            }

            var holes = canvas && typeof canvas.getHoles === 'function' ? canvas.getHoles() : null;
            var areaObj = ShapeGeometry.calculateAreaWithHoles(currentShape, currentParams, vertices, holes);
            form.dataset.shapeRealAreaCm2 = areaObj.outer;
            form.dataset.shapeNetAreaCm2 = areaObj.net;
            form.dataset.shapeHolesAreaCm2 = areaObj.holes;
            form.dataset.shapeHolesCount = holes ? holes.length : 0;
        }

        // ============================================
        // BBOX DISPLAY
        // ============================================

        // Powiadomienie systemu backupu o zmianie parametrów kształtu
        function _notifyBackup() {
            // Emituj event input z pierwszego widocznego inputa kształtu, żeby backup wyłapał zmianę
            var visibleInput = form.querySelector('[data-shape-param-wrapper]:not([style*="display: none"]) input[data-shape-param]');
            if (visibleInput) {
                visibleInput.dispatchEvent(new Event('input', { bubbles: true }));
            } else {
                // Fallback: emituj z length inputa
                var lengthInput = form.querySelector('input[data-field="length"]');
                if (lengthInput) lengthInput.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }

        function _updateBboxDisplay() {
            // Wyświetl na canvasie (panel info w lewym dolnym rogu)
            var formatkaDiv = form.querySelector('[data-shape-formatka]');
            if (!formatkaDiv) return;
            if (currentShape === 'rectangular' || currentShape === 'circle') {
                formatkaDiv.textContent = '';
                return;
            }
            var vertices = canvas ? canvas.getVertices() : null;
            var bbox = ShapeGeometry.calculateBbox(currentShape, currentParams, vertices);
            formatkaDiv.textContent = 'Formatka: ' + (Math.round(bbox.width * 10) / 10) + ' \u00d7 ' + (Math.round(bbox.height * 10) / 10) + ' cm';
        }

        // ============================================
        // UNDO/REDO BUTTONS
        // ============================================

        if (undoBtn) undoBtn.addEventListener('click', function() { if (canvas) { canvas.undo(); _updateUndoRedoButtons(); } });
        if (redoBtn) redoBtn.addEventListener('click', function() { if (canvas) { canvas.redo(); _updateUndoRedoButtons(); } });
        if (fitBtn) fitBtn.addEventListener('click', function() { if (canvas) canvas.fitToView(); });

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
                var vertices;
                if (canvas) {
                    vertices = canvas.getVertices();
                } else if (currentShape === 'rectangular') {
                    var lInput = form.querySelector('input[data-field="length"]');
                    var wInput = form.querySelector('input[data-field="width"]');
                    vertices = ShapeGeometry.generateVertices('rectangular', {
                        length: parseFloat(lInput ? lInput.value : 0) || 0,
                        width: parseFloat(wInput ? wInput.value : 0) || 0
                    });
                } else {
                    vertices = null;
                }
                var holesG = canvas && typeof canvas.getHoles === 'function' ? canvas.getHoles() : [];
                return ShapeGeometry.buildShapeData(currentShape, currentParams, vertices, holesG);
            },

            getShapeSvg: function() {
                if (canvas) return canvas.exportSVG();

                // Generuj SVG z klamerkami dla prostokąta i koła (canvas nie jest aktywny)
                var lInput = form.querySelector('input[data-field="length"]');
                var wInput = form.querySelector('input[data-field="width"]');
                var l = parseFloat(lInput ? lInput.value : 0) || 0;
                var w = parseFloat(wInput ? wInput.value : 0) || 0;
                if (l <= 0 || w <= 0) return '';

                var pad = 5;
                var fs = Math.max(5, Math.min(12, Math.min(l, w) * 0.15));
                var bracketM = fs * 3;
                var bracketCol = '#888';
                var bs = Math.max(0.3, fs * 0.12);
                var tick = fs * 0.6;
                var gap = fs * 0.4;

                if (currentShape === 'circle') {
                    var r = l / 2;
                    var d = Math.round(l * 10) / 10;
                    var totalW = l + pad * 2;
                    var totalH = l + pad * 2 + bracketM;
                    var by = pad + l + gap;
                    var brackets = '<line x1="' + pad + '" y1="' + by + '" x2="' + pad + '" y2="' + (by + tick) + '" stroke="' + bracketCol + '" stroke-width="' + bs + '"/>'
                        + '<line x1="' + (pad + l) + '" y1="' + by + '" x2="' + (pad + l) + '" y2="' + (by + tick) + '" stroke="' + bracketCol + '" stroke-width="' + bs + '"/>'
                        + '<line x1="' + pad + '" y1="' + (by + tick / 2) + '" x2="' + (pad + l) + '" y2="' + (by + tick / 2) + '" stroke="' + bracketCol + '" stroke-width="' + bs + '"/>'
                        + '<text x="' + (pad + r) + '" y="' + (by + tick + fs + 1) + '" text-anchor="middle" font-size="' + fs + '" fill="' + bracketCol + '" font-family="Poppins,sans-serif">\u2300' + d + '</text>';
                    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + totalW + ' ' + totalH + '">'
                        + '<circle cx="' + (r + pad) + '" cy="' + (r + pad) + '" r="' + r + '" fill="rgba(230,126,34,0.15)" stroke="#e67e22" stroke-width="1.5"/>'
                        + brackets + '</svg>';
                }

                // Prostokąt z klamerkami
                var totalW = l + pad * 2 + bracketM;
                var totalH = w + pad * 2 + bracketM;
                var lLabel = Math.round(l * 10) / 10 + '';
                var wLabel = Math.round(w * 10) / 10 + '';
                // Klamerka dolna
                var byBot = pad + w + gap;
                var midXBot = pad + l / 2;
                var bBot = '<line x1="' + pad + '" y1="' + byBot + '" x2="' + pad + '" y2="' + (byBot + tick) + '" stroke="' + bracketCol + '" stroke-width="' + bs + '"/>'
                    + '<line x1="' + (pad + l) + '" y1="' + byBot + '" x2="' + (pad + l) + '" y2="' + (byBot + tick) + '" stroke="' + bracketCol + '" stroke-width="' + bs + '"/>'
                    + '<line x1="' + pad + '" y1="' + (byBot + tick / 2) + '" x2="' + (pad + l) + '" y2="' + (byBot + tick / 2) + '" stroke="' + bracketCol + '" stroke-width="' + bs + '"/>'
                    + '<text x="' + midXBot + '" y="' + (byBot + tick + fs + 1) + '" text-anchor="middle" font-size="' + fs + '" fill="' + bracketCol + '" font-family="Poppins,sans-serif">' + lLabel + '</text>';
                // Klamerka prawa
                var bxR = pad + l + gap;
                var midYR = pad + w / 2;
                var bRight = '<line x1="' + bxR + '" y1="' + pad + '" x2="' + (bxR + tick) + '" y2="' + pad + '" stroke="' + bracketCol + '" stroke-width="' + bs + '"/>'
                    + '<line x1="' + bxR + '" y1="' + (pad + w) + '" x2="' + (bxR + tick) + '" y2="' + (pad + w) + '" stroke="' + bracketCol + '" stroke-width="' + bs + '"/>'
                    + '<line x1="' + (bxR + tick / 2) + '" y1="' + pad + '" x2="' + (bxR + tick / 2) + '" y2="' + (pad + w) + '" stroke="' + bracketCol + '" stroke-width="' + bs + '"/>'
                    + '<text x="' + (bxR + tick + 2) + '" y="' + (midYR + fs * 0.35) + '" font-size="' + fs + '" fill="' + bracketCol + '" font-family="Poppins,sans-serif">' + wLabel + '</text>';

                return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + totalW + ' ' + totalH + '">'
                    + '<rect x="' + pad + '" y="' + pad + '" width="' + l + '" height="' + w + '" fill="rgba(230,126,34,0.15)" stroke="#e67e22" stroke-width="1.5" rx="1"/>'
                    + bBot + bRight + '</svg>';
            },

            getShapeType: function() {
                return currentShape;
            },

            restore: function(shapeType, shapeData) {
                currentShape = shapeType;
                form.dataset.productShape = shapeType;
                select.value = shapeType;

                var config = ShapeGeometry.SHAPE_CONFIG[shapeType];
                if (!config) return;

                currentParams = (shapeData && shapeData.params) ? Object.assign({}, shapeData.params) : Object.assign({}, config.defaults);

                var hideCanvas = (shapeType === 'rectangular' || shapeType === 'circle');
                var usesOriginalInputs = (shapeType === 'rectangular' || shapeType === 'circle');
                editorContainer.classList.toggle('collapsed-canvas', hideCanvas);
                form.classList.toggle('shape-canvas-active', !hideCanvas);
                    if (toolbarEl) {
                    toolbarEl.style.display = hideCanvas ? 'none' : 'flex';
                    var isCircleLike = (shapeType === 'circle' || shapeType === 'oval');
                    for (var bi = 0; bi < toolButtons.length; bi++) {
                        toolButtons[bi].classList.toggle('disabled', isCircleLike);
                    }
                    _setActiveToolButton('cursor');
                    if (canvas) canvas.setActiveTool('cursor');
                }
                if (lengthWrapper) {
                    lengthWrapper.style.display = usesOriginalInputs ? '' : 'none';
                    var lengthLabel = lengthWrapper.querySelector('label');
                    if (lengthLabel) lengthLabel.textContent = (shapeType === 'circle') ? 'Średnica (cm)' : 'Długość (cm)';
                }
                if (widthWrapper) widthWrapper.style.display = (shapeType === 'rectangular') ? '' : 'none';
                if (hintEl) {
                    var showHintR = !(shapeType === 'rectangular' || shapeType === 'circle' || shapeType === 'oval');
                    hintEl.style.display = showHintR ? '' : 'none';
                    if (showHintR) hintEl.textContent = TOOL_HINTS.cursor;
                }

                _showShapeInputs(config);

                // Ustaw wartości z przywróconych danych
                for (var i = 0; i < config.inputs.length; i++) {
                    var key = config.inputs[i].key;
                    var inputEl = form.querySelector('[data-shape-param-wrapper="' + key + '"] input');
                    if (inputEl && currentParams[key] !== undefined) inputEl.value = currentParams[key];
                }

                if (!hideCanvas) {
                    _ensureCanvas();
                    var vertices = (shapeData && shapeData.vertices)
                        ? shapeData.vertices
                        : ShapeGeometry.generateVertices(shapeType, currentParams);
                    var holesR = (shapeData && shapeData.holes) ? shapeData.holes : [];
                    canvas.setShape(shapeType, currentParams, vertices, holesR);
                } else if (canvas) {
                    canvas.destroy();
                    canvas = null;
                }

                _syncToMainDimensions();
                _setupCircleSync();
                _updateBboxDisplay();
                if (typeof updatePrices === 'function') updatePrices();
            },

            setColorTheme: function(theme) {
                if (canvas) canvas.setColorTheme(theme);
            },

            setOutOfRangeDims: function(dims) {
                if (canvas) canvas.setOutOfRangeDims(dims);
            },

            destroy: function() {
                if (canvas) canvas.destroy();
            }
        };
    }

    return { init: init };
})();

window.ShapeEditor = ShapeEditor;
