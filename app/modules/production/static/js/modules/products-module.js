/**
 * products-module.js
 * ========================================================================
 * 
 * Moduł zarządzania listą produktów - restrukturyzacja tab produktów
 * 
 * Odpowiedzialności:
 * - Zaawansowane filtrowanie produktów (text search + 5 multi-select dropdownów)
 * - Proste renderowanie listy produktów (bez virtual scroll)
 * - Drag & drop z animacjami feedback
 * - Akcje grupowe (bulk actions) z modal
 * - Export Excel z opcjami
 * - Auto-refresh hybrydowy zachowujący stan UI
 * - System color coding i urgency indicators
 * // Import drag & drop functionality
 * // ProductsDragDrop will be loaded dynamically
 * 
 * Autor: Konrad Kmiecik
 * Wersja: 2.0 - Przepisany bez virtual scrolling
 * Data: 2025-01-15
 */

class ProductsModule {

    // Mapowanie statusów na przyjazne nazwy
    static STATUS_TRANSLATIONS = {
        'czeka_na_wyciecie': 'Czeka na wycięcie',
        'czeka_na_skladanie': 'Czeka na składanie', 
        'czeka_na_pakowanie': 'Czeka na pakowanie',
        'spakowane': 'Spakowane',
        'wstrzymane': 'Wstrzymane',
        'anulowane': 'Anulowane'
    };

    // Mapowanie statusów na ikony i kolory
    static STATUS_CONFIG = {
        'czeka_na_wyciecie': {
            icon: 'fa-cut',
            displayName: 'Czeka na wycięcie',
            color: 'cutting-theme',
            badgeClass: 'badge-warning'
        },
        'czeka_na_skladanie': {
            icon: 'fa-hammer',
            displayName: 'Czeka na składanie',
            color: 'assembly-theme', 
            badgeClass: 'badge-info'
        },
        'czeka_na_pakowanie': {
            icon: 'fa-box',
            displayName: 'Czeka na pakowanie',
            color: 'packaging-theme',
            badgeClass: 'badge-primary'
        },
        'spakowane': {
            icon: 'fa-check',
            displayName: 'Spakowane',
            color: 'text-success',
            badgeClass: 'badge-success'
        },
        'wstrzymane': {
            icon: 'fa-pause',
            displayName: 'Wstrzymane',
            color: 'text-warning',
            badgeClass: 'badge-warning'
        },
        'anulowane': {
            icon: 'fa-times',
            displayName: 'Anulowane',
            color: 'text-danger',
            badgeClass: 'badge-danger'
        }
    };

    constructor(shared, config) {
        this.shared = shared;
        this.config = config;
        this.isLoaded = false;
        this.templateLoaded = false;

        // Debounce timers
        this.debounceTimers = {
            textSearch: null,
            filtersUpdate: null
        };

        // Filter update timeout for custom multi-selects
        this.filterUpdateTimeout = null;

        // Main components
        this.components = {
            dragDrop: null,
            filters: null,
            modals: null,
            exportTool: null,
            fuzzySearchEngine: null,
            searchCache: new Map()
        };

        // State management
        this.state = {
            // Filtry
            currentFilters: {
                textSearch: '',
                woodSpecies: [],
                technologies: [],
                woodClasses: [],
                thicknesses: [],
                statuses: []
            },

            // Zaznaczone produkty
            selectedProducts: new Set(),

            // Lista i sortowanie
            products: [],
            filteredProducts: [],
            sortColumn: null,
            sortDirection: 'asc',

            // Auto-refresh
            lastUpdate: null,
            refreshInterval: null,

            // UI state
            isRefreshing: false,
            isExporting: false,
            isLoading: false,

            // Statystyki
            stats: {
                totalCount: 0,
                filteredCount: 0,
                totalVolume: 0,
                totalValue: 0,
                statusBreakdown: {}
            }
        };

        // DOM elements
        this.elements = {
            container: null,
            viewport: null,
            loadingState: null,
            emptyState: null,
            errorState: null,
            textSearch: null,
            selectAllCheckbox: null,
            productsCount: null
        };

        // Bound event handlers
        this.onTextSearchInput = this.handleTextSearchInput.bind(this);
        this.onFilterChange = this.handleFilterChange.bind(this);
        this.onProductSelect = this.handleProductSelect.bind(this);
        this.onSelectAll = this.handleSelectAll.bind(this);
        this.onBulkAction = this.handleBulkAction.bind(this);
        this.onExport = this.handleExport.bind(this);
        this.onSort = this.handleSort.bind(this);
        this.onKeydown = this.handleKeydown.bind(this);

        console.log('[ProductsModule] Constructor completed');
    }

    // ========================================================================
    // LIFECYCLE METHODS
    // ========================================================================

    async load() {
        try {
            console.log('[ProductsModule] Loading module...');

            // Inicjalizuj komponenty
            await this.initializeComponents();

            // Setup event listeners
            this.setupEventListeners();

            // Pokaż loading i załaduj produkty z opóźnieniem
            // (loadFiltersData() będzie wywołane po załadowaniu produktów)
            this.showLoadingAndLoadProducts();

            this.isLoaded = true;
            console.log('[ProductsModule] Module loaded successfully');

        } catch (error) {
            console.error('[ProductsModule] Failed to load module:', error);
            this.showErrorState('Nie udało się załadować modułu produktów');
        }
    }

    async unload() {
        try {
            console.log('[ProductsModule] Unloading module...');

            // Wyczyść timery
            Object.values(this.debounceTimers).forEach(timer => {
                if (timer) clearTimeout(timer);
            });

            if (this.state.refreshInterval) {
                clearInterval(this.state.refreshInterval);
            }

            // Usuń event listeners
            this.removeEventListeners();

            // Wyczyść dane
            this.state.products = [];
            this.state.filteredProducts = [];
            this.state.selectedProducts.clear();
            this.components.searchCache.clear();

            // Wyczyść UI
            if (this.elements.viewport) {
                this.elements.viewport.innerHTML = '';
            }

            this.isLoaded = false;
            // Cleanup drag & drop
            if (this.components.dragDrop) {
                this.components.dragDrop.destroy();
                this.components.dragDrop = null;
            }
            console.log('[ProductsModule] Module unloaded');

        } catch (error) {
            console.error('[ProductsModule] Error during unload:', error);
        }
    }

    async refresh() {
        if (this.state.isRefreshing) return;

        try {
            this.state.isRefreshing = true;
            console.log('[ProductsModule] Refreshing data...');

            await this.loadProductsData();
            this.applyAllFilters();
            this.renderProductsList();
            this.updateStats();

            console.log('[ProductsModule] Data refreshed successfully');

        } catch (error) {
            console.error('[ProductsModule] Failed to refresh data:', error);
        } finally {
            this.state.isRefreshing = false;
        }
    }

    destroy() {
        this.unload();
        // Destroy drag & drop
        if (this.components.dragDrop) {
            this.components.dragDrop.destroy();
            this.components.dragDrop = null;
        }
        this.components = null;
        this.state = null;
        this.elements = null;
        console.log('[ProductsModule] Module destroyed');
    }

    // ========================================================================
    // INITIALIZATION METHODS
    // ========================================================================

    async initializeComponents() {
        try {
            console.log('[ProductsModule] Initializing components...');

            // Pobierz elementy DOM
            this.elements = {
                container: document.getElementById('virtual-scroll-container'),
                viewport: document.getElementById('virtual-scroll-viewport'),
                loadingState: document.getElementById('products-loading'),
                emptyState: document.getElementById('products-empty-state'),
                errorState: document.getElementById('products-error-state'),
                textSearch: document.getElementById('products-text-search'),
                selectAllCheckbox: document.getElementById('select-all-products'),
                productsCount: document.getElementById('products-count')
            };

            // Walidacja kluczowych elementów
            if (!this.elements.container || !this.elements.viewport) {
                throw new Error('Required DOM elements not found');
            }

            // Ukryj spacery - nie potrzebujemy ich dla prostego renderowania
            const spacerTop = document.getElementById('virtual-scroll-spacer-top');
            const spacerBottom = document.getElementById('virtual-scroll-spacer-bottom');
            if (spacerTop) spacerTop.style.display = 'none';
            if (spacerBottom) spacerBottom.style.display = 'none';

            // Ustaw CSS dla prostego renderowania
            this.elements.container.style.overflow = 'auto';
            this.elements.container.style.maxHeight = '70vh';
            this.elements.viewport.style.position = 'relative';
            this.elements.viewport.style.display = 'block';

            // Inicjalizuj fuzzy search
            this.initializeFuzzySearch();

            // Inicjalizuj filtry badges
            this.initializeFilterBadges();

            // Inicjalizuj drag & drop
            this.initializeDragDrop();

            console.log('[ProductsModule] Components initialized');
            return true;

        } catch (error) {
            console.error('[ProductsModule] Failed to initialize components:', error);
            return false;
        }
    }

    initializeFuzzySearch() {
        // Prosty fuzzy search engine z Levenshtein distance
        this.components.fuzzySearchEngine = {
            search: (query, items, options = {}) => {
                if (!query || query.length < 2) return items;

                const threshold = options.threshold || 3; // max distance
                const fields = options.fields || ['original_product_name', 'short_product_id', 'client_name'];

                return items.filter(item => {
                    return fields.some(field => {
                        const value = item[field];
                        if (!value) return false;
                        
                        const distance = this.calculateLevenshteinDistance(
                            query.toLowerCase(),
                            value.toString().toLowerCase()
                        );
                        
                        return distance <= threshold || value.toString().toLowerCase().includes(query.toLowerCase());
                    });
                });
            }
        };
    }

    calculateLevenshteinDistance(a, b) {
        if (a.length === 0) return b.length;
        if (b.length === 0) return a.length;

        const matrix = [];

        for (let i = 0; i <= b.length; i++) {
            matrix[i] = [i];
        }

        for (let j = 0; j <= a.length; j++) {
            matrix[0][j] = j;
        }

        for (let i = 1; i <= b.length; i++) {
            for (let j = 1; j <= a.length; j++) {
                if (b.charAt(i - 1) === a.charAt(j - 1)) {
                    matrix[i][j] = matrix[i - 1][j - 1];
                } else {
                    matrix[i][j] = Math.min(
                        matrix[i - 1][j - 1] + 1,
                        matrix[i][j - 1] + 1,
                        matrix[i - 1][j] + 1
                    );
                }
            }
        }

        return matrix[b.length][a.length];
    }

    initializeFilterBadges() {
        this.badgesConfig = {
            badgesWrapper: document.getElementById('active-filters-container'),
            badgesContainer: document.getElementById('filter-badges'),
            clearAllBtn: document.getElementById('clear-all-filters'),
            activeFiltersCount: 0
        };

        // DEBUG: Sprawdź czy elementy zostały znalezione
        console.log('[ProductsModule] Initialize filter badges:', {
            badgesWrapper: !!this.badgesConfig.badgesWrapper,
            badgesContainer: !!this.badgesConfig.badgesContainer,
            clearAllBtn: !!this.badgesConfig.clearAllBtn
        });

        if (this.badgesConfig.clearAllBtn) {
            this.badgesConfig.clearAllBtn.addEventListener('click', () => {
                this.clearAllFilters();
            });
        }

        // Also setup clear filters button in empty state
        const clearFiltersEmpty = document.getElementById('clear-filters-empty');
        if (clearFiltersEmpty) {
            clearFiltersEmpty.addEventListener('click', () => {
                this.clearAllFilters();
            });
        }

        // Jeśli elementy nie zostały znalezione, spróbuj ponownie za chwilę
        if (!this.badgesConfig.badgesWrapper || !this.badgesConfig.badgesContainer) {
            console.warn('[ProductsModule] Badges elements not found during init, will retry...');
            setTimeout(() => {
                this.retryInitializeFilterBadges();
            }, 1000);
        }
    }

    retryInitializeFilterBadges() {
        console.log('[ProductsModule] Retrying filter badges initialization...');
        
        const wrapper = document.getElementById('active-filters-container');
        const container = document.getElementById('filter-badges');
        const clearBtn = document.getElementById('clear-all-filters');
        
        if (wrapper && container) {
            this.badgesConfig.badgesWrapper = wrapper;
            this.badgesConfig.badgesContainer = container;
            this.badgesConfig.clearAllBtn = clearBtn;
            
            console.log('[ProductsModule] Filter badges elements found on retry');
            
            if (clearBtn && !clearBtn.hasAttribute('data-listener-added')) {
                clearBtn.addEventListener('click', () => {
                    this.clearAllFilters();
                });
                clearBtn.setAttribute('data-listener-added', 'true');
            }
        } else {
            console.error('[ProductsModule] Filter badges elements still not found after retry');
        }
    }

    updateFilterBadges() {
        console.log('[ProductsModule] Updating filter badges...');
        
        // Jeśli elementy nie są zainicjalizowane, spróbuj je znaleźć
        if (!this.badgesConfig.badgesWrapper || !this.badgesConfig.badgesContainer) {
            console.log('[ProductsModule] Badges config missing, searching for elements...');
            this.badgesConfig.badgesWrapper = document.getElementById('active-filters-container');
            this.badgesConfig.badgesContainer = document.getElementById('filter-badges');
            this.badgesConfig.clearAllBtn = document.getElementById('clear-all-filters');
        }
        
        // DEBUG: Sprawdź czy elementy istnieją
        console.log('[ProductsModule] DEBUG badges elements:', {
            badgesWrapper: !!this.badgesConfig.badgesWrapper,
            badgesContainer: !!this.badgesConfig.badgesContainer,
            clearAllBtn: !!this.badgesConfig.clearAllBtn,
            wrapperElement: document.getElementById('active-filters-container'),
            containerElement: document.getElementById('filter-badges')
        });
        
        if (!this.badgesConfig.badgesContainer) {
            console.error('[ProductsModule] Badges container still not found!');
            return;
        }

        // Wyczyść istniejące badges
        this.badgesConfig.badgesContainer.innerHTML = '';
        console.log('[ProductsModule] Cleared existing badges');

        let badgeCount = 0;

        // Badge dla text search
        if (this.state.currentFilters.textSearch) {
            console.log('[ProductsModule] Adding text search badge:', this.state.currentFilters.textSearch);
            this.addFilterBadge('textSearch', `Szukaj: "${this.state.currentFilters.textSearch}"`);
            badgeCount++;
        }

        // Badges dla multi-select filtrów
        const multiSelectFilters = {
            woodSpecies: 'Gatunek',
            technologies: 'Technologia',
            woodClasses: 'Klasa',
            thicknesses: 'Grubość',
            statuses: 'Status'
        };

        Object.entries(multiSelectFilters).forEach(([filterKey, label]) => {
            const values = this.state.currentFilters[filterKey];
            if (values && values.length > 0) {
                console.log(`[ProductsModule] Adding ${filterKey} badges:`, values);
                values.forEach(value => {
                    const displayValue = filterKey === 'statuses' ? this.getStatusDisplayName(value) : value;
                    this.addFilterBadge(filterKey, `${label}: ${displayValue}`, value);
                    badgeCount++;
                });
            }
        });

        // WAŻNE: Pokaż/ukryj container - FORCE FIX
        const wrapper = document.getElementById('active-filters-container');
        if (wrapper) {
            const shouldShow = badgeCount > 0;
            wrapper.style.display = shouldShow ? 'block' : 'none';
            console.log(`[ProductsModule] FORCE: Set wrapper display to ${shouldShow ? 'flex' : 'none'}, badges count: ${badgeCount}`);
            
            // Aktualizuj też config
            this.badgesConfig.badgesWrapper = wrapper;
        } else {
            console.error('[ProductsModule] Cannot find active-filters-container element!');
        }

        // Stara logika dla porównania
        if (this.badgesConfig.badgesWrapper) {
            const shouldShow = badgeCount > 0;
            this.badgesConfig.badgesWrapper.style.display = shouldShow ? 'flex' : 'none';
            console.log(`[ProductsModule] CONFIG: Badges container display set to: ${shouldShow ? 'flex' : 'none'}, badges count: ${badgeCount}`);
        } else {
            console.error('[ProductsModule] this.badgesConfig.badgesWrapper is null!');
        }

        this.badgesConfig.activeFiltersCount = badgeCount;
        
        console.log(`[ProductsModule] Filter badges updated: ${badgeCount} badges created`);
    }

    addFilterBadge(filterType, text, value = null) {
        if (!this.badgesConfig.badgesContainer) return;

        const badge = document.createElement('span');
        badge.className = 'filter-badge';
        badge.setAttribute('data-filter-type', filterType);
        badge.setAttribute('data-filter-value', value || text);
        
        badge.innerHTML = `
            <span class="filter-badge-label">${text}</span>
            <i class="fas fa-times remove-filter"></i>
        `;

        // Event listener dla usuwania badge
        const removeBtn = badge.querySelector('.remove-filter');
        removeBtn.addEventListener('click', () => {
            this.removeFilterBadge(filterType, value || text);
        });

        this.badgesConfig.badgesContainer.appendChild(badge);
    }

    removeFilterBadge(filterType, value) {
        console.log(`[ProductsModule] Removing filter badge: ${filterType} - ${value}`);

        if (filterType === 'text') {
            this.state.currentFilters.textSearch = '';
            if (this.elements.textSearch) {
                this.elements.textSearch.value = '';
            }
        } else {
            // Remove from multi-select array
            const currentValues = this.state.currentFilters[filterType] || [];
            this.state.currentFilters[filterType] = currentValues.filter(v => v !== value);
            
            // Update the custom multi-select display
            this.updateCustomMultiSelectFromState(filterType, value, false);
        }

        // Zastosuj filtry
        this.applyAllFilters();
        this.renderProductsList();
        this.updateStats();
    }

    updateCustomMultiSelectFromState(filterType, value, isSelected) {
        // Find the corresponding dropdown
        const dropdownMapping = {
            woodSpecies: 'dropdown-wood-species',
            technologies: 'dropdown-technology', 
            woodClasses: 'dropdown-wood-class',
            thicknesses: 'dropdown-thickness',
            statuses: 'dropdown-status'
        };

        const dropdownId = dropdownMapping[filterType];
        if (!dropdownId) return;

        const dropdown = document.getElementById(dropdownId);
        if (!dropdown) return;

        // Find and update the checkbox
        const checkboxes = dropdown.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(checkbox => {
            if (checkbox.value === value) {
                checkbox.checked = isSelected;
            }
        });

        // Update display and select all state
        const displayId = dropdownId.replace('dropdown-', 'filter-');
        this.updateMultiSelectDisplay(displayId, filterType);
        this.updateSelectAllState(dropdown);
    }

    clearAllFilters() {
        console.log('[ProductsModule] Clearing all filters...');

        // Reset text search
        this.state.currentFilters.textSearch = '';
        if (this.elements.textSearch) {
            this.elements.textSearch.value = '';
        }

        // Reset multi-select filters
        this.state.currentFilters.woodSpecies = [];
        this.state.currentFilters.technologies = [];
        this.state.currentFilters.woodClasses = [];
        this.state.currentFilters.thicknesses = [];
        this.state.currentFilters.statuses = [];

        // Clear all custom multi-select checkboxes
        const allDropdowns = document.querySelectorAll('.multi-select-dropdown');
        allDropdowns.forEach(dropdown => {
            const checkboxes = dropdown.querySelectorAll('input[type="checkbox"]');
            checkboxes.forEach(checkbox => {
                checkbox.checked = false;
            });
        });

        // Update all displays
        const displays = ['filter-wood-species', 'filter-technology', 'filter-wood-class', 'filter-thickness', 'filter-status'];
        displays.forEach(displayId => {
            const placeholder = document.querySelector(`#${displayId} .multi-select-placeholder`);
            if (placeholder) {
                placeholder.textContent = 'Wszystkie';
                placeholder.className = 'multi-select-placeholder';
            }
        });

        // WAŻNE: Aktualizuj badges po wyczyszczeniu filtrów
        this.updateFilterBadges();

        // Zastosuj filtry
        this.applyAllFilters();
        this.renderProductsList();
        this.updateStats();
    }

    initializeDragDrop() {
        try {
            if (typeof ProductsDragDrop === 'undefined') {
                console.warn('[ProductsModule] ProductsDragDrop class not available');
                this.components.dragDrop = null;
                return false;
            }
            
            this.components.dragDrop = new ProductsDragDrop(this);
            const initialized = this.components.dragDrop.initialize();
            
            if (initialized) {
                console.log('[ProductsModule] Drag & Drop initialized successfully');
            } else {
                console.error('[ProductsModule] Failed to initialize Drag & Drop');
                this.components.dragDrop = null;
            }
            
            return initialized;
        } catch (error) {
            console.error('[ProductsModule] Error initializing Drag & Drop:', error);
            this.components.dragDrop = null;
            return false;
        }
    }

    // ========================================================================
    // EVENT LISTENERS SETUP
    // ========================================================================

    setupEventListeners() {
        console.log('[ProductsModule] Setting up event listeners...');

        // Text search
        if (this.elements.textSearch) {
            this.elements.textSearch.addEventListener('input', this.onTextSearchInput);
            this.elements.textSearch.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    this.elements.textSearch.value = '';
                    this.handleTextSearchInput();
                }
            });
        }

        // Select all checkbox
        if (this.elements.selectAllCheckbox) {
            this.elements.selectAllCheckbox.addEventListener('change', this.onSelectAll);
        }

        // Sortowanie nagłówków
        const sortableHeaders = document.querySelectorAll('.sortable-header');
        sortableHeaders.forEach(header => {
            header.addEventListener('click', this.onSort);
            header.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    this.onSort(e);
                }
            });
        });

        // Bulk actions event listeners
        this.setupBulkActionsEventListeners();

        // Keyboard shortcuts
        document.addEventListener('keydown', this.onKeydown);

        console.log('[ProductsModule] Event listeners setup completed');
    }

    setupBulkActionsEventListeners() {
        console.log('[ProductsModule] Setting up bulk actions event listeners...');

        // Bulk change status
        const bulkChangeStatus = document.getElementById('bulk-change-status');
        if (bulkChangeStatus) {
            bulkChangeStatus.addEventListener('click', (e) => {
                e.stopPropagation(); // ← DODAJ TĘ LINIĘ
                this.handleBulkAction('change-status');
            });
        }

        // Bulk export selected
        const bulkExportSelected = document.getElementById('bulk-export-selected');
        if (bulkExportSelected) {
            bulkExportSelected.addEventListener('click', () => {
                this.handleBulkAction('export-selected');
            });
        }

        // Bulk delete
        const bulkDelete = document.getElementById('bulk-delete');
        if (bulkDelete) {
            bulkDelete.addEventListener('click', () => {
                this.handleBulkAction('delete');
            });
        }

        // NOTE: Przycisk "Ustaw priorytet" (#bulk-set-priority) powinien zostać
        // usunięty z HTML template products-tab-content.html

        console.log('[ProductsModule] Bulk actions event listeners setup completed');
    }

    removeEventListeners() {
        if (this.elements.textSearch) {
            this.elements.textSearch.removeEventListener('input', this.onTextSearchInput);
        }

        if (this.elements.selectAllCheckbox) {
            this.elements.selectAllCheckbox.removeEventListener('change', this.onSelectAll);
        }

        const sortableHeaders = document.querySelectorAll('.sortable-header');
        sortableHeaders.forEach(header => {
            header.removeEventListener('click', this.onSort);
        });

        // Remove bulk actions event listeners
        const bulkChangeStatus = document.getElementById('bulk-change-status');
        const bulkExportSelected = document.getElementById('bulk-export-selected');
        const bulkDelete = document.getElementById('bulk-delete');

        if (bulkChangeStatus) {
            bulkChangeStatus.replaceWith(bulkChangeStatus.cloneNode(true));
        }
        if (bulkExportSelected) {
            bulkExportSelected.replaceWith(bulkExportSelected.cloneNode(true));
        }
        if (bulkDelete) {
            bulkDelete.replaceWith(bulkDelete.cloneNode(true));
        }

        document.removeEventListener('keydown', this.onKeydown);
    }

    // ========================================================================
    // DATA LOADING METHODS
    // ========================================================================

    async showLoadingAndLoadProducts() {
        try {
            console.log('[ProductsModule] Starting loading sequence...');

            // Pokaż loading state
            this.showLoadingState();

            // Opóźnienie dla UX - tab się otwiera natychmiast, potem loading
            await new Promise(resolve => setTimeout(resolve, 800));

            // Załaduj dane produktów
            await this.loadProductsData();

            // Załaduj opcje filtrów (po załadowaniu produktów)
            await this.loadFiltersData();

            // Zastosuj filtry i wyrenderuj
            this.applyAllFilters();
            this.renderProductsList();
            this.updateStats();

            // Ukryj loading
            this.hideAllStates();

            console.log('[ProductsModule] Loading sequence completed');

        } catch (error) {
            console.error('[ProductsModule] Failed to load products:', error);
            this.showErrorState('Nie udało się załadować listy produktów');
        }
    }

    async loadProductsData() {
        try {
            console.log('[ProductsModule] Loading products data...');

            // Użyj shared service jeśli dostępne
            if (this.shared && this.shared.apiClient) {
                console.log('[ProductsModule] Using shared API client');

                const filtersForApi = {
                    status: this.state.currentFilters.statuses.length > 0 ?
                        this.state.currentFilters.statuses[0] : 'all',
                    search: this.state.currentFilters.textSearch || '',
                    // DODAJ SORTOWANIE:
                    sort_by: 'priority_rank',    // NOWE: domyślnie sortuj po priority_rank
                    sort_order: 'asc',           // NOWE: rosnąco (1,2,3,4...)
                    load_all: 'true'
                };

                const data = await this.shared.apiClient.getProductsTabContent(filtersForApi);

                if (data.success && data.initial_data && data.initial_data.products) {
                    this.state.products = data.initial_data.products;
                    this.state.lastUpdate = new Date().toISOString();

                } else {
                    throw new Error(data.message || 'Failed to load products data from shared service');
                }
            } else {
                // Fallback - bezpośrednie wywołanie GET
                console.log('[ProductsModule] Using direct GET request');

                const params = new URLSearchParams({
                    status: this.state.currentFilters.statuses.length > 0 ?
                        this.state.currentFilters.statuses[0] : 'all',
                    search: this.state.currentFilters.textSearch || '',
                    // DODAJ SORTOWANIE:
                    sort_by: 'priority_rank',    // NOWE: domyślnie sortuj po priority_rank  
                    sort_order: 'asc',           // NOWE: rosnąco (1,2,3,4...)
                    load_all: 'true'
                });

                // ZMIANA: Użyj /products-filtered zamiast /products-tab-content
                const response = await fetch(`/production/api/products-filtered?${params.toString()}`, {
                    method: 'GET',
                    headers: {
                        'Content-Type': 'application/json',
                    }
                });

                if (!response.ok) {
                    throw new Error(`API request failed: ${response.status}`);
                }

                const data = await response.json();

                if (data.success && data.products) {
                    this.state.products = data.products;  // ZMIANA: data.products zamiast data.initial_data.products
                    this.state.lastUpdate = new Date().toISOString();

                    console.log(`[ProductsModule] Loaded ${data.products.length} products via direct GET`);
                } else {
                    throw new Error(data.message || 'Failed to load products data');
                }
            }

        } catch (error) {
            console.error('[ProductsModule] Error loading products data:', error);
            throw error;
        }
    }

    async loadFiltersData() {
        try {
            console.log('[ProductsModule] Loading filters data...');

            // TODO: Endpoint /products/filters-data będzie dodany w kolejnych krokach
            // Tymczasowo - ekstraktuj opcje filtrów z załadowanych produktów
            if (this.state.products.length > 0) {
                const filtersData = this.extractFiltersFromProducts(this.state.products);
                this.updateFilterOptions(filtersData);
                this.setupMultiSelectFilters();
                console.log('[ProductsModule] Filter options extracted from products');
            } else {
                console.log('[ProductsModule] No products loaded yet, skipping filters data');
            }

        } catch (error) {
            console.error('[ProductsModule] Error loading filters data:', error);
            // Nie przerywa ładowania, filtry będą działać z dostępnymi opcjami
        }
    }

    extractFiltersFromProducts(products) {
        const filters = {
            woodSpecies: new Set(),
            technologies: new Set(),
            woodClasses: new Set(),
            thicknesses: new Set(),
            statuses: new Set()
        };

        products.forEach(product => {
            if (product.parsed_wood_species) filters.woodSpecies.add(product.parsed_wood_species);
            if (product.parsed_technology) filters.technologies.add(product.parsed_technology);
            if (product.parsed_wood_class) filters.woodClasses.add(product.parsed_wood_class);
            if (product.parsed_thickness_cm) filters.thicknesses.add(product.parsed_thickness_cm + 'cm');
            if (product.current_status) filters.statuses.add(product.current_status);
        });

        return {
            woodSpecies: Array.from(filters.woodSpecies).sort(),
            technologies: Array.from(filters.technologies).sort(),
            woodClasses: Array.from(filters.woodClasses).sort(),
            thicknesses: Array.from(filters.thicknesses).sort((a, b) => parseFloat(a) - parseFloat(b)),
            statuses: Array.from(filters.statuses).sort()
        };
    }

    setupMultiSelectFilters() {
        console.log('[ProductsModule] Setting up custom multi-select filters...');

        // Wood species filter
        this.setupCustomMultiSelect('filter-wood-species', 'dropdown-wood-species', 'woodSpecies');
        
        // Technology filter
        this.setupCustomMultiSelect('filter-technology', 'dropdown-technology', 'technologies');
        
        // Wood class filter
        this.setupCustomMultiSelect('filter-wood-class', 'dropdown-wood-class', 'woodClasses');
        
        // Thickness filter
        this.setupCustomMultiSelect('filter-thickness', 'dropdown-thickness', 'thicknesses');
        
        // Status filter
        this.setupCustomMultiSelect('filter-status', 'dropdown-status', 'statuses');

        // Close dropdowns when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.multi-select-wrapper')) {
                this.closeAllDropdowns();
            }
        });
    }

    setupCustomMultiSelect(displayId, dropdownId, filterType) {
        const display = document.getElementById(displayId);
        const dropdown = document.getElementById(dropdownId);
        
        if (!display || !dropdown) {
            console.warn(`[ProductsModule] Multi-select elements not found: ${displayId}, ${dropdownId}`);
            return;
        }

        // Toggle dropdown on display click
        display.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleDropdown(dropdownId);
        });

        // Search within dropdown
        const searchInput = dropdown.querySelector('.multi-select-search input');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.filterDropdownOptions(dropdownId, e.target.value);
            });
        }

        // "Select all" functionality
        const selectAllOption = dropdown.querySelector('.multi-select-all input');
        if (selectAllOption) {
            selectAllOption.addEventListener('change', (e) => {
                this.handleSelectAllChange(dropdownId, filterType, e.target.checked);
            });
        }
    }

    toggleDropdown(dropdownId) {
        // Close all other dropdowns first
        this.closeAllDropdowns();
        
        const dropdown = document.getElementById(dropdownId);
        if (dropdown) {
            const isOpen = dropdown.classList.contains('show');
            dropdown.classList.toggle('show', !isOpen);
            
            // Update arrow direction
            const display = dropdown.parentElement.querySelector('.multi-select-display');
            const arrow = display?.querySelector('.multi-select-arrow');
            if (arrow) {
                arrow.classList.toggle('fa-chevron-up', !isOpen);
                arrow.classList.toggle('fa-chevron-down', isOpen);
            }
        }
    }

    closeAllDropdowns() {
        const dropdowns = document.querySelectorAll('.multi-select-dropdown');
        dropdowns.forEach(dropdown => {
            dropdown.classList.remove('show');
        });
        
        // Reset all arrows
        const arrows = document.querySelectorAll('.multi-select-arrow');
        arrows.forEach(arrow => {
            arrow.classList.remove('fa-chevron-up');
            arrow.classList.add('fa-chevron-down');
        });
    }

    filterDropdownOptions(dropdownId, searchTerm) {
        const dropdown = document.getElementById(dropdownId);
        if (!dropdown) return;

        const options = dropdown.querySelectorAll('.multi-select-option:not(.multi-select-all)');
        const searchLower = searchTerm.toLowerCase();

        options.forEach(option => {
            const label = option.querySelector('label');
            if (label) {
                const text = label.textContent.toLowerCase();
                const matches = text.includes(searchLower);
                option.style.display = matches ? 'flex' : 'none';
            }
        });
    }

    handleSelectAllChange(dropdownId, filterType, isChecked) {
        const dropdown = document.getElementById(dropdownId);
        if (!dropdown) return;

        const options = dropdown.querySelectorAll('.multi-select-option:not(.multi-select-all) input[type="checkbox"]');
        const visibleOptions = Array.from(options).filter(option => 
            option.closest('.multi-select-option').style.display !== 'none'
        );

        visibleOptions.forEach(checkbox => {
            checkbox.checked = isChecked;
            this.handleOptionChange(filterType, checkbox.value, isChecked);
        });

        this.updateMultiSelectDisplay(dropdownId.replace('dropdown-', 'filter-'), filterType);
        
        // WAŻNE: Aktualizuj badges po "select all"
        this.updateFilterBadges();
        
        this.applyAllFilters();
        this.renderProductsList();
        this.updateStats();
    }

    handleOptionChange(filterType, value, isChecked) {
        if (!this.state.currentFilters[filterType]) {
            this.state.currentFilters[filterType] = [];
        }

        if (isChecked) {
            if (!this.state.currentFilters[filterType].includes(value)) {
                this.state.currentFilters[filterType].push(value);
            }
        } else {
            this.state.currentFilters[filterType] = this.state.currentFilters[filterType].filter(v => v !== value);
        }
    }

    updateMultiSelectDisplay(displayId, filterType) {
        const display = document.getElementById(displayId);
        const placeholder = display?.querySelector('.multi-select-placeholder');
        
        if (!placeholder) return;

        const selectedValues = this.state.currentFilters[filterType] || [];
        
        if (selectedValues.length === 0) {
            placeholder.textContent = 'Wszystkie';
            placeholder.className = 'multi-select-placeholder';
        } else if (selectedValues.length === 1) {
            placeholder.textContent = selectedValues[0];
            placeholder.className = 'multi-select-placeholder selected';
        } else {
            placeholder.textContent = `Wybrano ${selectedValues.length}`;
            placeholder.className = 'multi-select-placeholder selected';
        }
    }

    updateFilterOptions(filtersData) {
        console.log('[ProductsModule] Updating custom multi-select options:', filtersData);
        
        // Update wood species options
        this.populateCustomDropdown('dropdown-wood-species', 'woodSpecies', filtersData.woodSpecies);
        
        // Update technology options
        this.populateCustomDropdown('dropdown-technology', 'technologies', filtersData.technologies);
        
        // Update wood class options
        this.populateCustomDropdown('dropdown-wood-class', 'woodClasses', filtersData.woodClasses);
        
        // Update thickness options  
        this.populateCustomDropdown('dropdown-thickness', 'thicknesses', filtersData.thicknesses);
        
        // Update status options with friendly names
        const statusOptions = filtersData.statuses.map(status => ({
            value: status,
            label: this.getStatusDisplayName(status)
        }));
        this.populateCustomDropdown('dropdown-status', 'statuses', statusOptions);
    }

    populateCustomDropdown(dropdownId, filterType, options) {
        const dropdown = document.getElementById(dropdownId);
        if (!dropdown) {
            console.warn(`[ProductsModule] Dropdown not found: ${dropdownId}`);
            return;
        }

        const optionsContainer = dropdown.querySelector('.multi-select-options');
        if (!optionsContainer) {
            console.warn(`[ProductsModule] Options container not found in: ${dropdownId}`);
            return;
        }

        // Preserve the "select all" option
        const selectAllOption = optionsContainer.querySelector('.multi-select-all');
        
        // Clear existing options (except select all)
        const existingOptions = optionsContainer.querySelectorAll('.multi-select-option:not(.multi-select-all)');
        existingOptions.forEach(option => option.remove());

        // Add new options
        options.forEach((option, index) => {
            const optionElement = this.createCustomOption(option, filterType, index);
            optionsContainer.appendChild(optionElement);
        });

        console.log(`[ProductsModule] Populated ${options.length} options for ${dropdownId}`);
    }

    createCustomOption(option, filterType, index) {
        const optionDiv = document.createElement('div');
        optionDiv.className = 'multi-select-option';

        let value, label;
        if (typeof option === 'string') {
            value = option;
            label = option;
        } else {
            value = option.value;
            label = option.label;
        }

        const optionId = `${filterType}-${index}`;
        
        optionDiv.innerHTML = `
            <input type="checkbox" id="${optionId}" value="${value}">
            <label for="${optionId}">${label}</label>
        `;

        // Add event listener for this option
        const checkbox = optionDiv.querySelector('input[type="checkbox"]');
        checkbox.addEventListener('change', (e) => {
            this.handleOptionChange(filterType, value, e.target.checked);
            
            // Get the correct display ID from the dropdown
            const dropdown = optionDiv.closest('.multi-select-dropdown');
            const dropdownId = dropdown.id;
            const displayId = dropdownId.replace('dropdown-', 'filter-');
            
            this.updateMultiSelectDisplay(displayId, filterType);
            this.updateSelectAllState(dropdown);
            
            // WAŻNE: Aktualizuj badges po zmianie filtra
            this.updateFilterBadges();
            
            // Apply filters after a short delay to allow for multiple selections
            clearTimeout(this.filterUpdateTimeout);
            this.filterUpdateTimeout = setTimeout(() => {
                this.applyAllFilters();
                this.renderProductsList();
                this.updateStats();
            }, 150);
        });

        return optionDiv;
    }

    updateSelectAllState(dropdown) {
        const selectAllCheckbox = dropdown.querySelector('.multi-select-all input[type="checkbox"]');
        const allOptions = dropdown.querySelectorAll('.multi-select-option:not(.multi-select-all) input[type="checkbox"]');
        const visibleOptions = Array.from(allOptions).filter(cb => 
            cb.closest('.multi-select-option').style.display !== 'none'
        );
        
        if (selectAllCheckbox && visibleOptions.length > 0) {
            const checkedCount = visibleOptions.filter(cb => cb.checked).length;
            
            if (checkedCount === 0) {
                selectAllCheckbox.checked = false;
                selectAllCheckbox.indeterminate = false;
            } else if (checkedCount === visibleOptions.length) {
                selectAllCheckbox.checked = true;
                selectAllCheckbox.indeterminate = false;
            } else {
                selectAllCheckbox.checked = false;
                selectAllCheckbox.indeterminate = true;
            }
        }
    }

    // ========================================================================
    // SIMPLE LIST RENDERING (NO VIRTUAL SCROLL)
    // ========================================================================

    renderProductsList() {
        try {
            console.log('[ProductsModule] Rendering products list...');
            
            if (!this.elements.viewport) {
                throw new Error('Viewport element not found');
            }

            // Wyczyść viewport
            this.elements.viewport.innerHTML = '';

            const products = this.state.filteredProducts;

            if (!products || products.length === 0) {
                this.showEmptyState();
                return;
            }

            // Utwórz fragment dla lepszej wydajności
            const fragment = document.createDocumentFragment();

            // Renderuj wszystkie produkty naraz
            products.forEach((product, index) => {
                const rowElement = this.createProductRow(product, index);
                if (rowElement) {
                    fragment.appendChild(rowElement);
                }
            });

            // Dodaj wszystkie wiersze do viewport
            this.elements.viewport.appendChild(fragment);

            // Aktualizuj licznik produktów
            this.updateProductsCount(products.length);

            // Synchronizuj checkboxy
            this.syncAllCheckboxes();

            console.log(`[ProductsModule] Rendered ${products.length} products`);

        } catch (error) {
            console.error('[ProductsModule] Error rendering products list:', error);
            this.showErrorState('Wystąpił błąd podczas renderowania listy produktów');
        }
    }

    createProductRow(product, index) {
        try {
            const template = document.getElementById('product-row-template');
            if (!template) {
                throw new Error('Product row template not found');
            }

            const clone = template.content.cloneNode(true);
            // ZMIANA: używamy nowej klasy z prefiksem prod_list-
            const rowElement = clone.querySelector('.prod_list-product-row');

            if (!rowElement) {
                throw new Error('Product row element not found in template');
            }

            // Ustaw podstawowe właściwości dla prostego renderowania
            rowElement.style.position = 'relative';
            rowElement.style.width = '100%';
            rowElement.style.minHeight = '65px';
            rowElement.style.marginBottom = '6px';
            rowElement.classList.add('simple-row');
            rowElement.setAttribute('data-product-id', product.id);
            rowElement.setAttribute('data-priority', product.priority_rank || product.priority_score || 0);
            rowElement.setAttribute('data-status', product.current_status || '');
            rowElement.setAttribute('data-index', index);

            // Wypełnij dane produktu
            this.populateProductRow(rowElement, product);

            // Dodaj event listeners
            this.attachRowEventListeners(rowElement, product);

            return rowElement;

        } catch (error) {
            console.error(`[ProductsModule] Error creating row for product ${product.id}:`, error);
            return null;
        }
    }

    populateProductRow(rowElement, product) {
        try {
            // Checkbox - NOWA KLASA
            const checkbox = rowElement.querySelector('.prod_list-product-checkbox');
            if (checkbox) {
                checkbox.checked = this.state.selectedProducts.has(product.id);
                checkbox.setAttribute('data-product-id', product.id);
            }

            // Priority rank (nie priority_score!) - NOWA KLASA
            const priorityElement = rowElement.querySelector('.prod_list-priority-rank');
            if (priorityElement) {
                // ZMIANA: używamy priority_rank zamiast priority_score
                const priority = parseInt(product.priority_rank) || parseInt(product.priority_score) || 100;
                priorityElement.textContent = priority;
            }

            // Product Name - NOWA KLASA
            const nameElement = rowElement.querySelector('.prod_list-product-name');
            if (nameElement) {
                nameElement.textContent = product.original_product_name || 'Brak nazwy';
            }

            // Product ID - NOWA KLASA
            const idElement = rowElement.querySelector('.prod_list-product-id');
            if (idElement) {
                idElement.textContent = `ID: ${product.short_product_id || product.id}`;
            }

            // Baselinker Order - NOWA KLASA
            const baselinkerElement = rowElement.querySelector('.prod_list-baselinker-order');
            if (baselinkerElement) {
                baselinkerElement.textContent = product.baselinker_order_id ?
                    `Baselinker: ${product.baselinker_order_id}` : '';
            }

            // Tags/Specs - NOWA KLASA
            const tagsElement = rowElement.querySelector('.prod_list-tags-cell');
            if (tagsElement) {
                tagsElement.innerHTML = this.generateProductTags(product);
            }

            // Volume - NOWA KLASA
            const volumeElement = rowElement.querySelector('.prod_list-volume-value');
            if (volumeElement) {
                const volume = parseFloat(product.volume_m3) || 0;
                volumeElement.textContent = `${volume.toFixed(3)} m³`;
            }

            // Value - NOWA KLASA
            const valueElement = rowElement.querySelector('.prod_list-currency-value');
            if (valueElement) {
                const value = parseFloat(product.total_value_net) || 0;
                valueElement.textContent = value.toLocaleString('pl-PL', {
                    style: 'currency',
                    currency: 'PLN',
                    minimumFractionDigits: 2
                });
            }

            // Status - NOWA KLASA
            const statusElement = rowElement.querySelector('.prod_list-status-badge');
            if (statusElement) {
                const statusConfig = this.getStatusConfig(product.current_status);
                statusElement.textContent = statusConfig.displayName;

                // ZMIANA: Używaj mapowania statusów na klasy CSS
                const statusClass = this.getStatusCSSClass(product.current_status);
                statusElement.className = `prod_list-status-badge ${statusClass}`;
            }

            // Deadline - NOWE KLASY
            const deadlineBadge = rowElement.querySelector('.prod_list-deadline-badge');
            const deadlineDate = rowElement.querySelector('.prod_list-deadline-date');

            if (deadlineBadge && deadlineDate) {
                const daysUntil = this.calculateDaysUntilDeadline(product.deadline_date);
                if (daysUntil !== null) {
                    deadlineBadge.textContent = this.getDeadlineLabel(daysUntil);
                    
                    // POPRAWKA: Używaj tylko klasy z prod_list- prefiksem
                    const deadlineClass = this.getDeadlineClass(daysUntil);
                    deadlineBadge.className = `prod_list-deadline-badge ${deadlineClass}`;

                    const deadlineFormatted = new Date(product.deadline_date).toLocaleDateString('pl-PL');
                    deadlineDate.textContent = deadlineFormatted;
                } else {
                    deadlineBadge.textContent = 'Brak';
                    deadlineBadge.className = 'prod_list-deadline-badge normal';
                    deadlineDate.textContent = '';
                }
            }

        } catch (error) {
            console.error('[ProductsModule] Error populating product row:', error);
        }
    }

    confirmDeleteProduct(product) {
        console.log(`[ProductsModule] Confirming delete for product ${product.id}`);
        
        const confirmMessage = `Czy na pewno chcesz usunąć produkt?\n\n${product.original_product_name}\nID: ${product.short_product_id}\n\nTa operacja jest nieodwracalna.`;
        
        if (confirm(confirmMessage)) {
            console.log(`Confirmed delete for product ${product.id}`);
            // TODO: Implementacja API call delete w przyszłych krokach
            this.deleteProduct(product.id);
        }
    }

    async deleteProduct(productId) {
        try {
            console.log(`[ProductsModule] Deleting product ${productId}...`);
            
            // TODO: Implementacja API call w przyszłych krokach
            alert(`Produkt ${productId} zostanie usunięty\n(Implementacja API delete endpoint w kolejnych krokach)`);
            
            // Tymczasowo usuń z lokalnego state
            this.state.products = this.state.products.filter(p => p.id != productId);
            this.state.filteredProducts = this.state.filteredProducts.filter(p => p.id != productId);
            this.state.selectedProducts.delete(productId);
            
            // Przerenderuj listę
            this.renderProductsList();
            this.updateStats();
            this.toggleBulkActionsVisibility();
            
            if (this.shared?.toastSystem) {
                this.shared.toastSystem.show(`Produkt został usunięty`, 'success', 3000);
            }
            
        } catch (error) {
            console.error('[ProductsModule] Error deleting product:', error);
            
            if (this.shared?.toastSystem) {
                this.shared.toastSystem.show(`Błąd usuwania produktu: ${error.message}`, 'error', 5000);
            } else {
                alert(`Błąd usuwania produktu: ${error.message}`);
            }
        }
    }

    getStatusCSSClass(status) {
        const statusClassMap = {
            'czeka_na_wyciecie': 'cutting',
            'w_trakcie_ciecia': 'cutting',
            'czeka_na_skladanie': 'assembly',
            'w_trakcie_skladania': 'assembly',
            'czeka_na_pakowanie': 'packaging',
            'w_trakcie_pakowania': 'packaging',
            'spakowane': 'completed',
            'wstrzymane': 'paused',
            'anulowane': 'cancelled'
        };

        return statusClassMap[status] || 'paused'; // default
    }

    generateProductTags(product) {
        const tags = [];

        // Species badge - używaj parsowanych pól
        if (product.parsed_wood_species) {
            const species = product.parsed_wood_species.toLowerCase();
            let speciesClass = 'prod_list-tag';

            switch (species) {
                case 'dąb':
                case 'oak':
                    speciesClass += ' species-oak';
                    break;
                case 'jesion':
                case 'ash':
                    speciesClass += ' species-ash';
                    break;
                case 'sosna':
                case 'pine':
                    speciesClass += ' species-pine';
                    break;
                case 'buk':
                case 'beech':
                    speciesClass += ' species-beech';
                    break;
                default:
                    speciesClass += ' species-oak'; // default
            }

            tags.push(`<span class="${speciesClass}">${product.parsed_wood_species.toUpperCase()}</span>`);
        }

        // Technology badge
        if (product.parsed_technology) {
            const tech = product.parsed_technology.toLowerCase();
            let techClass = 'prod_list-tag';

            switch (tech) {
                case 'lity':
                case 'lita':
                    techClass += ' tech-solid';
                    break;
                case 'mikrowczep':
                    techClass += ' tech-microchip';
                    break;
                case 'klejony':
                case 'klejona':
                    techClass += ' tech-laminated';
                    break;
                default:
                    techClass += ' tech-solid';
            }

            tags.push(`<span class="${techClass}">${product.parsed_technology.toUpperCase()}</span>`);
        }

        // Wood class badge
        if (product.parsed_wood_class) {
            const woodClass = product.parsed_wood_class.replace('/', '').toLowerCase();
            let classClass = 'prod_list-tag';

            switch (woodClass) {
                case 'aa':
                    classClass += ' class-aa';
                    break;
                case 'ab':
                    classClass += ' class-ab';
                    break;
                case 'bb':
                    classClass += ' class-bb';
                    break;
                default:
                    classClass += ' class-aa';
            }

            tags.push(`<span class="${classClass}">${product.parsed_wood_class}</span>`);
        }

        // Thickness badge
        if (product.parsed_thickness_cm) {
            tags.push(`<span class="prod_list-tag thickness">${product.parsed_thickness_cm}cm</span>`);
        }

        return tags.join(' ');
    }

    getDeadlineLabel(daysUntil) {
        // NAPRAWIONE - poprawne obliczenie deadline
        if (daysUntil < 0) return 'Opóźnione';
        if (daysUntil === 0) return 'Dziś';
        if (daysUntil === 1) return 'Jutro';
        if (daysUntil <= 7) return `${daysUntil} dni`;
        if (daysUntil <= 30) return `${Math.ceil(daysUntil / 7)} tyg.`;
        return `${Math.ceil(daysUntil / 30)} mies.`;
    }

    calculateDaysUntilDeadline(deadlineDate) {
        if (!deadlineDate) return null;
        
        const deadline = new Date(deadlineDate);
        const today = new Date();
        
        // Ustaw oba na środek dnia dla poprawnego porównania
        deadline.setHours(12, 0, 0, 0);
        today.setHours(12, 0, 0, 0);
        
        const diffTime = deadline.getTime() - today.getTime();
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        
        return diffDays;
    }

    attachRowEventListeners(rowElement, product) {
        try {
            // Checkbox - NOWA KLASA
            const checkbox = rowElement.querySelector('.prod_list-product-checkbox');
            if (checkbox) {
                checkbox.addEventListener('change', (e) => {
                    e.stopPropagation();
                    this.handleProductSelect(product.id, e.target.checked);
                });
            }

            // Details button - NOWA KLASA
            const detailsBtn = rowElement.querySelector('.prod_list-details-btn');
            if (detailsBtn) {
                detailsBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.showProductDetails(product.id);
                });
            }

            // Baselinker button - NOWA KLASA
            const baselinkerBtn = rowElement.querySelector('.prod_list-baselinker-btn');
            if (baselinkerBtn) {
                baselinkerBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (product.baselinker_order_id) {
                        const baselinkerUrl = `https://panel.baselinker.com/orders.php?order_id=${product.baselinker_order_id}`;
                        window.open(baselinkerUrl, '_blank');
                    }
                });
            }

            // Delete button - NOWA KLASA
            const deleteBtn = rowElement.querySelector('.prod_list-delete-btn');
            if (deleteBtn) {
                deleteBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.confirmDeleteProduct(product);
                });
            }

            // Priority element - klikalne
            const priorityElement = rowElement.querySelector('.prod_list-priority-rank');
            if (priorityElement) {
                priorityElement.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.showEditPriorityModal(product);
                });
            }

            // Row click - cały wiersz
            rowElement.addEventListener('click', (e) => {
                // Nie reaguj jeśli kliknięto w input, button lub link
                if (e.target.matches('input, button, a, svg, path')) {
                    return;
                }
                
                this.showProductDetails(product.id);
            });

        } catch (error) {
            console.error('[ProductsModule] Error attaching row listeners:', error);
        }
    }

    showProductEditModal(productId) {
        console.log(`[ProductsModule] Showing edit modal for product ${productId}`);
        // TODO: Implementacja w kroku 6 - Modal edycji produktu
        alert(`Edycja produktu ${productId}\n(Implementacja w kroku 6 - Modals i akcje grupowe)`);
    }

    showProductDeleteConfirmation(productId) {
        console.log(`[ProductsModule] Showing delete confirmation for product ${productId}`);
        
        if (confirm('Czy na pewno chcesz usunąć ten produkt?\n\nTa operacja jest nieodwracalna.')) {
            console.log(`Confirmed delete for product ${productId}`);
            // TODO: Implementacja API call delete w przyszłych krokach
            alert(`Produkt ${productId} zostanie usunięty\n(Implementacja API delete endpoint w kolejnych krokach)`);
        }
    }

    // ========================================================================
    // FILTERING METHODS
    // ========================================================================

    applyAllFilters() {
        try {
            console.log('[ProductsModule] Applying all filters...');
            
            let filtered = [...this.state.products];

            // Text search z fuzzy matching
            if (this.state.currentFilters.textSearch) {
                filtered = this.components.fuzzySearchEngine.search(
                    this.state.currentFilters.textSearch,
                    filtered,
                    {
                        fields: ['original_product_name', 'short_product_id', 'client_name'],
                        threshold: 2
                    }
                );
            }

            // Multi-select filtry (gdy będą zaimplementowane)
            filtered = this.applyMultiSelectFilters(filtered);

            this.state.filteredProducts = filtered;
            this.updateFilterBadges();

            console.log(`[ProductsModule] Filters applied. ${filtered.length}/${this.state.products.length} products match`);

        } catch (error) {
            console.error('[ProductsModule] Error applying filters:', error);
            this.state.filteredProducts = [...this.state.products];
        }
    }

    applyMultiSelectFilters(products) {
        let filtered = products;

        // Wood species filter
        if (this.state.currentFilters.woodSpecies.length > 0) {
            filtered = filtered.filter(p => 
                p.parsed_wood_species && this.state.currentFilters.woodSpecies.includes(p.parsed_wood_species)
            );
        }

        // Technology filter
        if (this.state.currentFilters.technologies.length > 0) {
            filtered = filtered.filter(p => 
                p.parsed_technology && this.state.currentFilters.technologies.includes(p.parsed_technology)
            );
        }

        // Wood class filter
        if (this.state.currentFilters.woodClasses.length > 0) {
            filtered = filtered.filter(p => 
                p.parsed_wood_class && this.state.currentFilters.woodClasses.includes(p.parsed_wood_class)
            );
        }

        // Thickness filter - POPRAWIONE - porównanie z jednostkami
        if (this.state.currentFilters.thicknesses.length > 0) {
            filtered = filtered.filter(p => {
                if (!p.parsed_thickness_cm) return false;
                const thicknessWithUnit = p.parsed_thickness_cm + 'cm';
                return this.state.currentFilters.thicknesses.includes(thicknessWithUnit);
            });
        }

        // Status filter
        if (this.state.currentFilters.statuses.length > 0) {
            filtered = filtered.filter(p => 
                p.current_status && this.state.currentFilters.statuses.includes(p.current_status)
            );
        }

        return filtered;
    }

    clearAllFilters() {
        console.log('[ProductsModule] Clearing all filters...');

        // Reset text search
        this.state.currentFilters.textSearch = '';
        if (this.elements.textSearch) {
            this.elements.textSearch.value = '';
        }

        // Reset multi-select filters
        this.state.currentFilters.woodSpecies = [];
        this.state.currentFilters.technologies = [];
        this.state.currentFilters.woodClasses = [];
        this.state.currentFilters.thicknesses = [];
        this.state.currentFilters.statuses = [];

        // Zastosuj filtry
        this.applyAllFilters();
        this.renderProductsList();
        this.updateStats();
    }

    // ========================================================================
    // EVENT HANDLERS
    // ========================================================================

    handleTextSearchInput(e) {
        const query = e ? e.target.value : this.elements.textSearch?.value || '';
        
        // Debounce search
        if (this.debounceTimers.textSearch) {
            clearTimeout(this.debounceTimers.textSearch);
        }

        this.debounceTimers.textSearch = setTimeout(() => {
            console.log(`[ProductsModule] Text search: "${query}"`);
            
            this.state.currentFilters.textSearch = query;
            
            // DEBUG: Sprawdź czy updateFilterBadges() jest wywoływane
            try {
                console.log('[ProductsModule] About to call updateFilterBadges()...');
                this.updateFilterBadges();
                console.log('[ProductsModule] updateFilterBadges() completed');
            } catch (error) {
                console.error('[ProductsModule] Error in updateFilterBadges():', error);
            }
            
            this.applyAllFilters();
            this.renderProductsList();
            this.updateStats();
        }, 300);
    }

    handleFilterChange(filterType, values) {
        console.log(`[ProductsModule] Filter changed: ${filterType}`, values);
        
        this.state.currentFilters[filterType] = Array.isArray(values) ? values : [values];
        
        // Debounce filters update
        if (this.debounceTimers.filtersUpdate) {
            clearTimeout(this.debounceTimers.filtersUpdate);
        }

        this.debounceTimers.filtersUpdate = setTimeout(() => {
            this.applyAllFilters();
            this.renderProductsList();
            this.updateStats();
        }, 150);
    }

    handleProductSelect(productId, isChecked) {
        console.log(`[ProductsModule] Product ${productId} selected: ${isChecked}`);
        
        if (isChecked) {
            this.state.selectedProducts.add(productId);
        } else {
            this.state.selectedProducts.delete(productId);
        }

        // Aktualizuj select all checkbox
        this.updateSelectAllCheckbox();
        
        // Pokaż/ukryj bulk actions
        this.toggleBulkActionsVisibility();
    }

    handleSelectAll(e) {
        const isChecked = e.target.checked;
        console.log(`[ProductsModule] Select all: ${isChecked}`);

        if (isChecked) {
            // Zaznacz wszystkie przefiltrowane produkty
            this.state.filteredProducts.forEach(product => {
                this.state.selectedProducts.add(product.id);
            });
        } else {
            // Odznacz wszystkie
            this.state.selectedProducts.clear();
        }

        // POPRAWKA: Aktualizuj checkboxy w wierszach z NOWĄ KLASĄ
        const productCheckboxes = document.querySelectorAll('.prod_list-product-checkbox');
        productCheckboxes.forEach(checkbox => {
            checkbox.checked = isChecked;
            const productId = parseInt(checkbox.getAttribute('data-product-id'));
            if (productId) {
                if (isChecked) {
                    this.state.selectedProducts.add(productId);
                } else {
                    this.state.selectedProducts.delete(productId);
                }
            }
        });

        // Pokaż/ukryj bulk actions
        this.toggleBulkActionsVisibility();
    }

    handleSort(e) {
        const column = e.currentTarget.getAttribute('data-sort');
        if (!column) return;

        console.log(`[ProductsModule] Sorting by: ${column}`);

        // Zmień kierunek sortowania
        if (this.state.sortColumn === column) {
            this.state.sortDirection = this.state.sortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            this.state.sortColumn = column;
            this.state.sortDirection = 'asc';
        }

        // Sortuj produkty
        this.sortProducts();
        this.renderProductsList();
        this.updateSortIndicators();
    }

    handleKeydown(e) {
        // Ctrl+A - Select all
        if (e.ctrlKey && e.key === 'a' && !e.target.matches('input, textarea')) {
            e.preventDefault();
            if (this.elements.selectAllCheckbox) {
                this.elements.selectAllCheckbox.checked = true;
                this.handleSelectAll({ target: this.elements.selectAllCheckbox });
            }
        }

        // Ctrl+E - Export
        if (e.ctrlKey && e.key === 'e') {
            e.preventDefault();
            this.handleExport();
        }

        // Escape - Clear selection
        if (e.key === 'Escape') {
            this.state.selectedProducts.clear();
            this.syncAllCheckboxes();
            this.toggleBulkActionsVisibility();
        }
    }

    handleBulkAction(actionType) {
        console.log(`[ProductsModule] Bulk action: ${actionType}`);
        
        const selectedIds = Array.from(this.state.selectedProducts);
        if (selectedIds.length === 0) {
            alert('Nie wybrano żadnych produktów');
            return;
        }

        switch (actionType) {
            case 'change-status':
                this.showBulkStatusChangeDropdown(selectedIds);
                break;
            case 'export-selected':
                this.handleExportSelected(selectedIds);
                break;
            case 'delete':
                this.showBulkDeleteConfirmation(selectedIds);
                break;
            default:
                console.warn(`Unknown bulk action: ${actionType}`);
        }
    }

    showBulkStatusChangeDropdown(selectedIds) {
        console.log('[ProductsModule] Showing bulk status change dropdown', selectedIds);
        
        // Remove existing dropdown if present
        const existingDropdown = document.getElementById('bulk-status-dropdown');
        if (existingDropdown) {
            existingDropdown.remove();
        }
        
        const statuses = [
            { value: 'czeka_na_wyciecie', label: 'Czeka na wycięcie' },
            { value: 'w_trakcie_ciecia', label: 'W trakcie cięcia' },
            { value: 'czeka_na_skladanie', label: 'Czeka na składanie' },
            { value: 'w_trakcie_skladania', label: 'W trakcie składania' },
            { value: 'czeka_na_pakowanie', label: 'Czeka na pakowanie' },
            { value: 'w_trakcie_pakowania', label: 'W trakcie pakowania' },
            { value: 'spakowane', label: 'Spakowane' },
            { value: 'wstrzymane', label: 'Wstrzymane' },
            { value: 'anulowane', label: 'Anulowane' }
        ];

        const dropdownHtml = `
            <div class="bulk-status-dropdown" id="bulk-status-dropdown">
                <div class="dropdown-header">
                    <strong>Zmień status dla ${selectedIds.length} produktów:</strong>
                    <button class="btn-close" id="close-status-dropdown" aria-label="Zamknij"></button>
                </div>
                <div class="dropdown-body">
                    ${statuses.map(status => `
                        <button class="dropdown-item status-item" data-status="${status.value}">
                            <span class="status-badge ${this.getStatusClass(status.value)}">${status.label}</span>
                        </button>
                    `).join('')}
                </div>
            </div>
        `;

        // Get bulk actions bar position
        const bulkActionsBar = document.getElementById('bulk-actions-bar');
        if (!bulkActionsBar) return;

        // Insert dropdown above bulk actions bar
        bulkActionsBar.insertAdjacentHTML('beforebegin', dropdownHtml);
        
        const dropdown = document.getElementById('bulk-status-dropdown');
        
        // Position dropdown
        this.positionBulkStatusDropdown(dropdown, bulkActionsBar);
        
        // Add event listeners
        this.setupBulkStatusDropdownEvents(dropdown, selectedIds);
        
        // Show dropdown with animation
        setTimeout(() => {
            dropdown.classList.add('show');
        }, 10);
        
        // Close on outside click
        document.addEventListener('click', this.closeBulkStatusDropdownOnOutsideClick.bind(this), { once: true });
    }

    positionBulkStatusDropdown(dropdown, bulkActionsBar) {
        const barRect = bulkActionsBar.getBoundingClientRect();
        
        dropdown.style.cssText = `
            position: fixed;
            bottom: ${window.innerHeight - barRect.top + 10}px;
            left: ${barRect.left}px;
            right: ${window.innerWidth - barRect.right}px;
            z-index: 1050;
            background: white;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            opacity: 0;
            transform: translateY(10px);
            transition: all 0.2s ease;
            max-height: 300px;
            overflow-y: auto;
        `;
    }

    setupBulkStatusDropdownEvents(dropdown, selectedIds) {
        // Close button
        const closeBtn = dropdown.querySelector('#close-status-dropdown');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                this.closeBulkStatusDropdown();
            });
        }
        
        // Status items
        const statusItems = dropdown.querySelectorAll('.status-item');
        statusItems.forEach(item => {
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                const newStatus = item.dataset.status;
                this.executeBulkStatusChange(selectedIds, newStatus);
            });
        });
    }

    closeBulkStatusDropdownOnOutsideClick(e) {
        const dropdown = document.getElementById('bulk-status-dropdown');
        if (dropdown && !dropdown.contains(e.target)) {
            this.closeBulkStatusDropdown();
        }
    }

    closeBulkStatusDropdown() {
        const dropdown = document.getElementById('bulk-status-dropdown');
        if (dropdown) {
            dropdown.classList.remove('show');
            setTimeout(() => {
                dropdown.remove();
            }, 200);
        }
    }

    executeBulkStatusChange(selectedIds, newStatus) {
        console.log(`[ProductsModule] Changing status to ${newStatus} for ${selectedIds.length} products`);
        
        // Close dropdown
        this.closeBulkStatusDropdown();
        
        // TODO: Implementacja API call w przyszłych krokach
        const statusName = this.getStatusDisplayName(newStatus);
        alert(`Status zostanie zmieniony na "${statusName}" dla ${selectedIds.length} produktów\n(Implementacja API w kolejnych krokach)`);
    }

    handleExportSelected(selectedIds) {
        console.log(`[ProductsModule] Export selected: ${selectedIds.length} products`);
        
        if (this.state.isExporting) return;
        
        this.state.isExporting = true;
        
        // TODO: Implementacja exportu Excel w kroku 7
        alert(`Export ${selectedIds.length} produktów do Excel\n(Implementacja w kroku 7 - Export Excel)`);
        
        setTimeout(() => {
            this.state.isExporting = false;
        }, 1000);
    }

    showBulkDeleteConfirmation(selectedIds) {
        console.log(`[ProductsModule] Showing delete confirmation for ${selectedIds.length} products`);
        
        const confirmMessage = `Czy na pewno chcesz usunąć ${selectedIds.length} produktów?\n\nTa operacja jest nieodwracalna.`;
        
        if (confirm(confirmMessage)) {
            console.log(`Confirmed delete for ${selectedIds.length} products`);
            // TODO: Implementacja API call delete w przyszłych krokach
            alert(`${selectedIds.length} produktów zostanie usuniętych\n(Implementacja API delete endpoint w kolejnych krokach)`);
        }
    }

    handleExport() {
        console.log('[ProductsModule] Starting export...');
        
        if (this.state.isExporting) return;
        
        this.state.isExporting = true;
        
        // Placeholder - implementacja w kolejnych krokach
        setTimeout(() => {
            alert('Export będzie zaimplementowany w kolejnych krokach');
            this.state.isExporting = false;
        }, 1000);
    }

    // ========================================================================
    // UI STATE MANAGEMENT
    // ========================================================================

    showLoadingState() {
        this.hideAllStates();
        if (this.elements.loadingState) {
            this.elements.loadingState.style.display = 'flex';
        }
        this.state.isLoading = true;
    }

    showEmptyState() {
        this.hideAllStates();
        if (this.elements.emptyState) {
            this.elements.emptyState.style.display = 'block';
        }
    }

    showErrorState(message) {
        this.hideAllStates();
        if (this.elements.errorState) {
            this.elements.errorState.style.display = 'block';
            const messageEl = this.elements.errorState.querySelector('#error-message');
            if (messageEl) {
                messageEl.textContent = message || 'Wystąpił nieoczekiwany błąd';
            }
        }
    }

    hideAllStates() {
        const states = [this.elements.loadingState, this.elements.emptyState, this.elements.errorState];
        states.forEach(state => {
            if (state) state.style.display = 'none';
        });
        this.state.isLoading = false;
    }

    updateProductsCount(count) {
        const countElement = document.querySelector('.products-count, .prod_list-products-count');
        if (countElement) {
            countElement.textContent = count;
        }

        const titleElement = document.querySelector('.products-section-title, .prod_list-section-title');
        if (titleElement) {
            titleElement.textContent = `Produkty (${count})`;
        }
    }

    syncAllCheckboxes() {
        const checkboxes = this.elements.viewport?.querySelectorAll('.prod_list-product-checkbox');
        if (checkboxes) {
            checkboxes.forEach(checkbox => {
                const productId = parseInt(checkbox.getAttribute('data-product-id'));
                checkbox.checked = this.state.selectedProducts.has(productId);
            });
        }
        
        this.updateSelectAllCheckbox();
    }

    initializeSelectAllCheckbox() {
        const selectAllCheckbox = document.getElementById('select-all-products'); // Zachowaj ID
        if (selectAllCheckbox) {
            selectAllCheckbox.addEventListener('change', (e) => {
                const isChecked = e.target.checked;

                // Znajdź wszystkie checkboxy produktów z NOWĄ KLASĄ
                const productCheckboxes = document.querySelectorAll('.prod_list-product-checkbox');

                productCheckboxes.forEach(checkbox => {
                    checkbox.checked = isChecked;
                    const productId = parseInt(checkbox.getAttribute('data-product-id'));
                    if (productId) {
                        if (isChecked) {
                            this.state.selectedProducts.add(productId);
                        } else {
                            this.state.selectedProducts.delete(productId);
                        }
                    }
                });

                // Emit event o zmianie selekcji
                this.shared.eventBus.emit('products:selection-changed', {
                    selectedProducts: Array.from(this.state.selectedProducts),
                    selectAll: isChecked
                });
            });
        }
    }

    updateSelectAllCheckbox() {
        if (!this.elements.selectAllCheckbox) return;

        const filteredCount = this.state.filteredProducts.length;
        const selectedCount = this.state.filteredProducts.filter(p => 
            this.state.selectedProducts.has(p.id)
        ).length;

        if (selectedCount === 0) {
            this.elements.selectAllCheckbox.checked = false;
            this.elements.selectAllCheckbox.indeterminate = false;
        } else if (selectedCount === filteredCount) {
            this.elements.selectAllCheckbox.checked = true;
            this.elements.selectAllCheckbox.indeterminate = false;
        } else {
            this.elements.selectAllCheckbox.checked = false;
            this.elements.selectAllCheckbox.indeterminate = true;
        }
    }

    toggleBulkActionsVisibility() {
        const selectedCount = this.state.selectedProducts.size;
        const bulkActionsBar = document.getElementById('bulk-actions-bar');
        
        if (bulkActionsBar) {
            if (selectedCount > 0) {
                bulkActionsBar.style.display = 'flex';
                const countSpan = document.getElementById('bulk-selected-count');
                if (countSpan) {
                    countSpan.textContent = selectedCount;
                }
            } else {
                bulkActionsBar.style.display = 'none';
            }
        }
    }

    updateSortIndicators() {
        const headers = document.querySelectorAll('.sortable-header');
        headers.forEach(header => {
            const column = header.getAttribute('data-sort');
            const icon = header.querySelector('i');
            
            if (icon) {
                icon.className = 'fas';
                
                if (column === this.state.sortColumn) {
                    if (this.state.sortDirection === 'asc') {
                        icon.classList.add('fa-sort-up');
                    } else {
                        icon.classList.add('fa-sort-down');
                    }
                } else {
                    icon.classList.add('fa-sort');
                }
            }
        });
    }

    // ========================================================================
    // SORTING & STATISTICS
    // ========================================================================

    sortProducts() {
        if (!this.state.sortColumn) return;

        this.state.filteredProducts.sort((a, b) => {
            let aVal = a[this.state.sortColumn];
            let bVal = b[this.state.sortColumn];

            // Handle different data types
            if (typeof aVal === 'string') {
                aVal = aVal.toLowerCase();
                bVal = bVal.toLowerCase();
            } else if (typeof aVal === 'number') {
                aVal = aVal || 0;
                bVal = bVal || 0;
            } else if (aVal instanceof Date) {
                aVal = aVal.getTime();
                bVal = bVal.getTime();
            }

            let result = 0;
            if (aVal < bVal) result = -1;
            else if (aVal > bVal) result = 1;

            return this.state.sortDirection === 'desc' ? -result : result;
        });
    }

    updateStats() {
        const products = this.state.filteredProducts;
        
        this.state.stats = {
            totalCount: this.state.products.length,
            filteredCount: products.length,
            totalVolume: products.reduce((sum, p) => sum + (parseFloat(p.volume_m3) || 0), 0),
            totalValue: products.reduce((sum, p) => sum + (parseFloat(p.total_value_net) || 0), 0),
            statusBreakdown: this.calculateStatusBreakdown(products)
        };

        // Aktualizuj UI statystyk
        this.updateStatsDisplay();
    }

    calculateStatusBreakdown(products) {
        const breakdown = {};
        products.forEach(product => {
            const status = product.current_status || 'unknown';
            breakdown[status] = (breakdown[status] || 0) + 1;
        });
        return breakdown;
    }

    updateStatsDisplay() {
        // Aktualizuj liczniki w UI - POPRAWIONE SELEKTORY
        const totalCountEl = document.getElementById('stats-total-count');
        const volumeEl = document.getElementById('stats-total-volume');
        const valueEl = document.getElementById('stats-total-value');
        const urgentEl = document.getElementById('stats-urgent-count');

        if (totalCountEl) totalCountEl.textContent = this.state.stats.filteredCount;
        if (volumeEl) volumeEl.textContent = this.state.stats.totalVolume.toFixed(3);
        if (valueEl) {
            valueEl.textContent = this.state.stats.totalValue.toLocaleString('pl-PL', {
                minimumFractionDigits: 0,
                maximumFractionDigits: 0
            });
        }

        // Oblicz pilne produkty (deadline <= 3 dni)
        const urgentCount = this.state.filteredProducts.filter(p => {
            if (!p.deadline_date) return false;
            const deadline = new Date(p.deadline_date);
            const today = new Date();
            const diffTime = deadline.getTime() - today.getTime();
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
            return diffDays <= 3;
        }).length;

        if (urgentEl) urgentEl.textContent = urgentCount;
    }

    // ========================================================================
    // COLOR CODING & UI HELPERS
    // ========================================================================

    getWoodSpeciesClass(species) {
        const speciesMap = {
            'Dąb': 'wood-species-dab',
            'Jesion': 'wood-species-jesion',
            'Buk': 'wood-species-buk',
            'Sosna': 'wood-species-sosna',
            'Świerk': 'wood-species-swierk'
        };
        return speciesMap[species] || 'wood-species-unknown';
    }

    getTechnologyClass(technology) {
        const technologyMap = {
            'Lity': 'technology-lity',
            'Mikrowczep': 'technology-mikrowczep',
            'Klejony': 'technology-klejony'
        };
        return technologyMap[technology] || 'technology-unknown';
    }

    getWoodClassClass(woodClass) {
        const classMap = {
            'A/A': 'wood-class-aa',
            'A/B': 'wood-class-ab',
            'B/B': 'wood-class-bb',
            'C/C': 'wood-class-cc'
        };
        return classMap[woodClass] || 'wood-class-unknown';
    }

    getStatusClass(status) {
        const statusMap = {
            'czeka_na_wyciecie': 'status-waiting',
            'w_trakcie_ciecia': 'status-cutting',
            'czeka_na_skladanie': 'status-waiting',
            'w_trakcie_skladania': 'status-assembly',
            'czeka_na_pakowanie': 'status-waiting',
            'w_trakcie_pakowania': 'status-packaging',
            'spakowane': 'status-completed',
            'anulowane': 'status-cancelled',
            'wstrzymane': 'status-paused'
        };
        return statusMap[status] || 'status-unknown';
    }

    getStatusDisplayName(status) {
        const statusNames = {
            'czeka_na_wyciecie': 'Czeka na wycięcie',
            'w_trakcie_ciecia': 'W trakcie cięcia',
            'czeka_na_skladanie': 'Czeka na składanie',
            'w_trakcie_skladania': 'W trakcie składania',
            'czeka_na_pakowanie': 'Czeka na pakowanie',
            'w_trakcie_pakowania': 'W trakcie pakowania',
            'spakowane': 'Spakowane',
            'anulowane': 'Anulowane',
            'wstrzymane': 'Wstrzymane'
        };
        return statusNames[status] || status;
    }

    getDeadlineClass(daysUntilDeadline) {
        if (daysUntilDeadline < 0) return 'urgent';
        if (daysUntilDeadline <= 1) return 'urgent';
        if (daysUntilDeadline <= 7) return 'warning';
        return 'normal';
    }

    updatePriorityColor(element, priority) {
        const score = parseInt(priority) || 100;
        element.className = 'priority-score';
        
        if (score >= 180) element.classList.add('priority-critical');
        else if (score >= 140) element.classList.add('priority-high');
        else if (score >= 80) element.classList.add('priority-medium');
        else element.classList.add('priority-low');
    }

    // ========================================================================
    // MODAL SZCZEGÓŁÓW PRODUKTU
    // ========================================================================

    /**
     * Pokazuje modal szczegółów produktu - REDESIGNED VERSION
     * @param {number} productId ID produktu
     */
    showProductDetails(productId) {
        console.log(`[ProductsModule] Showing details for product ${productId}`);
        
        // Znajdź produkt
        const product = this.state.filteredProducts.find(p => p.id == productId) || 
                    this.state.products.find(p => p.id == productId);
        
        if (!product) {
            alert('Nie znaleziono produktu');
            return;
        }
        
        // Usuń poprzedni modal
        const existingModal = document.getElementById('product-details-modal');
        if (existingModal) existingModal.remove();
        
        // Sklonuj template
        const template = document.getElementById('product-details-modal-template');
        const clone = template.content.cloneNode(true);
        
        // Wypełnij dane
        this.populateProductDetailsModal(clone, product);
        
        // Dodaj do DOM i pokaż
        document.body.appendChild(clone);
        const modal = new bootstrap.Modal(document.getElementById('product-details-modal'));
        modal.show();
        
        // Załaduj produkty z zamówienia (asynchronicznie)
        this.loadOrderProducts(productId);
        
        // Cleanup
        document.getElementById('product-details-modal').addEventListener('hidden.bs.modal', () => {
            document.getElementById('product-details-modal').remove();
        });
    }

    /**
     * Wypełnia modal szczegółów produktu - REDESIGNED VERSION
     * @param {DocumentFragment} modalElement Klonowany template modala
     * @param {Object} product Dane produktu
     */
    populateProductDetailsModal(modalElement, product) {
        try {
            console.log('[ProductsModule] Populating redesigned modal with product data:', product);

            // === HEADER ===
            const titleElement = modalElement.querySelector('.product-id-display');
            if (titleElement) {
                titleElement.textContent = product.short_product_id || `#${product.id}`;
            }

            const subtitleElement = modalElement.querySelector('.product-name-display');
            if (subtitleElement) {
                subtitleElement.textContent = product.original_product_name || 'Brak nazwy produktu';
            }

            const headerStatusBadge = modalElement.querySelector('.status-badge-large');
            if (headerStatusBadge) {
                this.updateHeaderStatus(headerStatusBadge, product);
            }

            // === STATYSTYKI ===
            this.populateStatsCards(modalElement, product);

            // === WSZYSTKIE POLA ===
            this.populateAllFields(modalElement, product);

            // === TIMELINE ===
            this.generateProductionTimeline(modalElement, product);

            // === AKCJE ===
            this.setupModalActions(modalElement, product);

            // === NOTATKI ===
            this.setupNotesHandling(modalElement, product);

            console.log('[ProductsModule] Modal populated successfully');

        } catch (error) {
            console.error('[ProductsModule] Error populating modal:', error);
        }
    }


    /**
     * Aktualizuje status w header modala
     */
    updateHeaderStatus(headerStatusBadge, product) {
        const statusIcon = headerStatusBadge.querySelector('i');
        const statusText = headerStatusBadge.querySelector('.status-text');
        const priorityIndicator = headerStatusBadge.querySelector('.priority-indicator');

        const statusConfig = this.getStatusConfig(product.current_status);
        
        if (statusIcon) {
            statusIcon.className = `fas ${statusConfig.icon} me-2`;
        }
        
        if (statusText) {
            statusText.textContent = statusConfig.displayName;
        }

        if (priorityIndicator) {
            const priority = parseInt(product.priority_score) || 100;
            priorityIndicator.className = `priority-indicator ${this.getPriorityClass(priority)}`;
        }
    }

    /**
     * Wypełnia karty statystyk na górze
     */
    populateStatsCards(modalElement, product) {
        const volumeElement = modalElement.querySelector('.stats-row .stat-value[data-field="volume_m3"]');
        if (volumeElement) {
            const volume = parseFloat(product.volume_m3) || 0;
            volumeElement.textContent = `${volume.toFixed(3)} m³`;
        }

        const valueElement = modalElement.querySelector('.stats-row .stat-value[data-field="total_value_net"]');
        if (valueElement) {
            const value = parseFloat(product.total_value_net) || 0;
            valueElement.textContent = value.toLocaleString('pl-PL', {
                style: 'currency', 
                currency: 'PLN'
            });
        }

        const deadlineElement = modalElement.querySelector('.stats-row .stat-value[data-field="days_until_deadline"]');
        if (deadlineElement) {
            const days = parseInt(product.days_until_deadline);
            if (!isNaN(days)) {
                deadlineElement.textContent = `${days} ${this.getDaysText(days)}`;
                deadlineElement.className = `stat-value ${this.getDeadlineClass(days)}`;
            } else {
                deadlineElement.textContent = 'Brak deadline';
                deadlineElement.className = 'stat-value text-muted';
            }
        }
    }

    /**
     * Wypełnia wszystkie pola danych w sekcjach
     */
    populateAllFields(modalElement, product) {
        const fields = modalElement.querySelectorAll('[data-field]');
        
        fields.forEach(field => {
            const fieldName = field.dataset.field;
            const fieldType = field.dataset.type;
            const unit = field.dataset.unit;
            
            let value = product[fieldName];
            
            if (fieldName === 'current_status') {
                const statusConfig = this.getStatusConfig(value);
                field.innerHTML = `
                    <i class="fas ${statusConfig.icon} me-2"></i>
                    <span class="status-text">${statusConfig.displayName}</span>
                `;
                field.className = `status-badge ${statusConfig.badgeClass}`;
                return;
            } else if (fieldName === 'sequence_display') {
                value = `${product.product_sequence_in_order || 1}/--`;
            } else if (fieldName === 'dimensions_display') {
                value = this.formatDimensions(product);
            } else if (fieldName === 'baselinker_link') {
                return;
            }
            
            const formattedValue = this.formatModalValue(value, fieldType, unit);
            
            if (fieldType === 'email' && value) {
                field.innerHTML = `<a href="mailto:${value}">${value}</a>`;
            } else {
                field.innerHTML = formattedValue;
            }
        });
    }

    /**
     * Generuje timeline produkcji
     */
    generateProductionTimeline(modalElement, product) {
        const timelineContainer = modalElement.querySelector('#productionTimeline');
        if (!timelineContainer) return;

        const stations = [
            {
                code: 'cutting',
                name: 'Wycięcie',
                status: 'czeka_na_wyciecie',
                icon: 'fas fa-cut',
                color: 'cutting-theme',
                startField: 'cutting_started_at',
                endField: 'cutting_completed_at',
                durationField: 'cutting_duration_minutes'
            },
            {
                code: 'assembly',
                name: 'Składanie',
                status: 'czeka_na_skladanie',
                icon: 'fas fa-hammer',
                color: 'assembly-theme',
                startField: 'assembly_started_at',
                endField: 'assembly_completed_at',
                durationField: 'assembly_duration_minutes'
            },
            {
                code: 'packaging',
                name: 'Pakowanie',
                status: 'czeka_na_pakowanie',
                icon: 'fas fa-box',
                color: 'packaging-theme',
                startField: 'packaging_started_at',
                endField: 'packaging_completed_at',
                durationField: 'packaging_duration_minutes'
            }
        ];

        let html = '';
        
        stations.forEach(station => {
            const timelineState = this.getTimelineState(station, product);
            const details = this.getTimelineDetails(station, product);
            
            html += `
                <div class="timeline-item ${timelineState.cssClass}">
                    <div class="timeline-icon ${station.color}">
                        <i class="${station.icon}"></i>
                    </div>
                    <div class="timeline-content">
                        <h6 class="timeline-title ${station.color}">${station.name}</h6>
                        <p class="timeline-details">${details.text}</p>
                        <span class="timeline-status">${timelineState.statusText}</span>
                    </div>
                </div>
            `;
        });

        timelineContainer.innerHTML = html;
    }

    /**
     * Określa stan timeline dla stacji
     */
    getTimelineState(station, product) {
        const statusMap = {
            'cutting': 'czeka_na_wyciecie',
            'assembly': 'czeka_na_skladanie', 
            'packaging': 'czeka_na_pakowanie'
        };

        const expectedStatus = statusMap[station.code];
        const currentStatus = product.current_status;

        if (product[station.endField]) {
            return {
                cssClass: 'timeline-completed',
                statusText: 'Zakończone'
            };
        } else if (currentStatus === expectedStatus) {
            return {
                cssClass: 'timeline-active',
                statusText: 'W trakcie'
            };
        } else {
            return {
                cssClass: 'timeline-pending',
                statusText: 'Oczekuje'
            };
        }
    }

    /**
     * Generuje szczegóły dla timeline
     */
    getTimelineDetails(station, product) {
        const startDate = product[station.startField];
        const endDate = product[station.endField];
        const duration = product[station.durationField];

        if (endDate) {
            const endFormatted = new Date(endDate).toLocaleString('pl-PL');
            const durationText = duration ? this.formatDuration(duration) : '';
            return {
                text: `Zakończono: ${endFormatted}${durationText ? ', czas: ' + durationText : ''}`
            };
        } else if (startDate) {
            const startFormatted = new Date(startDate).toLocaleString('pl-PL');
            const now = new Date();
            const start = new Date(startDate);
            const elapsed = Math.floor((now - start) / (1000 * 60));
            const elapsedText = this.formatDuration(elapsed);
            return {
                text: `Rozpoczęto: ${startFormatted}, czas: ${elapsedText}`
            };
        } else {
            const prevStations = {
                'assembly': 'wycięcie',
                'packaging': 'składanie'
            };
            const prevStation = prevStations[station.code];
            return {
                text: prevStation ? `Oczekuje na ${prevStation}` : 'Oczekuje na rozpoczęcie'
            };
        }
    }

    // ========================================================================
    // FUNKCJE TŁUMACZEŃ STATUSÓW
    // ========================================================================

    /**
     * Tłumaczy status na przyjazną nazwę
     */
    translateStatus(status) {
        return ProductsModule.STATUS_TRANSLATIONS[status] || status || 'Nieznany status';
    }

    /**
     * Zwraca kompletną konfigurację statusu
     */
    getStatusConfig(status) {
        const configs = {
            'czeka_na_wyciecie': {
                icon: 'fa-cut',
                displayName: 'Czeka na wycięcie',
                color: 'cutting-theme',
                cssClass: 'cutting'  // ← DODAJ TO
            },
            'w_trakcie_ciecia': {
                icon: 'fa-cut',
                displayName: 'W trakcie cięcia',
                color: 'cutting-theme',
                cssClass: 'cutting'  // ← DODAJ TO
            },
            'czeka_na_skladanie': {
                icon: 'fa-hammer',
                displayName: 'Czeka na składanie',
                color: 'assembly-theme',
                cssClass: 'assembly'  // ← DODAJ TO
            },
            'w_trakcie_skladania': {
                icon: 'fa-hammer',
                displayName: 'W trakcie składania',
                color: 'assembly-theme',
                cssClass: 'assembly'  // ← DODAJ TO
            },
            'czeka_na_pakowanie': {
                icon: 'fa-box',
                displayName: 'Czeka na pakowanie',
                color: 'packaging-theme',
                cssClass: 'packaging'  // ← DODAJ TO
            },
            'w_trakcie_pakowania': {
                icon: 'fa-box',
                displayName: 'W trakcie pakowania',
                color: 'packaging-theme',
                cssClass: 'packaging'  // ← DODAJ TO
            },
            'spakowane': {
                icon: 'fa-check',
                displayName: 'Spakowane',
                color: 'text-success',
                cssClass: 'completed'  // ← DODAJ TO
            },
            'wstrzymane': {
                icon: 'fa-pause',
                displayName: 'Wstrzymane',
                color: 'text-warning',
                cssClass: 'paused'  // ← DODAJ TO
            },
            'anulowane': {
                icon: 'fa-times',
                displayName: 'Anulowane',
                color: 'text-danger',
                cssClass: 'cancelled'  // ← DODAJ TO
            }
        };

        return configs[status] || {
            icon: 'fa-question',
            displayName: status || 'Nieznany',
            color: 'text-muted',
            cssClass: 'paused'  // ← DODAJ TO
        };
    }

    /**
     * Zwraca tylko klasę CSS dla badge statusu
     */
    getStatusBadgeClass(status) {
        return this.getStatusConfig(status).badgeClass;
    }

    /**
     * Zwraca przyjazną nazwę statusu dla wyświetlenia
     */
    getStatusDisplayName(status) {
        return this.getStatusConfig(status).displayName;
    }

    /**
     * Konfiguruje obsługę notatek produkcyjnych
     */
    setupNotesHandling(modalElement, product) {
        const editBtn = modalElement.querySelector('#editNotesBtn');
        const cancelBtn = modalElement.querySelector('#cancelNotesBtn');
        const saveBtn = modalElement.querySelector('#saveNotesBtn');
        const textarea = modalElement.querySelector('#notesTextarea');
        const notesDisplay = modalElement.querySelector('#notesDisplay');
        const notesEdit = modalElement.querySelector('#notesEdit');

        const currentNotes = product.production_notes || '';
        const notesField = notesDisplay.querySelector('[data-field="production_notes"]');
        
        if (notesField) {
            notesField.textContent = currentNotes || 'Brak notatek';
        }
        if (textarea) {
            textarea.value = currentNotes;
        }

        let originalNotesValue = currentNotes;

        if (editBtn) {
            editBtn.addEventListener('click', () => {
                this.startNotesEdit(notesDisplay, notesEdit, editBtn, textarea, originalNotesValue);
            });
        }

        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => {
                this.cancelNotesEdit(notesDisplay, notesEdit, editBtn, textarea, originalNotesValue);
            });
        }

        if (saveBtn) {
            saveBtn.addEventListener('click', () => {
                this.saveProductNotes(product.id, textarea.value, notesDisplay, notesEdit, editBtn, notesField);
            });
        }

        if (textarea) {
            textarea.addEventListener('input', () => {
                this.checkNotesChanges(textarea, saveBtn, originalNotesValue);
            });
        }
    }

    startNotesEdit(notesDisplay, notesEdit, editBtn, textarea, originalValue) {
        notesDisplay.style.display = 'none';
        notesEdit.style.display = 'block';
        editBtn.style.display = 'none';
        
        if (textarea) {
            textarea.focus();
            textarea.setSelectionRange(textarea.value.length, textarea.value.length);
        }
    }

    cancelNotesEdit(notesDisplay, notesEdit, editBtn, textarea, originalValue) {
        notesDisplay.style.display = 'block';
        notesEdit.style.display = 'none';
        editBtn.style.display = 'block';
        
        if (textarea) {
            textarea.value = originalValue;
        }
    }

    checkNotesChanges(textarea, saveBtn, originalValue) {
        if (!textarea || !saveBtn) return;
        
        const hasChanges = textarea.value.trim() !== originalValue.trim();
        saveBtn.disabled = !hasChanges;
    }

    async saveProductNotes(productId, notes, notesDisplay, notesEdit, editBtn, notesField) {
        try {
            const saveBtn = document.getElementById('saveNotesBtn');
            if (saveBtn) {
                const originalText = saveBtn.innerHTML;
                saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Zapisuję...';
                saveBtn.disabled = true;
            }

            const response = await fetch(`/production/api/products/${productId}/notes`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({ notes: notes })
            });

            const result = await response.json();

            if (!response.ok || !result.success) {
                throw new Error(result.error || `HTTP ${response.status}`);
            }

            notesDisplay.style.display = 'block';
            notesEdit.style.display = 'none';
            editBtn.style.display = 'block';

            if (notesField) {
                notesField.textContent = notes || 'Brak notatek';
            }

            if (this.shared?.toastSystem) {
                this.shared.toastSystem.showToast('Notatki zostały zapisane', 'success');
            }

        } catch (error) {
            console.error('[ProductsModule] Error saving notes:', error);
            
            if (this.shared?.toastSystem) {
                this.shared.toastSystem.showToast(`Błąd zapisu notatek: ${error.message}`, 'error');
            } else {
                alert(`Błąd zapisu notatek: ${error.message}`);
            }
        } finally {
            const saveBtn = document.getElementById('saveNotesBtn');
            if (saveBtn) {
                saveBtn.innerHTML = '<i class="fas fa-save me-1"></i>Zapisz';
                saveBtn.disabled = false;
            }
        }
    }

    /**
     * Ładuje produkty z tego samego zamówienia dla paska produktów
     */
    async loadOrderProducts(productId) {
        try {
            const response = await fetch(`/production/api/products/${productId}/order-products`, {
                method: 'GET',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            const result = await response.json();

            if (!response.ok || !result.success) {
                console.warn('[ProductsModule] Failed to load order products:', result.error);
                return;
            }

            this.renderProductsNavigation(result, productId);

        } catch (error) {
            console.error('[ProductsModule] Error loading order products:', error);
        }
    }

    /**
     * Renderuje pasek nawigacji produktów
     */
    renderProductsNavigation(orderData, currentProductId) {
        const navigation = document.getElementById('productsNavigation');
        const titleElement = document.getElementById('productsNavTitle');
        const buttonsContainer = document.getElementById('productsButtons');

        if (!navigation || !orderData.products) return;

        if (orderData.total_count <= 1) {
            navigation.style.display = 'none';
            return;
        }

        navigation.style.display = 'block';
        navigation.classList.add('show');

        if (titleElement) {
            titleElement.innerHTML = `
                Produkty w zamówieniu (${orderData.total_count})
            `;
        }

        if (buttonsContainer) {
            let buttonsHtml = '';

            orderData.products.forEach(product => {
                const isActive = product.id == currentProductId;
                
                buttonsHtml += `
                    <button class="product-nav-btn ${isActive ? 'active' : ''}" 
                            data-product-id="${product.id}"
                            onclick="window.productsModule?.switchToProduct(${product.id})"
                            title="Przełącz na produkt ${product.short_product_id}">
                        <div class="product-nav-spec">${product.specification}</div>
                        <div class="product-nav-id">${product.short_product_id}</div>
                    </button>
                `;
            });

            buttonsContainer.innerHTML = buttonsHtml;
        }

        const sequenceField = document.querySelector('[data-field="sequence_display"]');
        if (sequenceField && orderData.products) {
            const currentProduct = orderData.products.find(p => p.id == currentProductId);
            if (currentProduct) {
                sequenceField.textContent = `${currentProduct.sequence}/${orderData.total_count}`;
            }
        }
    }

    updateActiveProductButton(newProductId) {
        const productButtons = document.querySelectorAll('.product-nav-btn');
        
        productButtons.forEach(btn => {
            const btnProductId = btn.dataset.productId;
            
            if (btnProductId == newProductId) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
    }

    async fadeOutModalContent() {
        return new Promise(resolve => {
            const contentAreas = ['.details-section', '.sidebar-section'];
            
            contentAreas.forEach(selector => {
                const element = document.querySelector(selector);
                if (element) {
                    element.style.transition = 'opacity 0.2s ease';
                    element.style.opacity = '0.3';
                }
            });
            
            setTimeout(resolve, 200);
        });
    }

    async fadeInModalContent() {
        return new Promise(resolve => {
            const contentAreas = ['.details-section', '.sidebar-section'];
            
            contentAreas.forEach(selector => {
                const element = document.querySelector(selector);
                if (element) {
                    element.style.opacity = '1';
                }
            });
            
            setTimeout(() => {
                contentAreas.forEach(selector => {
                    const element = document.querySelector(selector);
                    if (element) {
                        element.style.transition = '';
                        element.style.opacity = '';
                    }
                });
                resolve();
            }, 200);
        });
    }

    /**
     * Przełącza widok na inny produkt
     */
    async switchToProduct(productId) {
        console.log('[ProductsModule] Switching to product:', productId);

        try {
            // Pokaż loading
            this.showModalLoading(true);
            
            // Aktualizuj aktywny przycisk
            this.updateActiveProductButton(productId);
            
            // Pobierz dane produktu
            const product = this.state.filteredProducts.find(p => p.id == productId) || 
                           this.state.products.find(p => p.id == productId);
            
            if (!product) {
                throw new Error(`Produkt ${productId} nie został znaleziony`);
            }

            // Fade out → aktualizuj → fade in
            await this.fadeOutModalContent();
            this.updateModalWithNewProduct(product);
            await this.fadeInModalContent();
            
            // Ukryj loading
            this.showModalLoading(false);
            
            console.log('[ProductsModule] Product switched successfully');

        } catch (error) {
            console.error('[ProductsModule] Error switching product:', error);
            this.showModalLoading(false);
            
            if (this.shared?.toastSystem) {
                this.shared.toastSystem.showToast(`Błąd: ${error.message}`, 'error');
            }
        }
    }

    updateModalWithNewProduct(product) {
        const titleElement = document.querySelector('.product-id-display');
        if (titleElement) {
            titleElement.textContent = product.short_product_id || `#${product.id}`;
        }

        const subtitleElement = document.querySelector('.product-name-display');
        if (subtitleElement) {
            subtitleElement.textContent = product.original_product_name || 'Brak nazwy produktu';
        }

        const headerStatusBadge = document.querySelector('.status-badge-large');
        if (headerStatusBadge) {
            this.updateHeaderStatus(headerStatusBadge, product);
        }

        // Aktualizuj statystyki używając sztucznego modalElement (document)
        this.populateStatsCards(document, product);
        this.populateAllFields(document, product);
        this.generateProductionTimeline(document, product);
        this.setupModalActions(document, product);

        // Aktualizuj notatki
        const notesField = document.querySelector('#notesDisplay [data-field="production_notes"]');
        const notesTextarea = document.querySelector('#notesTextarea');
        
        const currentNotes = product.production_notes || '';
        
        if (notesField) {
            notesField.textContent = currentNotes || 'Brak notatek';
        }
        
        if (notesTextarea) {
            notesTextarea.value = currentNotes;
        }

        // Resetuj stan edycji notatek
        const notesDisplay = document.querySelector('#notesDisplay');
        const notesEdit = document.querySelector('#notesEdit');
        const editBtn = document.querySelector('#editNotesBtn');
        
        if (notesDisplay && notesEdit && editBtn) {
            notesDisplay.style.display = 'block';
            notesEdit.style.display = 'none';
            editBtn.style.display = 'block';
        }
    }

    showModalLoading(show) {
        const modal = document.getElementById('product-details-modal');
        if (!modal) return;

        let loadingOverlay = document.getElementById('modal-loading-overlay-fixed');
        
        if (show) {
            // Usuń poprzedni overlay jeśli istnieje
            if (loadingOverlay) {
                loadingOverlay.remove();
            }
            
            // Stwórz nowy overlay
            loadingOverlay = document.createElement('div');
            loadingOverlay.id = 'modal-loading-overlay-fixed';
            loadingOverlay.className = 'modal-loading-overlay';
            loadingOverlay.innerHTML = `
                <div class="modal-loading-content">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Ładowanie...</span>
                    </div>
                    <div class="loading-text">Ładowanie danych produktu...</div>
                </div>
            `;
            
            // Dodaj do body (nie do modala) - będzie pokrywał cały ekran
            document.body.appendChild(loadingOverlay);
            
            // Pokaż loading z animacją
            loadingOverlay.style.display = 'flex';
            setTimeout(() => {
                loadingOverlay.classList.add('show');
            }, 10);
            
        } else {
            // Ukryj loading
            if (loadingOverlay) {
                loadingOverlay.classList.remove('show');
                setTimeout(() => {
                    if (loadingOverlay && loadingOverlay.parentNode) {
                        loadingOverlay.remove();
                    }
                }, 300);
            }
        }
    }

    /**
     * Konfiguruje akcje w modal
     */
    setupModalActions(modalElement, product) {
        const baselinkerBtn = modalElement.querySelector('#openBaselinkerBtn');
        if (baselinkerBtn && product.baselinker_order_id) {
            const baselinkerUrl = `https://panel-f.baselinker.com/orders.php#order:${product.baselinker_order_id}`;
            baselinkerBtn.href = baselinkerUrl;
            baselinkerBtn.target = '_blank';
        } else if (baselinkerBtn) {
            baselinkerBtn.style.display = 'none';
        }
    }

    // ========================================================================
    // POMOCNICZE FUNKCJE FORMATOWANIA
    // ========================================================================

    /**
     * Formatuje wartość dla wyświetlenia w modal
     */
    formatModalValue(value, type, unit) {
        if (value === null || value === undefined || value === '') {
            return '<span class="text-muted">Brak danych</span>';
        }
        
        switch (type) {
            case 'currency':
                return parseFloat(value).toLocaleString('pl-PL', {
                    style: 'currency', currency: 'PLN'
                });
            case 'decimal':
                return parseFloat(value).toFixed(3) + (unit ? ` ${unit}` : '');
            case 'date':
                return new Date(value).toLocaleDateString('pl-PL');
            case 'datetime':
                return new Date(value).toLocaleString('pl-PL');
            case 'duration':
                return this.formatDuration(value);
            case 'deadline-full':
                return this.formatDeadlineFull(value);
            case 'email':
                return `<a href="mailto:${value}">${value}</a>`;
            default:
                return value.toString() + (unit ? ` ${unit}` : '');
        }
    }

    /**
     * Formatuje wymiary produktu
     */
    formatDimensions(product) {
        const dimensions = [];

        if (product.parsed_length_cm) {
            dimensions.push(Math.round(product.parsed_length_cm));
        }
        if (product.parsed_width_cm) {
            dimensions.push(Math.round(product.parsed_width_cm));
        }
        if (product.parsed_thickness_cm) {
            dimensions.push(Math.round(product.parsed_thickness_cm));
        }

        return dimensions.length > 0 ? dimensions.join(' × ') + ' mm' : 'Brak danych';
    }

    /**
     * Formatuje czas trwania w minutach
     */
    formatDuration(minutes) {
        if (!minutes || minutes < 0) return '0min';
        
        const hours = Math.floor(minutes / 60);
        const mins = minutes % 60;
        
        if (hours > 0) {
            return `${hours}h ${mins}min`;
        } else {
            return `${mins}min`;
        }
    }

    formatDeadlineFull(deadlineDate) {
        if (!deadlineDate) return 'Brak deadline';
        
        const date = new Date(deadlineDate);
        const now = new Date();
        const diffTime = date - now;
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        
        const dateStr = date.toLocaleDateString('pl-PL');
        const daysText = this.getDaysText(Math.abs(diffDays));
        
        if (diffDays < 0) {
            return `${dateStr} (przeterminowane o ${Math.abs(diffDays)} ${daysText})`;
        } else {
            return `${dateStr} (${diffDays} ${daysText})`;
        }
    }

    /**
     * Zwraca tekstową formę dla dni
     */
    getDaysText(days) {
        if (days === 1) return 'dzień';
        if (days <= 2) return 'dni';
        return 'dni';
    }

    /**
     * Zwraca klasę CSS dla priorytetu
     */
    getPriorityClass(priority) {
        if (priority >= 180) return 'priority-critical';
        if (priority >= 140) return 'priority-high';
        if (priority >= 80) return 'priority-medium';
        return 'priority-low';
    }

    /**
     * Zwraca konfigurację statusu
     */
    getStatusConfig(status) {
        const configs = {
            'czeka_na_wyciecie': {
                icon: 'fa-cut',
                displayName: 'Wycinanie',
                color: 'cutting-theme'
            },
            'czeka_na_skladanie': {
                icon: 'fa-hammer',
                displayName: 'Składanie',
                color: 'assembly-theme'
            },
            'czeka_na_pakowanie': {
                icon: 'fa-box',
                displayName: 'Pakowanie',
                color: 'packaging-theme'
            },
            'spakowane': {
                icon: 'fa-check',
                displayName: 'Spakowane',
                color: 'text-success'
            },
            'wstrzymane': {
                icon: 'fa-pause',
                displayName: 'Wstrzymane',
                color: 'text-warning'
            },
            'anulowane': {
                icon: 'fa-times',
                displayName: 'Anulowane',
                color: 'text-danger'
            }
        };

        return configs[status] || {
            icon: 'fa-question',
            displayName: status || 'Nieznany',
            color: 'text-muted'
        };
    }

    // ========================================================================
    // DRAG & DROP PUBLIC API
    // ========================================================================

    enableDragDrop() {
        if (this.components.dragDrop) {
            this.components.dragDrop.enable();
            console.log('[ProductsModule] Drag & Drop enabled');
        }
    }

    disableDragDrop() {
        if (this.components.dragDrop) {
            this.components.dragDrop.disable();
            console.log('[ProductsModule] Drag & Drop disabled');
        }
    }

    isDragDropEnabled() {
        return this.components.dragDrop ? this.components.dragDrop.isEnabled() : false;
    }

    isDragging() {
        return this.components.dragDrop ? this.components.dragDrop.isDragging() : false;
    }

}

// ========================================================================
// EXPORT MODULE
// ========================================================================

// Export dla używania w template (onclick)
if (typeof window !== 'undefined') {
    // Funkcje notatek (dla backward compatibility jeśli gdzieś używane)
    window.toggleNotesEdit = function() {
        console.log('[Global] toggleNotesEdit called - deprecated, use modal functions');
    };
    
    // Funkcja przełączania produktów (używana w onclick)
    window.switchToProduct = function(productId) {
        if (window.productsModule) {
            window.productsModule.switchToProduct(productId);
        } else {
            console.error('[Global] productsModule not initialized');
        }
    };
    
    console.log('[ProductsModule] Global functions exported to window');
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ProductsModule;
}

// Make available globally
window.ProductsModule = ProductsModule;