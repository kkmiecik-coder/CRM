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
        }

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
                hintEl.style.display = shapeType === 'polygon' ? '' : 'none';
            }

            currentParams = Object.assign({}, config.defaults);

            _showShapeInputs(config);

            if (!hideCanvas) {
                _ensureCanvas();
                var vertices = ShapeGeometry.generateVertices(shapeType, currentParams);
                canvas.setShape(shapeType, currentParams, vertices);
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

            // Pokaż inputy potrzebne dla aktualnego kształtu + ustaw wartości
            for (var j = 0; j < config.inputs.length; j++) {
                var inp = config.inputs[j];
                var wrapper = form.querySelector('[data-shape-param-wrapper="' + inp.key + '"]');
                if (wrapper) {
                    wrapper.style.display = '';
                    // Aktualizuj label z konfiguracji (na wypadek współdzielonych kluczy z różnymi labelami)
                    var label = wrapper.querySelector('label');
                    if (label) label.textContent = inp.label + ' (' + inp.unit + ')';
                    // Ustaw wartość domyślną
                    var inputEl = wrapper.querySelector('input');
                    if (inputEl) inputEl.value = currentParams[inp.key] || '';
                }
            }

            if (validDiv) {
                // Pokaż validDiv tylko jeśli kształt ma inputy do walidacji
                validDiv.style.display = config.inputs.length > 0 ? '' : 'none';
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

        function _onCanvasParamsChange(params, vertices) {
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

            var area = ShapeGeometry.calculateArea(currentShape, currentParams, vertices);
            form.dataset.shapeRealAreaCm2 = area;
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

                var config = ShapeGeometry.SHAPE_CONFIG[shapeType];
                if (!config) return;

                currentParams = (shapeData && shapeData.params) ? Object.assign({}, shapeData.params) : Object.assign({}, config.defaults);

                var hideCanvas = (shapeType === 'rectangular' || shapeType === 'circle');
                var usesOriginalInputs = (shapeType === 'rectangular' || shapeType === 'circle');
                editorContainer.classList.toggle('collapsed-canvas', hideCanvas);
                form.classList.toggle('shape-canvas-active', !hideCanvas);
                if (lengthWrapper) {
                    lengthWrapper.style.display = usesOriginalInputs ? '' : 'none';
                    var lengthLabel = lengthWrapper.querySelector('label');
                    if (lengthLabel) lengthLabel.textContent = (shapeType === 'circle') ? 'Średnica (cm)' : 'Długość (cm)';
                }
                if (widthWrapper) widthWrapper.style.display = (shapeType === 'rectangular') ? '' : 'none';
                if (hintEl) hintEl.style.display = shapeType === 'polygon' ? '' : 'none';

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
                    canvas.setShape(shapeType, currentParams, vertices);
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
