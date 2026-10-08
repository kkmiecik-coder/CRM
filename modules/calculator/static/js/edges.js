/**
 * Moduł obróbki krawędzi dla kalkulatora WoodPower CRM
 * Wzorowany na woodconfigurator.js z PrestaShop
 */

const EdgesModule = (function() {
    'use strict';

    // ==========================================
    // KONFIGURACJA
    // ==========================================

    // Helper: sprawdza czy kształt jest okrągły (round, circle)
    function _isRoundShape(shape) {
        return shape === 'round' || shape === 'circle';
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
        dimensions: { length: 0, width: 0, thickness: 0 },
        labelsVisible: true,
        modalInitialized: false,
        productShape: 'rectangular', // 'rectangular' lub 'round'
        dynamicEdgeDefs: {},  // {G1: {length_cm: 80, group: 'top'}, D1: {...}, P1: {...}}

        // tabs
        activeTab: 'basic',  // 'basic' | 'advanced'

        // basic state (jak dotychczas)
        basic: {
            edgeType: 'round',
            rValue: 5,
            angleValue: null,         // Kąt fazowania (tylko dla chamfer)
            selectedEdges: new Set(),
        },

        // advanced state — Map<letter, {type, r_value, angle_value}>
        advanced: {
            edges: new Map(),
        },
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
        elements.tabsBar = modal.querySelector('.edges-tabs-bar');
        elements.tabBtns = modal.querySelectorAll('.edges-tab');
        elements.tabResetBtn = document.getElementById('edgesTabReset');
        elements.panelBasic = modal.querySelector('[data-panel="basic"]');
        elements.panelAdvanced = modal.querySelector('[data-panel="advanced"]');
        elements.basicDisabledBanner = document.getElementById('edgesBasicDisabledBanner');
        elements.advancedList = document.getElementById('edgesAdvancedList');
        elements.advancedImportBtn = document.getElementById('edgesAdvancedImport');
        elements.advancedBulkType = document.getElementById('edgesAdvancedBulkType');
        elements.advancedBulkR = document.getElementById('edgesAdvancedBulkR');
        elements.advancedBulkAngle = document.getElementById('edgesAdvancedBulkAngle');
        elements.advancedBulkApply = document.getElementById('edgesAdvancedBulkApply');
        elements.advancedVisualization = document.getElementById('edgesAdvancedVisualization');
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

        // Przycisk oczka w preview — toggle etykiet (globalny na wszystkich produktach)
        document.addEventListener('click', function(e) {
            var btn = e.target.closest('.edges-preview-toggle-labels');
            if (!btn) return;
            e.preventDefault();

            // Toggle globalny stan
            state.labelsVisible = !state.labelsVisible;

            // Aktualizuj wszystkie przyciski oczka i SVG we wszystkich produktach
            document.querySelectorAll('.edges-preview-toggle-labels').forEach(function(b) {
                b.classList.toggle('labels-hidden', !state.labelsVisible);
            });
            document.querySelectorAll('.edges-preview-svg .edges-labels').forEach(function(g) {
                g.classList.toggle('edges-labels-hidden', !state.labelsVisible);
            });
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
        // Event delegation dla inputów wymiarów — reset krawędzi przy zmianie
        document.addEventListener('input', function(e) {
            const input = e.target;
            if (input.matches('input[data-field="length"], input[data-field="width"], input[data-field="thickness"]')) {
                const form = input.closest('.quote-form');
                if (form) {
                    updateButtonState(form);
                    // Reset krawędzi — wymiary się zmieniły (prawdziwa zmiana pola)
                    if (form.dataset.edgesData) {
                        state.currentForm = form;
                        resetEdges();
                    }
                    // Topologia (zadanie 13: także narożniki z rysunku) po resecie
                    if (window.ShapeEdgesSync) window.ShapeEdgesSync.syncForm(form);
                }
            }
        });

        // Rysunek z Canvy wypełnia wymiary programowo (bez zdarzenia input, które kasowałoby
        // krawędzie) — stan przycisku „+ Dodaj” odświeżamy tu, bez resetu krawędzi
        document.addEventListener('shape:changed', function(e) {
            const form = e.target && e.target.closest ? e.target.closest('.quote-form') : null;
            if (form) updateButtonState(form);
        });

        // Reset krawędzi przy zmianie kształtu
        document.addEventListener('change', function(e) {
            var select = e.target;
            if (select.matches('[data-field="shapeSelect"]')) {
                var form = select.closest('.quote-form');
                if (form && form.dataset.edgesData) {
                    state.currentForm = form;
                    resetEdges();
                }
                if (form && window.ShapeEdgesSync) window.ShapeEdgesSync.syncForm(form);
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
                // Ręczny „Resetuj” = brak obróbki krawędzi, także narożników: pusty stan trafia
                // na rysunek (narożniki ostre), a wpisy odtwarzamy z niego. Inaczej narożnik
                // zostałby na rysunku bez opłaty, a następna synchronizacja i tak by go dopisała.
                // Reset z „Docięcie do wymiaru = Nie” (cut_to_size.js) rysunku nie rusza —
                // syncForm przy docięciu Nie nie zapisuje żadnych wpisów.
                if (form && window.ShapeEdgesSync && form.dataset.cutToSize !== 'false') {
                    const wynik = window.ShapeEdgesSync.pullCornersFromEdges(form);
                    window.ShapeEdgesSync.syncForm(form);
                    // Narożniki zmieniają pole kształtu — cena musi to zobaczyć
                    if (wynik.changed && typeof updatePrices === 'function') updatePrices();
                }
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

        // UWAGA: Event listenery dla SVG są dodawane w attachSvgEventListeners()
        // wywoływanym po każdym rysunku modalu (renderModalSvg)

        // Setup tabs (Podstawowy / Zaawansowany)
        setupTabs();
        // Setup akcje w Zaawansowanym (Import, Bulk apply)
        setupAdvancedActions();

        state.modalInitialized = true;
    }

    // ==========================================
    // TABS: Podstawowy / Zaawansowany
    // ==========================================

    function setupTabs() {
        if (!elements.tabBtns || !elements.tabBtns.length) return;
        elements.tabBtns.forEach(btn => {
            btn.addEventListener('click', () => switchTab(btn.dataset.tab));
        });
        if (elements.tabResetBtn) {
            elements.tabResetBtn.addEventListener('click', resetActiveTab);
        }
    }

    function switchTab(tabName) {
        if (state.activeTab === tabName) return;
        state.activeTab = tabName;
        elements.tabBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === tabName));
        if (elements.panelBasic) elements.panelBasic.style.display = (tabName === 'basic') ? '' : 'none';
        if (elements.panelAdvanced) elements.panelAdvanced.style.display = (tabName === 'advanced') ? '' : 'none';
        if (tabName === 'advanced') {
            renderAdvancedList();
            renderAdvancedVisualization();
        } else {
            refreshBasicDisabledState();
        }
    }

    function resetActiveTab() {
        if (state.activeTab === 'basic') {
            state.basic.selectedEdges.clear();
            state.basic.edgeType = 'round';
            state.basic.rValue = 5;
            state.basic.angleValue = null;
            // odśwież widok basic (uncheck checkboxes)
            if (elements.checkboxes) elements.checkboxes.forEach(cb => { cb.checked = false; });
            _odznaczPozycjeDynamiczne();
            if (elements.typeSelect) elements.typeSelect.value = 'round';
            if (elements.rValueInput) elements.rValueInput.value = 5;
            // Odśwież SVG (wyczyść aktywne podświetlenia)
            elements.svg && elements.svg.querySelectorAll('.edges-line.edges-line-active').forEach(l => l.classList.remove('edges-line-active'));
            if (typeof updateAngleButtons === 'function') updateAngleButtons();
            calculatePrice();
        } else {
            state.advanced.edges.clear();
            renderAdvancedList();
            renderAdvancedVisualization();
            updateAdvancedPrice();
        }
    }

    const BANER_MIESZANA = 'Konfiguracja zaawansowana zawiera różne typy/promienie. Zresetuj zakładkę „Zaawansowany”, aby pracować w Podstawowym.';
    const BANER_NAROZNIKI = 'Narożniki ustawione na rysunku kształtu edytujesz w zakładce „Zaawansowany”.';

    function refreshBasicDisabledState() {
        if (!elements.panelBasic || !elements.basicDisabledBanner) return;
        // Narożniki z rysunku mają własne wymiary — tryb podstawowy (jeden R dla wszystkiego) by je nadpisał
        let naroznikiZRysunku = false;
        try {
            naroznikiZRysunku = !!window.ShapeEdgesSync && JSON.parse(state.currentForm?.dataset.edgesData || '[]')
                .some(e => window.ShapeEdgesSync.isCornerLetter(e.letter));
        } catch (e) { naroznikiZRysunku = false; }
        if (advancedIsMixed() || naroznikiZRysunku) {
            elements.basicDisabledBanner.textContent = naroznikiZRysunku ? BANER_NAROZNIKI : BANER_MIESZANA;
            elements.panelBasic.classList.add('edges-basic-panel-disabled');
            elements.basicDisabledBanner.style.display = '';
        } else {
            elements.panelBasic.classList.remove('edges-basic-panel-disabled');
            elements.basicDisabledBanner.style.display = 'none';
        }
    }

    function advancedIsMixed() {
        const tuples = new Set();
        for (const [_, cfg] of state.advanced.edges) {
            if (cfg.type === 'sharp') continue;
            tuples.add(`${cfg.type}|${cfg.r_value}|${cfg.angle_value ?? ''}`);
            if (tuples.size > 1) return true;
        }
        return false;
    }

    // ==========================================
    // ZAAWANSOWANY — render per-edge + bulk apply
    // ==========================================

    function getActiveEdgeDefinitions() {
        // Wycięcia (H…) z rysunku — dla prostokąta i koła dochodzą do ich własnych liter
        const wyciecia = Object.entries(state.dynamicEdgeDefs)
            .filter(([letter]) => letter.charAt(0) === 'H')
            .map(([letter, def]) => ({ letter, name: def.name || letter, dimensionKey: 'dynamic', dynamicDef: def }));
        if (_isRoundShape(state.productShape)) {
            return [
                { letter: 'KG', name: 'Krawędź górna (obwód)', dimensionKey: 'perimeter' },
                { letter: 'KD', name: 'Krawędź dolna (obwód)', dimensionKey: 'perimeter' },
            ].concat(wyciecia);
        }
        if (state.productShape !== 'rectangular' && Object.keys(state.dynamicEdgeDefs).length > 0) {
            return Object.entries(state.dynamicEdgeDefs).map(([letter, def]) => ({
                letter, name: def.name || letter, dimensionKey: 'dynamic', dynamicDef: def,
            }));
        }
        // rectangular
        return Object.entries(EDGES).map(([letter, def]) => ({
            letter, name: def.name, dimensionKey: def.dimension,
        })).concat(wyciecia);
    }

    function computeEdgeLengthCm(def) {
        if (def.dimensionKey === 'perimeter') {
            return calculateEllipsePerimeterCm(state.dimensions.length, state.dimensions.width);
        }
        if (def.dimensionKey === 'dynamic') {
            return def.dynamicDef.length_cm || 0;
        }
        return state.dimensions[def.dimensionKey] || 0;
    }

    function computeEdgePrice(def, cfg, lengthCm) {
        if (cfg.type === 'sharp') return 0;
        const pricePerMb = getPricePerMb(cfg.type);
        const pricePerCorner = getPricePerCorner(cfg.type);
        const isCorner = (def.dimensionKey === 'thickness' || (def.dynamicDef && _jestNaroznikiem(def.dynamicDef.group)));
        return isCorner ? pricePerCorner : (lengthCm / 100) * pricePerMb;
    }

    function renderAngleOptions(selected) {
        const angles = (CONFIG.CHAMFER_ANGLES && CONFIG.CHAMFER_ANGLES.angles) || [45, 30, 60];
        return angles.map(a => `<option value="${a}"${a===selected?' selected':''}>${a}°</option>`).join('');
    }

    function renderAdvancedList() {
        const container = elements.advancedList;
        if (!container) return;
        container.innerHTML = '';

        const definitions = getActiveEdgeDefinitions();
        definitions.forEach(def => {
            const cfg = state.advanced.edges.get(def.letter) || { type: 'sharp', r_value: null, angle_value: null };
            const row = document.createElement('div');
            row.className = 'edges-advanced-row';
            row.dataset.edge = def.letter;

            const lengthCm = computeEdgeLengthCm(def);
            const price = computeEdgePrice(def, cfg, lengthCm);

            // Limity promienia R z konfiguracji (aktualizowane z bazy danych),
            // a nie zahardkodowane - aby widok zaawansowany respektował ustawienia.
            // Narożnik (pion): limit z geometrii rysunku; krawędzie poziome — z konfiguracji typu
            const naroznik = (def.dimensionKey === 'thickness' || (def.dynamicDef && _jestNaroznikiem(def.dynamicDef.group)));
            let rLimits = CONFIG.R_LIMITS[cfg.type] || CONFIG.R_LIMITS.round || { min: 3, max: 20, default: 5 };
            if (naroznik && window.ShapeEdgesSync && cfg.type !== 'sharp') {
                const maks = window.ShapeEdgesSync.maxForLetter(state.currentForm, def.letter, cfg.type);
                if (maks != null) rLimits = { min: 1, max: maks, default: Math.min(rLimits.default || 5, maks) };
            }

            row.innerHTML = `
                <span class="edge-letter">${def.letter}</span>
                <span class="edge-name">${def.name} <small>(${lengthCm.toFixed(1)} cm)</small></span>
                <select class="edge-type">
                    <option value="sharp"${cfg.type==='sharp'?' selected':''}>Ostra</option>
                    <option value="round"${cfg.type==='round'?' selected':''}>Zaokrąglenie</option>
                    <option value="chamfer"${cfg.type==='chamfer'?' selected':''}>Fazowanie</option>
                </select>
                <input class="edge-r" type="number" min="${rLimits.min}" max="${rLimits.max}" value="${cfg.r_value || rLimits.default || 5}" ${cfg.type==='sharp'?'disabled':''}>
                <select class="edge-angle" ${(cfg.type!=='chamfer' || naroznik)?'disabled':''}>
                    ${renderAngleOptions(cfg.angle_value)}
                </select>
                <span class="edge-price">${price.toFixed(2)} zł</span>
                <span></span>
            `;

            container.appendChild(row);

            row.querySelector('.edge-type').addEventListener('change', e => {
                onAdvancedRowChange(def.letter, { type: e.target.value });
            });
            row.querySelector('.edge-r').addEventListener('input', e => {
                onAdvancedRowChange(def.letter, { r_value: parseInt(e.target.value, 10) });
            });
            row.querySelector('.edge-angle').addEventListener('change', e => {
                onAdvancedRowChange(def.letter, { angle_value: parseInt(e.target.value, 10) });
            });
        });

        updateAdvancedPrice();
    }

    function onAdvancedRowChange(letter, patch) {
        const current = state.advanced.edges.get(letter) || { type: 'sharp', r_value: null, angle_value: null };
        const next = { ...current, ...patch };
        if (next.type === 'sharp') {
            state.advanced.edges.delete(letter);
        } else {
            if (!next.r_value) next.r_value = (next.type === 'round') ? 5 : 3;
            if (next.type !== 'chamfer') next.angle_value = null;
            else if (!next.angle_value) next.angle_value = 45;
            // Fazowanie narożnika w rzucie jest zawsze symetryczne — kąt 45°
            if (next.type === 'chamfer' && window.ShapeEdgesSync && window.ShapeEdgesSync.isCornerLetter(letter)) {
                next.angle_value = 45;
            }
            state.advanced.edges.set(letter, next);
        }
        renderAdvancedList();
        renderAdvancedVisualization();
    }

    function updateAdvancedPrice() {
        let total = 0;
        getActiveEdgeDefinitions().forEach(def => {
            const cfg = state.advanced.edges.get(def.letter);
            if (!cfg || cfg.type === 'sharp') return;
            total += computeEdgePrice(def, cfg, computeEdgeLengthCm(def));
        });
        const brutto = total * CONFIG.VAT_RATE;
        if (elements.priceBrutto) elements.priceBrutto.textContent = brutto.toFixed(2).replace('.', ',') + ' zł';
        if (elements.priceNetto) elements.priceNetto.textContent = '(' + total.toFixed(2).replace('.', ',') + ' zł netto)';
    }

    // Wizualizacja zakładki Zaawansowany: ten sam rysunek co w Podstawowym i w sekcji „Krawędzie”
    // (z wycięciami), krawędzie w kolorze typu z konfiguracji zaawansowanej: zielony = zaokrąglenie,
    // pomarańczowy = fazowanie, szary = ostra. Etykieta ustawionej krawędzi ma kolor jej linii.
    function renderAdvancedVisualization() {
        const container = elements.advancedVisualization;
        if (!container) return;
        container.innerHTML = '';
        if (!state.currentForm) return;
        const typKrawedzi = (letter) => state.advanced.edges.get(letter)?.type || 'sharp';
        const kolor = (type) => (type === 'round') ? '#2E7D32' : (type === 'chamfer') ? '#ED6B24' : '#cccccc';
        const ustawione = new Set();
        state.advanced.edges.forEach((cfg, letter) => { if (cfg.type !== 'sharp') ustawione.add(letter); });

        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', '0 0 320 220');
        svg.setAttribute('class', 'edges-interactive-svg');
        _drawEdgesFigure(svg, state.currentForm, ustawione);
        svg.querySelectorAll('.edges-line').forEach(line => {
            const type = typKrawedzi(line.dataset.edge);
            line.style.stroke = kolor(type);
            line.style.strokeWidth = (type === 'sharp') ? '2' : '3';
        });
        svg.querySelectorAll('.edges-label').forEach(label => {
            const type = typKrawedzi(label.dataset.edge);
            const kolko = label.querySelector('circle');
            if (kolko && type !== 'sharp') kolko.style.fill = kolor(type);
        });
        const etykiety = svg.querySelector('.edges-labels');
        if (etykiety && !state.labelsVisible) etykiety.classList.add('edges-labels-hidden');
        container.appendChild(svg);
    }

    function setupAdvancedActions() {
        if (!elements.advancedImportBtn) return;

        elements.advancedImportBtn.addEventListener('click', () => {
            state.advanced.edges.clear();
            state.basic.selectedEdges.forEach(letter => {
                state.advanced.edges.set(letter, {
                    type: state.basic.edgeType,
                    r_value: state.basic.rValue,
                    angle_value: state.basic.angleValue,
                });
            });
            renderAdvancedList();
            renderAdvancedVisualization();
        });

        // Wypełnij select kąta dynamicznie tym samym mechanizmem co render w wierszu
        if (elements.advancedBulkAngle) {
            elements.advancedBulkAngle.innerHTML = renderAngleOptions(45);
        }

        elements.advancedBulkType.addEventListener('change', () => {
            elements.advancedBulkAngle.style.display =
                (elements.advancedBulkType.value === 'chamfer') ? '' : 'none';
        });

        elements.advancedBulkApply.addEventListener('click', () => {
            const type = elements.advancedBulkType.value;
            const r = parseInt(elements.advancedBulkR.value, 10);
            const angle = (type === 'chamfer') ? parseInt(elements.advancedBulkAngle.value, 10) : null;
            getActiveEdgeDefinitions().forEach(def => {
                if (type === 'sharp') state.advanced.edges.delete(def.letter);
                else state.advanced.edges.set(def.letter, { type, r_value: r, angle_value: angle });
            });
            renderAdvancedList();
            renderAdvancedVisualization();
        });
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

        // Przełącz UI (lista krawędzi) w zależności od kształtu produktu
        if (_isRoundShape(state.productShape)) {
            showRoundEdgesUI();
            showCutoutGroupsForSimpleShape(_shapeDataFor(state.currentForm), state.dimensions.thickness);
        } else if (state.productShape !== 'rectangular' && state.currentForm._shapeEditor) {
            // Nieregularny kształt — dynamiczne krawędzie G/D/P
            showDynamicEdgesUI(state.currentForm._shapeEditor.getShapeData(), state.dimensions.thickness);
        } else {
            showRectangularEdgesUI();
            showCutoutGroupsForSimpleShape(_shapeDataFor(state.currentForm), state.dimensions.thickness);
        }

        // Rysunek: ten sam co w sekcji „Krawędzie” (każdy kształt, z wycięciami)
        renderModalSvg();

        // Lista zaawansowana bierze wycięcia ze state.dynamicEdgeDefs, które ustawiliśmy dopiero teraz
        // (loadSavedState renderował ją wcześniej, na definicjach z poprzedniego otwarcia)
        if (state.activeTab === 'advanced') {
            renderAdvancedList();
            renderAdvancedVisualization();
        }

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
        state.basic.edgeType = elements.typeSelect.value;

        // Aktualizuj limity promienia R
        const limits = CONFIG.R_LIMITS[state.basic.edgeType];
        if (limits) {
            elements.rValueInput.min = limits.min;
            elements.rValueInput.max = limits.max;

            // Jeśli aktualna wartość poza limitami, ustaw domyślną
            if (state.basic.rValue < limits.min || state.basic.rValue > limits.max) {
                state.basic.rValue = limits.default;
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

        if (state.basic.edgeType === 'chamfer') {
            // Pokaż grupę kąta
            elements.angleGroup.style.display = 'flex';

            // Wypełnij przyciskami z konfiguracji
            const angles = CONFIG.CHAMFER_ANGLES.angles;
            const defaultAngle = CONFIG.CHAMFER_ANGLES.default;

            // Ustaw domyślną wartość jeśli nie ustawiona
            if (!state.basic.angleValue || !angles.includes(state.basic.angleValue)) {
                state.basic.angleValue = defaultAngle;
            }

            elements.angleButtons.innerHTML = angles.map(angle =>
                `<button type="button" class="edges-angle-btn ${angle === state.basic.angleValue ? 'active' : ''}" data-angle="${angle}">${angle}°</button>`
            ).join('');

            // Dodaj event listenery do przycisków
            elements.angleButtons.querySelectorAll('.edges-angle-btn').forEach(btn => {
                btn.addEventListener('click', onAngleButtonClick);
            });
        } else {
            // Ukryj grupę kąta i wyczyść wartość
            elements.angleGroup.style.display = 'none';
            state.basic.angleValue = null;
        }
    }

    function onAngleButtonClick(e) {
        const angle = parseInt(e.target.dataset.angle);
        state.basic.angleValue = angle;

        // Aktualizuj klasy active
        elements.angleButtons.querySelectorAll('.edges-angle-btn').forEach(btn => {
            btn.classList.toggle('active', parseInt(btn.dataset.angle) === angle);
        });
    }

    function onRValueChange() {
        state.basic.rValue = parseInt(elements.rValueInput.value) || 3;
        calculatePrice();
    }

    function onCheckboxChange(e) {
        const item = e.target.closest('.edges-item');
        const edge = item.dataset.edge;

        if (e.target.checked) {
            state.basic.selectedEdges.add(edge);
            item.classList.add('selected');
            updateSvgEdge(edge, true);
        } else {
            state.basic.selectedEdges.delete(edge);
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
            else if (action === 'deselect-all') { targetEdges = []; state.basic.selectedEdges.clear(); }

            if (action !== 'deselect-all') {
                targetEdges.forEach(function(eid) { state.basic.selectedEdges.add(eid); });
            }

            dynSection.querySelectorAll('.edges-item').forEach(function(item) {
                var eid = item.dataset.edge;
                var cb = item.querySelector('input[type="checkbox"]');
                var isSelected = state.basic.selectedEdges.has(eid);
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
            state.basic.selectedEdges.add(edge);
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

    // Lista dynamiczna (wycięcia prostokąta/koła, krawędzie kształtów nietypowych) ma własne
    // checkboxy poza elements.checkboxes — po wyczyszczeniu state.basic.selectedEdges też je odznaczamy
    function _odznaczPozycjeDynamiczne() {
        const sekcja = elements.modal?.querySelector('.edges-dynamic-section');
        if (!sekcja) return;
        sekcja.querySelectorAll('.edges-item').forEach(item => {
            const cb = item.querySelector('input[type="checkbox"]');
            if (cb) cb.checked = false;
            item.classList.remove('active');
            updateSvgEdge(item.dataset.edge, false);
        });
    }

    function deselectAllEdges() {
        state.basic.selectedEdges.clear();
        // Odznacz checkboxy prostokąta
        elements.checkboxes.forEach(cb => {
            cb.checked = false;
            cb.closest('.edges-item')?.classList.remove('selected');
        });
        EDGE_GROUPS.all.forEach(edge => updateSvgEdge(edge, false));
        _odznaczPozycjeDynamiczne();

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
    // SVG - RYSUNEK MODALU
    // ==========================================

    // Rysunek zakładki Podstawowy: ten sam co podgląd w sekcji „Krawędzie” (_drawEdgesFigure —
    // prostokąt, koło i wielokąt, z wycięciami), z interakcjami modalu. Zaznaczenie z Podstawowego
    // rysuje już _drawEdgesFigure (klasa active na liniach i etykietach).
    function renderModalSvg() {
        if (!elements.svg || !state.currentForm) return;
        _drawEdgesFigure(elements.svg, state.currentForm, state.basic.selectedEdges);
        // Grupa etykiet powstaje od nowa przy każdym rysunku (querySelector — element jest w SVG)
        elements.labelsGroup = elements.svg.querySelector('#edgeLabelsGroup');
        if (elements.labelsGroup) elements.labelsGroup.classList.toggle('edges-labels-hidden', !state.labelsVisible);
        // Klik w krawędź/etykietę przełącza zaznaczenie, hover podświetla wiersz listy
        attachSvgEventListeners();
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

        // Narożniki dziur (H{h}.N{j}) — klikalne kółka
        elements.svg.querySelectorAll('.edges-corner-dot').forEach(dot => {
            dot.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                const edge = this.dataset.edge;
                toggleEdgeSelection(edge);
            });
            dot.addEventListener('mouseenter', function() {
                const edge = this.dataset.edge;
                highlightListItem(edge, true);
                highlightEdge(edge, true);
                this.classList.add('highlight');
            });
            dot.addEventListener('mouseleave', function() {
                const edge = this.dataset.edge;
                highlightListItem(edge, false);
                highlightEdge(edge, false);
                this.classList.remove('highlight');
            });
        });
    }

    // ==========================================
    // SVG - AKTUALIZACJA STANU
    // ==========================================

    function updateSvgEdge(edge, active) {
        const line = elements.svg?.querySelector(`.edges-line[data-edge="${edge}"]`);
        const label = elements.svg?.querySelector(`.edges-label[data-edge="${edge}"]`);
        const dot = elements.svg?.querySelector(`.edges-corner-dot[data-edge="${edge}"]`);

        if (line) {
            line.classList.toggle('active', active);
        }
        if (label) {
            label.classList.toggle('active', active);
        }
        if (dot) {
            dot.classList.toggle('active', active);
        }
    }

    function highlightEdge(edge, highlight) {
        const line = elements.svg?.querySelector(`.edges-line[data-edge="${edge}"]`);
        const label = elements.svg?.querySelector(`.edges-label[data-edge="${edge}"]`);
        const dot = elements.svg?.querySelector(`.edges-corner-dot[data-edge="${edge}"]`);
        if (line) {
            line.classList.toggle('highlight', highlight);
        }
        if (label) {
            label.classList.toggle('highlight', highlight);
        }
        if (dot) {
            dot.classList.toggle('highlight', highlight);
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
        const pricePerMb = getPricePerMb(state.basic.edgeType);
        const pricePerCorner = getPricePerCorner(state.basic.edgeType);

        if (_isRoundShape(state.productShape)) {
            // Kształt okrągły: krawędzie obwodowe KG/KD
            const perimeterCm = calculateEllipsePerimeterCm(
                state.dimensions.length, state.dimensions.width
            );
            const perimeterMb = perimeterCm / 100;

            state.basic.selectedEdges.forEach(edge => {
                if (ROUND_EDGES[edge]) {
                    totalNetto += perimeterMb * pricePerMb;
                    horizontalCount++;
                    return;
                }
                const d = _definicjaWyciecia(edge);
                if (!d) return;
                if (_jestNaroznikiem(d.group)) { totalNetto += pricePerCorner; cornerCount++; }
                else { totalNetto += (d.length_cm / 100) * pricePerMb; horizontalCount++; }
            });
        } else if (state.productShape !== 'rectangular' && Object.keys(state.dynamicEdgeDefs).length > 0) {
            // Nieregularny kształt: dynamiczne krawędzie G/D/P
            state.basic.selectedEdges.forEach(edge => {
                const def = state.dynamicEdgeDefs[edge];
                if (!def) return;

                if (_jestNaroznikiem(def.group)) {
                    // Krawędzie pionowe = narożniki — osobny cennik
                    totalNetto += pricePerCorner;
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
            state.basic.selectedEdges.forEach(edge => {
                const def = EDGES[edge];
                if (!def) {
                    const d = _definicjaWyciecia(edge);
                    if (!d) return;
                    if (_jestNaroznikiem(d.group)) { totalNetto += pricePerCorner; cornerCount++; }
                    else { totalNetto += (d.length_cm / 100) * pricePerMb; horizontalCount++; }
                    return;
                }

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

        const quantityInput = state.currentForm.querySelector('input[data-field="quantity"]');
        const quantity = parseInt(quantityInput?.value) || 1;

        // Zablokowany Podstawowy (baner: narożniki z rysunku albo mieszana konfiguracja zaawansowana)
        // nie ma własnej konfiguracji — stosujemy zaawansowaną, jak mówi baner. Inaczej pusta
        // konfiguracja podstawowa zdjęłaby wszystkie narożniki z rysunku.
        const podstawowyZablokowany = state.activeTab === 'basic'
            && !!elements.panelBasic?.classList.contains('edges-basic-panel-disabled');
        const edgesMode = podstawowyZablokowany ? 'advanced' : state.activeTab;
        let edgesData = [];
        let totalPrices;

        if (edgesMode === 'advanced') {
            // Tryb zaawansowany — per-edge
            getActiveEdgeDefinitions().forEach(def => {
                const cfg = state.advanced.edges.get(def.letter);
                if (!cfg || cfg.type === 'sharp') return;
                const lengthCm = computeEdgeLengthCm(def);
                const lengthMm = lengthCm * 10;
                const priceNetto = computeEdgePrice(def, cfg, lengthCm);
                const isCorner = (def.dimensionKey === 'thickness' || (def.dynamicDef && _jestNaroznikiem(def.dynamicDef.group)));
                // Długości z pełną dokładnością (wszystkie wpisy krawędzi): cenę na żywo backend
                // liczy z nich, a zapis z dokładnej geometrii — zaokrąglone dawały różnicę groszy.
                // Zaokrąglamy tylko przy wyświetlaniu.
                edgesData.push({
                    letter: def.letter,
                    type: cfg.type,
                    r_value: cfg.r_value,
                    angle_value: cfg.angle_value || null,
                    length_mm: lengthMm,
                    length_cm: lengthCm,
                    is_corner: isCorner,
                    price_netto: Math.round(priceNetto * 100) / 100,
                    price_brutto: Math.round(priceNetto * CONFIG.VAT_RATE * 100) / 100,
                });
            });
            // Sumy z mnożnikiem quantity
            let netto = 0, brutto = 0, horizontalCount = 0, cornerCount = 0;
            edgesData.forEach(e => {
                netto += e.price_netto; brutto += e.price_brutto;
                if (e.is_corner) cornerCount++; else horizontalCount++;
            });
            totalPrices = {
                netto: Math.round(netto * quantity * 100) / 100,
                brutto: Math.round(brutto * quantity * 100) / 100,
                horizontalCount, cornerCount,
            };
        } else {
            const result = buildBasicEdgesData(quantity);
            edgesData = result.edgesData;
            totalPrices = result.totalPrices;
        }

        // ====== SVG zapis ======
        // Ten sam rysunek co w modalu i w sekcji „Krawędzie”, zaznaczone zapisywane wpisy
        // (rysowany od nowa, więc podświetlenie spod kursora nie trafia do zapisu)
        const edgesSvg = _buildEdgesSvgHeadless(state.currentForm, edgesData, edgesMode);

        // Zapisz w dataset formularza (ceny już pomnożone przez ilość sztuk)
        state.currentForm.dataset.edgesData = JSON.stringify(edgesData);
        state.currentForm.dataset.edgesMode = edgesMode;
        state.currentForm.dataset.edgesNetto = totalPrices.netto;
        state.currentForm.dataset.edgesBrutto = totalPrices.brutto;
        state.currentForm.dataset.edgesCount = edgesData.length;
        state.currentForm.dataset.edgesSvg = edgesSvg;
        state.currentForm.dataset.edgesQuantity = quantity;
        state.currentForm.dataset.edgesDimHash = state.dimensions.length + '|' + state.dimensions.width + '|' + state.dimensions.thickness + '|' + (state.currentForm.dataset.productShape || 'rectangular');

        if (edgesMode === 'basic') {
            state.currentForm.dataset.edgesType = state.basic.edgeType;
            state.currentForm.dataset.edgesRValue = state.basic.rValue;
            state.currentForm.dataset.edgesAngleValue = state.basic.edgeType === 'chamfer' ? (state.basic.angleValue || '') : '';
        } else {
            state.currentForm.dataset.edgesType = 'mixed';
            state.currentForm.dataset.edgesRValue = '';
            state.currentForm.dataset.edgesAngleValue = '';
        }

        // Podsumowanie z datasetu (oba tryby)
        renderEdgesSummary(state.currentForm);
        if (window.ShapeEdgesSync) {
            // Narożniki z modalu trafiają na rysunek; za duże przycinamy do geometrii
            const wynikNaroznikow = window.ShapeEdgesSync.pullCornersFromEdges(state.currentForm);
            // Litery krawędzi odnoszą się do tej topologii — kolejne zmiany rysunku porównujemy z nią
            window.ShapeEdgesSync.rememberTopology(state.currentForm);
            // Rysunek jest źródłem prawdy o narożnikach: wpisy odtwarzamy z niego już po przycięciu
            // (modal 800 mm → rysunek 500 mm). Topologia zapamiętana wyżej, więc nic nie zostanie
            // unieważnione; syncForm nie woła applyEdges ani pull, więc pętli nie ma.
            window.ShapeEdgesSync.syncForm(state.currentForm);
            if (wynikNaroznikow.clamped && state.currentForm._shapeEditor) {
                state.currentForm._shapeEditor.showHint('Część narożników przycięto do największego wymiaru, jaki mieści się w kształcie.');
            }
        }

        // Wywołaj aktualizację globalnego podsumowania
        if (typeof updateGlobalSummary === 'function') {
            updateGlobalSummary();
        }

        // Zaktualizuj podgląd SVG w sekcji krawędzi
        updateEdgesPreview(state.currentForm);

        closeModal();
    }

    // ==========================================
    // BASIC: zbieranie edgesData (wyciągnięte z applyEdges)
    // ==========================================
    function _wpisWyciecia(edge, d, pricePerMb, pricePerCorner) {
        const naroznik = _jestNaroznikiem(d.group);
        const priceNetto = naroznik ? pricePerCorner : (d.length_cm / 100) * pricePerMb;
        return {
            letter: edge,
            type: state.basic.edgeType,
            r_value: state.basic.rValue,
            angle_value: state.basic.edgeType === 'chamfer' ? state.basic.angleValue : null,
            length_mm: d.length_cm * 10,
            length_cm: d.length_cm,
            is_corner: naroznik,
            price_netto: Math.round(priceNetto * 100) / 100,
            price_brutto: Math.round(priceNetto * CONFIG.VAT_RATE * 100) / 100
        };
    }

    function buildBasicEdgesData(quantity) {
        const prices = calculatePrice();
        const totalPrices = {
            netto: Math.round(prices.netto * quantity * 100) / 100,
            brutto: Math.round(prices.brutto * quantity * 100) / 100,
            horizontalCount: prices.horizontalCount,
            cornerCount: prices.cornerCount
        };

        const pricePerMb = getPricePerMb(state.basic.edgeType);
        const pricePerCorner = getPricePerCorner(state.basic.edgeType);
        const edgesData = [];

        if (_isRoundShape(state.productShape)) {
            // Kształt okrągły: krawędzie obwodowe KG/KD
            const perimeterCm = calculateEllipsePerimeterCm(
                state.dimensions.length, state.dimensions.width
            );
            const perimeterMm = perimeterCm * 10;
            const perimeterMb = perimeterCm / 100;

            state.basic.selectedEdges.forEach(edge => {
                const def = ROUND_EDGES[edge];
                if (!def) {
                    const d = _definicjaWyciecia(edge);
                    if (d) edgesData.push(_wpisWyciecia(edge, d, pricePerMb, pricePerCorner));
                    return;
                }

                const priceNetto = perimeterMb * pricePerMb;

                edgesData.push({
                    letter: edge,
                    type: state.basic.edgeType,
                    r_value: state.basic.rValue,
                    angle_value: state.basic.edgeType === 'chamfer' ? state.basic.angleValue : null,
                    length_mm: perimeterMm,
                    length_cm: perimeterCm,
                    is_corner: false,
                    is_round_perimeter: true,
                    price_netto: Math.round(priceNetto * 100) / 100,
                    price_brutto: Math.round(priceNetto * CONFIG.VAT_RATE * 100) / 100
                });
            });
        } else if (state.productShape !== 'rectangular' && Object.keys(state.dynamicEdgeDefs).length > 0) {
            // Nieregularny kształt: dynamiczne krawędzie G/D/P
            state.basic.selectedEdges.forEach(edge => {
                const def = state.dynamicEdgeDefs[edge];
                if (!def) return;

                const isVertical = _jestNaroznikiem(def.group);
                const lengthCm = def.length_cm;
                const lengthMm = lengthCm * 10;
                // Krawędzie pionowe (P*) = narożniki — osobny cennik
                const priceNetto = isVertical ? pricePerCorner : (lengthCm / 100) * pricePerMb;

                edgesData.push({
                    letter: edge,
                    type: state.basic.edgeType,
                    r_value: state.basic.rValue,
                    angle_value: state.basic.edgeType === 'chamfer' ? state.basic.angleValue : null,
                    length_mm: lengthMm,
                    length_cm: lengthCm,
                    is_corner: isVertical,
                    price_netto: Math.round(priceNetto * 100) / 100,
                    price_brutto: Math.round(priceNetto * CONFIG.VAT_RATE * 100) / 100
                });
            });
        } else {
            // Kształt prostokątny: standardowe krawędzie
            state.basic.selectedEdges.forEach(edge => {
                const def = EDGES[edge];
                if (!def) {
                    const d = _definicjaWyciecia(edge);
                    if (d) edgesData.push(_wpisWyciecia(edge, d, pricePerMb, pricePerCorner));
                    return;
                }

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
                    type: state.basic.edgeType,
                    r_value: state.basic.rValue,
                    angle_value: state.basic.edgeType === 'chamfer' ? state.basic.angleValue : null,
                    length_mm: lengthMm,
                    length_cm: lengthCm,
                    is_corner: def.group === 'corner',
                    price_netto: Math.round(priceNetto * 100) / 100,
                    price_brutto: Math.round(priceNetto * CONFIG.VAT_RATE * 100) / 100
                });
            });
        }

        return { edgesData, totalPrices };
    }

    /**
     * Buduje SVG do zapisu w bazie z rysunku krawędzi (sourceSvg z _buildEdgesSvgHeadless).
     * Mode 'basic': zachowanie 1:1 (pomarańcz dla aktywnych).
     * Mode 'advanced': kolorowanie per typ (zielony=round, pomarańcz=chamfer, szary=sharp).
     */
    function buildEdgesSvgForSave(edgesData, mode, sourceSvg) {
        if (!sourceSvg || edgesData.length === 0) return '';
        const svgClone = sourceSvg.cloneNode(true);
        const labelsGroup = svgClone.querySelector('#edgeLabelsGroup');
        if (labelsGroup) labelsGroup.remove();

        // Bazowe style faces (wspólne dla obu trybów)
        const baseStyleMap = {
            '.edges-face': { fill: '#f0f0f0', stroke: 'none' },
            '.edges-face-top': { fill: '#e8e8e8' },
            '.edges-face-front': { fill: '#d8d8d8' },
            '.edges-face-right': { fill: '#c8c8c8' },
            '.edges-face-left': { fill: '#d0d0d0' },
            '.edges-face-back': { fill: '#b8b8b8' },
        };
        Object.entries(baseStyleMap).forEach(([selector, styles]) => {
            svgClone.querySelectorAll(selector).forEach(el => {
                Object.entries(styles).forEach(([prop, value]) => el.style.setProperty(prop, value));
            });
        });

        if (mode === 'advanced') {
            const colorFor = (type) => type === 'round' ? '#2E7D32' : (type === 'chamfer' ? '#ED6B24' : '#666');
            const byLetter = new Map(edgesData.map(e => [e.letter, e]));
            svgClone.querySelectorAll('.edges-line').forEach(line => {
                const e = byLetter.get(line.dataset.edge);
                line.style.fill = 'none';
                if (e) {
                    line.style.stroke = colorFor(e.type);
                    line.style.strokeWidth = '3';
                } else {
                    line.style.stroke = '#666';
                    line.style.strokeWidth = '2';
                }
            });
        } else {
            // basic — pomarańcz dla aktywnych, szary dla pozostałych
            const activeSet = new Set(edgesData.map(e => e.letter));
            svgClone.querySelectorAll('.edges-line').forEach(line => {
                line.style.fill = 'none';
                if (activeSet.has(line.dataset.edge)) {
                    line.style.stroke = '#ED6B24';
                    line.style.strokeWidth = '3';
                } else {
                    line.style.stroke = '#666';
                    line.style.strokeWidth = '2';
                }
            });
        }

        // viewBox auto-fit (jak dotychczas)
        try {
            svgClone.style.position = 'absolute';
            svgClone.style.visibility = 'hidden';
            document.body.appendChild(svgClone);
            const bbox = svgClone.getBBox();
            const padding = 5;
            svgClone.setAttribute('viewBox', `${bbox.x - padding} ${bbox.y - padding} ${bbox.width + 2*padding} ${bbox.height + 2*padding}`);
            document.body.removeChild(svgClone);
            svgClone.style.removeProperty('position');
            svgClone.style.removeProperty('visibility');
        } catch (e) {
            // Ignore errors during SVG clone cleanup
        }

        return svgClone.outerHTML;
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
        state.basic.selectedEdges.clear();

        // Wyczyść dataset
        delete state.currentForm.dataset.edgesData;
        delete state.currentForm.dataset.edgesNetto;
        delete state.currentForm.dataset.edgesBrutto;
        delete state.currentForm.dataset.edgesCount;
        delete state.currentForm.dataset.edgesType;
        delete state.currentForm.dataset.edgesRValue;
        delete state.currentForm.dataset.edgesAngleValue;
        delete state.currentForm.dataset.edgesSvg;
        delete state.currentForm.dataset.edgesQuantity;
        delete state.currentForm.dataset.edgesDimHash;

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

    const TYPY_PODSUMOWANIA = { round: 'Zaokrąglenie', chamfer: 'Fazowanie' };

    // Wiersz podsumowania krawędzi z danych formularza — oba tryby, ceny z datasetu
    // (po /calculate to cena z backendu). Grupuje litery po typie, R i kącie.
    function renderEdgesSummary(form) {
        if (!form) return;
        const optionsSummary = form.querySelector('.edges-options-summary');
        if (!optionsSummary) return;
        const edgesRow = optionsSummary.querySelector('.edges-row');
        const textEl = optionsSummary.querySelector('.edges-summary-text');
        const priceEl = optionsSummary.querySelector('.edges-summary-price');
        let priceNettoEl = optionsSummary.querySelector('.edges-summary-price-netto');
        const openBtn = form.querySelector('.open-edges-modal-btn');
        if (!priceNettoEl && edgesRow) {
            const content = edgesRow.querySelector('.options-summary-content');
            if (content) {
                priceNettoEl = document.createElement('span');
                priceNettoEl.className = 'options-summary-price-netto edges-summary-price-netto';
                content.appendChild(priceNettoEl);
            }
        }
        let wpisy = [];
        try { wpisy = JSON.parse(form.dataset.edgesData || '[]'); } catch (e) { wpisy = []; }
        wpisy = wpisy.filter(e => e.type && e.type !== 'sharp');
        if (!wpisy.length) {
            if (edgesRow) edgesRow.style.display = 'none';
            if (openBtn) openBtn.textContent = '+ Dodaj';
            updateOptionsSummaryVisibility(optionsSummary);
            return;
        }
        const grupy = new Map();
        wpisy.forEach(e => {
            const klucz = e.type + '|' + e.r_value + '|' + (e.type === 'chamfer' ? (e.angle_value || '') : '');
            if (!grupy.has(klucz)) grupy.set(klucz, { e: e, litery: [] });
            grupy.get(klucz).litery.push(e.letter);
        });
        const tekst = Array.from(grupy.values()).map(g => {
            let t = (TYPY_PODSUMOWANIA[g.e.type] || g.e.type) + ' R' + g.e.r_value;
            if (g.e.type === 'chamfer' && g.e.angle_value) t += ' (' + g.e.angle_value + '°)';
            return t + ': ' + g.litery.sort().join(', ');
        }).join(' · ');
        if (textEl) textEl.textContent = tekst;
        if (priceEl) priceEl.textContent = formatPLN(parseFloat(form.dataset.edgesBrutto) || 0) + ' brutto';
        if (priceNettoEl) priceNettoEl.textContent = formatPLN(parseFloat(form.dataset.edgesNetto) || 0) + ' netto';
        if (edgesRow) edgesRow.style.display = 'flex';
        if (openBtn) openBtn.textContent = 'Edytuj';
        updateOptionsSummaryVisibility(optionsSummary);
    }

    // SVG krawędzi do zapisu (Zastosuj w modalu i synchronizacja bez modalu) — rysunek jak podgląd w sekcji
    function _buildEdgesSvgHeadless(form, entries, mode) {
        const svgEl = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svgEl.setAttribute('viewBox', '0 0 320 220');
        svgEl.setAttribute('class', 'edges-interactive-svg');
        _drawEdgesFigure(svgEl, form, new Set(entries.map(e => e.letter)));
        return buildEdgesSvgForSave(entries, mode, svgEl);
    }

    // Zapis krawędzi do formularza bez modalu (synchronizacja z rysunkiem).
    // Ceny per krawędź to podgląd z /api/edge-options — wiążącą cenę liczy backend.
    function setFormEdges(form, entries, mode) {
        if (!form) return;
        if (!entries || !entries.length) {
            const poprzedni = state.currentForm;
            state.currentForm = form;
            resetEdges();
            state.currentForm = poprzedni;
            // Pusta lista = reset, ale cenę z backendu trzeba przeliczyć już bez krawędzi
            if (typeof updatePrices === 'function') updatePrices();
            return;
        }
        const quantity = parseInt(form.querySelector('input[data-field="quantity"]')?.value) || 1;
        let netto = 0, brutto = 0;
        const wycenione = entries.map(e => {
            const surowa = (e.type === 'sharp') ? 0
                : (e.is_corner ? getPricePerCorner(e.type) : ((parseFloat(e.length_cm) || 0) / 100) * getPricePerMb(e.type));
            const w = Object.assign({}, e, {
                price_netto: Math.round(surowa * 100) / 100,
                price_brutto: Math.round(surowa * CONFIG.VAT_RATE * 100) / 100
            });
            netto += w.price_netto;
            brutto += w.price_brutto;
            return w;
        });
        form.dataset.edgesData = JSON.stringify(wycenione);
        form.dataset.edgesMode = mode;
        form.dataset.edgesCount = wycenione.length;
        form.dataset.edgesQuantity = quantity;
        form.dataset.edgesNetto = Math.round(netto * quantity * 100) / 100;
        form.dataset.edgesBrutto = Math.round(brutto * quantity * 100) / 100;
        if (mode === 'advanced') {
            form.dataset.edgesType = 'mixed';
            form.dataset.edgesRValue = '';
            form.dataset.edgesAngleValue = '';
        }
        form.dataset.edgesSvg = _buildEdgesSvgHeadless(form, wycenione, mode);
        renderEdgesSummary(form);
        updateEdgesPreview(form);
        if (typeof updatePrices === 'function') updatePrices();
    }

    function loadSavedState() {
        if (!state.currentForm) return;

        const savedData = state.currentForm.dataset.edgesData;
        const savedType = state.currentForm.dataset.edgesType;
        const savedRValue = state.currentForm.dataset.edgesRValue;
        const savedAngleValue = state.currentForm.dataset.edgesAngleValue;
        const edgesMode = state.currentForm.dataset.edgesMode || 'basic';

        // Reset stanu obu zakładek
        state.basic.selectedEdges.clear();
        state.advanced.edges.clear();

        // Ustaw aktywną zakładkę
        state.activeTab = (edgesMode === 'advanced') ? 'advanced' : 'basic';
        if (elements.tabBtns && elements.tabBtns.length) {
            elements.tabBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === state.activeTab));
        }
        if (elements.panelBasic) elements.panelBasic.style.display = (state.activeTab === 'basic') ? '' : 'none';
        if (elements.panelAdvanced) elements.panelAdvanced.style.display = (state.activeTab === 'advanced') ? '' : 'none';
        // Blokada Podstawowego (klasa + baner) z poprzedniego otwarcia nie może przechodzić na ten produkt;
        // zakładkę przelicza switchTab('basic'). Nie wołamy tu refreshBasicDisabledState: stara forma
        // w trybie basic z narożnikami otworzyłaby się na zablokowanym Podstawowym przy pustej liście zaawansowanej.
        if (elements.panelBasic) elements.panelBasic.classList.remove('edges-basic-panel-disabled');
        if (elements.basicDisabledBanner) elements.basicDisabledBanner.style.display = 'none';

        // Jeśli mamy zapisany tryb advanced — wypełnij mapę i zakończ tutaj
        if (edgesMode === 'advanced' && savedData) {
            try {
                const arr = JSON.parse(savedData);
                arr.forEach(e => {
                    state.advanced.edges.set(e.letter, {
                        type: e.type,
                        r_value: e.r_value,
                        angle_value: e.angle_value || null,
                    });
                });
            } catch (err) {
                console.error('EdgesModule: Błąd wczytywania zaawansowanego stanu:', err);
            }
            // Render listy + wizualizacji nastąpi przy otwarciu panelu advanced (switchTab),
            // a tu wywołujemy bezpośrednio bo panel już jest pokazany.
            renderAdvancedList();
            renderAdvancedVisualization();
            return;
        }

        // Reset UI checkboxów (SVG będzie generowany później z prawidłowym stanem)
        elements.checkboxes.forEach(cb => {
            cb.checked = false;
            cb.closest('.edges-item').classList.remove('selected');
        });
        // NIE wywołuj updateSvgEdge tutaj - SVG będzie generowany PÓŹNIEJ
        // i sam zaznaczy prawidłowe krawędzie na podstawie state.basic.selectedEdges

        if (!savedData) {
            // Brak zapisanych danych dla tego formularza - ustaw domyślne wartości z CONFIG.R_LIMITS
            state.basic.edgeType = 'round';
            const defaultLimits = CONFIG.R_LIMITS['round'] || { min: 3, max: 20, default: 5 };
            state.basic.rValue = defaultLimits.default;
            state.basic.angleValue = null;
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
                state.basic.selectedEdges.add(edge.letter);
            });

            // Przywróć typ i promień R
            state.basic.edgeType = savedType || 'round';
            state.basic.rValue = parseInt(savedRValue) || 5;

            // Przywróć kąt fazowania
            if (savedAngleValue && state.basic.edgeType === 'chamfer') {
                state.basic.angleValue = parseInt(savedAngleValue);
            } else {
                state.basic.angleValue = null;
            }

            // Aktualizuj UI kontrolek
            if (elements.typeSelect) elements.typeSelect.value = state.basic.edgeType;
            if (elements.rValueInput) elements.rValueInput.value = state.basic.rValue;

            // Aktualizuj limity R dla wybranego typu
            const limits = CONFIG.R_LIMITS[state.basic.edgeType];
            if (limits && elements.rValueInput) {
                elements.rValueInput.min = limits.min;
                elements.rValueInput.max = limits.max;
            }

            // Aktualizuj select kąta
            updateAngleButtons();

            // Zaznacz checkboxy zgodnie z zapisanym stanem
            // (rysunek modalu powstaje później, w renderModalSvg)
            elements.checkboxes.forEach(cb => {
                const item = cb.closest('.edges-item');
                const edge = item.dataset.edge;
                const isSelected = state.basic.selectedEdges.has(edge);

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
     * Reset przy zmianie wymiarów + aktualizacja wizualna podsumowania krawędzi.
     * Wywoływane gdy użytkownik zmienia wymiary produktu.
     *
     * UWAGA: Wiążąca cena krawędzi liczona jest w backendzie
     * (POST /calculator/api/calculate) — ta funkcja NIE liczy cen, tylko czyta
     * ostatnią znaną wartość z form.dataset.edgesNetto/edgesBrutto (zapisaną przez
     * applyProductResult w calculator-api.js) i odświeża wiersz podsumowania.
     * Podgląd cen per-krawędź w modalu (calculatePrice/updateAdvancedPrice w tym
     * pliku) to tylko podgląd liczony lokalnie z cen `/api/edge-options` —
     * wiążąca cena i tak przyjdzie z `/calculate` po zapisie modala.
     */
    function recalculateEdgesForForm(form) {
        if (!form) return;

        const savedData = form.dataset.edgesData;
        if (!savedData) return;

        // Pobierz aktualne wymiary z formularza
        const lengthInput = form.querySelector('input[data-field="length"]');
        const widthInput = form.querySelector('input[data-field="width"]');
        const thicknessInput = form.querySelector('input[data-field="thickness"]');

        const dimensions = {
            length: parseFloat(lengthInput?.value) || 0,
            width: parseFloat(widthInput?.value) || 0,
            thickness: parseFloat(thicknessInput?.value) || 0
        };

        // Jeśli brak wymiarów, nie przeliczaj
        if (dimensions.length <= 0 || dimensions.width <= 0 || dimensions.thickness <= 0) {
            return;
        }

        // Sprawdź czy wymiary lub kształt się zmieniły — jeśli tak, resetuj krawędzie
        var formShape = form.dataset.productShape || 'rectangular';
        var currentDimHash = dimensions.length + '|' + dimensions.width + '|' + dimensions.thickness + '|' + formShape;
        var savedDimHash = form.dataset.edgesDimHash || '';
        if (savedDimHash && currentDimHash !== savedDimHash) {
            state.currentForm = form;
            resetEdges();
            return;
        }

        form.dataset.edgesDimHash = currentDimHash;

        // Ceny z backendu (ustawione przez applyProductResult po odpowiedzi /calculate)
        const totalNettoWithQuantity = parseFloat(form.dataset.edgesNetto) || 0;
        const totalBruttoWithQuantity = parseFloat(form.dataset.edgesBrutto) || 0;

        // Zaktualizuj wizualne podsumowanie (pokazuje cenę łączną z uwzględnieniem ilości)
        const optionsSummary = form.querySelector('.edges-options-summary');
        const edgesRow = optionsSummary?.querySelector('.edges-row');

        if (edgesRow) {
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
                        state.basic.selectedEdges.add(edgeLetter);
                        this.closest('.edges-item').classList.add('selected');
                    } else {
                        state.basic.selectedEdges.delete(edgeLetter);
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

        // Synchronizuj checkboxy z state.basic.selectedEdges
        roundSection.querySelectorAll('.edges-item').forEach(item => {
            const edgeLetter = item.dataset.edge;
            const cb = item.querySelector('input[type="checkbox"]');
            if (cb) {
                cb.checked = state.basic.selectedEdges.has(edgeLetter);
                item.classList.toggle('selected', state.basic.selectedEdges.has(edgeLetter));
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

    // Piony obrysu i wycięć liczone jak narożniki (za sztukę) — tak liczy pricing_service
    function _jestNaroznikiem(group) {
        return group === 'vertical' || group === 'hole_vertical';
    }

    // Krawędź wycięcia (H…) z definicji z rysunku — używane przez prostokąt i koło
    function _definicjaWyciecia(edge) {
        return (String(edge).charAt(0) === 'H' && state.dynamicEdgeDefs[edge]) ? state.dynamicEdgeDefs[edge] : null;
    }

    function _shapeDataFor(form) {
        return (form && form._shapeEditor) ? form._shapeEditor.getShapeData() : null;
    }

    // Definicje z rysunku w formacie listy modalu ({id, group, name, length})
    function _definicjeZRysunku(shapeType, shapeData, thickness) {
        if (!window.ShapeEdgesSync || !shapeData) return [];
        return window.ShapeEdgesSync.edgeDefinitions(shapeType, shapeData, thickness).map(function(d) {
            return { id: d.id, group: d.group, name: d.name, length: d.length_cm };
        });
    }

    function _zapiszDefinicje(edges) {
        state.dynamicEdgeDefs = {};
        edges.forEach(function(e) {
            state.dynamicEdgeDefs[e.id] = { length_cm: e.length, group: e.group, name: e.name };
        });
    }

    function _pozycjaListyHtml(e, naroznik) {
        var dl = Math.round(e.length * 10) / 10;
        return '<div class="edges-item' + (naroznik ? ' edges-corner-item' : '') + '" data-edge="' + e.id + '">' +
            '<label class="edges-checkbox">' +
            '<input type="checkbox" name="edge_' + e.id + '">' +
            '<span class="edges-letter' + (naroznik ? ' edges-letter-corner' : '') + '">' + e.id + '</span>' +
            '<span class="edges-name">' + e.name + '</span>' +
            '<span class="edges-length">(' + dl + ' cm)</span>' +
            '</label></div>';
    }

    // Grupy „WYCIĘCIE n” (G, D, P albo obwód elipsy)
    function _htmlGrupWyciec(edges, liczbaWyciec) {
        var html = '';
        for (var n = 1; n <= liczbaWyciec; n++) {
            var prefiks = 'H' + n + '.';
            var swoje = edges.filter(function(e) { return e.id.indexOf(prefiks) === 0; });
            if (!swoje.length) continue;
            html += '<div class="edges-group edges-group-hole"><h5>WYCIĘCIE ' + n + '</h5><div class="edges-list">';
            ['hole_top', 'hole_bottom', 'hole_vertical'].forEach(function(grupa) {
                swoje.filter(function(e) { return e.group === grupa; }).forEach(function(e) {
                    html += _pozycjaListyHtml(e, grupa === 'hole_vertical');
                });
            });
            html += '</div></div>';
        }
        return html;
    }

    // Checkboxy listy dynamicznej: stan z basic.selectedEdges, zmiana → SVG i cena
    function _podepnijPozycje(section) {
        if (!section) return;
        section.querySelectorAll('.edges-item').forEach(function(item) {
            var edgeId = item.dataset.edge;
            var checkbox = item.querySelector('input[type="checkbox"]');
            if (!checkbox) return;
            checkbox.checked = state.basic.selectedEdges.has(edgeId);
            if (checkbox.checked) item.classList.add('active');
            checkbox.addEventListener('change', function() {
                if (this.checked) {
                    state.basic.selectedEdges.add(edgeId);
                    item.classList.add('active');
                } else {
                    state.basic.selectedEdges.delete(edgeId);
                    item.classList.remove('active');
                }
                updateSvgEdge(edgeId, this.checked);
                calculatePrice();
            });
            item.addEventListener('mouseenter', function() { highlightEdge(edgeId, true); });
            item.addEventListener('mouseleave', function() { highlightEdge(edgeId, false); });
        });
    }

    // Prostokąt i koło: obrys na swoich literach (A–H/N, KG/KD), wycięcia jako grupy „WYCIĘCIE n”
    function showCutoutGroupsForSimpleShape(shapeData, thickness) {
        var modal = elements.modal;
        if (!modal) return;
        var stara = modal.querySelector('.edges-dynamic-section');
        if (stara) stara.remove();
        var edges = _definicjeZRysunku(state.productShape, shapeData, thickness);
        _zapiszDefinicje(edges);
        var liczba = window.ShapeCutouts ? ShapeCutouts.fromShapeData(shapeData).length : 0;
        if (!liczba) return;
        var html = '<div class="edges-section edges-dynamic-section">' + _htmlGrupWyciec(edges, liczba) + '</div>';
        var cel = _isRoundShape(state.productShape)
            ? modal.querySelector('.edges-round-section')
            : modal.querySelector('.edges-top-section');
        if (cel) cel.insertAdjacentHTML('afterend', html);
        _podepnijPozycje(modal.querySelector('.edges-dynamic-section'));
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

        // Definicje z rysunku: G/D/P obrysu + wycięcia (elipsa: jedna krawędź obwodowa)
        var edges = _definicjeZRysunku(state.productShape, shapeData, thickness);
        if (!edges.length) return;
        _zapiszDefinicje(edges);
        var holes = window.ShapeCutouts ? ShapeCutouts.fromShapeData(shapeData) : [];

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

        // Grupy: per wycięcie (WYCIĘCIE 1, WYCIĘCIE 2, ...)
        html += _htmlGrupWyciec(edges, holes.length);

        html += '</div>';

        // Wstaw do modalu (po edges-top-section)
        var topSection = modal.querySelector('.edges-top-section');
        if (topSection) {
            topSection.insertAdjacentHTML('afterend', html);
        }

        // Podepnij event listenery do nowych checkboxów
        _podepnijPozycje(modal.querySelector('.edges-dynamic-section'));

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
     * Aktualizuje podświetlenie SVG dla krawędzi okrągłych (linia i etykieta KG/KD)
     */
    function updateRoundSvgHighlights() {
        ['KG', 'KD'].forEach(edge => updateSvgEdge(edge, state.basic.selectedEdges.has(edge)));
    }

    // ==========================================
    // PODGLĄD SVG W SEKCJI KRAWĘDZI
    // ==========================================

    // Rysunek izometryczny krawędzi — jeden dla podglądu w sekcji, modalu (obie zakładki) i zapisywanego SVG
    function _drawEdgesFigure(svgEl, form, activeEdges) {
        const lengthVal = parseFloat(form.querySelector('[data-field="length"]')?.value) || 100;
        const widthVal = parseFloat(form.querySelector('[data-field="width"]')?.value) || 50;
        const thicknessVal = parseFloat(form.querySelector('[data-field="thickness"]')?.value) || 4;
        const shape = form.dataset.productShape || 'rectangular';
        const shapeData = form._shapeEditor ? form._shapeEditor.getShapeData() : null;

        if (_isRoundShape(shape)) {
            // Koło: width = length (średnica)
            const roundW = (shape === 'circle') ? lengthVal : widthVal;
            generateRoundPreviewSVG(svgEl, lengthVal, roundW, thicknessVal, activeEdges, shapeData);
        } else if (shape !== 'rectangular' && shapeData) {
            // Nieregularny kształt — renderuj z wierzchołków
            generateShapePreviewSVG(svgEl, shapeData, thicknessVal, activeEdges, shape);
        } else {
            generateRectPreviewSVG(svgEl, lengthVal, widthVal, thicknessVal, activeEdges, shapeData);
        }
    }

    /**
     * Generuje podgląd SVG krawędzi (bez etykiet, bez interakcji)
     * @param {HTMLElement} form - formularz produktu
     */
    function updateEdgesPreview(form) {
        if (!form) return;

        const svgEl = form.querySelector('.edges-preview-svg');
        if (!svgEl) return;

        // Pobierz aktywne krawędzie z dataset formularza
        let activeEdges = new Set();
        try {
            const edgesData = JSON.parse(form.dataset.edgesData || '[]');
            edgesData.forEach(e => activeEdges.add(e.letter));
        } catch (err) { /* brak danych */ }

        _drawEdgesFigure(svgEl, form, activeEdges);

        // Zastosuj globalny stan etykiet po przebudowie SVG
        if (!state.labelsVisible) {
            var labelsG = svgEl.querySelector('.edges-labels');
            if (labelsG) labelsG.classList.add('edges-labels-hidden');
        }
    }

    function _pkt(arr) {
        return arr.map(function(p) { return p.x + ',' + p.y; }).join(' ');
    }

    function _etykietaSvg(id, x, y, cls) {
        return '<g class="edges-label' + cls + '" data-edge="' + id + '"><circle cx="' + x + '" cy="' + (y - 2) +
            '" r="11"/><text x="' + x + '" y="' + (y + 2) + '" font-size="8">' + id + '</text></g>';
    }

    // Wycięcia na izometrii: mapGora/mapDol(x, y w cm) → {x, y} na ekranie.
    // Wielokąt: krawędzie G/D per bok i P per wierzchołek; elipsa: obwód góra H{n}.G1 i dół H{n}.D1.
    function _svgWyciec(shapeData, mapGora, mapDol, activeEdges) {
        var svg = '', etykiety = '';
        if (!window.ShapeCutouts || !shapeData) return { svg: svg, etykiety: etykiety };
        ShapeCutouts.fromShapeData(shapeData).forEach(function(c, ci) {
            var h = 'H' + (ci + 1) + '.';
            var ec = function(id) { return activeEdges.has(id) ? ' active' : ''; };
            if (c.type === 'ellipse') {
                var pts = ShapeCutouts.ring(c);
                var gora = pts.map(function(p) { return mapGora(p[0], p[1]); });
                var dol = pts.map(function(p) { return mapDol(p[0], p[1]); });
                svg += '<polygon class="edges-face edges-face-back" points="' + _pkt(gora) + '"/>';
                svg += '<polygon class="edges-line' + ec(h + 'D1') + '" data-edge="' + h + 'D1" points="' + _pkt(dol) + '" fill="none"/>';
                svg += '<polygon class="edges-line' + ec(h + 'G1') + '" data-edge="' + h + 'G1" points="' + _pkt(gora) + '" fill="none"/>';
                var s = mapGora(c.cx, c.cy);
                etykiety += _etykietaSvg(h + 'G1', s.x, s.y, ec(h + 'G1'));
                return;
            }
            var g = c.points.map(function(p) { return mapGora(p[0], p[1]); });
            var d = c.points.map(function(p) { return mapDol(p[0], p[1]); });
            svg += '<polygon class="edges-face edges-face-back" points="' + _pkt(g) + '"/>';
            for (var j = 0; j < g.length; j++) {
                var k = (j + 1) % g.length;
                var gId = h + 'G' + (j + 1), dId = h + 'D' + (j + 1), pId = h + 'P' + (j + 1);
                svg += '<line class="edges-line' + ec(dId) + '" data-edge="' + dId + '" x1="' + d[j].x + '" y1="' + d[j].y + '" x2="' + d[k].x + '" y2="' + d[k].y + '"/>';
                svg += '<line class="edges-line edges-corner' + ec(pId) + '" data-edge="' + pId + '" x1="' + g[j].x + '" y1="' + g[j].y + '" x2="' + d[j].x + '" y2="' + d[j].y + '"/>';
                svg += '<line class="edges-line' + ec(gId) + '" data-edge="' + gId + '" x1="' + g[j].x + '" y1="' + g[j].y + '" x2="' + g[k].x + '" y2="' + g[k].y + '"/>';
                etykiety += _etykietaSvg(gId, (g[j].x + g[k].x) / 2, (g[j].y + g[k].y) / 2, ec(gId));
            }
        });
        return { svg: svg, etykiety: etykiety };
    }

    function generateRectPreviewSVG(svgEl, length, width, thickness, activeEdges, shapeData) {
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

        // Plan (x, y w cm; przód = y 0) → górna/dolna ściana izometrii
        const mapGora = (x, y) => ({
            x: pPLG.x + (x / length) * (pPPG.x - pPLG.x) + (y / width) * (pTLG.x - pPLG.x),
            y: pPLG.y + (x / length) * (pPPG.y - pPLG.y) + (y / width) * (pTLG.y - pPLG.y)
        });
        const mapDol = (x, y) => ({
            x: pPLD.x + (x / length) * (pPPD.x - pPLD.x) + (y / width) * (pTLD.x - pPLD.x),
            y: pPLD.y + (x / length) * (pPPD.y - pPLD.y) + (y / width) * (pTLD.y - pPLD.y)
        });
        const wyc = _svgWyciec(shapeData, mapGora, mapDol, activeEdges);

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
            ${wyc.svg}
            <g class="edges-labels" id="edgeLabelsGroup">
                <g class="edges-label ${ec('A')}" data-edge="A"><circle cx="${(pPLG.x+pPPG.x)/2}" cy="${(pPLG.y+pPPG.y)/2-12}" r="10"/><text x="${(pPLG.x+pPPG.x)/2}" y="${(pPLG.y+pPPG.y)/2-8}">A</text></g>
                <g class="edges-label ${ec('B')}" data-edge="B"><circle cx="${(pTLG.x+pTPG.x)/2}" cy="${(pTLG.y+pTPG.y)/2-12}" r="10"/><text x="${(pTLG.x+pTPG.x)/2}" y="${(pTLG.y+pTPG.y)/2-8}">B</text></g>
                <g class="edges-label ${ec('C')}" data-edge="C"><circle cx="${(pTLG.x+pPLG.x)/2-14}" cy="${(pTLG.y+pPLG.y)/2}" r="10"/><text x="${(pTLG.x+pPLG.x)/2-14}" y="${(pTLG.y+pPLG.y)/2+4}">C</text></g>
                <g class="edges-label ${ec('D')}" data-edge="D"><circle cx="${(pTPG.x+pPPG.x)/2+14}" cy="${(pTPG.y+pPPG.y)/2}" r="10"/><text x="${(pTPG.x+pPPG.x)/2+14}" y="${(pTPG.y+pPPG.y)/2+4}">D</text></g>
                <g class="edges-label ${ec('E')}" data-edge="E"><circle cx="${(pPLD.x+pPPD.x)/2}" cy="${(pPLD.y+pPPD.y)/2+12}" r="10"/><text x="${(pPLD.x+pPPD.x)/2}" y="${(pPLD.y+pPPD.y)/2+16}">E</text></g>
                <g class="edges-label ${ec('H')}" data-edge="H"><circle cx="${(pTPD.x+pPPD.x)/2+14}" cy="${(pTPD.y+pPPD.y)/2}" r="10"/><text x="${(pTPD.x+pPPD.x)/2+14}" y="${(pTPD.y+pPPD.y)/2+4}">H</text></g>
                <g class="edges-label edges-label-corner ${ec('N1')}" data-edge="N1"><circle cx="${pPLG.x-14}" cy="${(pPLG.y+pPLD.y)/2}" r="10"/><text x="${pPLG.x-14}" y="${(pPLG.y+pPLD.y)/2+4}">N1</text></g>
                <g class="edges-label edges-label-corner ${ec('N2')}" data-edge="N2"><circle cx="${pPPG.x+14}" cy="${(pPPG.y+pPPD.y)/2}" r="10"/><text x="${pPPG.x+14}" y="${(pPPG.y+pPPD.y)/2+4}">N2</text></g>
                <g class="edges-label edges-label-corner ${ec('N4')}" data-edge="N4"><circle cx="${pTPG.x+14}" cy="${(pTPG.y+pTPD.y)/2}" r="10"/><text x="${pTPG.x+14}" y="${(pTPG.y+pTPD.y)/2+4}">N4</text></g>
                ${wyc.etykiety}
            </g>
        `;
    }

    function generateRoundPreviewSVG(svgEl, length, width, thickness, activeEdges, shapeData) {
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

        // Plan koła (0..średnica, przód = y 0) → elipsa górnej/dolnej ściany
        const mapGora = (x, y) => ({ x: cx + (x / length * 2 - 1) * rx, y: cy + (1 - y / width * 2) * ry });
        const mapDol = (x, y) => ({ x: cx + (x / length * 2 - 1) * rx, y: cy + sT + (1 - y / width * 2) * ry });
        const wyc = _svgWyciec(shapeData, mapGora, mapDol, activeEdges);

        svgEl.innerHTML = `
            <ellipse class="edges-face edges-face-front" cx="${cx}" cy="${cy + sT}" rx="${rx}" ry="${ry}"/>
            <path class="edges-face edges-face-right" d="M${cx - rx},${cy} A${rx},${ry} 0 0,0 ${cx + rx},${cy} L${cx + rx},${cy + sT} A${rx},${ry} 0 0,1 ${cx - rx},${cy + sT} Z"/>
            <ellipse class="edges-face edges-face-top" cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}"/>
            <path class="edges-line${ecKD}" data-edge="KD" d="M${cx - rx},${cy + sT} A${rx},${ry} 0 0,0 ${cx + rx},${cy + sT}" fill="none"/>
            <ellipse class="edges-line${ecKG}" data-edge="KG" cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="none"/>
            <line class="edges-line" x1="${cx - rx}" y1="${cy}" x2="${cx - rx}" y2="${cy + sT}"/>
            <line class="edges-line" x1="${cx + rx}" y1="${cy}" x2="${cx + rx}" y2="${cy + sT}"/>
            ${wyc.svg}
            <g class="edges-labels" id="edgeLabelsGroup">
                <g class="edges-label${ecKG}" data-edge="KG"><circle cx="${cx}" cy="${cy - ry - 14}" r="12"/><text x="${cx}" y="${cy - ry - 10}">KG</text></g>
                <g class="edges-label${ecKD}" data-edge="KD"><circle cx="${cx}" cy="${cy + sT + ry + 14}" r="12"/><text x="${cx}" y="${cy + sT + ry + 18}">KD</text></g>
                ${wyc.etykiety}
            </g>
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

        // Górna powierzchnia (wypełnienie); wycięcia dorysowuje _svgWyciec
        var topPathD = 'M ';
        for (var tpi = 0; tpi < topPts.length; tpi++) {
            topPathD += topPts[tpi].x + ',' + topPts[tpi].y + (tpi < topPts.length - 1 ? ' L ' : '');
        }
        topPathD += ' Z';
        svg += '<path class="edges-face edges-face-top" d="' + topPathD + '"/>';

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

        // Wycięcia z rysunku (wielokąt: G/D/P per bok, elipsa: obwód)
        var wyc = _svgWyciec(shapeData,
            function(x, y) { return project3D(x, y, 0); },
            function(x, y) { return project3D(x, y, effectiveThickness); },
            activeEdges);
        svg += wyc.svg;

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

        svg += wyc.etykiety;

        svg += '</g>';

        svgEl.innerHTML = svg;
    }

    // ==========================================
    // PUBLICZNE API
    // ==========================================

    /**
     * Re-build listy edges w modalu (np. po zmianie holes z canvasu).
     * No-op gdy modal nie jest otwarty.
     */
    function refresh(shapeData, thickness) {
        if (!elements.modal) return;
        // Modal może być otwarty bez klasy open (różne ścieżki) — sprawdzaj display
        var isOpen = elements.modal.classList.contains('open') ||
                     (elements.modal.style.display && elements.modal.style.display !== 'none');
        if (!isOpen) return;
        var th = (typeof thickness === 'number' && thickness > 0) ? thickness : state.dimensions.thickness;
        // Prostokąt i koło mają własne litery obrysu — odświeżamy tylko grupy wycięć
        if (_isRoundShape(state.productShape) || state.productShape === 'rectangular') {
            showCutoutGroupsForSimpleShape(shapeData, th);
            return;
        }
        if (!shapeData || !shapeData.vertices || shapeData.vertices.length < 3) return;
        showDynamicEdgesUI(shapeData, th);
    }

    return {
        init,
        openModal,
        closeModal,
        refresh,
        getState: () => ({ ...state }),
        getSelectedEdges: () => Array.from(state.basic.selectedEdges),
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
        EDGE_GROUPS,
        // Zapis krawędzi bez modalu (synchronizacja z rysunkiem Canvy)
        setFormEdges,
        renderEdgesSummary,
        // qdraft_backup.js woła updateOpenButton(form) po odtworzeniu szkicu
        updateOpenButton: renderEdgesSummary
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
