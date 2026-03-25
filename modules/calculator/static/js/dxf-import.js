(function () {
    'use strict';

    /* ============================================================
       DXF Import Modal — WoodPower CRM Calculator
       ============================================================ */

    // ---- Shape labels (Polish) ----
    var SHAPE_LABELS = {
        'rectangular':            'Prostokąt',
        'circle':                 'Koło',
        'triangle_right':         'Trójkąt prostokątny',
        'triangle_equilateral':   'Trójkąt równoboczny',
        'triangle_isosceles':     'Trójkąt równoramienny',
        'triangle_custom':        'Trójkąt dowolny',
        'trapezoid_asymmetric':   'Trapez',
        'parallelogram':          'Równoległobok',
        'polygon':                'Wielokąt'
    };

    // ---- State ----
    var state = {
        products: [],        // raw products from backend (params already in cm)
        currentUnit: 'mm',   // what unit the file was in (for display label only)
        cards: []            // card data objects mirroring the DOM
    };

    // ---- DOM refs (resolved after DOMContentLoaded) ----
    var els = {};

    function resolveEls() {
        els.overlay      = document.getElementById('dxf-import-overlay');
        els.closeBtn     = document.getElementById('dxf-import-close');
        els.dropzone     = document.getElementById('dxf-dropzone');
        els.fileInput    = document.getElementById('dxf-file-input');
        els.loading      = document.getElementById('dxf-loading');
        els.unitBar      = document.getElementById('dxf-unit-bar');
        els.productsList = document.getElementById('dxf-products-list');
        els.footer       = document.getElementById('dxf-import-footer');
        els.cancelBtn    = document.getElementById('dxf-cancel-btn');
        els.confirmBtn   = document.getElementById('dxf-confirm-btn');
        els.triggerBtn   = document.getElementById('import-dxf-btn');
    }

    /* ============================================================
       OPEN / CLOSE
       ============================================================ */

    function openModal() {
        if (!els.overlay) return;
        els.overlay.classList.add('active');
    }

    function closeModal() {
        if (!els.overlay) return;
        els.overlay.classList.remove('active');
        resetState();
    }

    function resetState() {
        state.products = [];
        state.currentUnit = 'mm';
        state.cards = [];

        // Hide tooltip
        if (tooltipEl) tooltipEl.style.display = 'none';

        // Hide dynamic sections
        if (els.loading)      { els.loading.classList.remove('active'); }
        if (els.unitBar)      { els.unitBar.style.display = 'none'; }
        if (els.footer)       { els.footer.style.display = 'none'; }
        if (els.productsList) { els.productsList.innerHTML = ''; }

        // Show dropzone again
        if (els.dropzone) { els.dropzone.style.display = ''; }

        // Reset file input
        if (els.fileInput) { els.fileInput.value = ''; }
    }

    /* ============================================================
       DROPZONE
       ============================================================ */

    function setupDropzone() {
        var dz = els.dropzone;
        var fi = els.fileInput;
        if (!dz || !fi) return;

        // Click to open file picker
        dz.addEventListener('click', function () {
            fi.click();
        });

        // File selected via picker
        fi.addEventListener('change', function () {
            if (fi.files && fi.files.length > 0) {
                handleFile(fi.files[0]);
            }
        });

        // Drag events
        dz.addEventListener('dragover', function (e) {
            e.preventDefault();
            dz.classList.add('dragover');
        });

        dz.addEventListener('dragleave', function (e) {
            e.preventDefault();
            dz.classList.remove('dragover');
        });

        dz.addEventListener('drop', function (e) {
            e.preventDefault();
            dz.classList.remove('dragover');
            var files = e.dataTransfer && e.dataTransfer.files;
            if (files && files.length > 0) {
                handleFile(files[0]);
            }
        });
    }

    /* ============================================================
       FILE VALIDATION & UPLOAD
       ============================================================ */

    function handleFile(file) {
        // Validate extension
        if (!file.name.toLowerCase().endsWith('.dxf')) {
            showError('Nieprawidłowy format pliku. Wybierz plik z rozszerzeniem .dxf');
            return;
        }

        // Validate size (10 MB)
        var maxBytes = 10 * 1024 * 1024;
        if (file.size > maxBytes) {
            showError('Plik jest za duży. Maksymalny rozmiar to 10 MB.');
            return;
        }

        uploadFile(file);
    }

    function showError(msg) {
        alert(msg);
    }

    function showLoading(show) {
        if (!els.loading) return;
        if (show) {
            els.loading.classList.add('active');
            if (els.dropzone) els.dropzone.style.display = 'none';
        } else {
            els.loading.classList.remove('active');
        }
    }

    function uploadFile(file) {
        showLoading(true);

        var formData = new FormData();
        formData.append('file', file);

        fetch('/calculator/api/import-dxf', {
            method: 'POST',
            body: formData
        })
        .then(function (response) {
            if (!response.ok) {
                return response.json().then(function (data) {
                    throw new Error(data.error || ('Błąd serwera: ' + response.status));
                });
            }
            return response.json();
        })
        .then(function (data) {
            showLoading(false);
            handleImportResult(data);
        })
        .catch(function (err) {
            showLoading(false);
            if (els.dropzone) els.dropzone.style.display = '';
            showError('Błąd podczas importu pliku DXF: ' + (err.message || err));
        });
    }

    /* ============================================================
       HANDLE BACKEND RESULT
       ============================================================ */

    function handleImportResult(data) {
        state.products = data.products || [];

        // Determine default unit from backend hint
        var backendUnit = data.units || null;
        if (backendUnit === 'cm') {
            state.currentUnit = 'cm';
        } else {
            // mm, m, or null → default mm display (most CNC files)
            state.currentUnit = 'mm';
        }

        if (state.products.length === 0) {
            showError('Nie znaleziono żadnych rozpoznanych kształtów w pliku DXF.');
            if (els.dropzone) els.dropzone.style.display = '';
            return;
        }

        // Show unit bar and set active button
        if (els.unitBar) {
            els.unitBar.style.display = '';
            updateUnitButtons();
        }

        renderProductCards();

        if (els.footer) els.footer.style.display = '';
    }

    /* ============================================================
       UNIT TOGGLE
       ============================================================ */

    function setupUnitToggle() {
        var bar = els.unitBar;
        if (!bar) return;

        bar.addEventListener('click', function (e) {
            var btn = e.target.closest('.dxf-unit-btn');
            if (!btn) return;
            var unit = btn.getAttribute('data-unit');
            if (unit === state.currentUnit) return;
            state.currentUnit = unit;
            updateUnitButtons();
            // Re-render cards to update displayed dimension labels (values stay in cm)
            renderProductCards();
        });
    }

    function updateUnitButtons() {
        var btns = els.unitBar ? els.unitBar.querySelectorAll('.dxf-unit-btn') : [];
        btns.forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-unit') === state.currentUnit);
        });
    }

    /* ============================================================
       PRODUCT CARDS
       ============================================================ */

    function renderProductCards() {
        var list = els.productsList;
        if (!list) return;
        list.innerHTML = '';
        state.cards = [];

        state.products.forEach(function (product, idx) {
            var cardData = buildCardData(product, idx);
            state.cards.push(cardData);
            list.appendChild(cardData.el);
        });
    }

    /* ============================================================
       SVG PREVIEW — read-only shape visualization with brackets
       ============================================================ */

    var SVG_NS = 'http://www.w3.org/2000/svg';
    var SVG_COLORS = {
        fill:    'rgba(33, 150, 243, 0.12)',
        stroke:  '#2196F3',
        bracket: '#e67e22',
        text:    '#e67e22'
    };

    function buildShapeSvg(shapeType, verticesCm, params, bboxWmm, bboxHmm) {
        var pad = 20;       // padding around shape
        var bracketGap = 6; // gap between shape and bracket
        var tick = 5;       // bracket tick height
        var fs = 9;         // font size
        var sw = 1;         // stroke width for brackets
        var bracketSpace = tick + fs + 8;     // space for bottom bracket (below)
        var bracketSpaceR = tick + fs * 4.5;  // space for right bracket (text "XX.X cm" wider)

        if (shapeType === 'circle') {
            return _buildCircleSvg(params, pad, bracketGap, tick, fs, sw, bracketSpaceR);
        }

        var verts = verticesCm;
        if (!verts || verts.length < 3) {
            // Fallback: rectangle from bbox
            var w = bboxWmm / 10, h = bboxHmm / 10;
            verts = [[0,0],[w,0],[w,h],[0,h]];
        }

        // Normalize to (0,0)
        var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (var i = 0; i < verts.length; i++) {
            if (verts[i][0] < minX) minX = verts[i][0];
            if (verts[i][1] < minY) minY = verts[i][1];
            if (verts[i][0] > maxX) maxX = verts[i][0];
            if (verts[i][1] > maxY) maxY = verts[i][1];
        }
        var shapeW = maxX - minX;
        var shapeH = maxY - minY;
        if (shapeW <= 0 || shapeH <= 0) return '';

        // SVG dimensions — fit shape + brackets
        var totalW = shapeW + pad * 2 + bracketSpaceR;
        var totalH = shapeH + pad * 2 + bracketSpace;

        // Build polygon points (flip Y: SVG y=0 is top)
        var pts = '';
        for (var j = 0; j < verts.length; j++) {
            var sx = (verts[j][0] - minX) + pad;
            var sy = (maxY - verts[j][1]) + pad; // flip Y
            pts += _r(sx) + ',' + _r(sy) + ' ';
        }

        // Shape polygon
        var shape = '<polygon points="' + pts.trim() + '" fill="' + SVG_COLORS.fill + '" stroke="' + SVG_COLORS.stroke + '" stroke-width="1.5"/>';

        // Bottom bracket (width)
        var brackets = _hBracket(pad, pad + shapeW, pad + shapeH + bracketGap, _dimLabel(shapeW), false);

        // Right bracket (height)
        brackets += _vBracket(pad + shapeW + bracketGap, pad, pad + shapeH, _dimLabel(shapeH));

        return '<svg xmlns="' + SVG_NS + '" viewBox="0 0 ' + _r(totalW) + ' ' + _r(totalH) + '" style="width:100%;height:100%;">'
            + shape + brackets + '</svg>';
    }

    function _buildCircleSvg(params, pad, bracketGap, tick, fs, sw, bracketSpace) {
        var d = parseFloat(params.diameter || 0);
        if (d <= 0) return '';
        var r = d / 2;

        var totalW = d + pad * 2 + bracketSpace;
        var totalH = d + pad * 2 + bracketSpace;

        var cx = pad + r;
        var cy = pad + r;

        var circle = '<circle cx="' + _r(cx) + '" cy="' + _r(cy) + '" r="' + _r(r) + '" fill="' + SVG_COLORS.fill + '" stroke="' + SVG_COLORS.stroke + '" stroke-width="1.5"/>';

        // Diameter line + label
        var dimLine = '<line x1="' + _r(cx - r) + '" y1="' + _r(cy) + '" x2="' + _r(cx + r) + '" y2="' + _r(cy) + '" stroke="' + SVG_COLORS.bracket + '" stroke-width="' + sw + '" stroke-dasharray="3,2"/>';
        var label = '<text x="' + _r(cx) + '" y="' + _r(cy - 4) + '" text-anchor="middle" font-size="' + fs + '" fill="' + SVG_COLORS.text + '" font-family="Poppins,sans-serif">⌀' + _dimLabel(d) + '</text>';

        return '<svg xmlns="' + SVG_NS + '" viewBox="0 0 ' + _r(totalW) + ' ' + _r(totalH) + '" style="width:100%;height:100%;">'
            + circle + dimLine + label + '</svg>';
    }

    function _hBracket(x1, x2, y, label, textAbove) {
        var tick = 5, fs = 9, sw = 1, col = SVG_COLORS.bracket;
        var mid = (x1 + x2) / 2;
        var ty = textAbove ? (y - 2) : (y + tick + fs + 1);
        return '<line x1="' + _r(x1) + '" y1="' + _r(y) + '" x2="' + _r(x1) + '" y2="' + _r(y + tick) + '" stroke="' + col + '" stroke-width="' + sw + '"/>'
             + '<line x1="' + _r(x2) + '" y1="' + _r(y) + '" x2="' + _r(x2) + '" y2="' + _r(y + tick) + '" stroke="' + col + '" stroke-width="' + sw + '"/>'
             + '<line x1="' + _r(x1) + '" y1="' + _r(y + tick/2) + '" x2="' + _r(x2) + '" y2="' + _r(y + tick/2) + '" stroke="' + col + '" stroke-width="' + sw + '"/>'
             + '<text x="' + _r(mid) + '" y="' + _r(ty) + '" text-anchor="middle" font-size="' + fs + '" fill="' + col + '" font-family="Poppins,sans-serif">' + label + '</text>';
    }

    function _vBracket(x, y1, y2, label) {
        var tick = 5, fs = 9, sw = 1, col = SVG_COLORS.bracket;
        var mid = (y1 + y2) / 2;
        return '<line x1="' + _r(x) + '" y1="' + _r(y1) + '" x2="' + _r(x + tick) + '" y2="' + _r(y1) + '" stroke="' + col + '" stroke-width="' + sw + '"/>'
             + '<line x1="' + _r(x) + '" y1="' + _r(y2) + '" x2="' + _r(x + tick) + '" y2="' + _r(y2) + '" stroke="' + col + '" stroke-width="' + sw + '"/>'
             + '<line x1="' + _r(x + tick/2) + '" y1="' + _r(y1) + '" x2="' + _r(x + tick/2) + '" y2="' + _r(y2) + '" stroke="' + col + '" stroke-width="' + sw + '"/>'
             + '<text x="' + _r(x + tick + 3) + '" y="' + _r(mid + fs/3) + '" font-size="' + fs + '" fill="' + col + '" font-family="Poppins,sans-serif">' + label + '</text>';
    }

    function _dimLabel(cm) {
        var v = Math.round(cm * 10) / 10;
        return v + ' cm';
    }

    function _r(n) { return Math.round(n * 100) / 100; }

    /* ---- Preview tooltip on hover ---- */

    var tooltipEl = null;

    function _ensureTooltip() {
        if (tooltipEl) return tooltipEl;
        tooltipEl = document.createElement('div');
        tooltipEl.className = 'dxf-preview-tooltip';
        document.body.appendChild(tooltipEl);
        return tooltipEl;
    }

    function _attachPreviewTooltip(previewDiv, svgStr) {
        previewDiv.addEventListener('mouseenter', function (e) {
            var tip = _ensureTooltip();
            tip.innerHTML = svgStr;
            tip.style.display = 'block';
            _positionTooltip(e);
        });
        previewDiv.addEventListener('mousemove', _positionTooltip);
        previewDiv.addEventListener('mouseleave', function () {
            if (tooltipEl) tooltipEl.style.display = 'none';
        });
    }

    function _positionTooltip(e) {
        if (!tooltipEl) return;
        var tipW = 600, tipH = 500;
        var x = e.clientX + 20;
        var y = e.clientY - 100;
        // Keep within viewport
        if (x + tipW > window.innerWidth) x = e.clientX - tipW - 20;
        if (y < 10) y = 10;
        if (y + tipH > window.innerHeight) y = window.innerHeight - tipH - 10;
        tooltipEl.style.left = x + 'px';
        tooltipEl.style.top = y + 'px';
    }

    function buildCardData(product, idx) {
        var shapeType  = product.shape_type || 'rectangular';
        var isCircle   = (shapeType === 'circle');
        var params     = product.params || {};           // already in cm
        var verticesCm = product.vertices_cm || [];
        var layer      = product.layer || '0';

        // Dimension values to pre-fill (all in cm from backend)
        var dimA = 0; // length (or diameter for circle)
        var dimB = 0; // width (not used for circle)

        if (isCircle) {
            dimA = parseFloat(params.diameter || 0);
        } else {
            // For all other shapes use bbox
            dimA = parseFloat(params.length || (product.bbox_width_mm / 10) || 0);
            dimB = parseFloat(params.width  || (product.bbox_height_mm / 10) || 0);
        }

        // Round to 1 decimal place
        dimA = Math.round(dimA * 10) / 10;
        dimB = Math.round(dimB * 10) / 10;

        // Build card element
        var card = document.createElement('div');
        card.className = 'dxf-product-card selected';

        // --- Top row ---
        var topRow = document.createElement('div');
        topRow.className = 'dxf-card-top';

        var checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'dxf-card-checkbox';
        checkbox.checked = true;

        var badge = document.createElement('span');
        badge.className = 'dxf-shape-badge';
        badge.textContent = SHAPE_LABELS[shapeType] || shapeType;

        topRow.appendChild(checkbox);
        topRow.appendChild(badge);

        if (layer && layer !== '0') {
            var layerEl = document.createElement('span');
            layerEl.className = 'dxf-layer-name';
            layerEl.textContent = 'Warstwa: ' + layer;
            topRow.appendChild(layerEl);
        }

        card.appendChild(topRow);

        // --- Card body: inputs (left) + preview (right) ---
        var cardBody = document.createElement('div');
        cardBody.className = 'dxf-card-body';

        // Left: inputs in 2-column grid
        var inputsRow = document.createElement('div');
        inputsRow.className = 'dxf-card-inputs';

        var inputDimA, inputDimB, inputThickness, inputQty;

        if (isCircle) {
            inputDimA = createInputGroup('Średnica (cm)', dimA, 'dimA', false);
        } else {
            inputDimA = createInputGroup('Dł. (cm)', dimA, 'dimA', false);
            inputDimB = createInputGroup('Szer. (cm)', dimB, 'dimB', false);
        }

        inputThickness = createInputGroup('Grub. (cm)', '', 'thickness', false);
        inputQty       = createInputGroup('Ilość', 1, 'qty', true);

        inputsRow.appendChild(inputDimA.wrapper);
        if (inputDimB) inputsRow.appendChild(inputDimB.wrapper);
        inputsRow.appendChild(inputThickness.wrapper);
        inputsRow.appendChild(inputQty.wrapper);

        cardBody.appendChild(inputsRow);

        // Right: SVG preview with hover tooltip
        var svgStr = buildShapeSvg(shapeType, verticesCm, params, product.bbox_width_mm, product.bbox_height_mm);
        if (svgStr) {
            var previewDiv = document.createElement('div');
            previewDiv.className = 'dxf-card-preview';
            previewDiv.innerHTML = svgStr;
            _attachPreviewTooltip(previewDiv, svgStr);
            cardBody.appendChild(previewDiv);
        }

        card.appendChild(cardBody);

        // --- Checkbox toggles .selected class ---
        checkbox.addEventListener('change', function () {
            card.classList.toggle('selected', checkbox.checked);
        });

        var cardData = {
            el:            card,
            checkbox:      checkbox,
            inputDimA:     inputDimA.input,
            inputDimB:     inputDimB ? inputDimB.input : null,
            inputThickness: inputThickness.input,
            inputQty:      inputQty.input,
            product:       product,
            shapeType:     shapeType,
            isCircle:      isCircle,
            params:        params,
            verticesCm:    verticesCm
        };

        return cardData;
    }

    function createInputGroup(labelText, value, key, isInt) {
        var wrapper = document.createElement('div');
        wrapper.className = 'dxf-input-group';

        var label = document.createElement('label');
        label.textContent = labelText;

        var input = document.createElement('input');
        input.type = 'number';
        input.min = '0';
        input.step = isInt ? '1' : '0.01';
        if (value !== '' && value !== null && value !== undefined) {
            input.value = value;
        }

        wrapper.appendChild(label);
        wrapper.appendChild(input);

        return { wrapper: wrapper, input: input };
    }

    /* ============================================================
       IMPORT ACTION
       ============================================================ */

    function setupImportBtn() {
        var btn = els.confirmBtn;
        if (!btn) return;
        btn.addEventListener('click', onConfirmImport);
    }

    // ---- Restore overlay helpers (reuses #restore-overlay from backup system) ----

    function showRestoreOverlay(message) {
        var overlay = document.getElementById('restore-overlay');
        if (overlay) {
            var textEl = document.getElementById('restoreLoadingText');
            if (textEl) textEl.textContent = message;
            overlay.style.display = 'flex';
        }
    }

    function updateRestoreProgress(percent) {
        var fill = document.getElementById('restoreProgressFill');
        var text = document.getElementById('restoreProgressPercent');
        if (fill) fill.style.width = percent + '%';
        if (text) text.textContent = Math.round(percent) + '%';
    }

    function hideRestoreOverlay() {
        var overlay = document.getElementById('restore-overlay');
        if (overlay) overlay.style.display = 'none';
        updateRestoreProgress(0);
    }

    function onConfirmImport() {
        // Collect selected cards
        var selected = state.cards.filter(function (c) {
            return c.checkbox.checked;
        });

        if (selected.length === 0) {
            alert('Zaznacz przynajmniej jeden produkt do zaimportowania.');
            return;
        }

        // Warn about missing thickness
        var missingThickness = selected.filter(function (c) {
            var val = parseFloat(c.inputThickness.value);
            return !val || val <= 0;
        });

        if (missingThickness.length > 0) {
            var ok = window.confirm(
                missingThickness.length + ' produkt(y) nie ma uzupełnionej grubości. ' +
                'Kontynuować bez grubości?'
            );
            if (!ok) return;
        }

        // Close DXF modal, show restore overlay
        closeModal();
        showRestoreOverlay('Przygotowanie importu DXF...');
        updateRestoreProgress(0);

        // Check if first product form is empty — reuse it instead of creating new
        var firstFormEmpty = _isFirstFormEmpty();

        // Inject products sequentially with progress
        var total = selected.length;
        var idx = 0;

        function nextProduct() {
            if (idx >= total) {
                showRestoreOverlay('Finalizacja...');
                updateRestoreProgress(100);
                setTimeout(function () {
                    hideRestoreOverlay();
                    if (typeof window.activateProductCard === 'function') {
                        // Activate first imported product (skip product 0 which existed before)
                        var allForms = document.querySelectorAll('.quote-forms .quote-form');
                        var firstImported = allForms.length - total;
                        if (firstImported >= 0) window.activateProductCard(firstImported);
                    }
                    if (typeof window.generateProductsSummary === 'function') window.generateProductsSummary();
                    if (typeof window.updatePrices === 'function') window.updatePrices();
                }, 400);
                return;
            }

            var current = idx + 1;
            showRestoreOverlay('Importowanie produktu ' + current + ' z ' + total + '...');
            updateRestoreProgress(Math.round((idx / total) * 90));

            var reuseFirst = (idx === 0 && firstFormEmpty);
            injectProduct(selected[idx], reuseFirst, function () {
                idx++;
                updateRestoreProgress(Math.round((idx / total) * 90));
                setTimeout(nextProduct, 150);
            });
        }

        // Start after a brief delay so overlay renders
        setTimeout(nextProduct, 100);
    }

    function _isFirstFormEmpty() {
        var container = document.querySelector('.quote-forms');
        if (!container) return false;
        var forms = container.querySelectorAll('.quote-form');
        if (forms.length !== 1) return false;
        var form = forms[0];
        var l = form.querySelector('[data-field="length"]');
        var w = form.querySelector('[data-field="width"]');
        var t = form.querySelector('[data-field="thickness"]');
        return (!l || !l.value) && (!w || !w.value) && (!t || !t.value);
    }

    function _round1(val) {
        return Math.round(val * 10) / 10;
    }

    function injectProduct(cardData, reuseExisting, onDone) {
        // Read user-edited values from card, round to 1 decimal
        var dimA      = _round1(parseFloat(cardData.inputDimA.value) || 0);
        var dimB      = cardData.inputDimB ? _round1(parseFloat(cardData.inputDimB.value) || 0) : 0;
        var thickness = _round1(parseFloat(cardData.inputThickness.value) || 0);
        var qty       = parseInt(cardData.inputQty.value, 10) || 1;
        var shapeType = cardData.shapeType;
        var isCircle  = cardData.isCircle;

        var length = isCircle ? dimA : dimA;
        var width  = isCircle ? dimA : dimB;

        // Step 1: reuse first empty form or add new product
        if (reuseExisting) {
            // Use existing first form — no need to add new
        } else if (typeof window.addNewProduct === 'function') {
            window.addNewProduct();
        } else {
            console.error('[DXF Import] window.addNewProduct not found');
            if (onDone) onDone();
            return;
        }

        // Step 2: wait for DOM to settle then fill values
        setTimeout(function () {
            var container = document.querySelector('.quote-forms');
            if (!container) {
                console.error('[DXF Import] .quote-forms not found');
                if (onDone) onDone();
                return;
            }

            var forms = container.querySelectorAll('.quote-form');
            if (!forms.length) { if (onDone) onDone(); return; }
            var form = reuseExisting ? forms[0] : forms[forms.length - 1];

            // Set basic dimension fields
            setField(form, 'length',    length);
            setField(form, 'width',     width);
            setField(form, 'thickness', thickness);
            setField(form, 'quantity',  qty);

            // Step 3: handle non-rectangular shapes
            if (shapeType !== 'rectangular') {
                var shapeSelect = form.querySelector('[data-field="shapeSelect"]');
                if (shapeSelect) {
                    shapeSelect.value = shapeType;
                    shapeSelect.dispatchEvent(new Event('change', { bubbles: true }));

                    // Wait for shape editor to initialise, then restore shape params
                    setTimeout(function () {
                        if (form._shapeEditor && typeof form._shapeEditor.restore === 'function') {
                            // Round all params to 1 decimal
                            var rawParams = cardData.params || {};
                            var restoreParams = {};
                            for (var pk in rawParams) {
                                restoreParams[pk] = (typeof rawParams[pk] === 'number') ? _round1(rawParams[pk]) : rawParams[pk];
                            }
                            if (isCircle) {
                                restoreParams.diameter = dimA;
                            } else {
                                restoreParams.length = dimA;
                                if (restoreParams.width !== undefined) restoreParams.width = dimB;
                            }

                            // Round vertices to 1 decimal
                            var roundedVerts = (cardData.verticesCm || []).map(function(v) {
                                return [_round1(v[0]), _round1(v[1])];
                            });

                            form._shapeEditor.restore(shapeType, {
                                params:   restoreParams,
                                vertices: roundedVerts
                            });
                        }

                        if (onDone) onDone();
                    }, 150);
                } else {
                    if (onDone) onDone();
                }
            } else {
                if (onDone) onDone();
            }

        }, 200);
    }

    function setField(form, fieldName, value) {
        var input = form.querySelector('[data-field="' + fieldName + '"]');
        if (!input) return;
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
    }

    /* ============================================================
       INIT
       ============================================================ */

    function init() {
        resolveEls();

        if (!els.overlay) {
            // DXF modal not present on this page
            return;
        }

        // Open modal
        if (els.triggerBtn) {
            els.triggerBtn.addEventListener('click', openModal);
        }

        // Close via X button
        if (els.closeBtn) {
            els.closeBtn.addEventListener('click', closeModal);
        }

        // Close via cancel button
        if (els.cancelBtn) {
            els.cancelBtn.addEventListener('click', closeModal);
        }

        // Close on overlay backdrop click (not on modal itself)
        els.overlay.addEventListener('click', function (e) {
            if (e.target === els.overlay) {
                closeModal();
            }
        });

        // Close on Escape key
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && els.overlay.classList.contains('active')) {
                closeModal();
            }
        });

        setupDropzone();
        setupUnitToggle();
        setupImportBtn();
    }

    // Wait for DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
