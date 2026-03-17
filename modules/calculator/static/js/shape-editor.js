// shape-editor.js
// Orchestrates: shape dropdown <-> dynamic inputs <-> canvas
// Dependencies: ShapeGeometry, ShapeCanvas

var ShapeEditor = (function() {
    'use strict';

    function init(form) {
        var select = form.querySelector('[data-field="shapeSelect"]');
        var editorContainer = form.querySelector('[data-shape-editor]');
        var inputsColumn = form.querySelector('[data-shape-inputs]');
        var canvasEl = form.querySelector('[data-shape-canvas]');
        var scaleIndicator = form.querySelector('[data-shape-scale]');
        var undoBtn = form.querySelector('[data-shape-undo]');
        var redoBtn = form.querySelector('[data-shape-redo]');
        var fitBtn = form.querySelector('[data-shape-fit]');
        var hintEl = form.querySelector('[data-shape-hint]');
        var lengthWrapper = form.querySelector('[data-dim-field="length-wrapper"]');
        var widthWrapper = form.querySelector('[data-dim-field="width-wrapper"]');

        if (!select || !editorContainer) return null;

        var canvas = null;
        var currentShape = select.value || 'rectangular';
        var currentParams = {};
        var isUpdating = false;

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
            currentShape = shapeType;
            form.dataset.productShape = shapeType;

            var config = ShapeGeometry.SHAPE_CONFIG[shapeType];
            if (!config) return;

            var isSimpleRect = (shapeType === 'rectangular');
            editorContainer.classList.toggle('collapsed-canvas', isSimpleRect);

            // Pokaż/ukryj oryginalne inputy length/width
            if (lengthWrapper) lengthWrapper.style.display = isSimpleRect ? '' : 'none';
            if (widthWrapper) widthWrapper.style.display = isSimpleRect ? '' : 'none';

            if (hintEl) {
                hintEl.style.display = shapeType === 'polygon' ? '' : 'none';
            }

            currentParams = Object.assign({}, config.defaults);

            _renderInputs(config);

            if (!isSimpleRect) {
                _ensureCanvas();
                var vertices = ShapeGeometry.generateVertices(shapeType, currentParams);
                canvas.setShape(shapeType, currentParams, vertices);
            }

            _syncToMainDimensions();

            if (typeof updatePrices === 'function') updatePrices();
        }

        // ============================================
        // RENDER DYNAMIC INPUTS
        // ============================================

        function _renderInputs(config) {
            inputsColumn.innerHTML = '';

            // Nie renderuj inputów dla prostokąta (używa natywnych length/width)
            if (currentShape === 'rectangular') return;

            for (var i = 0; i < config.inputs.length; i++) {
                var input = config.inputs[i];
                var row = document.createElement('div');
                row.className = 'shape-param-field';
                row.innerHTML =
                    '<label class="input-txt">' + input.label + ' (' + input.unit + '):</label>' +
                    '<input type="number" step="0.1" min="0.1"' +
                    ' data-shape-param="' + input.key + '"' +
                    ' class="input-window"' +
                    ' value="' + (currentParams[input.key] || '') + '">';
                inputsColumn.appendChild(row);
            }

            var bboxDiv = document.createElement('div');
            bboxDiv.className = 'shape-bbox-info';
            bboxDiv.setAttribute('data-shape-bbox', '');
            inputsColumn.appendChild(bboxDiv);

            var validDiv = document.createElement('div');
            validDiv.className = 'shape-validation-error';
            validDiv.setAttribute('data-shape-validation', '');
            inputsColumn.appendChild(validDiv);

            var paramInputs = inputsColumn.querySelectorAll('input[data-shape-param]');
            for (var j = 0; j < paramInputs.length; j++) {
                paramInputs[j].addEventListener('input', _onInputChange);
            }

            _updateBboxDisplay();
        }

        // ============================================
        // INPUT -> CANVAS SYNC
        // ============================================

        function _onInputChange() {
            if (isUpdating) return;
            isUpdating = true;

            var paramInputs = inputsColumn.querySelectorAll('input[data-shape-param]');
            for (var i = 0; i < paramInputs.length; i++) {
                currentParams[paramInputs[i].dataset.shapeParam] = parseFloat(paramInputs[i].value) || 0;
            }

            var errors = ShapeGeometry.validate(currentShape, currentParams);
            var validDiv = inputsColumn.querySelector('[data-shape-validation]');
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

            var paramInputs = inputsColumn.querySelectorAll('input[data-shape-param]');
            for (var i = 0; i < paramInputs.length; i++) {
                var key = paramInputs[i].dataset.shapeParam;
                if (params[key] !== undefined) {
                    paramInputs[i].value = params[key];
                }
            }

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
        // SYNC TO MAIN DIMENSION FIELDS
        // ============================================

        function _syncToMainDimensions() {
            var vertices = canvas ? canvas.getVertices() : null;
            var bbox = ShapeGeometry.calculateBbox(currentShape, currentParams, vertices);

            var lengthInput = form.querySelector('input[data-field="length"]');
            var widthInput = form.querySelector('input[data-field="width"]');

            if (currentShape === 'rectangular') {
                // Prostokąt: length/width widoczne, edytowalne normalnie
                return;
            }

            // Nie-prostokątne: length/width ukryte (display:none na wrapperze),
            // ale wartości aktualizowane z bbox do wyceny drewna
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

        function _updateBboxDisplay() {
            var bboxDiv = inputsColumn.querySelector('[data-shape-bbox]');
            if (!bboxDiv) return;
            if (currentShape === 'rectangular') {
                bboxDiv.textContent = '';
                return;
            }
            var vertices = canvas ? canvas.getVertices() : null;
            var bbox = ShapeGeometry.calculateBbox(currentShape, currentParams, vertices);
            bboxDiv.textContent = 'Bbox: ' + (Math.round(bbox.width * 10) / 10) + ' \u00d7 ' + (Math.round(bbox.height * 10) / 10) + ' cm';
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

                var isSimpleRect = (shapeType === 'rectangular');
                editorContainer.classList.toggle('collapsed-canvas', isSimpleRect);
                if (lengthWrapper) lengthWrapper.style.display = isSimpleRect ? '' : 'none';
                if (widthWrapper) widthWrapper.style.display = isSimpleRect ? '' : 'none';
                if (hintEl) hintEl.style.display = shapeType === 'polygon' ? '' : 'none';

                _renderInputs(config);
                var paramInputs = inputsColumn.querySelectorAll('input[data-shape-param]');
                for (var i = 0; i < paramInputs.length; i++) {
                    var key = paramInputs[i].dataset.shapeParam;
                    if (currentParams[key] !== undefined) paramInputs[i].value = currentParams[key];
                }

                if (!isSimpleRect) {
                    _ensureCanvas();
                    var vertices = (shapeData && shapeData.vertices)
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

    return { init: init };
})();

window.ShapeEditor = ShapeEditor;
