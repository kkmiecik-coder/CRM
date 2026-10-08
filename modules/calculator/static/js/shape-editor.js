// shape-editor.js
// Spina: lista kształtów <-> pola wymiarów <-> Canva <-> suwak „Rysunek”.
// Zależności: ShapeGeometry, ShapeCorners, ShapeCutouts, ShapeCanvas

var ShapeEditor = (function() {
    'use strict';

    var DEFAULT_TOOL = 'select';   // V — zaznaczanie; A (direct) to edycja punktów

    var TOOL_HINTS = {
        select: 'Kliknij wycięcie, żeby je zaznaczyć i przesunąć. Strzałki = 0,1 cm (Shift = 1 cm), Delete = usuń. A = punkty obrysu.',
        direct: 'Przeciągnij punkt kształtu lub wycięcia. Shift = ruch w jednej osi.',
        add: 'Klik w bok = nowy punkt. Klik w środku = wycięcie punkt po punkcie (Enter lub prawy klik kończy).',
        remove: 'Kliknij punkt, żeby go usunąć (min. 3 punkty).',
        ellipse: 'Przeciągnij w środku kształtu. Shift = koło, Alt = od środka.',
        rect: 'Przeciągnij w środku kształtu. Shift = kwadrat, Alt = od środka.',
        corner: 'Przeciągnij kropkę w rogu do środka. Shift = wszystkie rogi kształtu, dwuklik = wpisz wymiar.',
        rotate: 'Chwyć kształt i obracaj. Shift = co 15°. Obrót zmienia formatkę.'
    };

    // Skróty jak w Illustratorze
    var KEY_TO_TOOL = { v: 'select', a: 'direct', '+': 'add', '=': 'add', '-': 'remove',
                        l: 'ellipse', m: 'rect', n: 'corner', r: 'rotate' };

    var KOMUNIKAT_ZLE_WYCIECIE = 'Wycięcie wychodzi poza kształt albo nachodzi na inne. Popraw je, żeby zapisać wycenę.';

    // Prostokąt i koło mają własne pola wymiarów, a Canvę na żądanie (suwak „Rysunek”)
    function _isSimpleShape(shape) {
        return shape === 'rectangular' || shape === 'circle';
    }

    // Czy zapisany kształt ma wycięcia albo narożniki (wtedy rysunek musi być widoczny)
    function _shapeDataHasFeatures(sd) {
        if (!sd) return false;
        if (Array.isArray(sd.cutouts) && sd.cutouts.length) return true;
        if (Array.isArray(sd.holes) && sd.holes.length) return true;
        return ShapeCorners.hasAny(sd.corners);
    }

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
        var switchInput = form.querySelector('[data-shape-canvas-toggle]');
        var switchLabel = form.querySelector('[data-shape-canvas-switch]');
        var lengthInput = form.querySelector('input[data-field="length"]');
        var widthInput = form.querySelector('input[data-field="width"]');
        var lengthWrapper = form.querySelector('[data-dim-field="length-wrapper"]');
        var widthWrapper = form.querySelector('[data-dim-field="width-wrapper"]');
        var validDiv = form.querySelector('[data-shape-validation]');
        var cornerTypeBar = form.querySelector('[data-corner-type-bar]');
        var cornerTypeButtons = cornerTypeBar ? cornerTypeBar.querySelectorAll('[data-corner-type]') : [];
        var cornerType = 'round';   // typ z przełącznika narzędzia N (łuk / ścięcie)

        if (!select || !editorContainer) return null;

        var canvas = null;
        var currentShape = select.value || 'rectangular';
        var currentParams = {};
        var paramsPrzedKonwersja = null;   // params prostokąta/koła sprzed zamiany w wielokąt na Canvie
        var isUpdating = false;
        var userWantsCanvas = false;   // wybór suwaka „Rysunek” dla prostokąta i koła

        // Wszystkie wrappery inputów kształtów (statyczne w HTML)
        var allParamWrappers = form.querySelectorAll('[data-shape-param-wrapper]');
        var allParamInputs = form.querySelectorAll('[data-shape-param-wrapper] input[data-shape-param]');
        for (var i = 0; i < allParamInputs.length; i++) {
            allParamInputs[i].addEventListener('input', _onInputChange);
        }

        // ============================================
        // WIDOCZNOŚĆ ELEMENTÓW (oko)
        // ============================================

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

        // ============================================
        // NARZĘDZIA: przyciski, podpowiedzi, skróty
        // ============================================

        function _setActiveToolButton(tool) {
            for (var ti = 0; ti < toolButtons.length; ti++) {
                toolButtons[ti].classList.toggle('active', toolButtons[ti].dataset.shapeTool === tool);
            }
            if (hintEl && form.classList.contains('shape-canvas-active')) {
                hintEl.textContent = TOOL_HINTS[tool] || TOOL_HINTS[DEFAULT_TOOL];
                hintEl.style.display = '';
            }
            // Przełącznik typu narożnika tylko przy narzędziu N
            if (cornerTypeBar) cornerTypeBar.hidden = (tool !== 'corner');
        }

        function _setTool(tool) {
            if (canvas) canvas.setActiveTool(tool);
            _setActiveToolButton(tool);
        }

        function _setCornerType(type) {
            cornerType = type;
            for (var ci = 0; ci < cornerTypeButtons.length; ci++) {
                cornerTypeButtons[ci].classList.toggle('active', cornerTypeButtons[ci].dataset.cornerType === type);
            }
            if (canvas) canvas.setCornerType(type);
        }

        for (var ct = 0; ct < cornerTypeButtons.length; ct++) {
            (function(btn) {
                btn.addEventListener('click', function() { _setCornerType(btn.dataset.cornerType); });
            })(cornerTypeButtons[ct]);
        }
        // Formularz bywa klonem produktu z otwartym narzędziem N: aktywny typ i widoczność
        // paska wyprowadzamy od zera (Canvy jeszcze nie ma, więc aktywne jest narzędzie domyślne)
        _setCornerType(cornerType);
        if (cornerTypeBar) cornerTypeBar.hidden = true;

        // Narzędzie niedostępne dla kształtu: koło nie ma obrotu
        function _updateToolButtons() {
            for (var bi = 0; bi < toolButtons.length; bi++) {
                var id = toolButtons[bi].dataset.shapeTool;
                toolButtons[bi].classList.toggle('disabled', currentShape === 'circle' && id === 'rotate');
            }
        }

        for (var tb = 0; tb < toolButtons.length; tb++) {
            (function(btn) {
                btn.addEventListener('click', function() {
                    if (btn.classList.contains('disabled') || btn.hidden) return;
                    _setTool(btn.dataset.shapeTool);
                });
            })(toolButtons[tb]);
        }

        // Skróty — tylko gdy Canva aktywna i fokus poza polami formularza
        document.addEventListener('keydown', function(e) {
            if (!canvas) return;
            if (!form.classList.contains('shape-canvas-active')) return;
            if (e.ctrlKey || e.metaKey || e.altKey) return;
            var tag = (document.activeElement && document.activeElement.tagName) || '';
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            var key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
            var tool = KEY_TO_TOOL[key];
            if (!tool || !toolbarEl) return;
            var btn = toolbarEl.querySelector('[data-shape-tool="' + tool + '"]');
            if (!btn || btn.hidden || btn.classList.contains('disabled')) return;
            e.preventDefault();
            _setTool(tool);
        });

        // ============================================
        // CANVA: tworzenie, widoczność, suwak „Rysunek”
        // ============================================

        function _ensureCanvas() {
            if (canvas) return;
            canvas = ShapeCanvas.create(canvasEl, {
                shapeType: currentShape,
                scaleIndicator: scaleIndicator,
                onParamsChange: _onCanvasParamsChange,
                onShapeTypeChange: _onCanvasShapeTypeChange
            });
            canvas.setActiveTool(DEFAULT_TOOL);
            canvas.setCornerType(cornerType);
            _setActiveToolButton(DEFAULT_TOOL);
            _syncVisibilityCheckboxes();
        }

        function _destroyCanvas() {
            if (!canvas) return;
            canvas.destroy();
            canvas = null;
        }

        function _hasFeatures() { return !!(canvas && canvas.hasFeatures()); }
        function _canvasRequired() { return !_isSimpleShape(currentShape); }
        function _canvasLocked() { return _canvasRequired() || _hasFeatures(); }

        // Wymiary prostokąta/koła z pól formularza
        function _paramsFromInputs() {
            var l = parseFloat(lengthInput ? lengthInput.value : '') || 0;
            var w = parseFloat(widthInput ? widthInput.value : '') || 0;
            if (currentShape === 'circle') return { diameter: l };
            return { length: l, width: w };
        }

        // Tylko dodatnie wymiary z pól (przy wczytywaniu pola bywają jeszcze puste)
        function _nonZeroInputs() {
            var p = _paramsFromInputs(), wynik = {};
            Object.keys(p).forEach(function(k) { if (p[k] > 0) wynik[k] = p[k]; });
            return wynik;
        }

        function _rectVerticesFromInputs() {
            var p = _paramsFromInputs();
            return (p.length > 0 && p.width > 0) ? ShapeGeometry.generateVertices('rectangular', p) : null;
        }

        // Odwrotność: wymiary prostokąta z rysunku → pola (formatka wierzchołków). Wpisujemy tylko
        // różniące się wartości, żeby nie przestawiać zapisu pola (np. „120.0”) bez potrzeby.
        function _rectInputsFromVertices(vertices) {
            if (!vertices || vertices.length < 3) return;
            var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            vertices.forEach(function(v) {
                minX = Math.min(minX, v[0]); maxX = Math.max(maxX, v[0]);
                minY = Math.min(minY, v[1]); maxY = Math.max(maxY, v[1]);
            });
            // Zaokrąglenie do 1e-6 cm tylko zdejmuje szum odejmowania floatów (130.4 − 10.1)
            var l = Math.round((maxX - minX) * 1e6) / 1e6, w = Math.round((maxY - minY) * 1e6) / 1e6;
            if (!(l > 0) || !(w > 0)) return;
            if (lengthInput && parseFloat(lengthInput.value) !== l) lengthInput.value = l;
            if (widthInput && parseFloat(widthInput.value) !== w) widthInput.value = w;
        }

        // Świeży prostokąt/koło na Canvie z pól formularza (bez wycięć i narożników).
        // currentParams zostaje nietknięte: zwykły prostokąt/koło zapisuje się tak samo
        // niezależnie od tego, czy suwak „Rysunek” był kiedyś włączony.
        function _loadSimpleShapeIntoCanvas() {
            var params = _paramsFromInputs();
            var verts = currentShape === 'rectangular' ? _rectVerticesFromInputs() : null;
            canvas.setShape(currentShape, params, verts, [], []);
        }

        // Canva dla kształtu nietypowego (domyślne wymiary kształtu, bez wycięć i narożników)
        function _loadDefaultShapeIntoCanvas() {
            var config = ShapeGeometry.SHAPE_CONFIG[currentShape];
            currentParams = Object.assign({}, config ? config.defaults : {});
            canvas.setShape(currentShape, currentParams,
                config ? ShapeGeometry.generateVertices(currentShape, currentParams) : null, [], []);
        }

        // Canva wymagana dla kształtów nietypowych i przy wycięciach/narożnikach,
        // dla zwykłego prostokąta i koła — według suwaka „Rysunek”
        function _applyCanvasVisibility() {
            var visible = _canvasLocked() || userWantsCanvas;
            if (visible && !canvas) {
                _ensureCanvas();
                if (_isSimpleShape(currentShape)) _loadSimpleShapeIntoCanvas();
                else _loadDefaultShapeIntoCanvas();
            } else if (!visible && canvas) {
                _destroyCanvas();
            }
            editorContainer.classList.toggle('collapsed-canvas', !visible);
            form.classList.toggle('shape-canvas-active', visible);
            if (toolbarEl) toolbarEl.style.display = visible ? 'flex' : 'none';
            if (hintEl) {
                hintEl.style.display = visible ? '' : 'none';
                if (visible) hintEl.textContent = TOOL_HINTS[canvas.getActiveTool()] || '';
            }
            _updateToolButtons();
            _syncSwitch();
            if (visible && canvas) {
                // Kontener był ukryty — po pokazaniu przelicz rozmiar i dopasuj widok
                canvas.resize();
                canvas.fitToView();
            }
            // Pola powierzchni zależą od tego, czy Canva istnieje i ma cechy — po każdej
            // zmianie widoczności muszą odpowiadać aktualnemu stanowi
            _syncToMainDimensions();
        }

        function _syncSwitch() {
            if (!switchInput) return;
            var locked = _canvasLocked();
            switchInput.checked = locked || userWantsCanvas;
            switchInput.disabled = locked;
            if (switchLabel) {
                switchLabel.classList.toggle('is-locked', locked);
                switchLabel.title = _canvasRequired()
                    ? 'Kształt nietypowy edytujesz na rysunku'
                    : (locked
                        ? 'Produkt ma wycięcia lub narożniki, rysunek musi być widoczny'
                        : 'Pokaż lub ukryj rysunek kształtu');
            }
        }

        if (switchInput) {
            switchInput.addEventListener('change', function() {
                if (_canvasLocked()) { _syncSwitch(); return; }
                userWantsCanvas = switchInput.checked;
                _applyCanvasVisibility();
            });
        }

        // Prostokąt/koło z Canvą: wymiary z pól → rysunek (wycięcia w miejscu, narożniki przycięte).
        // Do Canvy idą tylko wymiary dodatnie: pusty albo zerowy wymiar zerowałby wierzchołki
        // i nieodwracalnie kasował narożniki. Gdy rysunek ma narożniki lub wycięcia, wymiary
        // trafiają do niego dopiero po zatwierdzeniu pola (change), bo wartości pośrednie
        // przy pisaniu („1” w drodze do „100”) przycinałyby je bez odwrotu.
        function _onDimInput(e) {
            if (isUpdating || !canvas || !_isSimpleShape(currentShape)) return;
            var naChange = !!(e && e.type === 'change');
            var zCechami = _hasFeatures();
            if (zCechami && !naChange) {
                // Rysunek czeka na zatwierdzenie pola, ale pola powierzchni (np. koła) liczą się od razu
                _syncToMainDimensions();
                return;
            }
            if (!zCechami && naChange) return;   // bez cech rysunek poszedł już na input
            var dodatnie = _nonZeroInputs();
            if (!Object.keys(dodatnie).length) return;
            canvas.setOuterParams(dodatnie);
            _afterCanvasChange();
            // Wymiar zatwierdzony przy narożnikach/wycięciach przyciął je dopiero teraz; watcher
            // wymiarów w edges.js reaguje wyłącznie na input, więc wpisy narożników odświeżamy tu
            if (zCechami && window.ShapeEdgesSync) window.ShapeEdgesSync.syncForm(form);
            // Po zatwierdzeniu pola powierzchnie mogły się zmienić już po cenie liczonej na input
            if (naChange && typeof updatePrices === 'function') updatePrices();
        }
        [lengthInput, widthInput].forEach(function(el) {
            if (!el) return;
            el.addEventListener('input', _onDimInput);
            el.addEventListener('change', _onDimInput);
        });

        // Wspólne po każdej zmianie rysunku: pola, powierzchnie, suwak, walidacja
        function _afterCanvasChange() {
            _syncToMainDimensions();
            _updateBboxDisplay();
            _updateUndoRedoButtons();
            _syncSwitch();
            _updateValidity();
        }

        // Wycięcia poza obrysem / nachodzące: komunikat pod kształtem (zapis blokuje save_quote.js)
        function _updateValidity() {
            if (!validDiv) return;
            var zle = canvas ? canvas.getInvalidCutouts() : [];
            if (zle.length) {
                validDiv.textContent = KOMUNIKAT_ZLE_WYCIECIE;
                validDiv.style.display = '';
            } else if (validDiv.textContent === KOMUNIKAT_ZLE_WYCIECIE) {
                validDiv.textContent = '';
                validDiv.style.display = 'none';
            }
        }

        // ============================================
        // ZMIANA KSZTAŁTU Z LISTY
        // ============================================

        select.addEventListener('change', function() {
            _switchShape(this.value);
        });

        function _applyDimWrappers(shapeType) {
            var simple = _isSimpleShape(shapeType);
            if (lengthWrapper) {
                lengthWrapper.style.display = simple ? '' : 'none';
                var lengthLabel = lengthWrapper.querySelector('label');
                if (lengthLabel) lengthLabel.textContent = (shapeType === 'circle') ? 'Średnica (cm)' : 'Długość (cm)';
            }
            if (widthWrapper) widthWrapper.style.display = (shapeType === 'rectangular') ? '' : 'none';
        }

        function _switchShape(shapeType) {
            var prevShape = currentShape;
            currentShape = shapeType;
            form.dataset.productShape = shapeType;
            var config = ShapeGeometry.SHAPE_CONFIG[shapeType];
            if (!config) return;

            _applyDimWrappers(shapeType);
            // Wyczyść width gdy przełączamy z koła (gdzie width = średnica) na prostokąt
            if (prevShape === 'circle' && shapeType === 'rectangular' && widthInput) widthInput.value = '';

            currentParams = Object.assign({}, config.defaults);
            paramsPrzedKonwersja = null;
            _showShapeInputs(config);

            // Nowy kształt zaczyna bez wycięć i narożników
            if (!_isSimpleShape(shapeType)) {
                _ensureCanvas();
                canvas.setShape(shapeType, currentParams, ShapeGeometry.generateVertices(shapeType, currentParams), [], []);
            } else if (canvas) {
                _loadSimpleShapeIntoCanvas();
            }
            _applyCanvasVisibility();
            _setTool(DEFAULT_TOOL);

            _syncToMainDimensions();
            // Etykieta formatki przeliczana TUTAJ (po utworzeniu Canvy) — wcześniej
            // nie ma wierzchołków i wyszłoby „Formatka: 0 × 0 cm”
            _updateBboxDisplay();
            _setupCircleSync();
            _updateValidity();
            if (typeof updatePrices === 'function') updatePrices();
            // Odświeża przycisk „+ Dodaj” krawędzi i walidatory (pola wymiarów mogły zniknąć albo
            // wrócić). Bez syncForm — krawędzie przy zmianie kształtu obsługuje edges.js (reset).
            _emitShapeChangedEvent();
        }

        function _setupCircleSync() {
            if (!lengthInput || !widthInput) return;
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
                if (lengthInput.value) widthInput.value = lengthInput.value;
            }
        }

        // ============================================
        // POLA PARAMETRÓW KSZTAŁTU (ukryte — edycja na Canvie)
        // ============================================

        function _showShapeInputs(config) {
            for (var wi = 0; wi < allParamWrappers.length; wi++) {
                allParamWrappers[wi].style.display = 'none';
            }
            if (validDiv && validDiv.textContent !== KOMUNIKAT_ZLE_WYCIECIE) {
                validDiv.style.display = 'none';
                validDiv.textContent = '';
            }
            if (!_isSimpleShape(currentShape)) _updateBboxDisplay();
        }

        function _onInputChange() {
            if (isUpdating) return;
            isUpdating = true;
            try {
                var config = ShapeGeometry.SHAPE_CONFIG[currentShape];
                if (config) {
                    for (var ci = 0; ci < config.inputs.length; ci++) {
                        var key = config.inputs[ci].key;
                        var inputEl = form.querySelector('[data-shape-param-wrapper="' + key + '"] input');
                        if (inputEl) currentParams[key] = parseFloat(inputEl.value) || 0;
                    }
                }
                var errors = ShapeGeometry.validate(currentShape, currentParams);
                if (validDiv) validDiv.textContent = errors.length > 0 ? errors[0] : '';
                if (canvas && errors.length === 0) canvas.updateFromParams(currentParams);
                _syncToMainDimensions();
                _updateBboxDisplay();
                _updateUndoRedoButtons();
                if (errors.length === 0 && typeof updatePrices === 'function') updatePrices();
            } finally {
                isUpdating = false;
            }
        }

        // ============================================
        // CANVA → FORMULARZ
        // ============================================

        function _onCanvasParamsChange(params, vertices, cutouts, corners) {
            if (isUpdating) return;
            isUpdating = true;
            try {
                // Prostokąt/koło trzyma wymiary w polach formularza, currentParams zostaje
                // jak dla zwykłego kształtu (bez śladu po suwaku „Rysunek”)
                if (!_isSimpleShape(currentShape)) currentParams = Object.assign({}, params);

                var config = ShapeGeometry.SHAPE_CONFIG[currentShape];
                if (config) {
                    for (var ci = 0; ci < config.inputs.length; ci++) {
                        var key = config.inputs[ci].key;
                        var inputEl = form.querySelector('[data-shape-param-wrapper="' + key + '"] input');
                        if (inputEl && params[key] !== undefined) inputEl.value = params[key];
                    }
                }
                // Koło: uchwyt średnicy na rysunku → pole Średnica
                if (currentShape === 'circle' && params.diameter > 0) {
                    if (lengthInput) lengthInput.value = params.diameter;
                    if (widthInput) widthInput.value = params.diameter;
                }
                // Prostokąt: pola Długość/Szerokość z wierzchołków rysunku (cofnięcie i ponowienie
                // zmiany wymiaru, dwuklik w wymiar boku). Bez zdarzenia input — ono kasowałoby
                // krawędzie; walidatory i podsumowanie uruchamia zdarzenie shape:changed.
                if (currentShape === 'rectangular') _rectInputsFromVertices(vertices);

                _afterCanvasChange();
                if (typeof updatePrices === 'function') updatePrices();
                _notifyShapeChanged();

                // Modal krawędzi (gdy otwarty) odświeża listę po zmianie wycięć/wierzchołków
                if (window.EdgesModule && typeof window.EdgesModule.refresh === 'function') {
                    try {
                        var thicknessInput = form.querySelector('input[data-field="thickness"]');
                        var thicknessVal = thicknessInput ? (parseFloat(thicknessInput.value) || 0) : 0;
                        window.EdgesModule.refresh(_buildShapeData(), thicknessVal);
                    } catch (e) {
                        console.warn('[ShapeEditor] EdgesModule.refresh failed:', e);
                    }
                }
            } finally {
                isUpdating = false;
            }
        }

        function _onCanvasShapeTypeChange(newType) {
            // Prostokąt → wielokąt: wielokąt przejmuje params z rysunku, więc zapamiętujemy
            // params zwykłego kształtu, żeby powrót (cofnięcie, obrót tam i z powrotem) dał
            // zapis identyczny jak przed konwersją (reguła F3)
            if (_isSimpleShape(currentShape) && !_isSimpleShape(newType)) {
                paramsPrzedKonwersja = Object.assign({}, currentParams);
            }
            currentShape = newType;
            select.value = newType;
            form.dataset.productShape = newType;
            // Prostokąt → wielokąt (przeciągnięty punkt, obrót): pola wymiarów znikają,
            // rysunek staje się obowiązkowy. Cofnięty obrót wraca do prostokąta.
            _applyDimWrappers(newType);
            if (_isSimpleShape(newType)) {
                // Canva jest otwarta: gdy typ wraca na prostokąt/koło, suwak ma zostać włączony
                userWantsCanvas = true;
                if (paramsPrzedKonwersja) currentParams = paramsPrzedKonwersja;
                paramsPrzedKonwersja = null;
                // Pola wymiarów z przywróconego rysunku, datasety powierzchni jak dla zwykłego kształtu
                if (newType === 'rectangular' && canvas) _rectInputsFromVertices(canvas.getVertices());
                _syncToMainDimensions();
            }
            _updateToolButtons();
            _syncSwitch();
        }

        // ============================================
        // POLA WYMIARÓW I POWIERZCHNIE
        // ============================================

        function _syncToMainDimensions() {
            if (currentShape === 'circle') {
                // Koło: width = length (średnica)
                if (lengthInput && widthInput) widthInput.value = lengthInput.value;
            } else if (currentShape !== 'rectangular') {
                // Kształty nietypowe: length/width z formatki
                var bbox = ShapeGeometry.calculateBbox(currentShape, currentParams, canvas ? canvas.getVertices() : null);
                if (lengthInput) lengthInput.value = Math.round(bbox.width * 10) / 10;
                if (widthInput) widthInput.value = Math.round(bbox.height * 10) / 10;
            }
            if (!canvas || (_isSimpleShape(currentShape) && !canvas.hasFeatures())) {
                // Zwykły prostokąt/koło (z rysunkiem czy bez) nie ma pól powierzchni w datasetach —
                // objętość liczona jak przed zmianą, niezależnie od suwaka „Rysunek”
                delete form.dataset.shapeRealAreaCm2;
                delete form.dataset.shapeNetAreaCm2;
                delete form.dataset.shapeHolesAreaCm2;
                delete form.dataset.shapeHolesCount;
                return;
            }
            var cutouts = canvas.getCutouts();
            var params = _isSimpleShape(currentShape)
                ? Object.assign({}, currentParams, _paramsFromInputs())
                : currentParams;
            var pola = ShapeGeometry.calculateAreas(currentShape, params, canvas.getVertices(), canvas.getCorners(), cutouts);
            form.dataset.shapeRealAreaCm2 = pola.outer;
            form.dataset.shapeNetAreaCm2 = pola.net;
            form.dataset.shapeHolesAreaCm2 = pola.holes;
            form.dataset.shapeHolesCount = cutouts.length;
        }

        // Backup szkicu i krawędzie dowiadują się o zmianie rysunku własnym zdarzeniem.
        // Dawniej udawaliśmy „input” na polu Długość, co przy okazji kasowało całą
        // konfigurację krawędzi przy każdej zmianie na Canvie.
        function _notifyShapeChanged() {
            // Najpierw krawędzie, potem zdarzenie — słuchacze (podsumowanie, backup) widzą stan po
            // synchronizacji. Zdarzenie wychodzi zawsze, także gdy synchronizacja rzuci wyjątek.
            try {
                if (window.ShapeEdgesSync) window.ShapeEdgesSync.syncForm(form);
            } finally {
                _emitShapeChangedEvent();
            }
        }

        // Samo zdarzenie zmiany rysunku (walidatory wymiarów, podsumowanie, przycisk „+ Dodaj”,
        // backup szkicu, nieaktualna wysyłka, wykrywanie zmian w edycji)
        function _emitShapeChangedEvent() {
            form.dispatchEvent(new CustomEvent('shape:changed', { bubbles: true }));
        }

        function _updateBboxDisplay() {
            var formatkaDiv = form.querySelector('[data-shape-formatka]');
            if (!formatkaDiv) return;
            if (_isSimpleShape(currentShape)) {
                formatkaDiv.textContent = '';
                return;
            }
            var bbox = ShapeGeometry.calculateBbox(currentShape, currentParams, canvas ? canvas.getVertices() : null);
            formatkaDiv.textContent = 'Formatka: ' + (Math.round(bbox.width * 10) / 10) + ' × ' + (Math.round(bbox.height * 10) / 10) + ' cm';
        }

        // ============================================
        // COFNIJ / PONÓW / DOPASUJ
        // ============================================

        if (undoBtn) undoBtn.addEventListener('click', function() { if (canvas) { canvas.undo(); _updateUndoRedoButtons(); } });
        if (redoBtn) redoBtn.addEventListener('click', function() { if (canvas) { canvas.redo(); _updateUndoRedoButtons(); } });
        if (fitBtn) fitBtn.addEventListener('click', function() { if (canvas) canvas.fitToView(); });

        function _updateUndoRedoButtons() {
            if (undoBtn) undoBtn.disabled = !canvas || !canvas.canUndo();
            if (redoBtn) redoBtn.disabled = !canvas || !canvas.canRedo();
        }

        // ============================================
        // DANE DO ZAPISU
        // ============================================

        function _buildShapeData() {
            // Gałąź Canvy: kształt nietypowy albo prostokąt/koło z wycięciami lub narożnikami
            if (canvas && (!_isSimpleShape(currentShape) || canvas.hasFeatures())) {
                var params = _isSimpleShape(currentShape)
                    ? Object.assign({}, currentParams, _paramsFromInputs())
                    : currentParams;
                return ShapeGeometry.buildShapeData(currentShape, params, canvas.getVertices(),
                    canvas.getCutouts(), canvas.getRotation(), canvas.getCorners());
            }
            // Zwykły prostokąt/koło (z rysunkiem czy bez) — dokładnie jak przed zmianą
            var vertices = null;
            if (currentShape === 'rectangular') {
                vertices = ShapeGeometry.generateVertices('rectangular', {
                    length: parseFloat(lengthInput ? lengthInput.value : 0) || 0,
                    width: parseFloat(widthInput ? widthInput.value : 0) || 0
                });
            }
            return ShapeGeometry.buildShapeData(currentShape, currentParams, vertices, [], 0, []);
        }

        // Formularz bywa klonem produktu z żywą Canvą: pola wymiarów, klasę, pasek narzędzi,
        // suwak i komunikat wyprowadzamy od zera z bieżącego kształtu
        _applyDimWrappers(currentShape);
        _applyCanvasVisibility();
        _updateValidity();

        // ============================================
        // PUBLIC API
        // ============================================

        return {
            setShape: _switchShape,

            getShapeData: _buildShapeData,

            getShapeSvg: function() {
                // Rysunek z Canvy: kształty nietypowe oraz prostokąt/koło z wycięciami lub narożnikami.
                // Zwykły prostokąt/koło — dotychczasowy generator (rysunki produkcji bez zmian).
                if (canvas && (!_isSimpleShape(currentShape) || canvas.hasFeatures())) return canvas.exportSVG();
                // Generuj SVG z klamerkami dla zwykłego prostokąta i koła (bez wycięć i narożników)
                var l = parseFloat(lengthInput ? lengthInput.value : 0) || 0;
                var w = parseFloat(widthInput ? widthInput.value : 0) || 0;
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
                var simple = _isSimpleShape(shapeType);
                currentParams = (shapeData && shapeData.params)
                    ? Object.assign({}, shapeData.params)
                    : Object.assign({}, config.defaults);
                paramsPrzedKonwersja = null;

                _applyDimWrappers(shapeType);
                _showShapeInputs(config);
                for (var ri = 0; ri < config.inputs.length; ri++) {
                    var key = config.inputs[ri].key;
                    var inputEl = form.querySelector('[data-shape-param-wrapper="' + key + '"] input');
                    if (inputEl && currentParams[key] !== undefined) inputEl.value = currentParams[key];
                }

                // Rysunek: zawsze dla nietypowych; prostokąt/koło — gdy zapisano wycięcia lub narożniki
                userWantsCanvas = _shapeDataHasFeatures(shapeData);
                _destroyCanvas();
                if (!simple || userWantsCanvas) {
                    _ensureCanvas();
                    var vertices = (shapeData && shapeData.vertices) ? shapeData.vertices : null;
                    if (!vertices && !simple) vertices = ShapeGeometry.generateVertices(shapeType, currentParams);
                    if (!vertices && shapeType === 'rectangular') vertices = _rectVerticesFromInputs();
                    var params = simple ? Object.assign({}, currentParams, _nonZeroInputs()) : currentParams;
                    canvas.setShape(shapeType, params, vertices,
                        ShapeCutouts.fromShapeData(shapeData), shapeData ? shapeData.corners : null);
                    // setShape zeruje kąt — przywracamy go z zapisanych danych
                    if (shapeData && shapeData.rotation != null) canvas.setRotation(shapeData.rotation);
                    // Prostokąt/koło: wymiary są w polach, currentParams wraca do domyślnych jak
                    // przy zwykłym kształcie (po usunięciu wszystkich cech zapis jest ten sam)
                    if (simple) currentParams = Object.assign({}, config.defaults);
                }
                _applyCanvasVisibility();
                _setTool(DEFAULT_TOOL);
                _syncToMainDimensions();
                _setupCircleSync();
                _updateBboxDisplay();
                _updateValidity();
                if (typeof updatePrices === 'function') updatePrices();
            },

            // Po zmianie rysunku z zewnątrz (np. narożniki z modułu krawędzi)
            refreshAfterExternalChange: function() {
                _applyCanvasVisibility();
                _afterCanvasChange();
            },

            // Narożniki z modułu krawędzi → rysunek. Prostokąt bez rysunku dostaje go z pól.
            // Nie woła _notifyShapeChanged ani syncForm: wpisy krawędzi zostają nietknięte
            // (stara wycena nie zmienia ceny po wczytaniu), odświeża się tylko rysunek i pola.
            applyCorners: function(spec) {
                if (!canvas) {
                    if (!_isSimpleShape(currentShape)) return { changed: false, clamped: false };
                    _ensureCanvas();
                    _loadSimpleShapeIntoCanvas();
                    // Rysunek powstał na życzenie krawędzi: po zdjęciu ostatniego narożnika
                    // zostaje włączony (suwak odblokowany, nadal włączony)
                    userWantsCanvas = true;
                }
                var wynik = canvas.setAllCorners(spec);
                _applyCanvasVisibility();
                _afterCanvasChange();
                return wynik;
            },

            // Komunikat pod rysunkiem (czerwony, znika po 3 s); bez Canvy nic nie robi
            showHint: function(msg) {
                if (canvas) canvas.showHint(msg);
            },

            // Czy da się zapisać: żadne wycięcie nie wychodzi poza kształt ani nie nachodzi na inne
            isGeometryValid: function() {
                return !canvas || canvas.getInvalidCutouts().length === 0;
            },

            hasFeatures: function() {
                return _hasFeatures();
            },

            getCanvas: function() {
                return canvas;
            },

            getRotation: function() {
                return canvas && typeof canvas.getRotation === 'function' ? canvas.getRotation() : 0;
            },

            setRotation: function(deg) {
                if (canvas && typeof canvas.setRotation === 'function') canvas.setRotation(deg);
            },

            setColorTheme: function(theme) {
                if (canvas) canvas.setColorTheme(theme);
            },

            setOutOfRangeDims: function(dims) {
                if (canvas) canvas.setOutOfRangeDims(dims);
            },

            destroy: function() {
                _destroyCanvas();
            }
        };
    }

    return { init: init };
})();

window.ShapeEditor = ShapeEditor;
