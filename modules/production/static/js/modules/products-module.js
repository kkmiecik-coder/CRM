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
        'czeka_na_wyciecie': 'Wycinanie - mikro',
        'czeka_na_skladanie': 'Składanie - lite',
        'czeka_na_sklejanie': 'Sklejanie',
        'czeka_na_formatowanie': 'Formatowanie',
        'czeka_na_wykanczanie': 'Wykańczanie',
        'czeka_na_lakiernie': 'Lakiernia',
        'czeka_na_logistyke': 'Logistyka',
        'czeka_na_pakowanie': 'Pakowanie',
        'spakowane': 'Spakowane',
        'w_realizacji': 'W realizacji',
        'wstrzymane': 'Wstrzymane',
        'anulowane': 'Anulowane'
    };

    // Mapowanie statusów na ikony i kolory
    static STATUS_CONFIG = {
        'czeka_na_wyciecie': { icon: 'fa-cut', displayName: 'Wycinanie - mikro', color: 'cutting-theme', badgeClass: 'badge-cutting' },
        'w_trakcie_ciecia': { icon: 'fa-cut', displayName: 'Wycinanie - mikro', color: 'cutting-theme', badgeClass: 'badge-cutting' },
        'czeka_na_skladanie': { icon: 'fa-hammer', displayName: 'Składanie - lite', color: 'assembly-theme', badgeClass: 'badge-assembly' },
        'w_trakcie_skladania': { icon: 'fa-hammer', displayName: 'Składanie - lite', color: 'assembly-theme', badgeClass: 'badge-assembly' },
        'czeka_na_sklejanie': { icon: 'fa-compress-arrows-alt', displayName: 'Sklejanie', color: 'gluing-theme', badgeClass: 'badge-gluing' },
        'w_trakcie_sklejania': { icon: 'fa-compress-arrows-alt', displayName: 'Sklejanie', color: 'gluing-theme', badgeClass: 'badge-gluing' },
        'czeka_na_formatowanie': { icon: 'fa-ruler-combined', displayName: 'Formatowanie', color: 'formatting-theme', badgeClass: 'badge-formatting' },
        'w_trakcie_formatowania': { icon: 'fa-ruler-combined', displayName: 'Formatowanie', color: 'formatting-theme', badgeClass: 'badge-formatting' },
        'czeka_na_wykanczanie': { icon: 'fa-star', displayName: 'Wykańczanie', color: 'finishing-theme', badgeClass: 'badge-finishing' },
        'w_trakcie_wykanczania': { icon: 'fa-star', displayName: 'Wykańczanie', color: 'finishing-theme', badgeClass: 'badge-finishing' },
        'czeka_na_lakiernie': { icon: 'fa-paint-roller', displayName: 'Lakiernia', color: 'painting-theme', badgeClass: 'badge-painting' },
        'czeka_na_logistyke': { icon: 'fa-truck', displayName: 'Logistyka', color: 'logistics-theme', badgeClass: 'badge-logistics' },
        'czeka_na_pakowanie': { icon: 'fa-box', displayName: 'Pakowanie', color: 'packaging-theme', badgeClass: 'badge-packaging' },
        'w_trakcie_pakowania': { icon: 'fa-box', displayName: 'Pakowanie', color: 'packaging-theme', badgeClass: 'badge-packaging' },
        'spakowane': { icon: 'fa-check-circle', displayName: 'Spakowane', color: 'text-success', badgeClass: 'badge-success' },
        'w_realizacji': { icon: 'fa-cog', displayName: 'W realizacji', color: 'text-info', badgeClass: 'badge-info' },
        'wstrzymane': { icon: 'fa-pause-circle', displayName: 'Wstrzymane', color: 'text-warning', badgeClass: 'badge-warning' },
        'anulowane': { icon: 'fa-times-circle', displayName: 'Anulowane', color: 'text-danger', badgeClass: 'badge-danger' }
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

            // Render-time view-state filtra — zamiast mutować produkty flagą _dimmed
            // trzymamy zbiór kluczy produktów pasujących do aktywnego filtra i flagę
            // informującą czy jakikolwiek filtr jest aktywny. Konsumenci odpytują
            // helper _isProductDimmed(product) zamiast czytać pole z modelu.
            matchingProductIds: new Set(),
            filtersActive: false,

            // Lista i sortowanie
            products: [],
            filteredProducts: [],
            sortColumn: null,
            sortDirection: 'asc',

            // Order grouping
            orders: [],           // Grouped orders
            filteredOrders: [],   // After filtering
            expandedOrders: new Set(),  // Track which orders are expanded

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

            // Pobierz elementy DOM - try new IL IDs first, fallback to old IDs
            this.elements = {
                container: document.getElementById('il-orders-list') || document.getElementById('virtual-scroll-container'),
                viewport: document.getElementById('il-orders-list') || document.getElementById('virtual-scroll-viewport'),
                loadingState: document.getElementById('il-products-loading') || document.getElementById('products-loading'),
                emptyState: document.getElementById('il-products-empty') || document.getElementById('products-empty-state'),
                errorState: document.getElementById('il-products-error') || document.getElementById('products-error-state'),
                textSearch: document.getElementById('il-products-search') || document.getElementById('products-text-search'),
                selectAllCheckbox: document.getElementById('il-select-all') || document.getElementById('select-all-products'),
                productsCount: document.getElementById('il-stats-products') || document.getElementById('products-count')
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

            // Setup select-all handler for new IL template
            const selectAll = document.getElementById('il-select-all');
            if (selectAll) {
                selectAll.addEventListener('change', () => {
                    // Wspólna logika — select-all operuje tylko na filteredProducts (pomija przygaszone)
                    this._applySelectAll(selectAll.checked);

                    // Sync checkboxów specyficznych dla układu IL (inny layout niż .prod_list-*)
                    // Zaznaczamy tylko te produkty które realnie trafiły do selekcji (widoczne)
                    document.querySelectorAll('.il-product-checkbox').forEach(cb => {
                        const productId = parseInt(cb.getAttribute('data-product-id'));
                        const key = productId ? this._getProductKeyById(productId) : null;
                        cb.checked = key ? this.state.selectedProducts.has(key) : false;
                    });
                    // Order-level checkboxy aktualizujemy przez indeterminate state
                    document.querySelectorAll('.il-order-card').forEach(card => {
                        const orderKey = card.getAttribute('data-order-key');
                        const orderCheckbox = card.querySelector('.il-order-checkbox');
                        if (!orderCheckbox || !orderKey) return;
                        const order = this.state.filteredOrders.find(o => o.orderKey === orderKey);
                        if (order) this._updateOrderCheckboxState(orderCheckbox, order);
                    });
                    this.toggleBulkActionsVisibility();
                });
            }

            // Ustaw CSS dla prostego renderowania (only for old layout)
            if (document.getElementById('virtual-scroll-container')) {
                this.elements.container.style.overflow = 'auto';
                this.elements.container.style.maxHeight = '70vh';
                this.elements.viewport.style.position = 'relative';
                this.elements.viewport.style.display = 'block';
            }

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
                const queryLower = query.toLowerCase().trim();

                // Pola które używają exact match (numery zamówień)
                const exactMatchFields = ['baselinker_order_id', 'client_order_number'];

                return items.filter(item => {
                    return fields.some(field => {
                        const value = item[field];
                        if (value === null || value === undefined || value === '') return false;

                        const valueStr = String(value).toLowerCase();

                        // Dla numerów zamówień używamy prostego includes (exact match)
                        if (exactMatchFields.includes(field)) {
                            return valueStr.includes(queryLower);
                        }

                        // Dla innych pól używamy fuzzy search
                        const distance = this.calculateLevenshteinDistance(queryLower, valueStr);
                        return distance <= threshold || valueStr.includes(queryLower);
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
            badgesWrapper: document.getElementById('il-active-filters'),
            badgesContainer: document.getElementById('il-filter-badges'),
            clearAllBtn: document.getElementById('il-clear-all-filters'),
            activeFiltersCount: 0
        };

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
        
        const wrapper = document.getElementById('il-active-filters');
        const container = document.getElementById('il-filter-badges');
        const clearBtn = document.getElementById('il-clear-all-filters');
        
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
        // Jeśli elementy nie są zainicjalizowane, spróbuj je znaleźć
        if (!this.badgesConfig.badgesWrapper || !this.badgesConfig.badgesContainer) {
            this.badgesConfig.badgesWrapper = document.getElementById('il-active-filters');
            this.badgesConfig.badgesContainer = document.getElementById('il-filter-badges');
            this.badgesConfig.clearAllBtn = document.getElementById('il-clear-all-filters');
        }

        if (!this.badgesConfig.badgesContainer) {
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
        const wrapper = document.getElementById('il-active-filters');
        if (wrapper) {
            const shouldShow = badgeCount > 0;
            wrapper.style.display = shouldShow ? 'block' : 'none';
            console.log(`[ProductsModule] FORCE: Set wrapper display to ${shouldShow ? 'flex' : 'none'}, badges count: ${badgeCount}`);

            // Aktualizuj też config
            this.badgesConfig.badgesWrapper = wrapper;
        } else {
            console.error('[ProductsModule] Cannot find il-active-filters element!');
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

        // Zastosuj filtry (applyAllFilters now renders + updates stats)
        this.applyAllFilters();
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

        // Zastosuj filtry (applyAllFilters now renders + updates stats)
        this.applyAllFilters();
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

            // Zastosuj filtry i wyrenderuj (applyAllFilters now calls renderOrdersList + updateStats)
            this.applyAllFilters();

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
                    this.state.orders = this.groupProductsIntoOrders(this.state.products);
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
                    this.state.orders = this.groupProductsIntoOrders(this.state.products);
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
            if (!e.target.closest('.il-multiselect') && !e.target.closest('.multi-select-wrapper')) {
                this.closeAllDropdowns();
            }
        });
    }

    setupCustomMultiSelect(displayId, dropdownId, filterType) {
        const displayEl = document.getElementById(displayId);
        const dropdown = document.getElementById(dropdownId);

        if (!displayEl || !dropdown) {
            console.warn(`[ProductsModule] Multi-select elements not found: ${displayId}, ${dropdownId}`);
            return;
        }

        // Find the clickable trigger — either .il-filter-dropdown or .multi-select-display inside
        const trigger = displayEl.querySelector('.il-filter-dropdown') || displayEl.querySelector('.multi-select-display') || displayEl;

        // Toggle dropdown on trigger click
        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleDropdown(dropdownId);
        });

        // Search within dropdown (support both old and new class names)
        const searchInput = dropdown.querySelector('.il-multiselect-search') || dropdown.querySelector('.multi-select-search input');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.filterDropdownOptions(dropdownId, e.target.value);
            });
        }

        // "Select all" functionality (support both old and new markup)
        const selectAllOption = dropdown.querySelector('.il-multiselect-option input[value="__all__"]') || dropdown.querySelector('.multi-select-all input');
        if (selectAllOption) {
            selectAllOption.addEventListener('change', (e) => {
                this.handleSelectAllChange(dropdownId, filterType, e.target.checked);
            });
        }
    }

    toggleDropdown(dropdownId) {
        // Close all other dropdowns first
        this.closeAllDropdowns(dropdownId);

        const dropdown = document.getElementById(dropdownId);
        if (dropdown) {
            const isOpen = dropdown.style.display !== 'none' && dropdown.style.display !== '';
            dropdown.style.display = isOpen ? 'none' : 'block';
            dropdown.classList.toggle('show', !isOpen);

            // Update arrow direction (support both old and new)
            const parent = dropdown.closest('.il-multiselect') || dropdown.parentElement;
            const arrow = parent?.querySelector('.il-chevron') || parent?.querySelector('.multi-select-arrow');
            if (arrow) {
                arrow.classList.toggle('fa-chevron-up', !isOpen);
                arrow.classList.toggle('fa-chevron-down', isOpen);
            }
        }
    }

    closeAllDropdowns(exceptId) {
        const dropdowns = document.querySelectorAll('.il-multiselect-options, .multi-select-dropdown');
        dropdowns.forEach(dropdown => {
            if (exceptId && dropdown.id === exceptId) return;
            dropdown.style.display = 'none';
            dropdown.classList.remove('show');
        });
        
        // Reset all arrows
        const arrows = document.querySelectorAll('.il-chevron, .multi-select-arrow');
        arrows.forEach(arrow => {
            arrow.classList.remove('fa-chevron-up');
            arrow.classList.add('fa-chevron-down');
        });
    }

    filterDropdownOptions(dropdownId, searchTerm) {
        const dropdown = document.getElementById(dropdownId);
        if (!dropdown) return;

        const options = dropdown.querySelectorAll('.il-multiselect-option, .multi-select-option:not(.multi-select-all)');
        const searchLower = searchTerm.toLowerCase();

        options.forEach(option => {
            const input = option.querySelector('input');
            if (input && input.value === '__all__') return; // skip "select all"
            const text = option.textContent.toLowerCase();
            option.style.display = text.includes(searchLower) ? 'flex' : 'none';
        });
    }

    handleSelectAllChange(dropdownId, filterType, isChecked) {
        const dropdown = document.getElementById(dropdownId);
        if (!dropdown) return;

        const options = dropdown.querySelectorAll('.il-multiselect-option input[type="checkbox"]:not([value="__all__"]), .multi-select-option:not(.multi-select-all) input[type="checkbox"]');
        const visibleOptions = Array.from(options).filter(option => {
            const parent = option.closest('.il-multiselect-option') || option.closest('.multi-select-option');
            return parent && parent.style.display !== 'none';
        });

        visibleOptions.forEach(checkbox => {
            checkbox.checked = isChecked;
            this.handleOptionChange(filterType, checkbox.value, isChecked);
        });

        this.updateMultiSelectDisplay(dropdownId.replace('dropdown-', 'filter-'), filterType);
        
        // WAŻNE: Aktualizuj badges po "select all"
        this.updateFilterBadges();

        this.applyAllFilters();
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

        // Support both new IL and old template structure
        const optionsContainer = dropdown.querySelector('.multi-select-options') || dropdown;

        // Clear existing options (except select all and search)
        const existingOptions = optionsContainer.querySelectorAll('.multi-select-option:not(.multi-select-all), .il-multiselect-option:not(:first-child)');
        existingOptions.forEach(option => {
            // Don't remove "select all" option or search input
            const input = option.querySelector('input');
            if (input && input.value === '__all__') return;
            if (option.classList.contains('il-multiselect-search')) return;
            option.remove();
        });

        // Add new options
        options.forEach((option, index) => {
            const optionElement = this.createCustomOption(option, filterType, index);
            optionsContainer.appendChild(optionElement);
        });

        console.log(`[ProductsModule] Populated ${options.length} options for ${dropdownId}`);
    }

    createCustomOption(option, filterType, index) {
        const optionDiv = document.createElement('label');
        optionDiv.className = 'il-multiselect-option multi-select-option';

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

    // ========================================================================
    // ORDER GROUPING & RENDERING (IL Theme)
    // ========================================================================

    groupProductsIntoOrders(products) {
        const ordersMap = new Map();

        products.forEach(product => {
            const orderKey = product.internal_order_number || product.baselinker_order_id || `single-${product.id}`;

            if (!ordersMap.has(orderKey)) {
                ordersMap.set(orderKey, {
                    orderKey: orderKey,
                    clientName: product.client_name || 'Brak danych',
                    baselinkerOrderId: product.baselinker_order_id,
                    clientOrderNumber: product.client_order_number,
                    internalOrderNumber: product.internal_order_number,
                    products: [],
                    totalVolume: 0,
                    totalValue: 0,
                    productCount: 0,
                    status: null,
                    deadline: null,
                    isPriority: false,
                    orderNotes: product.order_notes || '',
                    attachmentUrl: null
                });
            }

            const order = ordersMap.get(orderKey);
            order.products.push(product);
            order.productCount++;
            order.totalVolume += (parseFloat(product.volume_m3) || 0) * (product.quantity || 1);
            order.totalValue += parseFloat(product.total_value_net) || 0;

            if (product.is_priority) order.isPriority = true;
            if (product.order_notes && !order.orderNotes) order.orderNotes = product.order_notes;
            if (product.attachment_file_url) order.attachmentUrl = product.attachment_file_url;

            // Earliest deadline
            if (product.deadline_date) {
                if (!order.deadline || product.deadline_date < order.deadline) {
                    order.deadline = product.deadline_date;
                }
            }
        });

        // Calculate order-level status
        ordersMap.forEach(order => {
            const statuses = [...new Set(order.products.map(p => p.current_status))];
            if (statuses.length === 1) {
                order.status = statuses[0];
                order.statusLabel = this.getStatusDisplayName(statuses[0]);
            } else {
                const completedCount = order.products.filter(p => p.current_status === 'spakowane').length;
                order.status = 'mixed';
                order.statusLabel = `Różne (${completedCount}/${order.productCount})`;
            }

            // Round totals
            order.totalVolume = Math.round(order.totalVolume * 10000) / 10000;
            order.totalValue = Math.round(order.totalValue * 100) / 100;
        });

        return Array.from(ordersMap.values());
    }

    renderOrdersList() {
        const container = document.getElementById('il-orders-list');
        if (!container) return;

        // Clear existing content (keep loading/empty/error states)
        container.querySelectorAll('.il-order-card').forEach(el => el.remove());

        if (this.state.filteredOrders.length === 0) {
            this.showEmptyState();
            return;
        }

        this.hideEmptyState();

        const fragment = document.createDocumentFragment();

        this.state.filteredOrders.forEach(order => {
            const orderElement = this.createOrderCard(order);
            fragment.appendChild(orderElement);
        });

        container.appendChild(fragment);
        this.updateProductsCount();
        this.syncAllCheckboxes();
    }

    hideEmptyState() {
        if (this.elements.emptyState) {
            this.elements.emptyState.style.display = 'none';
        }
    }

    createOrderCard(order) {
        const template = document.getElementById('il-order-template');
        if (!template) {
            console.warn('[ProductsModule] il-order-template not found, falling back');
            return document.createElement('div');
        }
        const clone = template.content.cloneNode(true);
        const card = clone.querySelector('.il-order-card');

        card.setAttribute('data-order-key', order.orderKey);

        // Add status class to card for mobile border-left
        const stationClass = this.getStationClassFromStatus(order.status);
        card.classList.add(stationClass);

        // Populate header
        const header = card.querySelector('.il-order-header');
        this.populateOrderHeader(header, order);

        // Populate products
        const productsContainer = card.querySelector('.il-order-products');
        order.products.forEach(product => {
            const productRow = this.createProductRow(product);
            productsContainer.appendChild(productRow);
        });

        // Expand/collapse state
        if (this.state.expandedOrders.has(order.orderKey)) {
            productsContainer.classList.remove('collapsed');
            header.classList.add('expanded');
            header.querySelector('.il-order-expand').classList.add('open');
        }

        // Populate mobile card meta
        this.populateCardMeta(card, order);

        // Attach event listeners
        this.attachOrderEventListeners(card, order);

        return card;
    }

    populateCardMeta(card, order) {
        const meta = card.querySelector('.il-order-card-meta');
        if (!meta) return;

        const parts = [];

        // Status
        if (order.statusLabel) {
            const badgeClass = this.getStatusBadgeClass(order.status);
            parts.push(`<span class="il-order-status-badge ${badgeClass}">${order.statusLabel}</span>`);
        }

        // Positions + Volume
        const metrics = [];
        if (order.productCount) metrics.push(`${order.productCount} poz.`);
        if (order.totalVolume) metrics.push(`${order.totalVolume.toFixed(4)} m³`);
        if (order.totalValue) metrics.push(`${order.totalValue.toLocaleString('pl-PL', {minimumFractionDigits: 2, maximumFractionDigits: 2})} zł`);
        if (metrics.length) {
            parts.push(`<span class="il-card-meta-metrics">${metrics.join(' · ')}</span>`);
        }

        // Deadline
        if (order.deadline) {
            const days = this.calculateDaysUntilDeadline(order.deadline);
            const dateStr = new Date(order.deadline).toLocaleDateString('pl-PL', {day: '2-digit', month: '2-digit'});
            const cls = days < 0 ? 'deadline-overdue' : days <= 1 ? 'deadline-urgent' : 'deadline-normal';
            parts.push(`<span class="il-card-meta-deadline ${cls}"><i class="fas fa-calendar-alt"></i> ${days} ${Math.abs(days) === 1 ? 'dzień' : 'dni'} (${dateStr})</span>`);
        }

        meta.innerHTML = parts.join('');
    }

    populateOrderHeader(header, order) {
        // Status left border
        const stationClass = this.getStationClassFromStatus(order.status);
        header.classList.add(stationClass);

        // Star — all priority = active+filled, some = partial (border only)
        const star = header.querySelector('.il-star-btn');
        const allPriority = order.products.length > 0 && order.products.every(p => p.is_priority);
        const anyPriority = order.products.some(p => p.is_priority);
        if (allPriority) {
            star.classList.add('active');
            star.querySelector('i').className = 'fas fa-star';
        } else if (anyPriority) {
            star.classList.add('partial');
        }

        // Client info
        header.querySelector('.il-order-client').textContent = order.clientName;
        const idsContainer = header.querySelector('.il-order-ids');
        if (order.internalOrderNumber) {
            idsContainer.innerHTML += `<span class="il-order-id-tag">${order.internalOrderNumber}</span>`;
        }
        if (order.baselinkerOrderId) {
            idsContainer.innerHTML += `<span class="il-order-id-tag">BL-${order.baselinkerOrderId}</span>`;
        }
        if (order.clientOrderNumber) {
            idsContainer.innerHTML += `<span class="il-order-id-tag">${order.clientOrderNumber}</span>`;
        }

        // Metrics
        header.querySelector('.il-order-positions').textContent = order.productCount;
        header.querySelector('.il-order-volume').textContent = `${order.totalVolume.toFixed(4)} m³`;
        header.querySelector('.il-order-value').textContent = `${order.totalValue.toLocaleString('pl-PL', {minimumFractionDigits: 2, maximumFractionDigits: 2})} zł`;

        // Status badge
        const badge = header.querySelector('.il-order-status-badge');
        badge.textContent = order.statusLabel;
        badge.className = `il-order-status-badge ${this.getStatusBadgeClass(order.status)}`;

        // Deadline
        const deadlineEl = header.querySelector('.il-order-deadline');
        if (order.deadline) {
            const days = this.calculateDaysUntilDeadline(order.deadline);
            const dateStr = new Date(order.deadline).toLocaleDateString('pl-PL', {day: '2-digit', month: '2-digit'});
            deadlineEl.textContent = `${days < 0 ? days : days} ${Math.abs(days) === 1 ? 'dzień' : 'dni'} (${dateStr})`;
            deadlineEl.className = `il-order-deadline ${days < 0 ? 'deadline-overdue' : days <= 1 ? 'deadline-urgent' : 'deadline-normal'}`;
        } else {
            deadlineEl.textContent = '—';
            deadlineEl.className = 'il-order-deadline deadline-normal';
        }
    }

    attachOrderEventListeners(card, order) {
        const header = card.querySelector('.il-order-header');
        const productsContainer = card.querySelector('.il-order-products');

        // Expand/collapse on header click
        header.addEventListener('click', (e) => {
            if (e.target.closest('.il-order-checkbox') ||
                e.target.closest('.il-star-btn') ||
                e.target.closest('.il-order-actions') ||
                e.target.closest('.il-drag-handle')) return;

            const isExpanded = this.state.expandedOrders.has(order.orderKey);
            if (isExpanded) {
                this.state.expandedOrders.delete(order.orderKey);
                productsContainer.classList.add('collapsed');
                header.classList.remove('expanded');
                header.querySelector('.il-order-expand').classList.remove('open');
            } else {
                this.state.expandedOrders.add(order.orderKey);
                productsContainer.classList.remove('collapsed');
                header.classList.add('expanded');
                header.querySelector('.il-order-expand').classList.add('open');
            }
        });

        // Order checkbox — selects all products in order
        const orderCheckbox = header.querySelector('.il-order-checkbox');
        orderCheckbox.addEventListener('change', (e) => {
            e.stopPropagation();
            // Reset indeterminate — user explicitly clicked
            orderCheckbox.indeterminate = false;
            // Iterujemy tylko produkty widoczne (pasujące do aktywnego filtra)
            const visibleProducts = order.products.filter(p => !this._isProductDimmed(p));
            visibleProducts.forEach(p => {
                const id = this._getProductKey(p);
                if (orderCheckbox.checked) {
                    this.state.selectedProducts.add(id);
                } else {
                    this.state.selectedProducts.delete(id);
                }
            });
            // Sync product checkboxes in this card — tylko widoczne produkty
            // Indeksy i w DOM odpowiadają pełnej liście order.products (razem z dimmed),
            // więc sprawdzamy stan przygaszenia przez helper przed zaznaczeniem
            card.querySelectorAll('.il-product-checkbox').forEach((cb, i) => {
                const p = order.products[i];
                if (p && !this._isProductDimmed(p)) {
                    cb.checked = orderCheckbox.checked;
                }
            });
            this.toggleBulkActionsVisibility();
        });

        // Product checkboxes
        card.querySelectorAll('.il-product-checkbox').forEach((cb, i) => {
            cb.addEventListener('change', () => {
                const product = order.products[i];
                const id = product.unique_id || String(product.id);
                if (cb.checked) {
                    this.state.selectedProducts.add(id);
                } else {
                    this.state.selectedProducts.delete(id);
                }
                // Update order checkbox — support indeterminate state
                this._updateOrderCheckboxState(orderCheckbox, order);
                this.toggleBulkActionsVisibility();
            });
        });

        // Star button (order-level)
        const starBtn = header.querySelector('.il-star-btn');
        starBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleOrderPriority(order);
        });

        // Action buttons — set disabled state based on data availability
        header.querySelectorAll('.il-order-action-btn').forEach(btn => {
            const action = btn.getAttribute('data-action');

            // Set disabled state
            if (action === 'attachment' && !order.attachmentUrl) {
                btn.classList.add('disabled');
                btn.setAttribute('disabled', 'true');
            }
            if (action === 'comment') {
                if (!order.orderNotes) {
                    btn.classList.add('disabled');
                    btn.setAttribute('disabled', 'true');
                } else {
                    btn.classList.add('has-comment');
                }
            }
            if (action === 'baselinker' && !order.baselinkerOrderId) {
                btn.classList.add('disabled');
                btn.setAttribute('disabled', 'true');
            }

            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (btn.classList.contains('disabled')) return;

                switch(action) {
                    case 'details':
                        this.showProductDetails(order.products[0].id || order.products[0].unique_id);
                        break;
                    case 'baselinker':
                        if (order.baselinkerOrderId) {
                            window.open(`https://panel-f.baselinker.com/orders.php#order:${order.baselinkerOrderId}`, '_blank');
                        }
                        break;
                    case 'attachment':
                        this.showAttachment(order);
                        break;
                    case 'comment':
                        this.showCommentTooltip(btn, order);
                        break;
                }
            });
        });

        // Drag handle
        const dragHandle = header.querySelector('.il-drag-handle');
        if (dragHandle) {
            card.setAttribute('draggable', 'true');
            card.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', order.orderKey);
                card.classList.add('dragging');
            });
            card.addEventListener('dragend', () => {
                card.classList.remove('dragging');
            });
        }
    }

    showCommentTooltip(btn, order) {
        // Toggle — jeśli tooltip jest już otwarty, zamknij
        const existing = document.querySelector('.il-comment-tooltip');
        if (existing) {
            existing.remove();
            return;
        }

        if (!order.orderNotes) return;

        const tooltip = document.createElement('div');
        tooltip.className = 'il-comment-tooltip';
        tooltip.textContent = order.orderNotes;
        document.body.appendChild(tooltip);

        // Pozycjonuj przy przycisku
        const rect = btn.getBoundingClientRect();
        tooltip.style.top = (rect.bottom + window.scrollY + 4) + 'px';
        tooltip.style.left = (rect.left + window.scrollX) + 'px';

        // Zamknij po kliknięciu gdziekolwiek
        const closeHandler = (e) => {
            if (!tooltip.contains(e.target) && e.target !== btn && !btn.contains(e.target)) {
                tooltip.remove();
                document.removeEventListener('click', closeHandler);
            }
        };
        setTimeout(() => document.addEventListener('click', closeHandler), 10);
    }

    showAttachment(order) {
        if (order.attachmentUrl) {
            // Use existing attachment modal if available
            if (typeof window.openAttachmentModalAdmin === 'function') {
                window.openAttachmentModalAdmin(order.attachmentUrl);
            } else {
                window.open(order.attachmentUrl, '_blank');
            }
        }
    }

    getStationClassFromStatus(status) {
        const map = {
            'czeka_na_wyciecie': 'status-cutting',
            'czeka_na_skladanie': 'status-assembly',
            'czeka_na_sklejanie': 'status-gluing',
            'czeka_na_formatowanie': 'status-formatting',
            'czeka_na_wykanczanie': 'status-finishing',
            'czeka_na_lakiernie': 'status-painting',
            'czeka_na_logistyke': 'status-logistics',
            'czeka_na_pakowanie': 'status-packaging',
            'spakowane': 'status-completed',
            'w_realizacji': 'status-inprogress',
            'wstrzymane': 'status-paused',
            'anulowane': 'status-cancelled',
            'mixed': 'status-mixed'
        };
        const normalized = status ? status.toLowerCase() : '';
        return map[normalized] || map[status] || 'status-completed';
    }

    getStatusBadgeClass(status) {
        const map = {
            'czeka_na_wyciecie': 'badge-cutting',
            'czeka_na_skladanie': 'badge-assembly',
            'czeka_na_sklejanie': 'badge-gluing',
            'czeka_na_formatowanie': 'badge-formatting',
            'czeka_na_wykanczanie': 'badge-finishing',
            'czeka_na_lakiernie': 'badge-painting',
            'czeka_na_logistyke': 'badge-logistics',
            'czeka_na_pakowanie': 'badge-packaging',
            'spakowane': 'badge-completed',
            'w_realizacji': 'badge-assembly',
            'wstrzymane': 'badge-paused',
            'anulowane': 'badge-cancelled',
            'mixed': 'badge-mixed'
        };
        const normalized = status ? status.toLowerCase() : '';
        return map[normalized] || map[status] || 'badge-completed';
    }

    sortOrders() {
        const col = this.state.sortColumn;
        const dir = this.state.sortDirection === 'asc' ? 1 : -1;

        if (!col) {
            // Default: sort by deadline (most urgent first)
            this.state.filteredOrders.sort((a, b) => {
                if (!a.deadline) return 1;
                if (!b.deadline) return -1;
                return a.deadline.localeCompare(b.deadline);
            });
            return;
        }

        this.state.filteredOrders.sort((a, b) => {
            let valA, valB;
            switch(col) {
                case 'client': valA = a.clientName; valB = b.clientName; break;
                case 'positions': valA = a.productCount; valB = b.productCount; break;
                case 'volume': valA = a.totalVolume; valB = b.totalVolume; break;
                case 'value': valA = a.totalValue; valB = b.totalValue; break;
                case 'status':
                    valA = a.statusLabel; valB = b.statusLabel; break;
                case 'deadline':
                    valA = a.deadline || 'z'; valB = b.deadline || 'z'; break;
                default: return 0;
            }
            if (typeof valA === 'string') return valA.localeCompare(valB) * dir;
            return (valA - valB) * dir;
        });
    }

    // New createProductRow for IL template
    createProductRow(product, index) {
        // Try new IL template first
        const template = document.getElementById('il-product-template');
        if (template) {
            return this._createILProductRow(product);
        }
        // Fallback to old template
        return this._createOldProductRow(product, index);
    }

    _createILProductRow(product) {
        const template = document.getElementById('il-product-template');
        const clone = template.content.cloneNode(true);
        const row = clone.querySelector('.il-product-row');

        // Atrybut musi być numerycznym PK — downstream czyta to przez parseInt(...)
        // w wielu miejscach. Fallback na unique_id (string typu "25_00123_1") dałby
        // NaN i cicho rozsynchronizowałby selekcję. PK z MySQL jest zawsze truthy.
        row.setAttribute('data-product-id', product.id);

        // Wyciszenie produktu nie pasującego do filtra — lookup przez helper
        // (zamiast czytać flagę z samego produktu). Klasa CSS pozostaje nieruszona.
        if (this._isProductDimmed(product)) {
            row.classList.add('il-product-dimmed');
        }

        // Checkbox
        const checkbox = row.querySelector('.il-product-checkbox');
        checkbox.checked = this.state.selectedProducts.has(product.unique_id || String(product.id));

        // Star (product-level)
        const productStar = row.querySelector('.il-product-star');
        if (productStar) {
            if (product.is_priority) {
                productStar.classList.add('active');
                productStar.querySelector('i').classList.replace('far', 'fas');
            }
            productStar.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleProductPriority(product, productStar);
            });
        }

        // Name
        row.querySelector('.il-product-name-text').textContent = product.original_product_name || '—';
        row.querySelector('.il-product-name-id').textContent = product.short_product_id || '';

        // Spec tags
        const specContainer = row.querySelector('.il-product-spec');
        const specs = [
            product.parsed_wood_species,
            product.parsed_technology,
            product.parsed_wood_class,
            product.parsed_thickness_cm ? `${product.parsed_thickness_cm}mm` : null
        ].filter(Boolean);
        specContainer.innerHTML = specs.map(s => `<span class="il-product-spec-tag">${s}</span>`).join('');

        // Quantity
        row.querySelector('.il-product-qty').textContent = `${product.quantity || 1} szt.`;

        // Volume
        const vol = ((product.volume_m3 || 0) * (product.quantity || 1)).toFixed(4);
        row.querySelector('.il-product-volume').textContent = `${vol} m³`;

        // Status badge per product
        const statusBadge = row.querySelector('.il-product-status-badge');
        if (statusBadge && product.current_status) {
            const badgeClass = this.getStatusBadgeClass(product.current_status);
            const statusName = this.getStatusDisplayName(product.current_status);
            statusBadge.textContent = statusName;
            statusBadge.className = `il-product-status-badge ${badgeClass}`;
        }

        return row;
    }

    _createOldProductRow(product, index) {
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
            rowElement.setAttribute('data-priority', product.priority_rank || 0);
            rowElement.setAttribute('data-status', product.current_status || '');
            rowElement.setAttribute('data-index', index);
            rowElement.setAttribute('data-is-priority', product.is_priority ? 'true' : 'false');
            rowElement.setAttribute('data-order-number', product.internal_order_number || '');

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
        // TODO: metoda obsługuje stary layout (prod_list-*) uruchamiany tylko gdy
        // w DOM brakuje #il-product-template. Obecnie template jest zawsze obecny,
        // więc ta ścieżka jest martwa — selektor .prod_list-product-checkbox
        // pozostawiony intencjonalnie dla spójności starego fallbacku.
        try {
            // 1. Checkbox
            const checkbox = rowElement.querySelector('.prod_list-product-checkbox');
            if (checkbox) {
                checkbox.checked = this.state.selectedProducts.has(this._getProductKey(product));
                checkbox.setAttribute('data-product-id', product.id);
            }

            // 2. Gwiazdka priorytetu
            const starBtn = rowElement.querySelector('.prod_list-star-btn');
            if (starBtn) {
                starBtn.setAttribute('data-product-id', product.id);
                starBtn.setAttribute('data-order-number', product.internal_order_number || '');
                if (product.is_priority) {
                    starBtn.classList.add('active');
                }
            }

            // 3. Priority rank
            const priorityElement = rowElement.querySelector('.prod_list-priority-rank');
            if (priorityElement) {
                const priority = parseInt(product.priority_rank) || 100;
                priorityElement.textContent = priority;
            }

            // 3. Klient (nazwa + numery zamówień)
            const clientNameElement = rowElement.querySelector('.prod_list-client-name');
            if (clientNameElement) {
                clientNameElement.textContent = product.client_name || 'Brak klienta';
            }

            // Numer wewnętrzny zamówienia
            const clientOrderElement = rowElement.querySelector('.prod_list-client-order-number');
            if (clientOrderElement) {
                clientOrderElement.textContent = product.client_order_number || '';
            }

            // Numer Baselinker
            const blOrderElement = rowElement.querySelector('.prod_list-bl-order-number');
            if (blOrderElement) {
                blOrderElement.textContent = product.baselinker_order_id ? `BL-${product.baselinker_order_id}` : '';
            }

            // 4. Produkt (nazwa + ID systemowy)
            const nameElement = rowElement.querySelector('.prod_list-product-name');
            if (nameElement) {
                nameElement.textContent = product.original_product_name || 'Brak nazwy';
            }

            const idElement = rowElement.querySelector('.prod_list-product-id');
            if (idElement) {
                idElement.textContent = product.short_product_id || product.id;
            }

            // 5. Ilość
            const quantityElement = rowElement.querySelector('.prod_list-quantity-value');
            if (quantityElement) {
                const quantity = product.quantity || 1;
                quantityElement.textContent = `${quantity} szt.`;
            }

            // 6. Objętość (volume * quantity)
            const volumeElement = rowElement.querySelector('.prod_list-volume-value');
            if (volumeElement) {
                const volume = parseFloat(product.volume_m3) || 0;
                const quantity = product.quantity || 1;
                const totalVolume = volume * quantity;
                volumeElement.textContent = `${totalVolume.toFixed(4)} m³`;
            }

            // 7. Status
            const statusElement = rowElement.querySelector('.prod_list-status-badge');
            if (statusElement) {
                const statusConfig = this.getStatusConfig(product.current_status);
                statusElement.textContent = statusConfig.displayName;
                const statusClass = this.getStatusCSSClass(product.current_status);
                statusElement.className = `prod_list-status-badge ${statusClass}`;
            }

            // 8. Deadline
            const deadlineElement = rowElement.querySelector('.prod_list-deadline-value');
            if (deadlineElement) {
                if (product.deadline_date) {
                    const deadlineDate = new Date(product.deadline_date);
                    const today = new Date();
                    today.setHours(0, 0, 0, 0);
                    const diffDays = Math.ceil((deadlineDate - today) / (1000 * 60 * 60 * 24));

                    // Format daty
                    const formattedDate = deadlineDate.toLocaleDateString('pl-PL', {
                        day: '2-digit',
                        month: '2-digit'
                    });
                    deadlineElement.textContent = formattedDate;

                    // Dodaj klasę w zależności od pilności
                    deadlineElement.classList.remove('deadline-urgent', 'deadline-soon');
                    if (diffDays < 0) {
                        deadlineElement.classList.add('deadline-urgent');
                        deadlineElement.textContent = `${formattedDate} ❗`;
                    } else if (diffDays <= 2) {
                        deadlineElement.classList.add('deadline-soon');
                    }
                } else {
                    deadlineElement.textContent = '—';
                }
            }

            // Hook dla załączników
            if (typeof window.handleProductAttachmentRender === 'function') {
                window.handleProductAttachmentRender(rowElement, product);
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
            const removedKey = this._getProductKeyById(productId);
            this.state.products = this.state.products.filter(p => p.id != productId);
            this.state.filteredProducts = this.state.filteredProducts.filter(p => p.id != productId);
            if (removedKey) this.state.selectedProducts.delete(removedKey);

            // Przerenderuj listę
            this.applyAllFilters();
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
        // TODO: listenery dla starego layoutu (prod_list-*) — patrz komentarz
        // przy populateProductRow. Ścieżka obecnie nieużywana (IL jest jedynym
        // aktywnym layoutem), zostawiona jako fallback.
        try {
            // Checkbox - stara klasa (layout prod_list-*)
            const checkbox = rowElement.querySelector('.prod_list-product-checkbox');
            if (checkbox) {
                checkbox.addEventListener('change', (e) => {
                    e.stopPropagation();
                    this.handleProductSelect(product, e.target.checked);
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
                        const baselinkerUrl = `https://panel-f.baselinker.com/orders.php#order:${product.baselinker_order_id}`;
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

            // Star button (gwiazdka priorytetu)
            const starBtn = rowElement.querySelector('.prod_list-star-btn');
            if (starBtn) {
                starBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.handleStarClick(starBtn, product);
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

    // ========================================================================
    // PRIORITY STAR METHODS - Obsługa gwiazdki priorytetu
    // ========================================================================

    /**
     * Toggle priorytetu pojedynczego produktu (klik w gwiazdkę produktu)
     */
    async toggleProductPriority(product, starBtn) {
        const newPriority = !product.is_priority;
        await this._sendPriorityUpdate(product.id, null, 'product', newPriority);
    }

    /**
     * Toggle priorytetu całego zamówienia (klik w gwiazdkę zamówienia)
     */
    async toggleOrderPriority(order) {
        const allHavePriority = order.products.every(p => p.is_priority);
        const newPriority = !allHavePriority;
        const orderNumber = order.internalOrderNumber || order.products[0]?.internal_order_number;
        await this._sendPriorityUpdate(null, orderNumber, 'order', newPriority);
    }

    /**
     * Wysyła żądanie zmiany priorytetu do API i aktualizuje UI
     */
    async _sendPriorityUpdate(productId, orderNumber, mode, isPriority) {
        try {
            const response = await fetch('/production/api/set-priority', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    product_id: productId,
                    order_number: orderNumber,
                    mode: mode,
                    is_priority: isPriority
                })
            });

            const data = await response.json();
            if (!data.success) throw new Error(data.error || 'Nieznany błąd');

            // Aktualizuj lokalne dane
            if (data.updated_products) {
                data.updated_products.forEach(updated => {
                    const localProduct = this.state.products.find(p => p.id === updated.id);
                    if (localProduct) localProduct.is_priority = updated.is_priority;
                    const filteredProduct = this.state.filteredProducts.find(p => p.id === updated.id);
                    if (filteredProduct) filteredProduct.is_priority = updated.is_priority;
                });
            }

            // Aktualizuj UI
            this.refreshStarUI();

            if (this.shared?.toastSystem) {
                const count = data.updated_products?.length || 1;
                const msg = isPriority
                    ? `Oznaczono ${count} produkt(ów) jako priorytetowe`
                    : `Usunięto priorytet dla ${count} produktu(ów)`;
                this.shared.toastSystem.show(msg, 'success', 3000);
            }

        } catch (error) {
            console.error('[ProductsModule] Error setting priority:', error);
            if (this.shared?.toastSystem) {
                this.shared.toastSystem.show(`Błąd: ${error.message}`, 'error', 5000);
            }
        }
    }

    /**
     * Odświeża stan gwiazdek w całym widoku (produkty + nagłówki zamówień)
     */
    refreshStarUI() {
        // Gwiazdki na produktach (il-product-row)
        document.querySelectorAll('.il-product-row[data-product-id]').forEach(row => {
            const productId = parseInt(row.getAttribute('data-product-id'));
            const product = this.state.products.find(p => p.id === productId);
            if (!product) return;
            const star = row.querySelector('.il-product-star');
            if (!star) return;
            const icon = star.querySelector('i');
            if (product.is_priority) {
                star.classList.add('active');
                if (icon) icon.classList.replace('far', 'fas');
            } else {
                star.classList.remove('active');
                if (icon) icon.classList.replace('fas', 'far');
            }
        });

        // Gwiazdki na nagłówkach zamówień
        document.querySelectorAll('.il-order-card').forEach(card => {
            const orderStar = card.querySelector('.il-order-header > .il-star-btn');
            if (!orderStar) return;
            const productRows = card.querySelectorAll('.il-product-row[data-product-id]');
            const productIds = Array.from(productRows).map(el => parseInt(el.getAttribute('data-product-id')));
            const orderProducts = this.state.products.filter(p => productIds.includes(p.id));

            const anyPriority = orderProducts.some(p => p.is_priority);
            const allPriority = orderProducts.length > 0 && orderProducts.every(p => p.is_priority);
            const icon = orderStar.querySelector('i');

            orderStar.classList.remove('active', 'partial');
            if (icon) icon.classList.replace('fas', 'far');

            if (allPriority) {
                orderStar.classList.add('active');
                if (icon) icon.classList.replace('far', 'fas');
            } else if (anyPriority) {
                orderStar.classList.add('partial');
            }
        });
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

            // Step 1: Group ALL products into orders first
            const allOrders = this.groupProductsIntoOrders(this.state.products);

            // Step 2: Determine which products match filters
            let matchingProductIds = new Set();
            let productsToCheck = [...this.state.products];

            const textSearch = this.state.currentFilters.textSearch?.trim();
            if (textSearch && this.components.fuzzySearchEngine) {
                productsToCheck = this.components.fuzzySearchEngine.search(textSearch, productsToCheck, {
                    fields: ['original_product_name', 'short_product_id', 'client_name', 'baselinker_order_id', 'client_order_number'],
                    threshold: 2
                });
            }
            productsToCheck = this.applyMultiSelectFilters(productsToCheck);
            productsToCheck.forEach(p => matchingProductIds.add(p.unique_id || String(p.id)));

            // Step 3: Filter orders — show order if ANY product matches.
            // Zamiast mutować produkty (p._dimmed) zapisujemy zbiór kluczy pasujących
            // oraz flagę aktywności filtra na instancji. Render i handlery odpytują
            // helper _isProductDimmed(product), więc model pozostaje nietknięty.
            const hasFilters = this.hasActiveFilters();
            this.state.matchingProductIds = matchingProductIds;
            this.state.filtersActive = hasFilters;
            this.state.filteredOrders = allOrders.filter(order => {
                const hasMatch = order.products.some(p => matchingProductIds.has(p.unique_id || String(p.id)));
                if (!hasMatch && hasFilters) return false;
                return true;
            });

            // Step 4: Filtered products for stats = only matching products
            this.state.filteredProducts = productsToCheck;

            this.sortOrders();
            this.updateFilterBadges();
            this.updateStats();
            this.renderOrdersList();

            console.log(`[ProductsModule] Filters applied. ${productsToCheck.length}/${this.state.products.length} products match, ${this.state.filteredOrders.length} orders`);

        } catch (error) {
            console.error('[ProductsModule] Error applying filters:', error);
            this.state.filteredProducts = [...this.state.products];
            this.state.filteredOrders = this.groupProductsIntoOrders(this.state.products);
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

        // Selekcja jest zachowywana — kontrakt spójny z applyAllFilters. Bulk actions i tak operują na przecięciu selekcji z widokiem.
        // Zastosuj filtry (applyAllFilters now renders + updates stats)
        this.applyAllFilters();
    }

    /**
     * Sprawdza czy są aktywne jakiekolwiek filtry
     * @returns {boolean}
     */
    hasActiveFilters() {
        const filters = this.state.currentFilters;

        return !!(
            filters.textSearch ||
            (filters.woodSpecies && filters.woodSpecies.length > 0) ||
            (filters.technologies && filters.technologies.length > 0) ||
            (filters.woodClasses && filters.woodClasses.length > 0) ||
            (filters.thicknesses && filters.thicknesses.length > 0) ||
            (filters.statuses && filters.statuses.length > 0)
        );
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
        }, 150);
    }

    handleProductSelect(productOrId, isChecked) {
        // Akceptujemy obiekt product albo numeryczne ID — normalizujemy do klucza kanonicznego
        let key;
        if (productOrId && typeof productOrId === 'object') {
            key = this._getProductKey(productOrId);
        } else {
            key = this._getProductKeyById(productOrId) || String(productOrId);
        }
        console.log(`[ProductsModule] Product ${key} selected: ${isChecked}`);

        if (!key) return;

        if (isChecked) {
            this.state.selectedProducts.add(key);
        } else {
            this.state.selectedProducts.delete(key);
        }

        this.updateSelectAllCheckbox();
        this.toggleBulkActionsVisibility();
    }

    handleSelectAll(e) {
        const isChecked = e.target.checked;
        console.log(`[ProductsModule] Select all: ${isChecked}`);

        // Wspólna logika — operuje wyłącznie na filteredProducts (pomija przygaszone produkty)
        this._applySelectAll(isChecked);
        // syncAllCheckboxes czyta state i ustawia checkboxy w DOM — brak ryzyka zaznaczenia przygaszonych
        this.syncAllCheckboxes();
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

        // Sortuj produkty/zamówienia
        this.sortProducts();
        this.sortOrders();
        this.renderOrdersList();
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

        // Akcje bulk operują wyłącznie na przecięciu selectedProducts ∩ filteredProducts.
        // Chroni przed sytuacją: filter A → select-all → filter B → bulk → akcja na ukrytych z A.
        const selectedIds = this._getVisibleSelectedKeys();
        if (selectedIds.length === 0) {
            alert('Nie wybrano widocznych produktów');
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
            { value: 'czeka_na_wyciecie', label: 'Wycinanie - mikro' },
            { value: 'czeka_na_skladanie', label: 'Składanie - lite' },
            { value: 'czeka_na_sklejanie', label: 'Sklejanie' },
            { value: 'czeka_na_formatowanie', label: 'Formatowanie' },
            { value: 'czeka_na_wykanczanie', label: 'Wykańczanie' },
            { value: 'czeka_na_lakiernie', label: 'Lakiernia' },
            { value: 'czeka_na_logistyke', label: 'Logistyka' },
            { value: 'czeka_na_pakowanie', label: 'Pakowanie' },
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
                        <button class="dropdown-item status-item ${this.getStatusBadgeClass(status.value)}" data-status="${status.value}">
                            ${status.label}
                        </button>
                    `).join('')}
                </div>
            </div>
        `;

        // Get bulk actions bar position
        const bulkActionsBar = document.getElementById('il-bulk-bar') || document.getElementById('bulk-actions-bar');
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
        
        // Close on outside click — delay to avoid catching the opening click
        setTimeout(() => {
            this._bulkStatusOutsideHandler = (e) => {
                const dropdown = document.getElementById('bulk-status-dropdown');
                const bulkBar = document.getElementById('il-bulk-bar') || document.getElementById('bulk-actions-bar');
                if (dropdown && !dropdown.contains(e.target) && (!bulkBar || !bulkBar.contains(e.target))) {
                    this.closeBulkStatusDropdown();
                    document.removeEventListener('click', this._bulkStatusOutsideHandler);
                }
            };
            document.addEventListener('click', this._bulkStatusOutsideHandler);
        }, 100);
    }

    positionBulkStatusDropdown(dropdown, bulkActionsBar) {
        const barRect = bulkActionsBar.getBoundingClientRect();
        const barCenterX = barRect.left + barRect.width / 2;
        // Position above bulk bar, centered to the bar
        dropdown.style.bottom = `${window.innerHeight - barRect.top + 10}px`;
        dropdown.style.left = `${barCenterX}px`;
        dropdown.style.transform = 'translateX(-50%)';
        dropdown.style.position = 'fixed';
        dropdown.style.zIndex = '10001';
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
        if (this._bulkStatusOutsideHandler) {
            document.removeEventListener('click', this._bulkStatusOutsideHandler);
            this._bulkStatusOutsideHandler = null;
        }
        const dropdown = document.getElementById('bulk-status-dropdown');
        if (dropdown) {
            dropdown.classList.remove('show');
            setTimeout(() => {
                dropdown.remove();
            }, 200);
        }
    }

    async executeBulkStatusChange(selectedIds, newStatus) {
        console.log(`[ProductsModule] Changing status to ${newStatus} for ${selectedIds.length} products`);
        this.closeBulkStatusDropdown();
        const productIds = this._resolveProductIds(selectedIds);
        try {
            const response = await fetch('/production/api/products/bulk-action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'update_status', product_ids: productIds, parameters: { new_status: newStatus } })
            });
            const result = await response.json();
            if (result.success) {
                const statusName = this.getStatusDisplayName(newStatus);
                if (this.shared?.toastSystem) this.shared.toastSystem.show(`Status zmieniony na "${statusName}" dla ${result.processed_count} produktów`, 'success');
                else alert(`Status zmieniony na "${statusName}" dla ${result.processed_count} produktów`);
                this.state.selectedProducts.clear();
                this.toggleBulkActionsVisibility();
                if (this.shared?.apiClient) this.shared.apiClient.clearCache();
                await this.refresh();
            } else {
                alert(`Błąd: ${result.error}`);
            }
        } catch (error) {
            console.error('[ProductsModule] Bulk status change failed:', error);
            alert(`Błąd zmiany statusu: ${error.message}`);
        }
    }

    async handleExportSelected(selectedIds) {
        console.log(`[ProductsModule] Export selected: ${selectedIds.length} products`);
        if (this.state.isExporting) return;
        this.state.isExporting = true;
        const productIds = this._resolveProductIds(selectedIds);
        try {
            const response = await fetch('/production/api/products/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ product_ids: productIds, format: 'excel' })
            });
            if (response.ok) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `produkty_export_${new Date().toISOString().slice(0,10)}.xlsx`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
                if (this.shared?.toastSystem) this.shared.toastSystem.show(`Wyeksportowano ${productIds.length} produktów`, 'success');
            } else {
                const result = await response.json();
                alert(`Błąd eksportu: ${result.error}`);
            }
        } catch (error) {
            console.error('[ProductsModule] Export failed:', error);
            alert(`Błąd eksportu: ${error.message}`);
        } finally {
            this.state.isExporting = false;
        }
    }

    async showBulkDeleteConfirmation(selectedIds) {
        const confirmMessage = `Czy na pewno chcesz usunąć ${selectedIds.length} produktów?\n\nTa operacja jest nieodwracalna.`;
        if (!confirm(confirmMessage)) return;
        const productIds = this._resolveProductIds(selectedIds);
        try {
            const response = await fetch('/production/api/products/bulk-action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'delete', product_ids: productIds, parameters: {} })
            });
            const result = await response.json();
            if (result.success) {
                if (this.shared?.toastSystem) this.shared.toastSystem.show(`Usunięto ${result.processed_count} produktów`, 'success');
                else alert(`Usunięto ${result.processed_count} produktów`);
                this.state.selectedProducts.clear();
                this.toggleBulkActionsVisibility();
                if (this.shared?.apiClient) this.shared.apiClient.clearCache();
                await this.refresh();
            } else {
                alert(`Błąd usuwania: ${result.error}`);
            }
        } catch (error) {
            console.error('[ProductsModule] Bulk delete failed:', error);
            alert(`Błąd usuwania: ${error.message}`);
        }
    }

    _updateOrderCheckboxState(orderCheckbox, order) {
        const checkedCount = order.products.filter(p =>
            this.state.selectedProducts.has(p.unique_id || String(p.id))
        ).length;
        const total = order.products.length;

        if (checkedCount === 0) {
            orderCheckbox.checked = false;
            orderCheckbox.indeterminate = false;
        } else if (checkedCount === total) {
            orderCheckbox.checked = true;
            orderCheckbox.indeterminate = false;
        } else {
            orderCheckbox.checked = false;
            orderCheckbox.indeterminate = true;
        }
    }

    /**
     * Kanoniczny klucz produktu używany w Set state.selectedProducts.
     * Zawsze string — unique_id (np. "25_00123_1_klej") albo String(id) jako fallback.
     * Wszystkie add/has/delete MUSZĄ przechodzić przez ten klucz, inaczej sprawdzanie typu
     * w Set nie zadziała (Set rozróżnia 123 od "123").
     */
    _getProductKey(product) {
        if (!product) return null;
        return product.unique_id || String(product.id);
    }

    /**
     * Znajduje klucz kanoniczny po numerycznym ID produktu z DOM (np. data-product-id).
     * Zwraca null jeśli produkt nie istnieje w cache — caller powinien zignorować akcję.
     */
    _getProductKeyById(numericId) {
        const product = this.state.products.find(p => p.id == numericId);
        return product ? this._getProductKey(product) : null;
    }

    /**
     * Zwraca true jeśli produkt NIE pasuje do aktywnego filtra i powinien być
     * wizualnie wyciszony (klasa CSS .il-product-dimmed, pominięty w select-all,
     * itd.). Render-time lookup przeciw state.matchingProductIds — nie czytamy
     * flag z samego produktu. Gdy filtr nie jest aktywny zwraca zawsze false.
     */
    _isProductDimmed(product) {
        if (!this.state.filtersActive) return false;
        const key = this._getProductKey(product);
        return !this.state.matchingProductIds.has(key);
    }

    /**
     * Zwraca klucze kanoniczne produktów które są JEDNOCZEŚNIE zaznaczone i widoczne
     * (w state.filteredProducts, więc nie są przygaszone filtrem). Używany przez bulk
     * flows — chroni przed wykonaniem akcji na selekcji pozostałej po zmianie filtra.
     */
    _getVisibleSelectedKeys() {
        const visibleKeys = [];
        this.state.filteredProducts.forEach(product => {
            const key = this._getProductKey(product);
            if (key && this.state.selectedProducts.has(key)) {
                visibleKeys.push(key);
            }
        });
        return visibleKeys;
    }

    /**
     * Wspólna implementacja select-all używana przez handlery
     * (IL template i handleSelectAll). Operuje WYŁĄCZNIE na state.filteredProducts —
     * dimmed produkty (niezgodne z filtrem) nigdy nie trafią do selekcji.
     * Po wywołaniu caller powinien zsynchronizować DOM checkboxy
     * (syncAllCheckboxes lub lokalny sync w swoim layout'cie).
     */
    _applySelectAll(isChecked) {
        this.state.filteredProducts.forEach(product => {
            const key = this._getProductKey(product);
            if (!key) return;
            if (isChecked) {
                this.state.selectedProducts.add(key);
            } else {
                this.state.selectedProducts.delete(key);
            }
        });
    }

    _resolveProductIds(selectedKeys) {
        const ids = [];
        selectedKeys.forEach(key => {
            const keyStr = String(key);
            const product = this.state.products.find(p => (p.unique_id || String(p.id)) === keyStr);
            if (product && product.id) {
                ids.push(product.id);
                return;
            }
            // Fallback — unique_id ma format "{short_product_id}-{id}" (np. "25-00123-1-42"),
            // więc DB id to ostatni segment po podziale na "-"
            const parts = keyStr.split('-');
            const numId = parseInt(parts[parts.length - 1]);
            if (!isNaN(numId)) ids.push(numId);
        });
        return ids;
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
            this.elements.emptyState.style.display = 'flex';

            // Sprawdź czy są aktywne filtry i dostosuj komunikat
            const hasActiveFilters = this.hasActiveFilters();
            const emptyReason = document.getElementById('empty-reason');
            const clearFiltersBtn = document.getElementById('clear-filters-empty');

            if (hasActiveFilters) {
                if (emptyReason) {
                    emptyReason.textContent = 'Nie znaleziono produktów spełniających aktywne kryteria filtrowania.';
                }
                if (clearFiltersBtn) {
                    clearFiltersBtn.style.display = 'inline-block';
                }
            } else {
                if (emptyReason) {
                    emptyReason.textContent = 'Nie ma żadnych produktów w systemie. Zaimportuj zamówienia z Baselinker.';
                }
                if (clearFiltersBtn) {
                    clearFiltersBtn.style.display = 'none';
                }
            }
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
        // Aktywny layout to IL — checkboxy mają klasę .il-product-checkbox,
        // a data-product-id leży na wierszu nadrzędnym (.il-product-row).
        // Szukamy globalnie (poza viewportem), bo IL renderuje poza starym
        // kontenerem virtual-scroll.
        const checkboxes = document.querySelectorAll('.il-product-checkbox');
        checkboxes.forEach(checkbox => {
            const row = checkbox.closest('.il-product-row');
            const productId = row ? parseInt(row.getAttribute('data-product-id')) : NaN;
            const key = productId ? this._getProductKeyById(productId) : null;
            checkbox.checked = key ? this.state.selectedProducts.has(key) : false;
        });

        this.updateSelectAllCheckbox();
    }

    // Usunięto initializeSelectAllCheckbox — kierowało się na ID #select-all-products,
    // które nie istnieje w aktywnym szablonie IL (jest tam #il-select-all, obsługiwane
    // już w initializeComponents). Funkcja nie była nigdzie wywoływana i była
    // martwa po migracji do layoutu IL.

    updateSelectAllCheckbox() {
        if (!this.elements.selectAllCheckbox) return;

        const filteredCount = this.state.filteredProducts.length;
        const selectedCount = this.state.filteredProducts.filter(p =>
            this.state.selectedProducts.has(this._getProductKey(p))
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

    /**
     * Sprawdza czy wszystkie zaznaczone produkty tworzą kompletne zamówienia
     * (bez częściowych selekcji). Liczy tylko widoczną selekcję — ukryte
     * produkty po zmianie filtra i tak nie biorą udziału w bulk actions.
     */
    areCompleteOrdersSelected() {
        if (this._getVisibleSelectedKeys().length === 0) return false;

        const selectedIds = this.state.selectedProducts;
        // Group selected products by order
        const orderProductCounts = new Map();
        const orderTotalCounts = new Map();

        this.state.filteredProducts.forEach(p => {
            const orderKey = p.internal_order_number || p.baselinker_order_id || `single-${p.id}`;
            orderTotalCounts.set(orderKey, (orderTotalCounts.get(orderKey) || 0) + 1);
            if (selectedIds.has(this._getProductKey(p))) {
                orderProductCounts.set(orderKey, (orderProductCounts.get(orderKey) || 0) + 1);
            }
        });

        // Every order that has any selection must be fully selected
        for (const [key, selected] of orderProductCounts) {
            if (selected !== orderTotalCounts.get(key)) return false;
        }
        return true;
    }

    toggleBulkActionsVisibility() {
        // Widoczna selekcja = przecięcie selectedProducts ∩ filteredProducts.
        // Używamy tego jako źródła prawdy dla liczników i widoczności paska bulk,
        // żeby licznik zgadzał się z checkboxem select-all i realnie zaznaczonymi
        // wierszami w widoku (obydwa operują na filteredProducts).
        const visibleCount = this._getVisibleSelectedKeys().length;
        const totalCount = this.state.selectedProducts.size;
        const hiddenCount = totalCount - visibleCount;
        const hasHidden = hiddenCount > 0;

        // Etykieta licznika — jeśli są zaznaczone produkty poza aktywnym filtrem,
        // informujemy użytkownika ile pozostało ukrytych (nie zniknęły z selekcji,
        // ale bulk actions i tak ich nie dotkną — patrz handleBulkAction).
        const countLabel = hasHidden
            ? `${visibleCount} zaznaczone w widoku (+${hiddenCount} ukryte)`
            : `${visibleCount} zaznaczone`;

        const completeOrders = visibleCount > 0 ? this.areCompleteOrdersSelected() : false;

        // New IL bulk bar
        const ilBar = document.getElementById('il-bulk-bar');
        if (ilBar) {
            // Pasek ukrywamy gdy nic widocznego nie jest zaznaczone — bulk actions
            // operują wyłącznie na widocznej selekcji, więc ukryte resztki nie
            // powinny trzymać paska otwartego.
            if (visibleCount > 0) {
                ilBar.style.display = 'flex';
                const countEl = ilBar.querySelector('.il-bulk-count');
                if (countEl) countEl.textContent = countLabel;

                // Enable status change button whenever any products are selected
                const statusBtn = ilBar.querySelector('.il-bulk-btn[data-action="status"]');
                if (statusBtn) {
                    statusBtn.disabled = false;
                    statusBtn.title = 'Zmień status zaznaczonych produktów';
                    statusBtn.style.opacity = '';
                }

                // Bind click handlers (only once)
                if (!ilBar._listenersAttached) {
                    ilBar._listenersAttached = true;
                    ilBar.querySelectorAll('.il-bulk-btn').forEach(btn => {
                        btn.addEventListener('click', () => {
                            if (btn.disabled) return;
                            const action = btn.getAttribute('data-action');
                            switch(action) {
                                case 'status':
                                    this.handleBulkAction('change-status');
                                    break;
                                case 'export':
                                    this.handleBulkAction('export-selected');
                                    break;
                                case 'delete':
                                    this.handleBulkAction('delete');
                                    break;
                            }
                        });
                    });
                }
            } else {
                ilBar.style.display = 'none';
            }
        }

        // Legacy bulk actions bar (fallback) — również oparty o widoczną selekcję
        const bulkActionsBar = document.getElementById('bulk-actions-bar');
        if (bulkActionsBar) {
            if (visibleCount > 0) {
                bulkActionsBar.style.display = 'flex';
                const countSpan = document.getElementById('bulk-selected-count');
                if (countSpan) {
                    countSpan.textContent = countLabel;
                }
                // Enable status change for any selected products
                const legacyStatusBtn = document.getElementById('bulk-change-status');
                if (legacyStatusBtn) {
                    legacyStatusBtn.disabled = false;
                    legacyStatusBtn.title = 'Zmień status zaznaczonych produktów';
                    legacyStatusBtn.style.opacity = '';
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
        const orders = this.state.filteredOrders;

        this.state.stats = {
            orderCount: orders.length,
            totalCount: products.length,
            filteredCount: products.length,
            totalQuantity: products.reduce((sum, p) => sum + (parseInt(p.quantity) || 1), 0),
            totalVolume: orders.reduce((sum, o) => sum + o.totalVolume, 0),
            totalValue: orders.reduce((sum, o) => sum + o.totalValue, 0),
            urgentCount: orders.filter(o => {
                if (!o.deadline) return false;
                return this.calculateDaysUntilDeadline(o.deadline) <= 3;
            }).length,
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
        const s = this.state.stats;

        // New IL stats elements
        this.updateElementText('il-stats-orders', s.orderCount);
        this.updateElementText('il-stats-products', s.totalCount);
        this.updateElementText('il-stats-volume', `${s.totalVolume.toFixed(4)} m³`);
        this.updateElementText('il-stats-value', `${s.totalValue.toLocaleString('pl-PL', {minimumFractionDigits: 2})} zł`);

        const urgentEl = document.getElementById('il-stats-urgent');
        if (urgentEl) {
            urgentEl.textContent = s.urgentCount;
            urgentEl.closest('.il-stat-card')?.classList.toggle('danger', s.urgentCount > 0);
        }

        // Legacy stats elements (fallback)
        const totalCountEl = document.getElementById('stats-total-count');
        const volumeEl = document.getElementById('stats-total-volume');
        const valueEl = document.getElementById('stats-total-value');
        const urgentLegacyEl = document.getElementById('stats-urgent-count');

        if (totalCountEl) {
            const positions = s.filteredCount;
            const quantity = s.totalQuantity;
            if (quantity > positions) {
                totalCountEl.innerHTML = `${positions} <small style="opacity:0.7">/ ${quantity} szt.</small>`;
            } else {
                totalCountEl.textContent = positions;
            }
        }
        if (volumeEl) volumeEl.textContent = s.totalVolume.toFixed(4);
        if (valueEl) {
            valueEl.textContent = s.totalValue.toLocaleString('pl-PL', {
                minimumFractionDigits: 0,
                maximumFractionDigits: 0
            });
        }
        if (urgentLegacyEl) urgentLegacyEl.textContent = s.urgentCount;
    }

    updateElementText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
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
        if (!status) return 'Nieznany';
        const normalized = status.toLowerCase();
        return ProductsModule.STATUS_TRANSLATIONS[normalized] || ProductsModule.STATUS_TRANSLATIONS[status] || status;
    }

    getDeadlineClass(daysUntilDeadline) {
        if (daysUntilDeadline < 0) return 'urgent';
        if (daysUntilDeadline <= 1) return 'urgent';
        if (daysUntilDeadline <= 7) return 'warning';
        return 'normal';
    }

    updatePriorityColor(element, priority) {
        const score = parseInt(priority) || 100;
        element.className = 'priority-rank';
        
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
    async showProductDetails(productId) {
        console.log(`[ProductsModule] Showing details for product ${productId}`);

        // Najpierw sprawdź cache — jeśli mamy komplet pól (w tym nowe stacje), użyj ich
        let product = this.state.filteredProducts.find(p => p.id == productId) ||
                     this.state.products.find(p => p.id == productId);

        const hasNewStationFields = product && (
            product.hasOwnProperty('gluing_started_at') ||
            product.hasOwnProperty('formatting_started_at') ||
            product.hasOwnProperty('finishing_started_at')
        );

        // Brak pełnych danych w cache → pobierz pojedynczy produkt z dedykowanego endpointu.
        // Historycznie używano /products-filtered bez parametrów, co zwracało tylko
        // pierwsze 50 wyników i dodatkowo nadpisywało state.products tym wycinkiem —
        // produkty poza pierwszą stroną pokazywały alert "Nie znaleziono produktu".
        if (!hasNewStationFields) {
            console.log(`[ProductsModule] Cached product missing new station fields, fetching from /products/${productId}/details`);
            try {
                const response = await fetch(`/production/api/products/${productId}/details`);
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const data = await response.json();
                if (data.success && data.product) {
                    product = data.product;
                    // Zaktualizuj pojedynczy rekord w cache zamiast podmieniać całość.
                    // Jeśli produkt nie był w cache (np. otwarty spoza aktualnej strony),
                    // dopisz go — inaczej lookupy po id (priority edit, _getProductKeyById)
                    // wracałyby null/undefined i bulk akcje cicho failowałyby.
                    const idxAll = this.state.products.findIndex(p => p.id == productId);
                    if (idxAll >= 0) this.state.products[idxAll] = product;
                    else this.state.products.push(product);
                    const idxFiltered = this.state.filteredProducts.findIndex(p => p.id == productId);
                    if (idxFiltered >= 0) this.state.filteredProducts[idxFiltered] = product;
                }
            } catch (error) {
                console.error('[ProductsModule] Error fetching product details:', error);
                // Fallback do cached obiektu jeśli jest — może brakować nowych pól, ale lepsze niż nic
            }
        } else {
            console.log('[ProductsModule] Using cached product data (has new station fields)');
        }

        if (!product) {
            alert('Nie znaleziono produktu');
            return;
        }

        // DEBUG: Loguj cały obiekt produktu
        console.log('[ProductsModule] Full product object:', product);
        console.log('[ProductsModule] Product keys:', Object.keys(product));

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

            // === POSTĘP PRODUKCJI (quantity) ===
            this.generateQuantityProgress(modalElement, product);

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
            const priority = parseInt(product.priority_rank) || 100;
            priorityIndicator.className = `priority-indicator ${this.getPriorityClass(priority)}`;
        }
    }

    /**
     * Wypełnia karty statystyk na górze
     */
    populateStatsCards(modalElement, product) {
        const volumeElement = modalElement.querySelector('.stats-row .stat-value[data-field="volume_m3"]');
        if (volumeElement) {
            const volume = (parseFloat(product.volume_m3) || 0) * (product.quantity || 1);
            volumeElement.textContent = `${volume.toFixed(4)} m³`;
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
                // Użyj total_products_in_order jeśli istnieje, inaczej pokaż placeholder
                const total = product.total_products_in_order || '--';
                value = `${product.product_sequence_in_order || 1}/${total}`;
            } else if (fieldName === 'dimensions_display') {
                value = this.formatDimensions(product);
            } else if (fieldName === 'baselinker_link') {
                return;
            } else if (fieldName === 'attachment_file_url') {
                // Specjalna obsługa dla linku do załącznika
                if (value && field.tagName === 'A') {
                    field.href = value;
                }
                return;
            }

            const formattedValue = this.formatModalValue(value, fieldType, unit);

            if (fieldType === 'email' && value) {
                field.innerHTML = `<a href="mailto:${value}">${value}</a>`;
            } else {
                field.innerHTML = formattedValue;
            }
        });

        // Obsługa pola obróbki krawędzi
        const edgeFieldGroup = modalElement.querySelector('#edge-processing-field-group');
        if (edgeFieldGroup) {
            if (product.parsed_edge_processing) {
                edgeFieldGroup.style.display = '';
                const edgeValue = edgeFieldGroup.querySelector('[data-field="parsed_edge_processing"]');
                if (edgeValue) {
                    var edgeText = '';
                    if (product.parsed_edge_type) {
                        edgeText = product.parsed_edge_type.charAt(0).toUpperCase() + product.parsed_edge_type.slice(1);
                        if (product.parsed_edge_radius) {
                            edgeText += ' R' + product.parsed_edge_radius;
                        }
                        if (product.parsed_edge_angle) {
                            edgeText += ' ' + product.parsed_edge_angle + '°';
                        }
                        if (product.parsed_edge_letters && product.parsed_edge_letters.length > 0) {
                            edgeText += ' (' + product.parsed_edge_letters.join(', ') + ')';
                        }
                    } else {
                        edgeText = 'Tak';
                    }
                    edgeValue.textContent = edgeText;
                    edgeValue.classList.add('text-success');
                }
            } else {
                edgeFieldGroup.style.display = 'none';
            }
        }

        // Obsługa pola załączników w specyfikacji technicznej - pokaż/ukryj w zależności od obecności załącznika
        const attachmentFieldGroup = modalElement.querySelector('#attachment-field-group');
        console.log('[ProductsModule] Attachment field group:', attachmentFieldGroup);
        console.log('[ProductsModule] Product attachment data:', {
            url: product.attachment_file_url,
            name: product.attachment_file_name
        });

        if (attachmentFieldGroup) {
            if (product.attachment_file_url && product.attachment_file_name) {
                attachmentFieldGroup.style.display = 'block';
                console.log('[ProductsModule] Showing attachment field');
            } else {
                attachmentFieldGroup.style.display = 'none';
                console.log('[ProductsModule] Hiding attachment field - no attachment');
            }
        } else {
            console.warn('[ProductsModule] Attachment field group element not found in modal');
        }
    }

    /**
     * Zwraca listę kodów stanowisk dla danej technologii produktu.
     * mikrowczep → wycinanie + wspólne stanowiska
     * lity → składanie + wspólne stanowiska
     */
    getStationsForProduct(product) {
        const technology = (product.parsed_technology || '').toLowerCase();
        const finishState = (product.parsed_finish_state || '').toLowerCase();

        // Sprawdź czy produkt wymaga lakierni (olejowane, lakierowane, bejcowane)
        const needsPainting = ['olej', 'lakier', 'bejc'].some(k => finishState.includes(k));

        // Wspólne stanowiska (od sklejania dalej)
        const commonStations = ['gluing', 'formatting', 'finishing'];

        if (needsPainting) {
            commonStations.push('painting');
        }

        commonStations.push('logistics', 'packaging');

        if (technology === 'mikrowczep') {
            return ['cutting', ...commonStations];
        } else if (technology === 'lity') {
            return ['assembly', ...commonStations];
        }

        // Fallback — pokaż oba (dla starych danych lub braku technologii)
        return ['cutting', 'assembly', ...commonStations];
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
                name: 'Wycinanie - mikro',
                status: 'czeka_na_wyciecie',
                icon: 'fas fa-cut',
                color: 'cutting-theme',
                startField: 'cutting_started_at',
                endField: 'cutting_completed_at',
                durationField: 'cutting_duration_minutes'
            },
            {
                code: 'assembly',
                name: 'Składanie - lite',
                status: 'czeka_na_skladanie',
                icon: 'fas fa-hammer',
                color: 'assembly-theme',
                startField: 'assembly_started_at',
                endField: 'assembly_completed_at',
                durationField: 'assembly_duration_minutes'
            },
            {
                code: 'gluing',
                name: 'Sklejanie',
                status: 'czeka_na_sklejanie',
                icon: 'fas fa-compress-arrows-alt',
                color: 'gluing-theme',
                startField: 'gluing_started_at',
                endField: 'gluing_completed_at',
                durationField: 'gluing_duration_minutes'
            },
            {
                code: 'formatting',
                name: 'Formatowanie',
                status: 'czeka_na_formatowanie',
                icon: 'fas fa-ruler-combined',
                color: 'formatting-theme',
                startField: 'formatting_started_at',
                endField: 'formatting_completed_at',
                durationField: 'formatting_duration_minutes'
            },
            {
                code: 'finishing',
                name: 'Wykańczanie',
                status: 'czeka_na_wykanczanie',
                icon: 'fas fa-star',
                color: 'finishing-theme',
                startField: 'finishing_started_at',
                endField: 'finishing_completed_at',
                durationField: 'finishing_duration_minutes'
            },
            {
                code: 'painting',
                name: 'Lakiernia',
                status: 'czeka_na_lakiernie',
                icon: 'fas fa-paint-roller',
                color: 'finishing-theme',
                startField: null,
                endField: 'painting_completed_at',
                durationField: null,
                isSubstep: true
            },
            {
                code: 'logistics',
                name: 'Logistyka',
                status: 'czeka_na_logistyke',
                icon: 'fas fa-truck',
                color: 'logistics-theme',
                startField: null,
                endField: 'logistics_completed_at',
                durationField: null
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

        // Filtruj stanowiska wg technologii produktu
        const allowedCodes = this.getStationsForProduct(product);
        const filteredStations = stations.filter(s => allowedCodes.includes(s.code));

        let html = '';
        const quantity = product.quantity || 1;

        filteredStations.forEach(station => {
            const timelineState = this.getTimelineState(station, product);
            const details = this.getTimelineDetails(station, product);

            // Ilość wykonana na tym stanowisku
            // Fallback: jeśli stanowisko jest zakończone (ma completed_at), ale quantity_done = 0,
            // to znaczy że dane są ze starego systemu - pokazujemy quantity jako done
            let quantityDone = product[`quantity_done_${station.code}`] || 0;
            const completedAt = product[station.endField];
            if (completedAt && quantityDone === 0) {
                quantityDone = quantity; // Stanowisko zakończone = wszystkie sztuki wykonane
            }
            const quantityInfo = `${quantityDone}/${quantity} szt.`;

            const isSubstep = station.isSubstep || false;
            const substepClass = isSubstep ? 'timeline-substep' : '';

            html += `
                <div class="timeline-item ${timelineState.cssClass} ${substepClass}">
                    <div class="timeline-icon ${station.color}">
                        <i class="${station.icon}"></i>
                    </div>
                    <div class="timeline-content">
                        <div class="timeline-header">
                            <h6 class="timeline-title ${station.color}">${station.name}</h6>
                            <span class="timeline-quantity">${quantityInfo}</span>
                        </div>
                        <p class="timeline-details">${details.text}</p>
                        <span class="timeline-status">${timelineState.statusText}</span>
                    </div>
                </div>
            `;
        });

        timelineContainer.innerHTML = html;
    }

    /**
     * Aktualizuje badge ilości w nagłówku timeline
     */
    generateQuantityProgress(modalElement, product) {
        const badge = modalElement.querySelector('#quantityBadge');
        if (!badge) return;

        const quantity = product.quantity || 1;
        const stations = this.getStationsForProduct(product);
        const endFields = {
            'cutting': 'cutting_completed_at',
            'assembly': 'assembly_completed_at',
            'gluing': 'gluing_completed_at',
            'formatting': 'formatting_completed_at',
            'finishing': 'finishing_completed_at',
            'logistics': 'logistics_completed_at',
            'packaging': 'packaging_completed_at'
        };
        const statusMap = {
            'cutting': 'czeka_na_wyciecie',
            'assembly': 'czeka_na_skladanie',
            'gluing': 'czeka_na_sklejanie',
            'formatting': 'czeka_na_formatowanie',
            'finishing': 'czeka_na_wykanczanie',
            'logistics': 'czeka_na_logistyke',
            'packaging': 'czeka_na_pakowanie'
        };

        const currentStatus = (product.current_status || '').toLowerCase();

        // Count completed + skipped + active stations
        let passedStations = 0;
        stations.forEach((station, index) => {
            if (product[endFields[station]]) {
                // Completed
                passedStations++;
            } else if (currentStatus === statusMap[station]) {
                // Currently active — count as half done
                passedStations += 0.5;
            } else {
                // Check if skipped (later station has progress)
                const laterStations = stations.slice(index + 1);
                const skipped = laterStations.some(later =>
                    product[endFields[later]] || currentStatus === statusMap[later]
                );
                if (skipped) passedStations++;
            }
        });

        // Spakowane = 100%
        if (currentStatus === 'spakowane') passedStations = stations.length;

        const totalPercent = Math.round((passedStations / stations.length) * 100);
        badge.textContent = `${quantity} szt. • ${totalPercent}%`;
    }

    /**
     * Określa stan timeline dla stacji
     */
    getTimelineState(station, product) {
        const stationOrder = ['cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'painting', 'logistics', 'packaging'];
        const endFields = {
            'cutting': 'cutting_completed_at',
            'assembly': 'assembly_completed_at',
            'gluing': 'gluing_completed_at',
            'formatting': 'formatting_completed_at',
            'finishing': 'finishing_completed_at',
            'painting': 'painting_completed_at',
            'logistics': 'logistics_completed_at',
            'packaging': 'packaging_completed_at'
        };
        const statusMap = {
            'cutting': 'czeka_na_wyciecie',
            'assembly': 'czeka_na_skladanie',
            'gluing': 'czeka_na_sklejanie',
            'formatting': 'czeka_na_formatowanie',
            'finishing': 'czeka_na_wykanczanie',
            'painting': 'czeka_na_lakiernie',
            'logistics': 'czeka_na_logistyke',
            'packaging': 'czeka_na_pakowanie'
        };

        const currentStatus = product.current_status;
        const expectedStatus = statusMap[station.code];

        // Completed — this station has a completed_at timestamp
        if (product[station.endField]) {
            return {
                cssClass: 'timeline-completed',
                statusText: 'Zakończone'
            };
        }

        // Active — product is currently at this station
        if (currentStatus === expectedStatus) {
            return {
                cssClass: 'timeline-active',
                statusText: 'W trakcie'
            };
        }

        // Check if a LATER station has completed_at or is the current station
        // If so, this station was skipped
        const currentIndex = stationOrder.indexOf(station.code);
        const laterStations = stationOrder.slice(currentIndex + 1);

        const laterHasProgress = laterStations.some(laterCode => {
            // Later station has completed_at
            if (product[endFields[laterCode]]) return true;
            // Product is currently at a later station
            if (currentStatus === statusMap[laterCode]) return true;
            // Product is already packed
            if (currentStatus === 'spakowane') return true;
            return false;
        });

        if (laterHasProgress) {
            return {
                cssClass: 'timeline-skipped',
                statusText: 'Pominięto'
            };
        }

        // Default — waiting
        return {
            cssClass: 'timeline-pending',
            statusText: 'Oczekuje'
        };
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
            return {
                text: 'Oczekuje na rozpoczęcie'
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
                displayName: 'Wycinanie - mikro',
                color: 'cutting-theme',
                cssClass: 'cutting'
            },
            'w_trakcie_ciecia': {
                icon: 'fa-cut',
                displayName: 'Wycinanie - mikro',
                color: 'cutting-theme',
                cssClass: 'cutting'
            },
            'czeka_na_skladanie': {
                icon: 'fa-hammer',
                displayName: 'Składanie - lite',
                color: 'assembly-theme',
                cssClass: 'assembly'
            },
            'w_trakcie_skladania': {
                icon: 'fa-hammer',
                displayName: 'Składanie - lite',
                color: 'assembly-theme',
                cssClass: 'assembly'
            },
            'czeka_na_sklejanie': {
                icon: 'fa-compress-arrows-alt',
                displayName: 'Sklejanie',
                color: 'gluing-theme',
                cssClass: 'gluing'
            },
            'w_trakcie_sklejania': {
                icon: 'fa-compress-arrows-alt',
                displayName: 'Sklejanie',
                color: 'gluing-theme',
                cssClass: 'gluing'
            },
            'czeka_na_formatowanie': {
                icon: 'fa-ruler-combined',
                displayName: 'Formatowanie',
                color: 'formatting-theme',
                cssClass: 'formatting'
            },
            'w_trakcie_formatowania': {
                icon: 'fa-ruler-combined',
                displayName: 'Formatowanie',
                color: 'formatting-theme',
                cssClass: 'formatting'
            },
            'czeka_na_wykanczanie': {
                icon: 'fa-star',
                displayName: 'Wykańczanie',
                color: 'finishing-theme',
                cssClass: 'finishing'
            },
            'w_trakcie_wykanczania': {
                icon: 'fa-star',
                displayName: 'Wykańczanie',
                color: 'finishing-theme',
                cssClass: 'finishing'
            },
            'czeka_na_lakiernie': {
                icon: 'fa-paint-roller',
                displayName: 'Lakiernia',
                color: 'painting-theme',
                cssClass: 'painting'
            },
            'czeka_na_logistyke': {
                icon: 'fa-truck',
                displayName: 'Logistyka',
                color: 'logistics-theme',
                cssClass: 'logistics'
            },
            'czeka_na_pakowanie': {
                icon: 'fa-box',
                displayName: 'Pakowanie',
                color: 'packaging-theme',
                cssClass: 'packaging'
            },
            'w_trakcie_pakowania': {
                icon: 'fa-box',
                displayName: 'Pakowanie',
                color: 'packaging-theme',
                cssClass: 'packaging'
            },
            'spakowane': {
                icon: 'fa-check-circle',
                displayName: 'Spakowane',
                color: 'text-success',
                cssClass: 'completed'
            },
            'w_realizacji': {
                icon: 'fa-cog',
                displayName: 'W realizacji',
                color: 'text-info',
                cssClass: 'in-progress'
            },
            'wstrzymane': {
                icon: 'fa-pause-circle',
                displayName: 'Wstrzymane',
                color: 'text-warning',
                cssClass: 'paused'
            },
            'anulowane': {
                icon: 'fa-times-circle',
                displayName: 'Anulowane',
                color: 'text-danger',
                cssClass: 'cancelled'
            }
        };

        const normalizedStatus = status ? status.toLowerCase().trim() : '';
        return configs[normalizedStatus] || {
            icon: 'fa-question-circle',
            displayName: normalizedStatus ? normalizedStatus.replace('czeka_na_', '').replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase()) : 'Nieznany',
            color: 'text-muted',
            cssClass: 'unknown'
        };
    }

    // getStatusBadgeClass — see new implementation above (line ~1645)

    // getStatusDisplayName — see unified version above (line ~3287) using STATUS_TRANSLATIONS

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
                        <div class="product-nav-spec">${product.specification || ''}</div>
                        <div class="product-nav-dim">${product.dimensions || ''}</div>
                        <div class="product-nav-id">${product.short_product_id}</div>
                    </button>
                `;
            });

            buttonsContainer.innerHTML = buttonsHtml;

            // Setup scroll arrows
            const leftArrow = document.getElementById('productsNavLeft');
            const rightArrow = document.getElementById('productsNavRight');
            const scrollAmount = 210;

            if (leftArrow) {
                leftArrow.addEventListener('click', () => {
                    buttonsContainer.scrollBy({ left: -scrollAmount, behavior: 'smooth' });
                });
            }
            if (rightArrow) {
                rightArrow.addEventListener('click', () => {
                    buttonsContainer.scrollBy({ left: scrollAmount, behavior: 'smooth' });
                });
            }
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

        // Przycisk odświeżania z Baselinker
        const refreshBtn = modalElement.querySelector('#refreshFromBaselinkerBtn');
        if (refreshBtn && product.baselinker_order_id) {
            refreshBtn.dataset.baselinkerOrderId = product.baselinker_order_id;
            refreshBtn.style.display = '';
            refreshBtn.onclick = () => this.openBaselinkerCompareModal(product.baselinker_order_id);
        } else if (refreshBtn) {
            refreshBtn.style.display = 'none';
        }
    }

    /**
     * Otwiera modal porównania z Baselinker
     */
    async openBaselinkerCompareModal(baselinkerOrderId) {
        const modal = document.getElementById('baselinkerCompareModal');
        if (!modal) {
            console.error('[ProductsModule] Modal baselinkerCompareModal nie znaleziony');
            return;
        }

        // Reset stanu modala
        const loading = modal.querySelector('#blCompareLoading');
        const error = modal.querySelector('#blCompareError');
        const noChanges = modal.querySelector('#blCompareNoChanges');
        const content = modal.querySelector('#blCompareContent');
        const applyBtn = modal.querySelector('#blApplyChangesBtn');

        loading.style.display = 'block';
        error.style.display = 'none';
        noChanges.style.display = 'none';
        content.style.display = 'none';
        applyBtn.disabled = true;

        // Otwórz modal
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();

        try {
            // Pobierz porównanie z API
            const response = await fetch('/production/api/admin/compare-baselinker-order', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    baselinker_order_id: baselinkerOrderId
                })
            });

            const data = await response.json();
            loading.style.display = 'none';

            if (!data.success) {
                error.style.display = 'block';
                modal.querySelector('#blCompareErrorText').textContent = data.error || 'Nieznany błąd';
                return;
            }

            if (!data.has_changes) {
                noChanges.style.display = 'block';
                return;
            }

            // Wyświetl zmiany
            this.renderBaselinkerChanges(modal, data);
            content.style.display = 'block';
            applyBtn.disabled = false;

            // Zapisz dane zmian dla przycisku zastosuj
            applyBtn.onclick = () => this.applyBaselinkerChanges(baselinkerOrderId, data.changes, bsModal);

        } catch (err) {
            console.error('[ProductsModule] Błąd porównania z Baselinker:', err);
            loading.style.display = 'none';
            error.style.display = 'block';
            modal.querySelector('#blCompareErrorText').textContent = 'Błąd połączenia z serwerem';
        }
    }

    /**
     * Renderuje zmiany z Baselinker w modalu
     */
    renderBaselinkerChanges(modal, data) {
        const orderNumberEl = modal.querySelector('#blCompareOrderNumber');
        if (orderNumberEl) {
            orderNumberEl.textContent = data.order_number || data.order_id;
        }

        // Produkty do usunięcia
        const removeSection = modal.querySelector('#blProductsToRemove');
        const removeList = modal.querySelector('#blRemoveList');
        const removeCount = modal.querySelector('#blRemoveCount');
        const toRemove = data.changes.products_to_remove || [];

        if (toRemove.length > 0) {
            removeSection.style.display = 'block';
            removeCount.textContent = toRemove.length;
            removeList.innerHTML = toRemove.map(p => `
                <div class="bl-change-item bl-change-remove">
                    <div class="bl-change-id">${p.short_product_id}</div>
                    <div class="bl-change-name">${p.original_product_name}</div>
                    <div class="bl-change-qty">× ${p.quantity} szt.</div>
                </div>
            `).join('');
        } else {
            removeSection.style.display = 'none';
        }

        // Produkty do dodania
        const addSection = modal.querySelector('#blProductsToAdd');
        const addList = modal.querySelector('#blAddList');
        const addCount = modal.querySelector('#blAddCount');
        const toAdd = data.changes.products_to_add || [];

        if (toAdd.length > 0) {
            addSection.style.display = 'block';
            addCount.textContent = toAdd.length;
            addList.innerHTML = toAdd.map(p => `
                <div class="bl-change-item bl-change-add">
                    <div class="bl-change-id">NOWY</div>
                    <div class="bl-change-name">${p.name}</div>
                    <div class="bl-change-qty">× ${p.quantity} szt.</div>
                </div>
            `).join('');
        } else {
            addSection.style.display = 'none';
        }

        // Produkty do aktualizacji
        const updateSection = modal.querySelector('#blProductsToUpdate');
        const updateList = modal.querySelector('#blUpdateList');
        const updateCount = modal.querySelector('#blUpdateCount');
        const toUpdate = data.changes.products_to_update || [];

        if (toUpdate.length > 0) {
            updateSection.style.display = 'block';
            updateCount.textContent = toUpdate.length;
            updateList.innerHTML = toUpdate.map(p => `
                <div class="bl-change-item bl-change-update">
                    <div class="bl-change-id">${p.short_product_id}</div>
                    <div class="bl-change-details">
                        ${p.changes.map(c => `
                            <div class="bl-field-change">
                                <span class="bl-field-label">${c.label}:</span>
                                <span class="bl-old-value">${c.old_value}</span>
                                <i class="fas fa-arrow-right mx-2"></i>
                                <span class="bl-new-value">${c.new_value}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `).join('');
        } else {
            updateSection.style.display = 'none';
        }

        // Zmiany na poziomie zamówienia
        const orderLevelSection = modal.querySelector('#blOrderLevelChanges');
        const orderLevelList = modal.querySelector('#blOrderLevelList');
        const orderLevelChanges = data.changes.order_level || [];

        if (orderLevelChanges.length > 0) {
            orderLevelSection.style.display = 'block';
            orderLevelList.innerHTML = orderLevelChanges.map(c => `
                <div class="bl-change-item bl-change-order">
                    <div class="bl-field-change">
                        <span class="bl-field-label">${c.label}:</span>
                        <span class="bl-old-value">${c.old_value || '(brak)'}</span>
                        <i class="fas fa-arrow-right mx-2"></i>
                        <span class="bl-new-value">${c.new_value || '(brak)'}</span>
                    </div>
                </div>
            `).join('');
        } else {
            orderLevelSection.style.display = 'none';
        }
    }

    /**
     * Aplikuje zmiany z Baselinker
     */
    async applyBaselinkerChanges(baselinkerOrderId, changes, bsModal) {
        const applyBtn = document.querySelector('#blApplyChangesBtn');
        const originalText = applyBtn.innerHTML;

        try {
            applyBtn.disabled = true;
            applyBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Zapisywanie...';

            const response = await fetch('/production/api/admin/apply-baselinker-changes', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    baselinker_order_id: baselinkerOrderId,
                    changes: changes
                })
            });

            const data = await response.json();

            if (data.success) {
                // Sukces - zamknij modal i odśwież listę
                bsModal.hide();

                // Pokaż powiadomienie
                this.showNotification('success',
                    `Zaktualizowano: dodano ${data.added}, usunięto ${data.removed}, zmodyfikowano ${data.updated} produktów`
                );

                // Odśwież listę produktów
                this.loadProducts(true);

                // Zamknij też modal szczegółów produktu
                const detailModal = document.getElementById('productModal');
                if (detailModal) {
                    const detailBsModal = bootstrap.Modal.getInstance(detailModal);
                    if (detailBsModal) {
                        detailBsModal.hide();
                    }
                }
            } else {
                alert(`Błąd: ${data.error}`);
                applyBtn.disabled = false;
                applyBtn.innerHTML = originalText;
            }

        } catch (err) {
            console.error('[ProductsModule] Błąd aplikowania zmian:', err);
            alert('Błąd połączenia z serwerem');
            applyBtn.disabled = false;
            applyBtn.innerHTML = originalText;
        }
    }

    /**
     * Wyświetla powiadomienie toast
     */
    showNotification(type, message) {
        // Sprawdź czy istnieje kontener na toasty
        let toastContainer = document.querySelector('.toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            toastContainer.style.zIndex = '9999';
            document.body.appendChild(toastContainer);
        }

        const toastId = 'toast-' + Date.now();
        const bgClass = type === 'success' ? 'bg-success' : (type === 'error' ? 'bg-danger' : 'bg-info');
        const icon = type === 'success' ? 'fa-check-circle' : (type === 'error' ? 'fa-exclamation-circle' : 'fa-info-circle');

        const toastHtml = `
            <div id="${toastId}" class="toast align-items-center text-white ${bgClass} border-0" role="alert">
                <div class="d-flex">
                    <div class="toast-body">
                        <i class="fas ${icon} me-2"></i>
                        ${message}
                    </div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
                </div>
            </div>
        `;

        toastContainer.insertAdjacentHTML('beforeend', toastHtml);

        const toastEl = document.getElementById(toastId);
        const toast = new bootstrap.Toast(toastEl, { delay: 5000 });
        toast.show();

        toastEl.addEventListener('hidden.bs.toast', () => {
            toastEl.remove();
        });
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

    // getStatusConfig — single definition at line ~3907, removed duplicate here

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