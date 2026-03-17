/**
 * Moduł obróbki krawędzi dla kalkulatora WoodPower CRM
 * Wzorowany na woodconfigurator.js z PrestaShop
 */

const EdgesModule = (function() {
    'use strict';

    // ==========================================
    // KONFIGURACJA
    // ==========================================

    // Helper: sprawdza czy kształt jest okrągły/eliptyczny (round, circle, ellipse)
    function _isRoundShape(shape) {
        return shape === 'round' || shape === 'circle' || shape === 'ellipse';
    }

    // Ceny domyślne (fallback gdy API niedostępne)
    const DEFAULT_PRICES = {
        chamfer: { per_mb: 15.00, per_corner: 5.00 },
        round: { per_mb: 15.00, per_corner: 5.00 }
    };

    // Dynamiczna konfiguracja - ceny będą aktualizowane z API
    const CONFIG = {
        // Ceny (netto, PLN) - pobierane dynamicznie z bazy danych
        prices: { ...DEFAULT_PRICES },
        pricesLoaded: false,
        VAT_RATE: 1.23,           // Stawka VAT

        // Promienie R
        R_LIMITS: {
            chamfer: { min: 3, max: 10, default: 3 },
            round: { min: 3, max: 20, default: 5 }
        },

        // Kąty fazowania (pobierane z bazy danych)
        CHAMFER_ANGLES: {
            angles: [30, 45, 60],  // Predefiniowane kąty
            default: 45           // Domyślny kąt
        }
    };

    /**
     * Pobiera ceny obróbki krawędzi z API
     * @returns {Promise<boolean>} true jeśli udało się pobrać ceny
     */
    async function loadPricesFromAPI() {
        try {
            const response = await fetch('/calculator/api/edge-options');
            if (!response.ok) {
                return false;
            }

            const data = await response.json();

            // API zwraca tablicę bezpośrednio [...]
            if (Array.isArray(data)) {
                data.forEach(option => {
                    if (option.type) {
                        // Aktualizuj ceny
                        CONFIG.prices[option.type] = {
                            per_mb: parseFloat(option.price_per_mb) || DEFAULT_PRICES[option.type]?.per_mb || 15.00,
                            per_corner: parseFloat(option.corner_price) || DEFAULT_PRICES[option.type]?.per_corner || 5.00
                        };

                        // Aktualizuj limity R (r_min, r_max, r_default) z bazy danych
                        if (option.r_min !== undefined || option.r_max !== undefined || option.r_default !== undefined) {
                            if (!CONFIG.R_LIMITS[option.type]) {
                                CONFIG.R_LIMITS[option.type] = { min: 3, max: 20, default: 5 };
                            }
                            if (option.r_min !== undefined && option.r_min !== null) {
                                CONFIG.R_LIMITS[option.type].min = parseInt(option.r_min);
                            }
                            if (option.r_max !== undefined && option.r_max !== null) {
                                CONFIG.R_LIMITS[option.type].max = parseInt(option.r_max);
                            }
                            if (option.r_default !== undefined && option.r_default !== null) {
                                CONFIG.R_LIMITS[option.type].default = parseInt(option.r_default);
                            }
                        }

                        // Aktualizuj kąty fazowania (tylko dla typu 'chamfer')
                        if (option.type === 'chamfer') {
                            if (option.chamfer_angles && Array.isArray(option.chamfer_angles) && option.chamfer_angles.length > 0) {
                                CONFIG.CHAMFER_ANGLES.angles = option.chamfer_angles;
                            }
                            if (option.angle_default !== undefined && option.angle_default !== null) {
                                CONFIG.CHAMFER_ANGLES.default = parseInt(option.angle_default);
                            }
                        }
                    }
                });
                CONFIG.pricesLoaded = true;
                return true;
            }
        } catch (error) {
            console.error('[EdgesModule] Błąd podczas pobierania cen:', error);
        }
        return false;
    }

    /**
     * Zwraca cenę za metr bieżący dla danego typu obróbki
     */
    function getPricePerMb(edgeType) {
        return CONFIG.prices[edgeType]?.per_mb || DEFAULT_PRICES[edgeType]?.per_mb || 15.00;
    }

    /**
     * Zwraca cenę za narożnik dla danego typu obróbki
     */
    function getPricePerCorner(edgeType) {
        return CONFIG.prices[edgeType]?.per_corner || DEFAULT_PRICES[edgeType]?.per_corner || 5.00;
    }

    // Definicje krawędzi - prostokąt
    const EDGES = {
        // Poziome górne
        A: { group: 'top', dimension: 'length', name: 'Góra przednia' },
        B: { group: 'top', dimension: 'length', name: 'Góra tylna' },
        C: { group: 'top', dimension: 'width', name: 'Góra lewa' },
        D: { group: 'top', dimension: 'width', name: 'Góra prawa' },

        // Poziome dolne
        E: { group: 'bottom', dimension: 'length', name: 'Dół przednia' },
        F: { group: 'bottom', dimension: 'length', name: 'Dół tylna' },
        G: { group: 'bottom', dimension: 'width', name: 'Dół lewa' },
        H: { group: 'bottom', dimension: 'width', name: 'Dół prawa' },

        // Narożniki
        N1: { group: 'corner', dimension: 'thickness', name: 'Przedni lewy' },
        N2: { group: 'corner', dimension: 'thickness', name: 'Przedni prawy' },
        N3: { group: 'corner', dimension: 'thickness', name: 'Tylny lewy' },
        N4: { group: 'corner', dimension: 'thickness', name: 'Tylny prawy' }
    };

    // Definicje krawędzi - kształt okrągły/owalny (2 krawędzie obwodowe)
    const ROUND_EDGES = {
        KG: { group: 'round_perimeter', name: 'Krawędź górna' },
        KD: { group: 'round_perimeter', name: 'Krawędź dolna' }
    };

    // Grupy krawędzi
    const EDGE_GROUPS = {
        top: ['A', 'B', 'C', 'D'],
        bottom: ['E', 'F', 'G', 'H'],
        horizontal: ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'],
        corner: ['N1', 'N2', 'N3', 'N4'],
        all: ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'N1', 'N2', 'N3', 'N4'],
        round_all: ['KG', 'KD']
    };

    /**
     * Oblicza obwód elipsy w cm (aproksymacja Ramanujan)
     */
    function calculateEllipsePerimeterCm(lengthCm, widthCm) {
        const a = lengthCm / 2, b = widthCm / 2;
        return Math.PI * (3 * (a + b) - Math.sqrt((3 * a + b) * (a + 3 * b)));
    }

    // ==========================================
    // STAN
    // ==========================================

    let state = {
        isOpen: false,
        currentForm: null,
        selectedEdges: new Set(),
        edgeType: 'round',
        rValue: 5,
        angleValue: null,         // Kąt fazowania (tylko dla chamfer)
        dimensions: { length: 0, width: 0, thickness: 0 },
        labelsVisible: true,
        modalInitialized: false,
        productShape: 'rectangular', // 'rectangular' lub 'round'
        dynamicEdgeDefs: {}  // {G1: {length_cm: 80, group: 'top'}, D1: {...}, P1: {...}}
    };

    // ==========================================
    // ELEMENTY DOM
    // ==========================================

    let elements = {};

    function cacheElements() {
        const modal = document.getElementById('edgesModal');
        if (!modal) return false;

        elements = {
            modal: modal,
            closeBtn: document.getElementById('closeEdgesModal'),
            applyBtn: document.getElementById('applyEdgesBtn'),
            toggleLabelsBtn: document.getElementById('toggleEdgeLabels'),
            typeSelect: document.getElementById('edgeTypeSelect'),
            rValueInput: document.getElementById('edgeRValue'),
            angleGroup: document.getElementById('edgesAngleGroup'),
            angleButtons: document.getElementById('edgeAngleButtons'),
            priceBrutto: document.getElementById('edgesPriceBrutto'),
            priceNetto: document.getElementById('edgesPriceNetto'),
            svg: document.getElementById('edgesSvg'),
            labelsGroup: document.getElementById('edgeLabelsGroup'),
            quickBtns: modal.querySelectorAll('.edges-quick-btn'),
            checkboxes: modal.querySelectorAll('.edges-item input[type="checkbox"]'),
            items: modal.querySelectorAll('.edges-item')
        };
        return true;
    }

    // ==========================================
    // INICJALIZACJA
    // ==========================================

    async function init() {

        // Pobierz ceny z API (nie blokuj inicjalizacji)
        loadPricesFromAPI();

        // Zawsze dodaj event listenery dla przycisków (event delegation na document)
        attachGlobalEventListeners();

        // Monitoruj zmiany wymiarów w formularzach
        setupDimensionWatchers();

        // Aktualizuj stan przycisków dla wszystkich formularzy
        updateAllButtonStates();

        // Wygeneruj domyślny podgląd SVG dla wszystkich formularzy
        document.querySelectorAll('.quote-form').forEach(form => {
            updateEdgesPreview(form);
        });

        // Przycisk oczka w preview — toggle etykiet
        document.addEventListener('click', function(e) {
            var btn = e.target.closest('.edges-preview-toggle-labels');
            if (!btn) return;
            e.preventDefault();
            btn.classList.toggle('labels-hidden');
            var section = btn.closest('.edges-section');
            var svg = section ? section.querySelector('.edges-preview-svg') : null;
            if (svg) {
                var labelsG = svg.querySelector('.edges-labels');
                if (labelsG) labelsG.classList.toggle('edges-labels-hidden');
            }
            // Synchronizuj z modalem
            state.labelsVisible = !btn.classList.contains('labels-hidden');
        });

    }

    /**
     * Sprawdza czy formularz ma wszystkie wymiary wypełnione
     */
    function formHasAllDimensions(form) {
        if (!form) return false;

        const lengthInput = form.querySelector('input[data-field="length"]');
        const widthInput = form.querySelector('input[data-field="width"]');
        const thicknessInput = form.querySelector('input[data-field="thickness"]');

        const length = parseFloat(lengthInput?.value) || 0;
        const width = parseFloat(widthInput?.value) || 0;
        const thickness = parseFloat(thicknessInput?.value) || 0;

        return length > 0 && width > 0 && thickness > 0;
    }

    /**
     * Aktualizuje stan przycisku dla pojedynczego formularza
     */
    function updateButtonState(form) {
        if (!form) return;

        const btn = form.querySelector('.open-edges-modal-btn');
        if (!btn) return;

        const hasAllDimensions = formHasAllDimensions(form);

        if (hasAllDimensions) {
            btn.disabled = false;
            btn.classList.remove('disabled');
            btn.title = '';
        } else {
            btn.disabled = true;
            btn.classList.add('disabled');
            btn.title = 'Uzupełnij wszystkie wymiary (długość, szerokość, grubość)';
        }
    }

    /**
     * Aktualizuje stan przycisków dla wszystkich formularzy
     */
    function updateAllButtonStates() {
        const forms = document.querySelectorAll('.quote-form');
        forms.forEach(form => updateButtonState(form));
    }

    /**
     * Ustawia nasłuchiwanie na zmiany wymiarów
     */
    function setupDimensionWatchers() {
        // Event delegation dla inputów wymiarów
        document.addEventListener('input', function(e) {
            const input = e.target;
            if (input.matches('input[data-field="length"], input[data-field="width"], input[data-field="thickness"]')) {
                const form = input.closest('.quote-form');
                if (form) {
                    updateButtonState(form);
                }
            }
        });
    }

    function attachGlobalEventListeners() {
        // Event delegation dla wszystkich kliknięć
        document.addEventListener('click', function(e) {
            // Otwieranie modala
            const openBtn = e.target.closest('.open-edges-modal-btn');
            if (openBtn && !openBtn.disabled) {
                e.preventDefault();
                const form = openBtn.closest('.quote-form');
                openModal(form);
                return;
            }

            // Przycisk Reset krawędzi
            const resetBtn = e.target.closest('.edges-reset-btn');
            if (resetBtn) {
                e.preventDefault();
                const form = resetBtn.closest('.quote-form');
                state.currentForm = form;
                resetEdges();
                return;
            }

            // Przycisk Reset wykończenia
            const finishingResetBtn = e.target.closest('.finishing-reset-btn');
            if (finishingResetBtn) {
                e.preventDefault();
                const form = finishingResetBtn.closest('.quote-form');
                if (typeof window.resetFinishing === 'function') {
                    window.resetFinishing(form);
                }
                return;
            }

            // Zamykanie przez klik na overlay modalu
            if (e.target.id === 'edgesModal') {
                closeModal();
            }
        });

        // Zamykanie przez ESC
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && state.isOpen) {
                closeModal();
            }
        });

    }

    /**
     * Dodaje event listenery do elementów wewnątrz modalu
     * Wywoływane tylko raz przy pierwszym otwarciu
     */
    function attachModalEventListeners() {
        if (state.modalInitialized) return;


        // Przycisk zamknięcia
        if (elements.closeBtn) {
            elements.closeBtn.addEventListener('click', function(e) {
                e.preventDefault();
                closeModal();
            });
        }

        // Przycisk Zastosuj
        if (elements.applyBtn) {
            elements.applyBtn.addEventListener('click', function(e) {
                e.preventDefault();
                applyEdges();
            });
        }

        // Przycisk toggle etykiet
        if (elements.toggleLabelsBtn) {
            elements.toggleLabelsBtn.addEventListener('click', function(e) {
                e.preventDefault();
                toggleLabels();
            });
        }

        // Select typu obróbki
        if (elements.typeSelect) {
            elements.typeSelect.addEventListener('change', onTypeChange);
        }

        // Input promienia R
        if (elements.rValueInput) {
            elements.rValueInput.addEventListener('input', onRValueChange);
        }

        // Przyciski kąta fazowania są dodawane dynamicznie w updateAngleButtons()

        // Przyciski szybkiego wyboru (Góra, Dół, Wszystkie, Odznacz)
        elements.quickBtns.forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const action = this.dataset.action;
                handleQuickAction(action);
            });
        });

        // Checkboxy krawędzi
        elements.checkboxes.forEach(checkbox => {
            checkbox.addEventListener('change', onCheckboxChange);
        });

        // Hovery na elementach listy -> podświetlenie SVG
        elements.items.forEach(item => {
            item.addEventListener('mouseenter', function() {
                const edge = this.dataset.edge;
                highlightEdge(edge, true);
            });
            item.addEventListener('mouseleave', function() {
                const edge = this.dataset.edge;
                highlightEdge(edge, false);
            });

            // Kliknięcie na cały item toggleuje checkbox
            item.addEventListener('click', function(e) {
                // Jeśli kliknięto bezpośrednio checkbox - pozwól na domyślne zachowanie
                if (e.target.type === 'checkbox') return;

                // Dla wszystkich innych kliknięć (label, span, itp.) - zatrzymaj domyślne
                // i przełącz checkbox ręcznie
                e.preventDefault();

                const checkbox = this.querySelector('input[type="checkbox"]');
                if (checkbox) {
                    checkbox.checked = !checkbox.checked;
                    checkbox.dispatchEvent(new Event('change', { bubbles: true }));
                }
            });
        });

        // UWAGA: Event listenery dla SVG są teraz dodawane w attachSvgEventListeners()
        // wywoływanym po każdej regeneracji SVG w generateProportionalSVG()

        state.modalInitialized = true;
    }

    // ==========================================
    // MODAL
    // ==========================================

    async function openModal(form) {
        state.currentForm = form || document.querySelector('.quote-form');

        // Sprawdź czy formularz ma wymiary
        if (!formHasAllDimensions(state.currentForm)) {
            return;
        }

        // Jeśli ceny nie zostały jeszcze załadowane, poczekaj na ich pobranie
        if (!CONFIG.pricesLoaded) {
            await loadPricesFromAPI();
        }

        state.isOpen = true;

        // Odczytaj kształt produktu z formularza
        state.productShape = state.currentForm.dataset.productShape || 'rectangular';

        // Jeśli elementy nie były jeszcze zcache'owane, zrób to teraz
        if (!elements.modal) {
            if (!cacheElements()) {
                console.error('[EdgesModule] Modal #edgesModal nie znaleziony w DOM!');
                return;
            }
        }

        // Dodaj event listenery dla elementów wewnątrz modalu (tylko raz)
        attachModalEventListeners();

        // Pobierz wymiary z formularza
        loadDimensionsFromForm();

        // WAŻNE: Najpierw wczytaj zapisany stan z formularza (lub zresetuj do domyślnych)
        loadSavedState();

        // Przełącz UI w zależności od kształtu produktu
        if (_isRoundShape(state.productShape)) {
            showRoundEdgesUI();
            generateRoundSVG(
                state.dimensions.length,
                state.dimensions.width,
                state.dimensions.thickness
            );
        } else if (state.productShape !== 'rectangular' && state.currentForm._shapeEditor) {
            // Nieregularny kształt — dynamiczne krawędzie G/D/P
            var shapeData = state.currentForm._shapeEditor.getShapeData();
            showDynamicEdgesUI(shapeData, state.dimensions.thickness);
            if (elements.svg && shapeData && shapeData.vertices) {
                generateShapePreviewSVG(elements.svg, shapeData, state.dimensions.thickness, state.selectedEdges, state.productShape);
            }
        } else {
            showRectangularEdgesUI();
            generateProportionalSVG(
                state.dimensions.length,
                state.dimensions.width,
                state.dimensions.thickness
            );
        }

        // Re-cache labelsGroup po każdym przebudowaniu SVG
        // Re-cache labelsGroup (querySelector bo element jest wewnątrz SVG)
        elements.labelsGroup = elements.svg ? elements.svg.querySelector('#edgeLabelsGroup') : document.getElementById('edgeLabelsGroup');

        // Aktualizuj długości krawędzi w UI
        updateEdgeLengths();

        // Pokaż modal
        elements.modal.style.display = 'flex';

        // Przelicz cenę
        calculatePrice();

    }

    function closeModal() {
        state.isOpen = false;
        elements.modal.style.display = 'none';
    }

    // ==========================================
    // WYMIARY
    // ==========================================

    function loadDimensionsFromForm() {
        if (!state.currentForm) return;

        const lengthInput = state.currentForm.querySelector('input[data-field="length"]');
        const widthInput = state.currentForm.querySelector('input[data-field="width"]');
        const thicknessInput = state.currentForm.querySelector('input[data-field="thickness"]');

        state.dimensions = {
            length: parseFloat(lengthInput?.value) || 0,
            width: parseFloat(widthInput?.value) || 0,
            thickness: parseFloat(thicknessInput?.value) || 0
        };
    }

    function updateEdgeLengths() {
        elements.items.forEach(item => {
            const edge = item.dataset.edge;
            const lengthSpan = item.querySelector('.edges-length');

            if (lengthSpan && EDGES[edge]) {
                const dimension = EDGES[edge].dimension;
                const lengthCm = state.dimensions[dimension] || 0;
                lengthSpan.textContent = `(${lengthCm.toFixed(1)} cm)`;
            }
        });
    }

    // ==========================================
    // OBSŁUGA ZDARZEŃ
    // ==========================================

    function onTypeChange() {
        state.edgeType = elements.typeSelect.value;

        // Aktualizuj limity promienia R
        const limits = CONFIG.R_LIMITS[state.edgeType];
        if (limits) {
            elements.rValueInput.min = limits.min;
            elements.rValueInput.max = limits.max;

            // Jeśli aktualna wartość poza limitami, ustaw domyślną
            if (state.rValue < limits.min || state.rValue > limits.max) {
                state.rValue = limits.default;
                elements.rValueInput.value = limits.default;
            }
        }

        // Aktualizuj widoczność i zawartość przycisków kąta fazowania
        updateAngleButtons();

        calculatePrice();
    }

    /**
     * Aktualizuje przyciski kąta fazowania - widoczność i stan
     */
    function updateAngleButtons() {
        if (!elements.angleGroup || !elements.angleButtons) return;

        if (state.edgeType === 'chamfer') {
            // Pokaż grupę kąta
            elements.angleGroup.style.display = 'flex';

            // Wypełnij przyciskami z konfiguracji
            const angles = CONFIG.CHAMFER_ANGLES.angles;
            const defaultAngle = CONFIG.CHAMFER_ANGLES.default;

            // Ustaw domyślną wartość jeśli nie ustawiona
            if (!state.angleValue || !angles.includes(state.angleValue)) {
                state.angleValue = defaultAngle;
            }

            elements.angleButtons.innerHTML = angles.map(angle =>
                `<button type="button" class="edges-angle-btn ${angle === state.angleValue ? 'active' : ''}" data-angle="${angle}">${angle}°</button>`
            ).join('');

            // Dodaj event listenery do przycisków
            elements.angleButtons.querySelectorAll('.edges-angle-btn').forEach(btn => {
                btn.addEventListener('click', onAngleButtonClick);
            });
        } else {
            // Ukryj grupę kąta i wyczyść wartość
            elements.angleGroup.style.display = 'none';
            state.angleValue = null;
        }
    }

    function onAngleButtonClick(e) {
        const angle = parseInt(e.target.dataset.angle);
        state.angleValue = angle;

        // Aktualizuj klasy active
        elements.angleButtons.querySelectorAll('.edges-angle-btn').forEach(btn => {
            btn.classList.toggle('active', parseInt(btn.dataset.angle) === angle);
        });
    }

    function onRValueChange() {
        state.rValue = parseInt(elements.rValueInput.value) || 3;
        calculatePrice();
    }

    function onCheckboxChange(e) {
        const item = e.target.closest('.edges-item');
        const edge = item.dataset.edge;

        if (e.target.checked) {
            state.selectedEdges.add(edge);
            item.classList.add('selected');
            updateSvgEdge(edge, true);
        } else {
            state.selectedEdges.delete(edge);
            item.classList.remove('selected');
            updateSvgEdge(edge, false);
        }

        calculatePrice();
    }

    function toggleEdgeSelection(edge) {
        const item = document.querySelector(`.edges-item[data-edge="${edge}"]`);
        if (!item) return;

        const checkbox = item.querySelector('input[type="checkbox"]');
        if (checkbox) {
            checkbox.checked = !checkbox.checked;
            checkbox.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    function handleQuickAction(action) {
        if (_isRoundShape(state.productShape)) {
            // Akcje dla kształtu okrągłego
            switch (action) {
                case 'select-top':
                    deselectAllEdges();
                    selectEdges(['KG']);
                    break;
                case 'select-bottom':
                    deselectAllEdges();
                    selectEdges(['KD']);
                    break;
                case 'select-all':
                    selectEdges(EDGE_GROUPS.round_all);
                    break;
                case 'deselect-all':
                    deselectAllEdges();
                    break;
            }
        } else if (state.productShape !== 'rectangular') {
            // Dynamiczne krawędzie
            var dynSection = elements.modal ? elements.modal.querySelector('.edges-dynamic-section') : null;
            if (!dynSection) return;

            var topEdges = [], bottomEdges = [], allEdges = [];
            dynSection.querySelectorAll('.edges-item').forEach(function(item) {
                var eid = item.dataset.edge;
                allEdges.push(eid);
                if (eid.charAt(0) === 'G') topEdges.push(eid);
                else if (eid.charAt(0) === 'D') bottomEdges.push(eid);
            });

            var targetEdges = [];
            if (action === 'select-top') targetEdges = topEdges;
            else if (action === 'select-bottom') targetEdges = bottomEdges;
            else if (action === 'select-all') targetEdges = allEdges;
            else if (action === 'deselect-all') { targetEdges = []; state.selectedEdges.clear(); }

            if (action !== 'deselect-all') {
                targetEdges.forEach(function(eid) { state.selectedEdges.add(eid); });
            }

            dynSection.querySelectorAll('.edges-item').forEach(function(item) {
                var eid = item.dataset.edge;
                var cb = item.querySelector('input[type="checkbox"]');
                var isSelected = state.selectedEdges.has(eid);
                if (cb) cb.checked = isSelected;
                item.classList.toggle('active', isSelected);
                updateSvgEdge(eid, isSelected);
            });

            calculatePrice();
            return;
        } else {
            // Akcje dla kształtu prostokątnego
            switch (action) {
                case 'select-top':
                    deselectAllEdges();
                    selectEdges(EDGE_GROUPS.top);
                    break;
                case 'select-bottom':
                    deselectAllEdges();
                    selectEdges(EDGE_GROUPS.bottom);
                    break;
                case 'select-all':
                    selectEdges(EDGE_GROUPS.all);
                    break;
                case 'deselect-all':
                    deselectAllEdges();
                    break;
            }
        }

        calculatePrice();
    }

    function selectEdges(edges) {
        edges.forEach(edge => {
            state.selectedEdges.add(edge);
            // Szukaj elementu krawędzi w całym modalu (obsługuje zarówno prostokąt, jak i okrągły)
            const item = elements.modal?.querySelector(`.edges-item[data-edge="${edge}"]`);
            if (item) {
                const checkbox = item.querySelector('input[type="checkbox"]');
                if (checkbox) checkbox.checked = true;
                item.classList.add('selected');
            }
            updateSvgEdge(edge, true);
        });
        if (_isRoundShape(state.productShape)) {
            updateRoundSvgHighlights();
        }
    }

    function deselectAllEdges() {
        state.selectedEdges.clear();
        // Odznacz checkboxy prostokąta
        elements.checkboxes.forEach(cb => {
            cb.checked = false;
            cb.closest('.edges-item')?.classList.remove('selected');
        });
        EDGE_GROUPS.all.forEach(edge => updateSvgEdge(edge, false));

        // Odznacz checkboxy okrągłego (jeśli istnieją)
        const roundSection = elements.modal?.querySelector('.edges-round-section');
        if (roundSection) {
            roundSection.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.checked = false;
                cb.closest('.edges-item')?.classList.remove('selected');
            });
        }
        if (_isRoundShape(state.productShape)) {
            updateRoundSvgHighlights();
        }
    }

    function toggleLabels() {
        state.labelsVisible = !state.labelsVisible;

        // Toggle w modalu
        if (elements.labelsGroup) {
            elements.labelsGroup.classList.toggle('edges-labels-hidden', !state.labelsVisible);
        }
        if (elements.toggleLabelsBtn) {
            elements.toggleLabelsBtn.textContent = state.labelsVisible ? 'Ukryj etykiety' : 'Pokaż etykiety';
        }

        // Synchronizuj preview w formularzu
        if (state.currentForm) {
            var previewBtn = state.currentForm.querySelector('.edges-preview-toggle-labels');
            if (previewBtn) previewBtn.classList.toggle('labels-hidden', !state.labelsVisible);
            var previewSvg = state.currentForm.querySelector('.edges-preview-svg .edges-labels');
            if (previewSvg) previewSvg.classList.toggle('edges-labels-hidden', !state.labelsVisible);
        }
    }

    // ==========================================
    // SVG - GENEROWANIE PROPORCJONALNE
    // ==========================================

    /**
     * Generuje proporcjonalny widok izometryczny SVG na podstawie wymiarów
     * @param {number} length - długość w cm
     * @param {number} width - szerokość w cm
     * @param {number} thickness - grubość w cm
     */
    function generateProportionalSVG(length, width, thickness) {
        if (!elements.svg) return;

        // Konfiguracja viewBox i marginesów
        const viewBoxWidth = 320;
        const viewBoxHeight = 220;
        const margin = 35; // Margines na etykiety

        // Obszar roboczy (bez marginesów na etykiety)
        const workWidth = viewBoxWidth - 2 * margin;
        const workHeight = viewBoxHeight - 2 * margin;

        // Parametry projekcji izometrycznej
        // Kąt izometryczny: oś X idzie w prawo-dół, oś Y idzie w lewo-dół
        const isoAngleX = Math.PI / 6;  // 30 stopni
        const isoAngleY = Math.PI / 6;  // 30 stopni

        // Oblicz proporcje wymiarów
        const maxDim = Math.max(length, width);

        // Minimalna grubość wizualna: 15% maksymalnego wymiaru lub rzeczywista grubość
        const minThicknessRatio = 0.15;
        const effectiveThickness = Math.max(thickness, maxDim * minThicknessRatio);

        // Skalowanie do obszaru roboczego
        // W izometrii: szerokość = length * cos(30) + width * cos(30)
        // wysokość = length * sin(30) + width * sin(30) + thickness
        const projectedWidth = (length + width) * Math.cos(isoAngleX);
        const projectedHeight = (length + width) * Math.sin(isoAngleX) + effectiveThickness;

        const scaleX = workWidth / projectedWidth;
        const scaleY = workHeight / projectedHeight;
        const scale = Math.min(scaleX, scaleY) * 0.85; // 85% żeby było trochę luzu

        // Przeskalowane wymiary
        const L = length * scale;  // długość (oś X izometryczna)
        const W = width * scale;   // szerokość (oś Y izometryczna)
        const T = effectiveThickness * scale; // grubość (oś Z - pionowa)

        // Wektory izometryczne
        const vecX = { x: Math.cos(isoAngleX), y: Math.sin(isoAngleX) };   // prawo-dół
        const vecY = { x: -Math.cos(isoAngleY), y: Math.sin(isoAngleY) };  // lewo-dół
        const vecZ = { x: 0, y: -1 };  // góra

        // Oblicz całkowity rozmiar rzutu bryły żeby wycentrować
        // Rzut izometryczny: szerokość = L*cos(30) + W*cos(30), wysokość = L*sin(30) + W*sin(30) + T
        const totalProjWidth = L * vecX.x + W * Math.abs(vecY.x);
        const totalProjHeight = L * vecX.y + W * vecY.y + T;

        // Punkt startowy (przedni-lewy-dolny róg) - wycentrowany
        const startX = (viewBoxWidth - totalProjWidth) / 2 + W * Math.abs(vecY.x);
        const startY = (viewBoxHeight - totalProjHeight) / 2 + T;

        // Oblicz wszystkie 8 wierzchołków sześcianu
        // Nazewnictwo zgodne z UI (A=góra przednia, E=dół przednia, itd.)
        // W renderingu izometrycznym: "przedni" = na dole-prawo, "tylny" = na górze-lewo

        // Dolna płaszczyzna (z=0)
        // Zaczynamy od tylnego-lewego rogu i idziemy zgodnie z renderingiem
        const pTylnyLewyDolny = {
            x: startX,
            y: startY
        };
        const pTylnyPrawyDolny = {
            x: pTylnyLewyDolny.x + L * vecX.x,
            y: pTylnyLewyDolny.y + L * vecX.y
        };
        const pPrzedniPrawyDolny = {
            x: pTylnyPrawyDolny.x + W * vecY.x,
            y: pTylnyPrawyDolny.y + W * vecY.y
        };
        const pPrzedniLewyDolny = {
            x: pTylnyLewyDolny.x + W * vecY.x,
            y: pTylnyLewyDolny.y + W * vecY.y
        };

        // Górna płaszczyzna (przesunięta o T w górę, czyli -T w y)
        const pTylnyLewyGorny = { x: pTylnyLewyDolny.x, y: pTylnyLewyDolny.y - T };
        const pTylnyPrawyGorny = { x: pTylnyPrawyDolny.x, y: pTylnyPrawyDolny.y - T };
        const pPrzedniPrawyGorny = { x: pPrzedniPrawyDolny.x, y: pPrzedniPrawyDolny.y - T };
        const pPrzedniLewyGorny = { x: pPrzedniLewyDolny.x, y: pPrzedniLewyDolny.y - T };

        // Generuj HTML dla SVG
        const svgContent = `
            <!-- Ściany (tło) - rysowane od tyłu do przodu -->
            <!-- Ściana tylna -->
            <polygon class="edges-face edges-face-back"
                     points="${pTylnyLewyDolny.x},${pTylnyLewyDolny.y} ${pTylnyPrawyDolny.x},${pTylnyPrawyDolny.y} ${pTylnyPrawyGorny.x},${pTylnyPrawyGorny.y} ${pTylnyLewyGorny.x},${pTylnyLewyGorny.y}"/>
            <!-- Ściana lewa -->
            <polygon class="edges-face edges-face-left"
                     points="${pTylnyLewyDolny.x},${pTylnyLewyDolny.y} ${pPrzedniLewyDolny.x},${pPrzedniLewyDolny.y} ${pPrzedniLewyGorny.x},${pPrzedniLewyGorny.y} ${pTylnyLewyGorny.x},${pTylnyLewyGorny.y}"/>
            <!-- Ściana górna -->
            <polygon class="edges-face edges-face-top"
                     points="${pTylnyLewyGorny.x},${pTylnyLewyGorny.y} ${pTylnyPrawyGorny.x},${pTylnyPrawyGorny.y} ${pPrzedniPrawyGorny.x},${pPrzedniPrawyGorny.y} ${pPrzedniLewyGorny.x},${pPrzedniLewyGorny.y}"/>
            <!-- Ściana przednia -->
            <polygon class="edges-face edges-face-front"
                     points="${pPrzedniLewyDolny.x},${pPrzedniLewyDolny.y} ${pPrzedniPrawyDolny.x},${pPrzedniPrawyDolny.y} ${pPrzedniPrawyGorny.x},${pPrzedniPrawyGorny.y} ${pPrzedniLewyGorny.x},${pPrzedniLewyGorny.y}"/>
            <!-- Ściana prawa -->
            <polygon class="edges-face edges-face-right"
                     points="${pTylnyPrawyDolny.x},${pTylnyPrawyDolny.y} ${pPrzedniPrawyDolny.x},${pPrzedniPrawyDolny.y} ${pPrzedniPrawyGorny.x},${pPrzedniPrawyGorny.y} ${pTylnyPrawyGorny.x},${pTylnyPrawyGorny.y}"/>

            <!-- Krawędzie ukryte (przerywane) -->
            <!-- F: Dół tylna - ukryta -->
            <line class="edges-line edges-hidden" data-edge="F"
                  x1="${pTylnyLewyDolny.x}" y1="${pTylnyLewyDolny.y}" x2="${pTylnyPrawyDolny.x}" y2="${pTylnyPrawyDolny.y}"/>
            <!-- G: Dół lewa - ukryta -->
            <line class="edges-line edges-hidden" data-edge="G"
                  x1="${pTylnyLewyDolny.x}" y1="${pTylnyLewyDolny.y}" x2="${pPrzedniLewyDolny.x}" y2="${pPrzedniLewyDolny.y}"/>
            <!-- N3: Narożnik tylny lewy - ukryty -->
            <line class="edges-line edges-hidden edges-corner" data-edge="N3"
                  x1="${pTylnyLewyGorny.x}" y1="${pTylnyLewyGorny.y}" x2="${pTylnyLewyDolny.x}" y2="${pTylnyLewyDolny.y}"/>

            <!-- Krawędzie górne (widoczne) -->
            <!-- A: Góra przednia -->
            <line class="edges-line" data-edge="A"
                  x1="${pPrzedniLewyGorny.x}" y1="${pPrzedniLewyGorny.y}" x2="${pPrzedniPrawyGorny.x}" y2="${pPrzedniPrawyGorny.y}"/>
            <!-- B: Góra tylna -->
            <line class="edges-line" data-edge="B"
                  x1="${pTylnyLewyGorny.x}" y1="${pTylnyLewyGorny.y}" x2="${pTylnyPrawyGorny.x}" y2="${pTylnyPrawyGorny.y}"/>
            <!-- C: Góra lewa -->
            <line class="edges-line" data-edge="C"
                  x1="${pTylnyLewyGorny.x}" y1="${pTylnyLewyGorny.y}" x2="${pPrzedniLewyGorny.x}" y2="${pPrzedniLewyGorny.y}"/>
            <!-- D: Góra prawa -->
            <line class="edges-line" data-edge="D"
                  x1="${pTylnyPrawyGorny.x}" y1="${pTylnyPrawyGorny.y}" x2="${pPrzedniPrawyGorny.x}" y2="${pPrzedniPrawyGorny.y}"/>

            <!-- Krawędzie dolne (widoczne) -->
            <!-- E: Dół przednia -->
            <line class="edges-line" data-edge="E"
                  x1="${pPrzedniLewyDolny.x}" y1="${pPrzedniLewyDolny.y}" x2="${pPrzedniPrawyDolny.x}" y2="${pPrzedniPrawyDolny.y}"/>
            <!-- H: Dół prawa -->
            <line class="edges-line" data-edge="H"
                  x1="${pTylnyPrawyDolny.x}" y1="${pTylnyPrawyDolny.y}" x2="${pPrzedniPrawyDolny.x}" y2="${pPrzedniPrawyDolny.y}"/>

            <!-- Narożniki (pionowe) - widoczne -->
            <!-- N1: Narożnik przedni lewy -->
            <line class="edges-line edges-corner" data-edge="N1"
                  x1="${pPrzedniLewyGorny.x}" y1="${pPrzedniLewyGorny.y}" x2="${pPrzedniLewyDolny.x}" y2="${pPrzedniLewyDolny.y}"/>
            <!-- N2: Narożnik przedni prawy -->
            <line class="edges-line edges-corner" data-edge="N2"
                  x1="${pPrzedniPrawyGorny.x}" y1="${pPrzedniPrawyGorny.y}" x2="${pPrzedniPrawyDolny.x}" y2="${pPrzedniPrawyDolny.y}"/>
            <!-- N4: Narożnik tylny prawy -->
            <line class="edges-line edges-corner" data-edge="N4"
                  x1="${pTylnyPrawyGorny.x}" y1="${pTylnyPrawyGorny.y}" x2="${pTylnyPrawyDolny.x}" y2="${pTylnyPrawyDolny.y}"/>

            <!-- Etykiety -->
            <g class="edges-labels" id="edgeLabelsGroup">
                <!-- Górne poziome -->
                ${generateLabel('A', midpoint(pPrzedniLewyGorny, pPrzedniPrawyGorny))}
                ${generateLabel('B', midpoint(pTylnyLewyGorny, pTylnyPrawyGorny))}
                ${generateLabel('C', midpoint(pTylnyLewyGorny, pPrzedniLewyGorny))}
                ${generateLabel('D', midpoint(pTylnyPrawyGorny, pPrzedniPrawyGorny))}

                <!-- Dolne poziome -->
                ${generateLabel('E', midpoint(pPrzedniLewyDolny, pPrzedniPrawyDolny))}
                ${generateLabel('F', midpoint(pTylnyLewyDolny, pTylnyPrawyDolny))}
                ${generateLabel('G', midpoint(pTylnyLewyDolny, pPrzedniLewyDolny))}
                ${generateLabel('H', midpoint(pTylnyPrawyDolny, pPrzedniPrawyDolny))}

                <!-- Narożniki -->
                ${generateCornerLabel('N1', midpoint(pPrzedniLewyGorny, pPrzedniLewyDolny), -14)}
                ${generateCornerLabel('N2', midpoint(pPrzedniPrawyGorny, pPrzedniPrawyDolny), 14)}
                ${generateCornerLabel('N3', midpoint(pTylnyLewyGorny, pTylnyLewyDolny), -14)}
                ${generateCornerLabel('N4', midpoint(pTylnyPrawyGorny, pTylnyPrawyDolny), 14)}
            </g>
        `;

        elements.svg.innerHTML = svgContent;

        // Zaktualizuj referencję do grupy etykiet
        elements.labelsGroup = document.getElementById('edgeLabelsGroup');

        // Ponownie przypisz event listenery do nowych elementów SVG
        attachSvgEventListeners();

        // Przywróć stan zaznaczonych krawędzi
        state.selectedEdges.forEach(edge => {
            updateSvgEdge(edge, true);
        });

        // Przywróć widoczność etykiet
        if (!state.labelsVisible && elements.labelsGroup) {
            elements.labelsGroup.classList.add('edges-labels-hidden');
        }
    }

    /**
     * Oblicza punkt środkowy między dwoma punktami
     */
    function midpoint(p1, p2) {
        return {
            x: (p1.x + p2.x) / 2,
            y: (p1.y + p2.y) / 2
        };
    }

    /**
     * Generuje HTML dla etykiety krawędzi
     */
    function generateLabel(letter, pos, offset = 0) {
        const offsetY = 4; // Przesunięcie tekstu w pionie dla centrowania
        return `
            <g class="edges-label" data-edge="${letter}">
                <circle cx="${pos.x}" cy="${pos.y}" r="12"/>
                <text x="${pos.x}" y="${pos.y + offsetY}">${letter}</text>
            </g>
        `;
    }

    /**
     * Generuje HTML dla etykiety narożnika
     */
    function generateCornerLabel(letter, pos, offsetX = 0) {
        const offsetY = 4;
        return `
            <g class="edges-label edges-label-corner" data-edge="${letter}">
                <circle cx="${pos.x + offsetX}" cy="${pos.y}" r="14"/>
                <text x="${pos.x + offsetX}" y="${pos.y + offsetY}">${letter}</text>
            </g>
        `;
    }

    /**
     * Przypisuje event listenery do elementów SVG
     * Wywoływane po regeneracji SVG
     */
    function attachSvgEventListeners() {
        if (!elements.svg) return;

        // Linie krawędzi
        elements.svg.querySelectorAll('.edges-line').forEach(line => {
            line.addEventListener('click', function(e) {
                e.preventDefault();
                const edge = this.dataset.edge;
                toggleEdgeSelection(edge);
            });
            line.addEventListener('mouseenter', function() {
                const edge = this.dataset.edge;
                highlightListItem(edge, true);
                highlightEdge(edge, true);
            });
            line.addEventListener('mouseleave', function() {
                const edge = this.dataset.edge;
                highlightListItem(edge, false);
                highlightEdge(edge, false);
            });
        });

        // Etykiety krawędzi
        elements.svg.querySelectorAll('.edges-label').forEach(label => {
            label.addEventListener('click', function(e) {
                e.preventDefault();
                const edge = this.dataset.edge;
                toggleEdgeSelection(edge);
            });
            label.addEventListener('mouseenter', function() {
                const edge = this.dataset.edge;
                highlightListItem(edge, true);
                highlightEdge(edge, true);
            });
            label.addEventListener('mouseleave', function() {
                const edge = this.dataset.edge;
                highlightListItem(edge, false);
                highlightEdge(edge, false);
            });
        });
    }

    // ==========================================
    // SVG - AKTUALIZACJA STANU
    // ==========================================

    function updateSvgEdge(edge, active) {
        const line = elements.svg?.querySelector(`.edges-line[data-edge="${edge}"]`);
        const label = elements.svg?.querySelector(`.edges-label[data-edge="${edge}"]`);

        if (line) {
            line.classList.toggle('active', active);
        }
        if (label) {
            label.classList.toggle('active', active);
        }
    }

    function highlightEdge(edge, highlight) {
        const line = elements.svg?.querySelector(`.edges-line[data-edge="${edge}"]`);
        const label = elements.svg?.querySelector(`.edges-label[data-edge="${edge}"]`);
        if (line) {
            line.classList.toggle('highlight', highlight);
        }
        if (label) {
            label.classList.toggle('highlight', highlight);
        }
    }

    function highlightListItem(edge, highlight) {
        const item = document.querySelector(`.edges-item[data-edge="${edge}"]`);
        if (item) {
            item.classList.toggle('hover', highlight);
        }
    }

    // ==========================================
    // KALKULACJA CENY
    // ==========================================

    function calculatePrice() {
        let totalNetto = 0;
        let horizontalCount = 0;
        let cornerCount = 0;

        // Pobierz ceny dla aktualnie wybranego typu obróbki
        const pricePerMb = getPricePerMb(state.edgeType);
        const pricePerCorner = getPricePerCorner(state.edgeType);

        if (_isRoundShape(state.productShape)) {
            // Kształt okrągły: krawędzie obwodowe KG/KD
            const perimeterCm = calculateEllipsePerimeterCm(
                state.dimensions.length, state.dimensions.width
            );
            const perimeterMb = perimeterCm / 100;

            state.selectedEdges.forEach(edge => {
                if (ROUND_EDGES[edge]) {
                    totalNetto += perimeterMb * pricePerMb;
                    horizontalCount++;
                }
            });
        } else if (state.productShape !== 'rectangular' && Object.keys(state.dynamicEdgeDefs).length > 0) {
            // Nieregularny kształt: dynamiczne krawędzie G/D/P
            state.selectedEdges.forEach(edge => {
                const def = state.dynamicEdgeDefs[edge];
                if (!def) return;

                if (def.group === 'vertical') {
                    // Krawędzie pionowe — cena za grubość
                    const lengthMb = def.length_cm / 100;
                    totalNetto += lengthMb * pricePerMb;
                    cornerCount++;
                } else {
                    // Krawędzie górne/dolne — cena za długość
                    const lengthMb = def.length_cm / 100;
                    totalNetto += lengthMb * pricePerMb;
                    horizontalCount++;
                }
            });
        } else {
            // Kształt prostokątny: standardowe 12 krawędzi
            state.selectedEdges.forEach(edge => {
                const def = EDGES[edge];
                if (!def) return;

                if (def.group === 'corner') {
                    totalNetto += pricePerCorner;
                    cornerCount++;
                } else {
                    const lengthCm = state.dimensions[def.dimension] || 0;
                    const lengthMb = lengthCm / 100;
                    totalNetto += lengthMb * pricePerMb;
                    horizontalCount++;
                }
            });
        }

        const totalBrutto = totalNetto * CONFIG.VAT_RATE;

        // Aktualizuj UI
        elements.priceBrutto.textContent = formatPLN(totalBrutto);
        elements.priceNetto.textContent = `(${formatPLN(totalNetto)} netto)`;

        return {
            netto: Math.round(totalNetto * 100) / 100,
            brutto: Math.round(totalBrutto * 100) / 100,
            horizontalCount,
            cornerCount
        };
    }

    function formatPLN(value) {
        return value.toLocaleString('pl-PL', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }) + ' zł';
    }

    // ==========================================
    // ZAPIS / ODCZYT STANU
    // ==========================================

    function applyEdges() {
        if (!state.currentForm) return;

        const prices = calculatePrice();

        // Pobierz ilość sztuk z formularza
        const quantityInput = state.currentForm.querySelector('input[data-field="quantity"]');
        const quantity = parseInt(quantityInput?.value) || 1;

        // Pomnóż ceny przez ilość sztuk
        const totalPrices = {
            netto: Math.round(prices.netto * quantity * 100) / 100,
            brutto: Math.round(prices.brutto * quantity * 100) / 100,
            horizontalCount: prices.horizontalCount,
            cornerCount: prices.cornerCount
        };

        // Pobierz ceny dla aktualnie wybranego typu obróbki
        const pricePerMb = getPricePerMb(state.edgeType);
        const pricePerCorner = getPricePerCorner(state.edgeType);

        // Zbierz dane o wybranych krawędziach
        const edgesData = [];

        if (_isRoundShape(state.productShape)) {
            // Kształt okrągły: krawędzie obwodowe KG/KD
            const perimeterCm = calculateEllipsePerimeterCm(
                state.dimensions.length, state.dimensions.width
            );
            const perimeterMm = perimeterCm * 10;
            const perimeterMb = perimeterCm / 100;

            state.selectedEdges.forEach(edge => {
                const def = ROUND_EDGES[edge];
                if (!def) return;

                const priceNetto = perimeterMb * pricePerMb;

                edgesData.push({
                    letter: edge,
                    type: state.edgeType,
                    r_value: state.rValue,
                    angle_value: state.edgeType === 'chamfer' ? state.angleValue : null,
                    length_mm: Math.round(perimeterMm * 100) / 100,
                    length_cm: Math.round(perimeterCm * 100) / 100,
                    is_corner: false,
                    is_round_perimeter: true,
                    price_netto: Math.round(priceNetto * 100) / 100,
                    price_brutto: Math.round(priceNetto * CONFIG.VAT_RATE * 100) / 100
                });
            });
        } else if (state.productShape !== 'rectangular' && Object.keys(state.dynamicEdgeDefs).length > 0) {
            // Nieregularny kształt: dynamiczne krawędzie G/D/P
            state.selectedEdges.forEach(edge => {
                const def = state.dynamicEdgeDefs[edge];
                if (!def) return;

                const lengthCm = def.length_cm;
                const lengthMm = lengthCm * 10;
                const priceNetto = (lengthCm / 100) * pricePerMb;

                edgesData.push({
                    letter: edge,
                    type: state.edgeType,
                    r_value: state.rValue,
                    angle_value: state.edgeType === 'chamfer' ? state.angleValue : null,
                    length_mm: Math.round(lengthMm * 100) / 100,
                    length_cm: Math.round(lengthCm * 100) / 100,
                    is_corner: def.group === 'vertical',
                    price_netto: Math.round(priceNetto * 100) / 100,
                    price_brutto: Math.round(priceNetto * CONFIG.VAT_RATE * 100) / 100
                });
            });
        } else {
            // Kształt prostokątny: standardowe krawędzie
            state.selectedEdges.forEach(edge => {
                const def = EDGES[edge];
                if (!def) return;

                const lengthCm = state.dimensions[def.dimension] || 0;
                const lengthMm = lengthCm * 10;

                let priceNetto = 0;
                if (def.group === 'corner') {
                    priceNetto = pricePerCorner;
                } else {
                    priceNetto = (lengthCm / 100) * pricePerMb;
                }

                edgesData.push({
                    letter: edge,
                    type: state.edgeType,
                    r_value: state.rValue,
                    angle_value: state.edgeType === 'chamfer' ? state.angleValue : null,
                    length_mm: lengthMm,
                    length_cm: lengthCm,
                    is_corner: def.group === 'corner',
                    price_netto: Math.round(priceNetto * 100) / 100,
                    price_brutto: Math.round(priceNetto * CONFIG.VAT_RATE * 100) / 100
                });
            });
        }

        // Pobierz SVG jako string do zapisu w bazie
        let edgesSvg = '';
        if (elements.svg && state.selectedEdges.size > 0) {
            // Klonuj SVG, aby nie modyfikować oryginału
            const svgClone = elements.svg.cloneNode(true);
            // Usuń grupę etykiet z klonu (dla czystszego podglądu)
            const labelsGroup = svgClone.querySelector('#edgeLabelsGroup');
            if (labelsGroup) {
                labelsGroup.remove();
            }

            // WAŻNE: Dodaj inline style do elementów SVG (style CSS nie są osadzone w SVG)
            const styleMap = {
                '.edges-face': { fill: '#f0f0f0', stroke: 'none' },
                '.edges-face-top': { fill: '#e8e8e8' },
                '.edges-face-front': { fill: '#d8d8d8' },
                '.edges-face-right': { fill: '#c8c8c8' },
                '.edges-face-left': { fill: '#d0d0d0' },
                '.edges-face-back': { fill: '#b8b8b8' },
                '.edges-line': { stroke: '#666', 'stroke-width': '2', fill: 'none' },
                '.edges-line.active': { stroke: '#ED6B24', 'stroke-width': '3' }
            };

            // Aplikuj style inline do każdego elementu
            Object.entries(styleMap).forEach(([selector, styles]) => {
                svgClone.querySelectorAll(selector).forEach(el => {
                    Object.entries(styles).forEach(([prop, value]) => {
                        el.style.setProperty(prop, value);
                    });
                });
            });

            // Dopasuj viewBox do rzeczywistej zawartości (bez etykiet)
            try {
                // Tymczasowo dodaj klon do DOM żeby obliczyć bbox
                svgClone.style.position = 'absolute';
                svgClone.style.visibility = 'hidden';
                document.body.appendChild(svgClone);

                const bbox = svgClone.getBBox();
                const padding = 5; // Mały margines
                const newViewBox = `${bbox.x - padding} ${bbox.y - padding} ${bbox.width + 2*padding} ${bbox.height + 2*padding}`;
                svgClone.setAttribute('viewBox', newViewBox);

                document.body.removeChild(svgClone);

                // Usuń tymczasowe style przed zapisem
                svgClone.style.removeProperty('position');
                svgClone.style.removeProperty('visibility');
            } catch (e) {
                // Ignore errors during SVG clone cleanup
            }

            edgesSvg = svgClone.outerHTML;
        }

        // Zapisz w dataset formularza (ceny już pomnożone przez ilość sztuk)
        state.currentForm.dataset.edgesData = JSON.stringify(edgesData);
        state.currentForm.dataset.edgesNetto = totalPrices.netto;
        state.currentForm.dataset.edgesBrutto = totalPrices.brutto;
        state.currentForm.dataset.edgesCount = state.selectedEdges.size;
        state.currentForm.dataset.edgesType = state.edgeType;
        state.currentForm.dataset.edgesRValue = state.rValue;
        state.currentForm.dataset.edgesAngleValue = state.edgeType === 'chamfer' ? state.angleValue : '';
        state.currentForm.dataset.edgesSvg = edgesSvg;
        state.currentForm.dataset.edgesQuantity = quantity; // Zapisz ilość dla debugowania

        // Aktualizuj przycisk (pokazuj cenę łączną z uwzględnieniem ilości)
        updateOpenButton(state.currentForm, totalPrices);

        // Wywołaj aktualizację globalnego podsumowania
        if (typeof updateGlobalSummary === 'function') {
            updateGlobalSummary();
        }

        // Zaktualizuj podgląd SVG w sekcji krawędzi
        updateEdgesPreview(state.currentForm);

        closeModal();
    }

    function updateOpenButton(form, prices) {
        // Szukaj kontenera krawędzi w sekcji edges
        let optionsSummary = form.querySelector('.edges-options-summary');
        if (!optionsSummary) return;

        const edgesRow = optionsSummary.querySelector('.edges-row');
        const textEl = optionsSummary.querySelector('.edges-summary-text');
        const priceEl = optionsSummary.querySelector('.edges-summary-price');
        let priceNettoEl = optionsSummary.querySelector('.edges-summary-price-netto');
        const openBtn = form.querySelector('.open-edges-modal-btn');

        // Jeśli element netto nie istnieje, utwórz go dynamicznie
        if (!priceNettoEl && edgesRow) {
            const content = edgesRow.querySelector('.options-summary-content');
            if (content) {
                priceNettoEl = document.createElement('span');
                priceNettoEl.className = 'options-summary-price-netto edges-summary-price-netto';
                content.appendChild(priceNettoEl);
            }
        }

        if (state.selectedEdges.size > 0) {
            // Buduj tekst podsumowania
            const edgeNames = Array.from(state.selectedEdges).sort().join(', ');
            const typeLabel = state.edgeType === 'chamfer' ? 'Fazowanie' : 'Zaokrąglenie';

            // Dla fazowania dodaj kąt do opisu
            let summaryText = `${typeLabel} R${state.rValue}`;
            if (state.edgeType === 'chamfer' && state.angleValue) {
                summaryText += ` (${state.angleValue}°)`;
            }
            summaryText += `: ${edgeNames}`;

            if (textEl) textEl.textContent = summaryText;
            if (priceEl) priceEl.textContent = formatPLN(prices.brutto) + ' brutto';
            if (priceNettoEl) priceNettoEl.textContent = formatPLN(prices.netto) + ' netto';
            if (edgesRow) edgesRow.style.display = 'flex';

            // Zmień tekst przycisku na "Zmień obróbkę krawędzi"
            if (openBtn) {
                openBtn.textContent = 'Edytuj';
            }
        } else {
            // Ukryj wiersz krawędzi
            if (edgesRow) edgesRow.style.display = 'none';

            // Przywróć oryginalny tekst przycisku
            if (openBtn) {
                openBtn.textContent = '+ Dodaj';
            }
        }

        // Aktualizuj widoczność głównego kontenera
        updateOptionsSummaryVisibility(optionsSummary);
    }

    /**
     * Aktualizuje widoczność kontenera options-summary
     */
    function updateOptionsSummaryVisibility(optionsSummary) {
        if (!optionsSummary) return;

        const row = optionsSummary.querySelector('.options-summary-row');
        const rowVisible = row && row.style.display !== 'none';

        optionsSummary.style.display = rowVisible ? 'flex' : 'none';
    }

    function resetEdges() {
        if (!state.currentForm) return;

        // Wyczyść zaznaczenie w stanie
        state.selectedEdges.clear();

        // Wyczyść dataset
        delete state.currentForm.dataset.edgesData;
        delete state.currentForm.dataset.edgesNetto;
        delete state.currentForm.dataset.edgesBrutto;
        delete state.currentForm.dataset.edgesCount;
        delete state.currentForm.dataset.edgesType;
        delete state.currentForm.dataset.edgesRValue;
        delete state.currentForm.dataset.edgesSvg;

        // Ukryj wiersz krawędzi w podsumowaniu
        const optionsSummary = state.currentForm.querySelector('.edges-options-summary');
        const edgesRow = optionsSummary?.querySelector('.edges-row');
        if (edgesRow) {
            edgesRow.style.display = 'none';
        }
        updateOptionsSummaryVisibility(optionsSummary);

        // Przywróć oryginalny tekst przycisku
        const openBtn = state.currentForm.querySelector('.open-edges-modal-btn');
        if (openBtn) {
            openBtn.textContent = '+ Dodaj';
        }

        // Zaktualizuj podgląd SVG (szare krawędzie)
        updateEdgesPreview(state.currentForm);

        // Wywołaj aktualizację globalnego podsumowania
        if (typeof updateGlobalSummary === 'function') {
            updateGlobalSummary();
        }
    }

    function loadSavedState() {
        if (!state.currentForm) return;

        const savedData = state.currentForm.dataset.edgesData;
        const savedType = state.currentForm.dataset.edgesType;
        const savedRValue = state.currentForm.dataset.edgesRValue;
        const savedAngleValue = state.currentForm.dataset.edgesAngleValue;

        // Reset stanu globalnego - WAŻNE dla izolacji między formularzami
        state.selectedEdges.clear();

        // Reset UI checkboxów (SVG będzie generowany później z prawidłowym stanem)
        elements.checkboxes.forEach(cb => {
            cb.checked = false;
            cb.closest('.edges-item').classList.remove('selected');
        });
        // NIE wywołuj updateSvgEdge tutaj - SVG będzie generowany PÓŹNIEJ
        // i sam zaznaczy prawidłowe krawędzie na podstawie state.selectedEdges

        if (!savedData) {
            // Brak zapisanych danych dla tego formularza - ustaw domyślne wartości z CONFIG.R_LIMITS
            state.edgeType = 'round';
            const defaultLimits = CONFIG.R_LIMITS['round'] || { min: 3, max: 20, default: 5 };
            state.rValue = defaultLimits.default;
            state.angleValue = null;
            if (elements.typeSelect) elements.typeSelect.value = 'round';
            if (elements.rValueInput) {
                elements.rValueInput.value = defaultLimits.default;
                elements.rValueInput.min = defaultLimits.min;
                elements.rValueInput.max = defaultLimits.max;
            }
            // Ukryj grupę kąta (domyślnie 'round')
            updateAngleButtons();
            return;
        }

        try {
            const edges = JSON.parse(savedData);

            // Przywróć stan z zapisanych danych formularza
            edges.forEach(edge => {
                state.selectedEdges.add(edge.letter);
            });

            // Przywróć typ i promień R
            state.edgeType = savedType || 'round';
            state.rValue = parseInt(savedRValue) || 5;

            // Przywróć kąt fazowania
            if (savedAngleValue && state.edgeType === 'chamfer') {
                state.angleValue = parseInt(savedAngleValue);
            } else {
                state.angleValue = null;
            }

            // Aktualizuj UI kontrolek
            if (elements.typeSelect) elements.typeSelect.value = state.edgeType;
            if (elements.rValueInput) elements.rValueInput.value = state.rValue;

            // Aktualizuj limity R dla wybranego typu
            const limits = CONFIG.R_LIMITS[state.edgeType];
            if (limits && elements.rValueInput) {
                elements.rValueInput.min = limits.min;
                elements.rValueInput.max = limits.max;
            }

            // Aktualizuj select kąta
            updateAngleButtons();

            // Zaznacz checkboxy zgodnie z zapisanym stanem
            // (SVG będzie aktualizowany przez generateProportionalSVG później)
            elements.checkboxes.forEach(cb => {
                const item = cb.closest('.edges-item');
                const edge = item.dataset.edge;
                const isSelected = state.selectedEdges.has(edge);

                cb.checked = isSelected;
                item.classList.toggle('selected', isSelected);
            });


        } catch (e) {
            console.error('EdgesModule: Błąd wczytywania zapisanego stanu:', e);
        }
    }

    // ==========================================
    // PRZELICZANIE KRAWĘDZI PO ZMIANIE WYMIARÓW
    // ==========================================

    /**
     * Przelicza cenę krawędzi dla formularza po zmianie wymiarów
     * Wywoływane gdy użytkownik zmienia wymiary produktu
     */
    function recalculateEdgesForForm(form) {
        if (!form) return;

        const savedData = form.dataset.edgesData;
        if (!savedData) return; // Brak zapisanych krawędzi - nic do przeliczenia

        // Pobierz aktualne wymiary z formularza
        const lengthInput = form.querySelector('input[data-field="length"]');
        const widthInput = form.querySelector('input[data-field="width"]');
        const thicknessInput = form.querySelector('input[data-field="thickness"]');
        const quantityInput = form.querySelector('input[data-field="quantity"]');

        const dimensions = {
            length: parseFloat(lengthInput?.value) || 0,
            width: parseFloat(widthInput?.value) || 0,
            thickness: parseFloat(thicknessInput?.value) || 0
        };

        // Pobierz ilość sztuk
        const quantity = parseInt(quantityInput?.value) || 1;

        // Jeśli brak wymiarów, nie przeliczaj
        if (dimensions.length <= 0 || dimensions.width <= 0 || dimensions.thickness <= 0) {
            return;
        }

        try {
            const edges = JSON.parse(savedData);
            const edgeType = form.dataset.edgesType || 'round';
            const rValue = parseInt(form.dataset.edgesRValue) || 5;

            // Pobierz ceny dla zapisanego typu obróbki
            const pricePerMb = getPricePerMb(edgeType);
            const pricePerCorner = getPricePerCorner(edgeType);

            let totalNetto = 0;
            const updatedEdgesData = [];

            const formShape = form.dataset.productShape || 'rectangular';

            edges.forEach(edge => {
                if (_isRoundShape(formShape)) {
                    // Krawędzie obwodowe dla kształtu okrągłego
                    const def = ROUND_EDGES[edge.letter];
                    if (!def) return;

                    const perimeterCm = calculateEllipsePerimeterCm(dimensions.length, dimensions.width);
                    const perimeterMm = perimeterCm * 10;
                    const priceNetto = (perimeterCm / 100) * pricePerMb;

                    totalNetto += priceNetto;

                    updatedEdgesData.push({
                        letter: edge.letter,
                        type: edgeType,
                        r_value: rValue,
                        length_mm: Math.round(perimeterMm * 100) / 100,
                        length_cm: Math.round(perimeterCm * 100) / 100,
                        is_corner: false,
                        is_round_perimeter: true,
                        price_netto: Math.round(priceNetto * 100) / 100,
                        price_brutto: Math.round(priceNetto * CONFIG.VAT_RATE * 100) / 100
                    });
                } else {
                    // Standardowe krawędzie prostokątne
                    const def = EDGES[edge.letter];
                    if (!def) return;

                    const lengthCm = dimensions[def.dimension] || 0;
                    const lengthMm = lengthCm * 10;

                    let priceNetto = 0;
                    if (def.group === 'corner') {
                        priceNetto = pricePerCorner;
                    } else {
                        priceNetto = (lengthCm / 100) * pricePerMb;
                    }

                    totalNetto += priceNetto;

                    updatedEdgesData.push({
                        letter: edge.letter,
                        type: edgeType,
                        r_value: rValue,
                        length_mm: lengthMm,
                        length_cm: lengthCm,
                        is_corner: def.group === 'corner',
                        price_netto: Math.round(priceNetto * 100) / 100,
                        price_brutto: Math.round(priceNetto * CONFIG.VAT_RATE * 100) / 100
                    });
                }
            });

            const totalBrutto = totalNetto * CONFIG.VAT_RATE;

            // Pomnóż przez ilość sztuk
            const totalNettoWithQuantity = Math.round(totalNetto * quantity * 100) / 100;
            const totalBruttoWithQuantity = Math.round(totalBrutto * quantity * 100) / 100;

            // Zaktualizuj dataset formularza (ceny już pomnożone przez ilość sztuk)
            form.dataset.edgesData = JSON.stringify(updatedEdgesData);
            form.dataset.edgesNetto = totalNettoWithQuantity;
            form.dataset.edgesBrutto = totalBruttoWithQuantity;
            form.dataset.edgesQuantity = quantity;

            // Zaktualizuj wizualne podsumowanie (pokazuj cenę łączną z uwzględnieniem ilości)
            const optionsSummary = form.querySelector('.edges-options-summary');
            const edgesRow = optionsSummary?.querySelector('.edges-row');

            if (edgesRow) {
                const textEl = edgesRow.querySelector('.edges-summary-text');
                const priceEl = edgesRow.querySelector('.edges-summary-price');
                let priceNettoEl = edgesRow.querySelector('.edges-summary-price-netto');

                // Jeśli element netto nie istnieje, utwórz go dynamicznie
                if (!priceNettoEl) {
                    const content = edgesRow.querySelector('.options-summary-content');
                    if (content) {
                        priceNettoEl = document.createElement('span');
                        priceNettoEl.className = 'options-summary-price-netto edges-summary-price-netto';
                        content.appendChild(priceNettoEl);
                    }
                }

                // Pokazuj cenę łączną (pomnożoną przez ilość sztuk)
                if (priceEl) {
                    priceEl.textContent = formatPLN(totalBruttoWithQuantity) + ' brutto';
                }
                if (priceNettoEl) {
                    priceNettoEl.textContent = formatPLN(totalNettoWithQuantity) + ' netto';
                }
            }

            // Wywołaj aktualizację globalnego podsumowania
            if (typeof updateGlobalSummary === 'function') {
                updateGlobalSummary();
            }


        } catch (e) {
            console.error('[EdgesModule] Błąd przeliczania krawędzi:', e);
        }
    }

    // ==========================================
    // KSZTAŁT OKRĄGŁY - UI
    // ==========================================

    /**
     * Przełącza modal na tryb krawędzi okrągłych (2 krawędzie obwodowe)
     */
    function showRoundEdgesUI() {
        const modal = elements.modal;
        if (!modal) return;

        // Ukryj standardowe sekcje krawędzi prostokąta
        modal.querySelectorAll('.edges-section').forEach(section => {
            section.style.display = 'none';
        });

        // Pokaż lub utwórz sekcję krawędzi okrągłych
        let roundSection = modal.querySelector('.edges-round-section');
        if (!roundSection) {
            roundSection = document.createElement('div');
            roundSection.className = 'edges-section edges-round-section';

            const perimeterCm = calculateEllipsePerimeterCm(
                state.dimensions.length, state.dimensions.width
            );

            roundSection.innerHTML = `
                <h4>Krawędzie obwodowe (kształt okrągły)</h4>
                <div class="edges-list">
                    <div class="edges-item edges-round-item" data-edge="KG">
                        <label class="edges-checkbox">
                            <input type="checkbox" name="edge_KG">
                            <span class="edges-letter">KG</span>
                            <span class="edges-name">Krawędź górna</span>
                            <span class="edges-length edges-round-length" data-round-edge="KG">(${perimeterCm.toFixed(1)} cm)</span>
                        </label>
                    </div>
                    <div class="edges-item edges-round-item" data-edge="KD">
                        <label class="edges-checkbox">
                            <input type="checkbox" name="edge_KD">
                            <span class="edges-letter">KD</span>
                            <span class="edges-name">Krawędź dolna</span>
                            <span class="edges-length edges-round-length" data-round-edge="KD">(${perimeterCm.toFixed(1)} cm)</span>
                        </label>
                    </div>
                </div>
            `;

            // Wstaw przed stopką modalu
            const body = modal.querySelector('.edges-modal-body');
            if (body) body.appendChild(roundSection);

            // Dodaj event listenery na checkboxy
            roundSection.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.addEventListener('change', function () {
                    const edgeLetter = this.closest('.edges-item').dataset.edge;
                    if (this.checked) {
                        state.selectedEdges.add(edgeLetter);
                        this.closest('.edges-item').classList.add('selected');
                    } else {
                        state.selectedEdges.delete(edgeLetter);
                        this.closest('.edges-item').classList.remove('selected');
                    }
                    // Aktualizuj SVG
                    updateRoundSvgHighlights();
                    calculatePrice();
                });
            });
        } else {
            roundSection.style.display = 'block';
            // Zaktualizuj długości obwodu
            const perimeterCm = calculateEllipsePerimeterCm(
                state.dimensions.length, state.dimensions.width
            );
            roundSection.querySelectorAll('.edges-round-length').forEach(el => {
                el.textContent = `(${perimeterCm.toFixed(1)} cm)`;
            });
        }

        // Synchronizuj checkboxy z state.selectedEdges
        roundSection.querySelectorAll('.edges-item').forEach(item => {
            const edgeLetter = item.dataset.edge;
            const cb = item.querySelector('input[type="checkbox"]');
            if (cb) {
                cb.checked = state.selectedEdges.has(edgeLetter);
                item.classList.toggle('selected', state.selectedEdges.has(edgeLetter));
            }
        });

        // Zmień szybkie akcje
        const quickBtns = modal.querySelectorAll('.edges-quick-btn');
        quickBtns.forEach(btn => {
            const action = btn.dataset.action;
            if (action === 'select-top') {
                btn.textContent = 'Góra';
                btn.dataset.roundAction = 'select-rt';
            } else if (action === 'select-bottom') {
                btn.textContent = 'Dół';
                btn.dataset.roundAction = 'select-rb';
            } else if (action === 'select-all') {
                btn.textContent = 'Oba';
            }
            // 'deselect-all' pozostaje bez zmian
        });
    }

    /**
     * Dynamiczny UI krawędzi G/D/P dla kształtów nieregularnych
     */
    function showDynamicEdgesUI(shapeData, thickness) {
        var modal = elements.modal;
        if (!modal) return;

        // Ukryj standardowe sekcje prostokątne
        modal.querySelectorAll('.edges-section').forEach(function(section) {
            section.style.display = 'none';
        });

        // Ukryj sekcję okrągłą
        var roundSection = modal.querySelector('.edges-round-section');
        if (roundSection) roundSection.style.display = 'none';

        // Usuń wcześniej wygenerowaną sekcję dynamiczną
        var existingDynamic = modal.querySelector('.edges-dynamic-section');
        if (existingDynamic) existingDynamic.remove();

        // Wygeneruj definicje krawędzi z ShapeGeometry
        var vertices = shapeData.vertices;
        if (!vertices || vertices.length < 3) return;

        var n = vertices.length;
        var edges = [];

        // Krawędzie górne G1-GN
        for (var i = 0; i < n; i++) {
            var j = (i + 1) % n;
            var dx = vertices[j][0] - vertices[i][0];
            var dy = vertices[j][1] - vertices[i][1];
            var len = Math.sqrt(dx * dx + dy * dy);
            edges.push({ id: 'G' + (i + 1), group: 'top', name: 'Góra ' + (i + 1), length: len });
        }
        // Krawędzie dolne D1-DN
        for (var i2 = 0; i2 < n; i2++) {
            var j2 = (i2 + 1) % n;
            var dx2 = vertices[j2][0] - vertices[i2][0];
            var dy2 = vertices[j2][1] - vertices[i2][1];
            var len2 = Math.sqrt(dx2 * dx2 + dy2 * dy2);
            edges.push({ id: 'D' + (i2 + 1), group: 'bottom', name: 'Dół ' + (i2 + 1), length: len2 });
        }
        // Krawędzie pionowe P1-PN
        for (var i3 = 0; i3 < n; i3++) {
            edges.push({ id: 'P' + (i3 + 1), group: 'vertical', name: 'Pion ' + (i3 + 1), length: thickness });
        }

        // Zapisz definicje do state (do calculatePrice)
        state.dynamicEdgeDefs = {};
        for (var ei = 0; ei < edges.length; ei++) {
            state.dynamicEdgeDefs[edges[ei].id] = {
                length_cm: edges[ei].length,
                group: edges[ei].group
            };
        }

        // Buduj HTML
        var html = '<div class="edges-section edges-dynamic-section">';

        // Grupa: Góra
        html += '<div class="edges-group"><h5>GÓRA</h5><div class="edges-list">';
        for (var g = 0; g < edges.length; g++) {
            if (edges[g].group !== 'top') continue;
            var e = edges[g];
            var lenStr = (Math.round(e.length * 10) / 10);
            html += '<div class="edges-item" data-edge="' + e.id + '">' +
                '<label class="edges-checkbox">' +
                '<input type="checkbox" name="edge_' + e.id + '">' +
                '<span class="edges-letter">' + e.id + '</span>' +
                '<span class="edges-name">' + e.name + '</span>' +
                '<span class="edges-length">(' + lenStr + ' cm)</span>' +
                '</label></div>';
        }
        html += '</div></div>';

        // Grupa: Dół
        html += '<div class="edges-group"><h5>DÓŁ</h5><div class="edges-list">';
        for (var d = 0; d < edges.length; d++) {
            if (edges[d].group !== 'bottom') continue;
            var ed = edges[d];
            var lenStr2 = (Math.round(ed.length * 10) / 10);
            html += '<div class="edges-item" data-edge="' + ed.id + '">' +
                '<label class="edges-checkbox">' +
                '<input type="checkbox" name="edge_' + ed.id + '">' +
                '<span class="edges-letter">' + ed.id + '</span>' +
                '<span class="edges-name">' + ed.name + '</span>' +
                '<span class="edges-length">(' + lenStr2 + ' cm)</span>' +
                '</label></div>';
        }
        html += '</div></div>';

        // Grupa: Pionowe
        html += '<div class="edges-group"><h5>PIONOWE</h5><div class="edges-list">';
        for (var p = 0; p < edges.length; p++) {
            if (edges[p].group !== 'vertical') continue;
            var ep = edges[p];
            var lenStr3 = (Math.round(ep.length * 10) / 10);
            html += '<div class="edges-item edges-corner-item" data-edge="' + ep.id + '">' +
                '<label class="edges-checkbox">' +
                '<input type="checkbox" name="edge_' + ep.id + '">' +
                '<span class="edges-letter edges-letter-corner">' + ep.id + '</span>' +
                '<span class="edges-name">' + ep.name + '</span>' +
                '<span class="edges-length">(' + lenStr3 + ' cm)</span>' +
                '</label></div>';
        }
        html += '</div></div>';

        html += '</div>';

        // Wstaw do modalu (po edges-top-section)
        var topSection = modal.querySelector('.edges-top-section');
        if (topSection) {
            topSection.insertAdjacentHTML('afterend', html);
        }

        // Podepnij event listenery do nowych checkboxów
        var dynamicSection = modal.querySelector('.edges-dynamic-section');
        if (dynamicSection) {
            dynamicSection.querySelectorAll('.edges-item').forEach(function(item) {
                var edgeId = item.dataset.edge;
                var checkbox = item.querySelector('input[type="checkbox"]');
                if (!checkbox) return;

                // Ustaw stan z aktualnie wybranych krawędzi
                checkbox.checked = state.selectedEdges.has(edgeId);
                if (checkbox.checked) item.classList.add('active');

                checkbox.addEventListener('change', function() {
                    if (this.checked) {
                        state.selectedEdges.add(edgeId);
                        item.classList.add('active');
                    } else {
                        state.selectedEdges.delete(edgeId);
                        item.classList.remove('active');
                    }
                    updateSvgEdge(edgeId, this.checked);
                    calculatePrice();
                });

                // Kliknięcie na całą etykietę w SVG
                item.addEventListener('mouseenter', function() {
                    highlightEdge(edgeId, true);
                });
                item.addEventListener('mouseleave', function() {
                    highlightEdge(edgeId, false);
                });
            });
        }

        // Szybkie akcje
        var quickBtns = modal.querySelectorAll('.edges-quick-btn');
        quickBtns.forEach(function(btn) {
            var action = btn.dataset.action;
            if (action === 'select-top') btn.textContent = 'Góra';
            else if (action === 'select-bottom') btn.textContent = 'Dół';
            else if (action === 'select-all') btn.textContent = 'Wszystkie';
        });
    }

    /**
     * Przywraca standardowy widok krawędzi prostokątnych
     */
    function showRectangularEdgesUI() {
        const modal = elements.modal;
        if (!modal) return;

        // Pokaż standardowe sekcje
        modal.querySelectorAll('.edges-section').forEach(section => {
            if (!section.classList.contains('edges-round-section')) {
                section.style.display = '';
            }
        });

        // Ukryj sekcję okrągłą (jeśli istnieje)
        const roundSection = modal.querySelector('.edges-round-section');
        if (roundSection) roundSection.style.display = 'none';

        // Przywróć szybkie akcje
        const quickBtns = modal.querySelectorAll('.edges-quick-btn');
        quickBtns.forEach(btn => {
            const action = btn.dataset.action;
            if (action === 'select-top') btn.textContent = 'Góra';
            else if (action === 'select-bottom') btn.textContent = 'Dół';
            else if (action === 'select-all') btn.textContent = 'Wszystkie';
            delete btn.dataset.roundAction;
        });
    }

    /**
     * Aktualizuje podświetlenie SVG dla krawędzi okrągłych
     */
    function updateRoundSvgHighlights() {
        const svg = elements.svg;
        if (!svg) return;

        const topEdge = svg.querySelector('[data-edge="KG"]');
        const bottomEdge = svg.querySelector('[data-edge="KD"]');

        if (topEdge) {
            topEdge.classList.toggle('active', state.selectedEdges.has('KG'));
        }
        if (bottomEdge) {
            bottomEdge.classList.toggle('active', state.selectedEdges.has('KD'));
        }
    }

    /**
     * Generuje izometryczny SVG owalnego produktu z 2 krawędziami (KG, KD)
     */
    function generateRoundSVG(L, W, T) {
        const svg = elements.svg;
        if (!svg) return;

        // Oblicz proporcje
        const maxDim = Math.max(L, W, T, 1);
        const scale = 200 / maxDim;
        const sL = Math.max(L * scale, 30);
        const sW = Math.max(W * scale, 20);
        const sT = Math.max(T * scale * 0.3, 8);

        // Środek SVG
        const cx = 160, cy = 100;

        // Izometryczne promienie elipsy
        const rx = sL * 0.45;
        const ry = sW * 0.25;

        // Wyczyść SVG
        svg.innerHTML = '';
        svg.setAttribute('viewBox', '0 0 320 220');

        // Dolna elipsa (bottom face)
        const bottomEllipse = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
        bottomEllipse.setAttribute('cx', cx);
        bottomEllipse.setAttribute('cy', cy + sT);
        bottomEllipse.setAttribute('rx', rx);
        bottomEllipse.setAttribute('ry', ry);
        bottomEllipse.setAttribute('class', 'edges-face edges-face-front');
        svg.appendChild(bottomEllipse);

        // Boki (pasek boczny) - path łączący górną i dolną elipsę
        const sidePath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        sidePath.setAttribute('d',
            `M${cx - rx},${cy} ` +
            `A${rx},${ry} 0 0,0 ${cx + rx},${cy} ` +
            `L${cx + rx},${cy + sT} ` +
            `A${rx},${ry} 0 0,1 ${cx - rx},${cy + sT} Z`
        );
        sidePath.setAttribute('class', 'edges-face edges-face-right');
        svg.appendChild(sidePath);

        // Górna elipsa (top face)
        const topEllipse = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
        topEllipse.setAttribute('cx', cx);
        topEllipse.setAttribute('cy', cy);
        topEllipse.setAttribute('rx', rx);
        topEllipse.setAttribute('ry', ry);
        topEllipse.setAttribute('class', 'edges-face edges-face-top');
        svg.appendChild(topEllipse);

        // Krawędź dolna (KD) - dolna pół-elipsa (renderowana przed KG, żeby była pod nią)
        const bottomEdge = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const bottomD = `M${cx - rx},${cy + sT} A${rx},${ry} 0 0,0 ${cx + rx},${cy + sT}`;
        bottomEdge.setAttribute('d', bottomD);
        bottomEdge.setAttribute('fill', 'none');
        bottomEdge.setAttribute('stroke-width', '3');
        bottomEdge.setAttribute('data-edge', 'KD');
        bottomEdge.setAttribute('class', 'edges-line' + (state.selectedEdges.has('KD') ? ' active' : ''));
        svg.appendChild(bottomEdge);

        // Krawędź górna (KG) - elipsa obwodowa (na wierzchu)
        const topEdge = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
        topEdge.setAttribute('cx', cx);
        topEdge.setAttribute('cy', cy);
        topEdge.setAttribute('rx', rx);
        topEdge.setAttribute('ry', ry);
        topEdge.setAttribute('fill', 'none');
        topEdge.setAttribute('stroke-width', '3');
        topEdge.setAttribute('data-edge', 'KG');
        topEdge.setAttribute('class', 'edges-line' + (state.selectedEdges.has('KG') ? ' active' : ''));
        svg.appendChild(topEdge);

        // Linie boczne (krawędzie pionowe łączące)
        const leftLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        leftLine.setAttribute('x1', cx - rx); leftLine.setAttribute('y1', cy);
        leftLine.setAttribute('x2', cx - rx); leftLine.setAttribute('y2', cy + sT);
        leftLine.setAttribute('class', 'edges-line');
        svg.appendChild(leftLine);

        const rightLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        rightLine.setAttribute('x1', cx + rx); rightLine.setAttribute('y1', cy);
        rightLine.setAttribute('x2', cx + rx); rightLine.setAttribute('y2', cy + sT);
        rightLine.setAttribute('class', 'edges-line');
        svg.appendChild(rightLine);

        // Etykiety
        if (state.labelsVisible) {
            const labelsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            labelsGroup.setAttribute('id', 'edgeLabelsGroup');
            labelsGroup.setAttribute('class', 'edges-labels');

            // Etykieta KG (góra)
            const kgLabel = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            kgLabel.setAttribute('class', 'edges-label');
            kgLabel.setAttribute('data-edge', 'KG');
            const kgCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            kgCircle.setAttribute('cx', cx); kgCircle.setAttribute('cy', cy - ry - 18);
            kgCircle.setAttribute('r', '14');
            const kgText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            kgText.setAttribute('x', cx); kgText.setAttribute('y', cy - ry - 14);
            kgText.textContent = 'KG';
            kgLabel.appendChild(kgCircle);
            kgLabel.appendChild(kgText);
            labelsGroup.appendChild(kgLabel);

            // Etykieta KD (dół)
            const kdLabel = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            kdLabel.setAttribute('class', 'edges-label');
            kdLabel.setAttribute('data-edge', 'KD');
            const kdCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            kdCircle.setAttribute('cx', cx); kdCircle.setAttribute('cy', cy + sT + ry + 18);
            kdCircle.setAttribute('r', '14');
            const kdText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            kdText.setAttribute('x', cx); kdText.setAttribute('y', cy + sT + ry + 22);
            kdText.textContent = 'KD';
            kdLabel.appendChild(kdCircle);
            kdLabel.appendChild(kdText);
            labelsGroup.appendChild(kdLabel);

            svg.appendChild(labelsGroup);
        }

        // Przypisz event listenery (klikanie w krawędzie i etykiety na SVG)
        attachSvgEventListeners();
    }

    // ==========================================
    // PODGLĄD SVG W SEKCJI KRAWĘDZI
    // ==========================================

    /**
     * Generuje podgląd SVG krawędzi (bez etykiet, bez interakcji)
     * @param {HTMLElement} form - formularz produktu
     */
    function updateEdgesPreview(form) {
        if (!form) return;

        const svgEl = form.querySelector('.edges-preview-svg');
        if (!svgEl) return;

        const lengthVal = parseFloat(form.querySelector('[data-field="length"]')?.value) || 100;
        const widthVal = parseFloat(form.querySelector('[data-field="width"]')?.value) || 50;
        const thicknessVal = parseFloat(form.querySelector('[data-field="thickness"]')?.value) || 4;

        // Pobierz aktywne krawędzie z dataset formularza
        let activeEdges = new Set();
        try {
            const edgesData = JSON.parse(form.dataset.edgesData || '[]');
            edgesData.forEach(e => activeEdges.add(e.letter));
        } catch (err) { /* brak danych */ }

        const shape = form.dataset.productShape || 'rectangular';

        if (_isRoundShape(shape)) {
            generateRoundPreviewSVG(svgEl, lengthVal, widthVal, thicknessVal, activeEdges);
        } else if (shape !== 'rectangular' && form._shapeEditor) {
            // Nieregularny kształt — renderuj z wierzchołków
            var shapeData = form._shapeEditor.getShapeData();
            generateShapePreviewSVG(svgEl, shapeData, thicknessVal, activeEdges, shape);
        } else {
            generateRectPreviewSVG(svgEl, lengthVal, widthVal, thicknessVal, activeEdges);
        }
    }

    function generateRectPreviewSVG(svgEl, length, width, thickness, activeEdges) {
        const viewBoxWidth = 320;
        const viewBoxHeight = 220;
        const margin = 20;

        const workWidth = viewBoxWidth - 2 * margin;
        const workHeight = viewBoxHeight - 2 * margin;

        const isoAngle = Math.PI / 6;
        const maxDim = Math.max(length, width);
        const effectiveThickness = Math.max(thickness, maxDim * 0.15);

        const projectedWidth = (length + width) * Math.cos(isoAngle);
        const projectedHeight = (length + width) * Math.sin(isoAngle) + effectiveThickness;

        const scale = Math.min(workWidth / projectedWidth, workHeight / projectedHeight) * 0.85;

        const L = length * scale;
        const W = width * scale;
        const T = effectiveThickness * scale;

        const vecX = { x: Math.cos(isoAngle), y: Math.sin(isoAngle) };
        const vecY = { x: -Math.cos(isoAngle), y: Math.sin(isoAngle) };

        const totalProjWidth = L * vecX.x + W * Math.abs(vecY.x);
        const totalProjHeight = L * vecX.y + W * vecY.y + T;

        const startX = (viewBoxWidth - totalProjWidth) / 2 + W * Math.abs(vecY.x);
        const startY = (viewBoxHeight - totalProjHeight) / 2 + T;

        // 8 wierzchołków
        const pTLD = { x: startX, y: startY };
        const pTPD = { x: pTLD.x + L * vecX.x, y: pTLD.y + L * vecX.y };
        const pPPD = { x: pTPD.x + W * vecY.x, y: pTPD.y + W * vecY.y };
        const pPLD = { x: pTLD.x + W * vecY.x, y: pTLD.y + W * vecY.y };
        const pTLG = { x: pTLD.x, y: pTLD.y - T };
        const pTPG = { x: pTPD.x, y: pTPD.y - T };
        const pPPG = { x: pPPD.x, y: pPPD.y - T };
        const pPLG = { x: pPLD.x, y: pPLD.y - T };

        const ec = (edge) => activeEdges.has(edge) ? 'active' : '';

        svgEl.innerHTML = `
            <polygon class="edges-face edges-face-back" points="${pTLD.x},${pTLD.y} ${pTPD.x},${pTPD.y} ${pTPG.x},${pTPG.y} ${pTLG.x},${pTLG.y}"/>
            <polygon class="edges-face edges-face-left" points="${pTLD.x},${pTLD.y} ${pPLD.x},${pPLD.y} ${pPLG.x},${pPLG.y} ${pTLG.x},${pTLG.y}"/>
            <polygon class="edges-face edges-face-top" points="${pTLG.x},${pTLG.y} ${pTPG.x},${pTPG.y} ${pPPG.x},${pPPG.y} ${pPLG.x},${pPLG.y}"/>
            <polygon class="edges-face edges-face-front" points="${pPLD.x},${pPLD.y} ${pPPD.x},${pPPD.y} ${pPPG.x},${pPPG.y} ${pPLG.x},${pPLG.y}"/>
            <polygon class="edges-face edges-face-right" points="${pTPD.x},${pTPD.y} ${pPPD.x},${pPPD.y} ${pPPG.x},${pPPG.y} ${pTPG.x},${pTPG.y}"/>
            <line class="edges-line edges-hidden ${ec('F')}" data-edge="F" x1="${pTLD.x}" y1="${pTLD.y}" x2="${pTPD.x}" y2="${pTPD.y}"/>
            <line class="edges-line edges-hidden ${ec('G')}" data-edge="G" x1="${pTLD.x}" y1="${pTLD.y}" x2="${pPLD.x}" y2="${pPLD.y}"/>
            <line class="edges-line edges-hidden edges-corner ${ec('N3')}" data-edge="N3" x1="${pTLG.x}" y1="${pTLG.y}" x2="${pTLD.x}" y2="${pTLD.y}"/>
            <line class="edges-line ${ec('A')}" data-edge="A" x1="${pPLG.x}" y1="${pPLG.y}" x2="${pPPG.x}" y2="${pPPG.y}"/>
            <line class="edges-line ${ec('B')}" data-edge="B" x1="${pTLG.x}" y1="${pTLG.y}" x2="${pTPG.x}" y2="${pTPG.y}"/>
            <line class="edges-line ${ec('C')}" data-edge="C" x1="${pTLG.x}" y1="${pTLG.y}" x2="${pPLG.x}" y2="${pPLG.y}"/>
            <line class="edges-line ${ec('D')}" data-edge="D" x1="${pTPG.x}" y1="${pTPG.y}" x2="${pPPG.x}" y2="${pPPG.y}"/>
            <line class="edges-line ${ec('E')}" data-edge="E" x1="${pPLD.x}" y1="${pPLD.y}" x2="${pPPD.x}" y2="${pPPD.y}"/>
            <line class="edges-line ${ec('H')}" data-edge="H" x1="${pTPD.x}" y1="${pTPD.y}" x2="${pPPD.x}" y2="${pPPD.y}"/>
            <line class="edges-line edges-corner ${ec('N1')}" data-edge="N1" x1="${pPLG.x}" y1="${pPLG.y}" x2="${pPLD.x}" y2="${pPLD.y}"/>
            <line class="edges-line edges-corner ${ec('N2')}" data-edge="N2" x1="${pPPG.x}" y1="${pPPG.y}" x2="${pPPD.x}" y2="${pPPD.y}"/>
            <line class="edges-line edges-corner ${ec('N4')}" data-edge="N4" x1="${pTPG.x}" y1="${pTPG.y}" x2="${pTPD.x}" y2="${pTPD.y}"/>
        `;
    }

    function generateRoundPreviewSVG(svgEl, length, width, thickness, activeEdges) {
        const maxDim = Math.max(length, width, thickness, 1);
        const scale = 200 / maxDim;
        const sL = Math.max(length * scale, 30);
        const sW = Math.max(width * scale, 20);
        const sT = Math.max(thickness * scale * 0.3, 8);

        const cx = 160, cy = 100;
        const rx = sL * 0.45;
        const ry = sW * 0.25;

        const ecKG = activeEdges.has('KG') ? ' active' : '';
        const ecKD = activeEdges.has('KD') ? ' active' : '';

        svgEl.innerHTML = `
            <ellipse class="edges-face edges-face-front" cx="${cx}" cy="${cy + sT}" rx="${rx}" ry="${ry}"/>
            <path class="edges-face edges-face-right" d="M${cx - rx},${cy} A${rx},${ry} 0 0,0 ${cx + rx},${cy} L${cx + rx},${cy + sT} A${rx},${ry} 0 0,1 ${cx - rx},${cy + sT} Z"/>
            <ellipse class="edges-face edges-face-top" cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}"/>
            <path class="edges-line${ecKD}" data-edge="KD" d="M${cx - rx},${cy + sT} A${rx},${ry} 0 0,0 ${cx + rx},${cy + sT}" fill="none"/>
            <ellipse class="edges-line${ecKG}" data-edge="KG" cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="none"/>
            <line class="edges-line" x1="${cx - rx}" y1="${cy}" x2="${cx - rx}" y2="${cy + sT}"/>
            <line class="edges-line" x1="${cx + rx}" y1="${cy}" x2="${cx + rx}" y2="${cy + sT}"/>
        `;
    }

    /**
     * Generuje podgląd SVG dla nieregularnych kształtów (trójkąt, trapez, wielokąt, równoległobok)
     * Widok izometryczny 3D z oznaczeniem krawędzi G/D/P
     */
    function generateShapePreviewSVG(svgEl, shapeData, thickness, activeEdges, shapeType) {
        if (!shapeData || !shapeData.vertices || shapeData.vertices.length < 3) {
            svgEl.innerHTML = '';
            return;
        }

        var verts = shapeData.vertices;
        var n = verts.length;
        var viewBoxWidth = 320;
        var viewBoxHeight = 220;
        var margin = 20;

        // Znajdź bbox wierzchołków
        var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (var i = 0; i < n; i++) {
            if (verts[i][0] < minX) minX = verts[i][0];
            if (verts[i][1] < minY) minY = verts[i][1];
            if (verts[i][0] > maxX) maxX = verts[i][0];
            if (verts[i][1] > maxY) maxY = verts[i][1];
        }
        var shapeW = maxX - minX || 1;
        var shapeH = maxY - minY || 1;

        // Projekcja 3D wzorowana na Illustrator 3D Extrude (42°, 16°, -14°)
        // Wektory definiują jak osie kształtu mapują na ekran (SVG: Y w dół)
        // vecShapeX: kształt X (prawo na canvasie) → ekran
        // vecShapeY: kształt Y (góra na canvasie) → ekran
        // vecZ: grubość → ekran (w dół)
        var vecShapeX = { x: 0.95, y: 0 };   // w prawo i lekko w dół
        var vecShapeY = { x: -0.36, y: -0.75 };  // lekko w lewo i do góry
        var vecZ = { x: 0.04, y: 0.65 };         // prawie prosto w dół (grubość)

        var effectiveThickness = Math.max(thickness, Math.max(shapeW, shapeH) * 0.15);

        var workWidth = viewBoxWidth - 2 * margin;
        var workHeight = viewBoxHeight - 2 * margin;

        // Oblicz bounding box projekcji do skalowania
        var testCorners = [
            [0, 0, 0], [shapeW, 0, 0], [0, shapeH, 0], [shapeW, shapeH, 0],
            [0, 0, effectiveThickness], [shapeW, 0, effectiveThickness],
            [0, shapeH, effectiveThickness], [shapeW, shapeH, effectiveThickness]
        ];
        var projMinX = Infinity, projMaxX = -Infinity, projMinY = Infinity, projMaxY = -Infinity;
        for (var ti = 0; ti < testCorners.length; ti++) {
            var tpx = testCorners[ti][0] * vecShapeX.x + testCorners[ti][1] * vecShapeY.x + testCorners[ti][2] * vecZ.x;
            var tpy = testCorners[ti][0] * vecShapeX.y + testCorners[ti][1] * vecShapeY.y + testCorners[ti][2] * vecZ.y;
            if (tpx < projMinX) projMinX = tpx;
            if (tpx > projMaxX) projMaxX = tpx;
            if (tpy < projMinY) projMinY = tpy;
            if (tpy > projMaxY) projMaxY = tpy;
        }
        var projW = projMaxX - projMinX || 1;
        var projH = projMaxY - projMinY || 1;
        var scale = Math.min(workWidth / projW, workHeight / projH) * 0.85;

        var T = effectiveThickness * scale;

        // Centrowanie
        var offsetX = (viewBoxWidth - projW * scale) / 2 - projMinX * scale;
        var offsetY = (viewBoxHeight - projH * scale) / 2 - projMinY * scale;

        // Projekcja 3D → 2D: Z=0 = górna powierzchnia, Z=thickness = dolna
        function project3D(px, py, pz) {
            var sx = (px - minX);
            var sy = (py - minY);
            return {
                x: offsetX + (sx * vecShapeX.x + sy * vecShapeY.x + pz * vecZ.x) * scale,
                y: offsetY + (sx * vecShapeX.y + sy * vecShapeY.y + pz * vecZ.y) * scale
            };
        }

        // Wierzchołki górnej (Z=thickness, bo góra to wyższa warstwa) i dolnej (Z=0) płaszczyzny
        var topPts = [];
        var botPts = [];
        for (var j = 0; j < n; j++) {
            var top = project3D(verts[j][0], verts[j][1], 0);
            var bot = project3D(verts[j][0], verts[j][1], effectiveThickness);
            topPts.push(top);
            botPts.push(bot);
        }

        // Renderuj SVG
        var svg = '';

        // Górna powierzchnia (wypełnienie)
        var topPolyPts = topPts.map(function(p) { return p.x + ',' + p.y; }).join(' ');
        svg += '<polygon class="edges-face edges-face-top" points="' + topPolyPts + '"/>';

        // Boczne ściany (łączą górę z dołem) — renderuj tylko widoczne
        for (var k = 0; k < n; k++) {
            var k2 = (k + 1) % n;
            var midX = (botPts[k].x + botPts[k2].x) / 2;
            // Prosta heurystyka widoczności: rysuj boki skierowane na "zewnątrz"
            var pts = [
                botPts[k].x + ',' + botPts[k].y,
                botPts[k2].x + ',' + botPts[k2].y,
                topPts[k2].x + ',' + topPts[k2].y,
                topPts[k].x + ',' + topPts[k].y
            ].join(' ');
            svg += '<polygon class="edges-face edges-face-front" points="' + pts + '" opacity="0.3"/>';
        }

        // Krawędzie górne (G1-GN)
        for (var g = 0; g < n; g++) {
            var g2 = (g + 1) % n;
            var edgeId = 'G' + (g + 1);
            var cls = 'edges-line' + (activeEdges.has(edgeId) ? ' active' : '');
            svg += '<line class="' + cls + '" data-edge="' + edgeId + '"' +
                ' x1="' + topPts[g].x + '" y1="' + topPts[g].y + '"' +
                ' x2="' + topPts[g2].x + '" y2="' + topPts[g2].y + '"/>';
        }

        // Krawędzie dolne (D1-DN) — przerywaną linią
        for (var d = 0; d < n; d++) {
            var d2 = (d + 1) % n;
            var dEdgeId = 'D' + (d + 1);
            var dCls = 'edges-line' + (activeEdges.has(dEdgeId) ? ' active' : '');
            svg += '<line class="' + dCls + '" data-edge="' + dEdgeId + '"' +
                ' x1="' + botPts[d].x + '" y1="' + botPts[d].y + '"' +
                ' x2="' + botPts[d2].x + '" y2="' + botPts[d2].y + '"/>';
        }

        // Krawędzie pionowe (P1-PN)
        for (var p = 0; p < n; p++) {
            var pEdgeId = 'P' + (p + 1);
            var pCls = 'edges-line edges-corner' + (activeEdges.has(pEdgeId) ? ' active' : '');
            svg += '<line class="' + pCls + '" data-edge="' + pEdgeId + '"' +
                ' x1="' + topPts[p].x + '" y1="' + topPts[p].y + '"' +
                ' x2="' + botPts[p].x + '" y2="' + botPts[p].y + '"/>';
        }

        // Etykiety z badge'ami (kółko + tekst) w grupie edgeLabelsGroup
        svg += '<g class="edges-labels" id="edgeLabelsGroup">';

        // Etykiety górnych krawędzi G1-GN
        for (var l = 0; l < n; l++) {
            var l2 = (l + 1) % n;
            var lx = (topPts[l].x + topPts[l2].x) / 2;
            var ly = (topPts[l].y + topPts[l2].y) / 2 - 8;
            var lEdgeId = 'G' + (l + 1);
            var lCls = activeEdges.has(lEdgeId) ? ' active' : '';
            svg += '<g class="edges-label' + lCls + '" data-edge="' + lEdgeId + '">';
            svg += '<circle cx="' + lx + '" cy="' + (ly - 2) + '" r="12"/>';
            svg += '<text x="' + lx + '" y="' + (ly + 2) + '">' + lEdgeId + '</text>';
            svg += '</g>';
        }

        // Etykiety dolnych krawędzi D1-DN
        for (var dl = 0; dl < n; dl++) {
            var dl2 = (dl + 1) % n;
            var dlx = (botPts[dl].x + botPts[dl2].x) / 2;
            var dly = (botPts[dl].y + botPts[dl2].y) / 2 + 8;
            var dlEdgeId = 'D' + (dl + 1);
            var dlCls = activeEdges.has(dlEdgeId) ? ' active' : '';
            svg += '<g class="edges-label' + dlCls + '" data-edge="' + dlEdgeId + '">';
            svg += '<circle cx="' + dlx + '" cy="' + (dly + 2) + '" r="12"/>';
            svg += '<text x="' + dlx + '" y="' + (dly + 6) + '">' + dlEdgeId + '</text>';
            svg += '</g>';
        }

        // Etykiety pionowych krawędzi P1-PN
        for (var pl = 0; pl < n; pl++) {
            var plx = (topPts[pl].x + botPts[pl].x) / 2 - 14;
            var ply = (topPts[pl].y + botPts[pl].y) / 2;
            var plEdgeId = 'P' + (pl + 1);
            var plCls = activeEdges.has(plEdgeId) ? ' active' : '';
            svg += '<g class="edges-label edges-label-corner' + plCls + '" data-edge="' + plEdgeId + '">';
            svg += '<circle cx="' + plx + '" cy="' + ply + '" r="12"/>';
            svg += '<text x="' + plx + '" y="' + (ply + 4) + '">' + plEdgeId + '</text>';
            svg += '</g>';
        }

        svg += '</g>';

        svgEl.innerHTML = svg;
    }

    // ==========================================
    // PUBLICZNE API
    // ==========================================

    return {
        init,
        openModal,
        closeModal,
        getState: () => ({ ...state }),
        getSelectedEdges: () => Array.from(state.selectedEdges),
        getEdgesData: (form) => {
            const data = form?.dataset?.edgesData;
            return data ? JSON.parse(data) : [];
        },
        getEdgesPrices: (form) => {
            return {
                netto: parseFloat(form?.dataset?.edgesNetto) || 0,
                brutto: parseFloat(form?.dataset?.edgesBrutto) || 0
            };
        },
        getEdgesSvg: (form) => {
            return form?.dataset?.edgesSvg || '';
        },
        reset: (form) => {
            state.currentForm = form;
            resetEdges();
        },
        // Aktualizacja stanu przycisku dla formularza
        updateButtonState,
        updateAllButtonStates,
        // Przeliczanie krawędzi po zmianie wymiarów
        recalculateEdgesForForm,
        // Podgląd SVG w sekcji krawędzi
        updateEdgesPreview,
        // Eksportuj konfigurację dla integracji z save_quote
        CONFIG,
        EDGES,
        ROUND_EDGES,
        EDGE_GROUPS
    };

})();

// Inicjalizuj po załadowaniu DOM lub natychmiast jeśli DOM już gotowy
(function initEdges() {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            setTimeout(function() {
                EdgesModule.init();
            }, 100);
        });
    } else {
        // DOM już załadowany
        setTimeout(function() {
            EdgesModule.init();
        }, 100);
    }
})();

// Eksportuj globalnie
window.EdgesModule = EdgesModule;
