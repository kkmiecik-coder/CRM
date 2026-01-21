/**
 * Moduł obróbki krawędzi dla kalkulatora WoodPower CRM
 * Wzorowany na woodconfigurator.js z PrestaShop
 */

const EdgesModule = (function() {
    'use strict';

    // ==========================================
    // KONFIGURACJA
    // ==========================================

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
                console.warn('[EdgesModule] Nie udało się pobrać cen z API, używam domyślnych');
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
                console.log('[EdgesModule] Ceny pobrane z bazy danych:', CONFIG.prices);
                console.log('[EdgesModule] Limity R pobrane z bazy danych:', CONFIG.R_LIMITS);
                console.log('[EdgesModule] Kąty fazowania pobrane z bazy danych:', CONFIG.CHAMFER_ANGLES);
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

    // Definicje krawędzi
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

    // Grupy krawędzi
    const EDGE_GROUPS = {
        top: ['A', 'B', 'C', 'D'],
        bottom: ['E', 'F', 'G', 'H'],
        horizontal: ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'],
        corner: ['N1', 'N2', 'N3', 'N4'],
        all: ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'N1', 'N2', 'N3', 'N4']
    };

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
        modalInitialized: false
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
        console.log('[EdgesModule] Rozpoczynam inicjalizację...');

        // Pobierz ceny z API (nie blokuj inicjalizacji)
        loadPricesFromAPI().then(success => {
            if (success) {
                console.log('[EdgesModule] ✅ Ceny załadowane z bazy danych');
            } else {
                console.warn('[EdgesModule] ⚠️ Używam domyślnych cen (API niedostępne)');
            }
        });

        // Zawsze dodaj event listenery dla przycisków (event delegation na document)
        attachGlobalEventListeners();

        // Monitoruj zmiany wymiarów w formularzach
        setupDimensionWatchers();

        // Aktualizuj stan przycisków dla wszystkich formularzy
        updateAllButtonStates();

        console.log('[EdgesModule] ✅ Zainicjalizowany pomyślnie');
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
                console.log('[EdgesModule] Kliknięto przycisk otwierania modalu, formularz:', form);
                openModal(form);
                return;
            }

            // Przycisk Reset krawędzi
            const resetBtn = e.target.closest('.edges-reset-btn');
            if (resetBtn) {
                e.preventDefault();
                const form = resetBtn.closest('.quote-form');
                console.log('[EdgesModule] Kliknięto przycisk reset krawędzi, formularz:', form);
                state.currentForm = form;
                resetEdges();
                return;
            }

            // Przycisk Reset wykończenia
            const finishingResetBtn = e.target.closest('.finishing-reset-btn');
            if (finishingResetBtn) {
                e.preventDefault();
                const form = finishingResetBtn.closest('.quote-form');
                console.log('[EdgesModule] Kliknięto przycisk reset wykończenia, formularz:', form);
                if (typeof window.resetFinishing === 'function') {
                    window.resetFinishing(form);
                } else {
                    console.warn('[EdgesModule] Funkcja resetFinishing nie jest dostępna');
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

        console.log('[EdgesModule] Event listenery globalne zostały dodane');
    }

    /**
     * Dodaje event listenery do elementów wewnątrz modalu
     * Wywoływane tylko raz przy pierwszym otwarciu
     */
    function attachModalEventListeners() {
        if (state.modalInitialized) return;

        console.log('[EdgesModule] Inicjalizuję event listenery modalu...');

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
                console.log('[EdgesModule] Kliknięto ZASTOSUJ');
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
                console.log('[EdgesModule] Quick action:', action);
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
        console.log('[EdgesModule] Event listenery modalu zainicjalizowane');
    }

    // ==========================================
    // MODAL
    // ==========================================

    async function openModal(form) {
        state.currentForm = form || document.querySelector('.quote-form');

        // Sprawdź czy formularz ma wymiary
        if (!formHasAllDimensions(state.currentForm)) {
            console.warn('[EdgesModule] Formularz nie ma wszystkich wymiarów');
            return;
        }

        // Jeśli ceny nie zostały jeszcze załadowane, poczekaj na ich pobranie
        if (!CONFIG.pricesLoaded) {
            console.log('[EdgesModule] Czekam na załadowanie cen z API...');
            await loadPricesFromAPI();
        }

        state.isOpen = true;

        // Jeśli elementy nie były jeszcze zcache'owane, zrób to teraz
        if (!elements.modal) {
            console.log('[EdgesModule] Cache\'uję elementy modalu przy pierwszym otwarciu...');
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
        // To czyści globalny state.selectedEdges i wczytuje dane dla TEGO konkretnego formularza
        // Musi być PRZED generateProportionalSVG(), bo SVG używa state.selectedEdges
        loadSavedState();

        // Wygeneruj proporcjonalny SVG na podstawie wymiarów
        // (generateProportionalSVG używa state.selectedEdges do podświetlenia krawędzi)
        generateProportionalSVG(
            state.dimensions.length,
            state.dimensions.width,
            state.dimensions.thickness
        );

        // Aktualizuj długości krawędzi w UI
        updateEdgeLengths();

        // Pokaż modal
        elements.modal.style.display = 'flex';

        // Przelicz cenę
        calculatePrice();

        console.log('[EdgesModule] Modal otwarty, wymiary:', state.dimensions, 'wybrane krawędzie:', Array.from(state.selectedEdges));
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
        switch (action) {
            case 'select-top':
                // Zamień zaznaczenie na górne krawędzie
                deselectAllEdges();
                selectEdges(EDGE_GROUPS.top);
                break;
            case 'select-bottom':
                // Zamień zaznaczenie na dolne krawędzie
                deselectAllEdges();
                selectEdges(EDGE_GROUPS.bottom);
                break;
            case 'select-all':
                // Zaznacz wszystkie
                selectEdges(EDGE_GROUPS.all);
                break;
            case 'deselect-all':
                deselectAllEdges();
                break;
        }

        calculatePrice();
    }

    function selectEdges(edges) {
        edges.forEach(edge => {
            state.selectedEdges.add(edge);
            const item = document.querySelector(`.edges-item[data-edge="${edge}"]`);
            if (item) {
                const checkbox = item.querySelector('input[type="checkbox"]');
                if (checkbox) checkbox.checked = true;
                item.classList.add('selected');
                updateSvgEdge(edge, true);
            }
        });
    }

    function deselectAllEdges() {
        state.selectedEdges.clear();
        elements.checkboxes.forEach(cb => {
            cb.checked = false;
            cb.closest('.edges-item')?.classList.remove('selected');
        });
        EDGE_GROUPS.all.forEach(edge => updateSvgEdge(edge, false));
    }

    function toggleLabels() {
        state.labelsVisible = !state.labelsVisible;

        if (state.labelsVisible) {
            elements.labelsGroup.classList.remove('edges-labels-hidden');
            elements.toggleLabelsBtn.textContent = 'Ukryj etykiety';
        } else {
            elements.labelsGroup.classList.add('edges-labels-hidden');
            elements.toggleLabelsBtn.textContent = 'Pokaż etykiety';
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

        state.selectedEdges.forEach(edge => {
            const def = EDGES[edge];
            if (!def) return;

            if (def.group === 'corner') {
                // Narożnik - cena za sztukę (z bazy danych)
                totalNetto += pricePerCorner;
                cornerCount++;
            } else {
                // Krawędź pozioma - cena za metr bieżący (z bazy danych)
                const lengthCm = state.dimensions[def.dimension] || 0;
                const lengthMb = lengthCm / 100;  // cm → m
                totalNetto += lengthMb * pricePerMb;
                horizontalCount++;
            }
        });

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

        // Pobierz ceny dla aktualnie wybranego typu obróbki
        const pricePerMb = getPricePerMb(state.edgeType);
        const pricePerCorner = getPricePerCorner(state.edgeType);

        // Zbierz dane o wybranych krawędziach
        const edgesData = [];
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
                console.warn('Nie udało się dopasować viewBox:', e);
            }

            edgesSvg = svgClone.outerHTML;
        }

        // Zapisz w dataset formularza
        state.currentForm.dataset.edgesData = JSON.stringify(edgesData);
        state.currentForm.dataset.edgesNetto = prices.netto;
        state.currentForm.dataset.edgesBrutto = prices.brutto;
        state.currentForm.dataset.edgesCount = state.selectedEdges.size;
        state.currentForm.dataset.edgesType = state.edgeType;
        state.currentForm.dataset.edgesRValue = state.rValue;
        state.currentForm.dataset.edgesAngleValue = state.edgeType === 'chamfer' ? state.angleValue : '';
        state.currentForm.dataset.edgesSvg = edgesSvg;

        // Aktualizuj przycisk
        updateOpenButton(state.currentForm, prices);

        // Wywołaj aktualizację globalnego podsumowania
        if (typeof updateGlobalSummary === 'function') {
            updateGlobalSummary();
        }

        closeModal();
    }

    function updateOpenButton(form, prices) {
        const finishingSection = form.querySelector('.finishing-section');
        if (!finishingSection) return;

        // Szukaj głównego kontenera .options-summary
        let optionsSummary = finishingSection.querySelector('.options-summary');

        // Jeśli nie ma kontenera, utwórz go dynamicznie
        if (!optionsSummary) {
            optionsSummary = document.createElement('div');
            optionsSummary.className = 'options-summary';
            optionsSummary.style.display = 'none';
            optionsSummary.innerHTML = `
                <div class="options-summary-row finishing-row" style="display: none;">
                    <div class="options-summary-content">
                        <span class="options-summary-text finishing-summary-text"></span>
                        <span class="options-summary-price finishing-summary-price"></span>
                        <span class="options-summary-price-netto finishing-summary-price-netto"></span>
                    </div>
                    <button type="button" class="options-reset-btn finishing-reset-btn">Resetuj</button>
                </div>
                <div class="options-summary-row edges-row" style="display: none;">
                    <div class="options-summary-content">
                        <span class="options-summary-text edges-summary-text"></span>
                        <span class="options-summary-price edges-summary-price"></span>
                        <span class="options-summary-price-netto edges-summary-price-netto"></span>
                    </div>
                    <button type="button" class="options-reset-btn edges-reset-btn">Resetuj</button>
                </div>
            `;
            finishingSection.appendChild(optionsSummary);
        }

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
                openBtn.textContent = 'Zmień obróbkę krawędzi';
            }
        } else {
            // Ukryj wiersz krawędzi
            if (edgesRow) edgesRow.style.display = 'none';

            // Przywróć oryginalny tekst przycisku
            if (openBtn) {
                openBtn.textContent = '+ Dodaj obróbkę krawędzi';
            }
        }

        // Aktualizuj widoczność głównego kontenera
        updateOptionsSummaryVisibility(optionsSummary);
    }

    /**
     * Aktualizuje widoczność głównego kontenera options-summary
     */
    function updateOptionsSummaryVisibility(optionsSummary) {
        if (!optionsSummary) return;

        const finishingRow = optionsSummary.querySelector('.finishing-row');
        const edgesRow = optionsSummary.querySelector('.edges-row');

        const finishingVisible = finishingRow && finishingRow.style.display !== 'none';
        const edgesVisible = edgesRow && edgesRow.style.display !== 'none';

        // Dodaj/usuń separator gdy oba wiersze są widoczne
        if (edgesRow) {
            if (finishingVisible && edgesVisible) {
                edgesRow.classList.add('has-separator');
            } else {
                edgesRow.classList.remove('has-separator');
            }
        }

        if (finishingVisible || edgesVisible) {
            optionsSummary.style.display = 'flex';
        } else {
            optionsSummary.style.display = 'none';
        }
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
        const finishingSection = state.currentForm.querySelector('.finishing-section');
        const optionsSummary = finishingSection?.querySelector('.options-summary');
        const edgesRow = optionsSummary?.querySelector('.edges-row');
        if (edgesRow) {
            edgesRow.style.display = 'none';
        }
        updateOptionsSummaryVisibility(optionsSummary);

        // Przywróć oryginalny tekst przycisku
        const openBtn = state.currentForm.querySelector('.open-edges-modal-btn');
        if (openBtn) {
            openBtn.textContent = '+ Dodaj obróbkę krawędzi';
        }

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
            console.log('[EdgesModule] Brak zapisanych krawędzi dla tego formularza - ustawiono domyślne z bazy:', defaultLimits);
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

            console.log('[EdgesModule] Wczytano zapisany stan dla formularza:', Array.from(state.selectedEdges));

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

        const dimensions = {
            length: parseFloat(lengthInput?.value) || 0,
            width: parseFloat(widthInput?.value) || 0,
            thickness: parseFloat(thicknessInput?.value) || 0
        };

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

            edges.forEach(edge => {
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
            });

            const totalBrutto = totalNetto * CONFIG.VAT_RATE;

            // Zaktualizuj dataset formularza
            form.dataset.edgesData = JSON.stringify(updatedEdgesData);
            form.dataset.edgesNetto = Math.round(totalNetto * 100) / 100;
            form.dataset.edgesBrutto = Math.round(totalBrutto * 100) / 100;

            // Zaktualizuj wizualne podsumowanie
            const finishingSection = form.querySelector('.finishing-section');
            const optionsSummary = finishingSection?.querySelector('.options-summary');
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

                if (priceEl) {
                    priceEl.textContent = formatPLN(totalBrutto) + ' brutto';
                }
                if (priceNettoEl) {
                    priceNettoEl.textContent = formatPLN(totalNetto) + ' netto';
                }
            }

            // Wywołaj aktualizację globalnego podsumowania
            if (typeof updateGlobalSummary === 'function') {
                updateGlobalSummary();
            }

            console.log('[EdgesModule] Przeliczono krawędzie dla formularza, nowa cena:', totalBrutto.toFixed(2), 'PLN');

        } catch (e) {
            console.error('[EdgesModule] Błąd przeliczania krawędzi:', e);
        }
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
        // Eksportuj konfigurację dla integracji z save_quote
        CONFIG,
        EDGES,
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
