/**
 * ArchiveModule — widok zamówień w pełni spakowanych.
 *
 * Niezależny od ProductsModule. Reużywa endpoint /products-tab-content z view=archive
 * oraz część stylów (.il-*) z products-tab.css; własny scope DOM przez prefix `arch-`.
 *
 * Bez: drag&drop, gwiazdki priorytetu, edycji statusu, recalc kolejki.
 * Zamiast: filtr zakresu dat, presety, statystyki archiwum (avg czas realizacji),
 *          kolumna "Zakończono" zamiast "Termin", sortowanie completedAt DESC.
 */

const STATUS_DISPLAY_NAMES = {
    'czeka_na_wyciecie': 'Czeka na wycięcie',
    'czeka_na_skladanie': 'Czeka na składanie',
    'czeka_na_sklejanie': 'Czeka na sklejanie',
    'czeka_na_formatowanie': 'Czeka na formatowanie',
    'czeka_na_wykanczanie': 'Czeka na wykańczanie',
    'czeka_na_lakiernie': 'Czeka na lakiernię',
    'czeka_na_logistyke': 'Czeka na logistykę',
    'czeka_na_pakowanie': 'Czeka na pakowanie',
    'spakowane': 'Spakowane',
    'w_realizacji': 'W realizacji',
    'wstrzymane': 'Wstrzymane',
    'anulowane': 'Anulowane'
};

class ArchiveModule {
    constructor(shared, config) {
        this.shared = shared;
        this.config = config;
        this.state = {
            products: [],
            orders: [],
            filteredOrders: [],
            filterOptions: {
                wood_species: [],
                technologies: [],
                wood_classes: [],
                thicknesses: []
            },
            filters: {
                search: '',
                woodSpecies: new Set(),
                technologies: new Set(),
                woodClasses: new Set(),
                thicknesses: new Set(),
                completedFrom: '',
                completedTo: ''
            },
            stats: null,
            expandedOrders: new Set(),
            isLoading: false
        };
        this.elements = {};
        this._searchDebounceTimer = null;
        this._initialized = false;
    }

    // ──────────────────────────────────────────────────────────────────────
    // LIFECYCLE
    // ──────────────────────────────────────────────────────────────────────

    async load(initialData) {
        this.cacheElements();

        if (initialData && Array.isArray(initialData.products)) {
            this.consumePayload(initialData);
        } else {
            await this.fetchData();
        }

        this.populateMultiselectOptions();
        this.attachEventListeners();
        this.applyFiltersAndRender();

        this._initialized = true;
        console.log('[ArchiveModule] Loaded with', this.state.orders.length, 'orders');
    }

    cacheElements() {
        const root = document.getElementById('archive-module-container');
        if (!root) {
            console.error('[ArchiveModule] Root container not found');
            return;
        }
        this.elements = {
            root,
            search: document.getElementById('arch-search'),
            applyFiltersBtn: document.getElementById('arch-apply-filters'),
            clearAllBtn: document.getElementById('arch-clear-all-filters'),
            activeFilters: document.getElementById('arch-active-filters'),
            filterBadges: document.getElementById('arch-filter-badges'),
            ordersList: document.getElementById('arch-orders-list'),
            loading: document.getElementById('arch-products-loading'),
            empty: document.getElementById('arch-products-empty'),
            emptyReason: document.getElementById('arch-empty-reason'),
            clearFiltersEmptyBtn: document.getElementById('arch-clear-filters-empty'),
            error: document.getElementById('arch-products-error'),
            errorMessage: document.getElementById('arch-error-message'),
            retryBtn: document.getElementById('arch-retry-load'),
            completedFrom: document.getElementById('arch-completed-from'),
            completedTo: document.getElementById('arch-completed-to'),
            datePresets: root.querySelectorAll('.arch-date-preset'),
            // stats
            statOrders: document.getElementById('arch-stats-orders'),
            statProducts: document.getElementById('arch-stats-products'),
            statVolume: document.getElementById('arch-stats-volume'),
            statValue: document.getElementById('arch-stats-value'),
            statAvgDays: document.getElementById('arch-stats-avg-days'),
            // multiselects
            multiselects: {
                'wood-species': {
                    container: document.getElementById('arch-filter-wood-species'),
                    dropdown: document.getElementById('arch-dropdown-wood-species')
                },
                'technology': {
                    container: document.getElementById('arch-filter-technology'),
                    dropdown: document.getElementById('arch-dropdown-technology')
                },
                'wood-class': {
                    container: document.getElementById('arch-filter-wood-class'),
                    dropdown: document.getElementById('arch-dropdown-wood-class')
                },
                'thickness': {
                    container: document.getElementById('arch-filter-thickness'),
                    dropdown: document.getElementById('arch-dropdown-thickness')
                }
            }
        };
    }

    // ──────────────────────────────────────────────────────────────────────
    // DATA FETCH
    // ──────────────────────────────────────────────────────────────────────

    async fetchData() {
        if (this.state.isLoading) return;
        this.state.isLoading = true;
        this.showLoading();
        try {
            const params = { view: 'archive' };
            if (this.state.filters.completedFrom) params.completed_from = this.state.filters.completedFrom;
            if (this.state.filters.completedTo) params.completed_to = this.state.filters.completedTo;

            const resp = await this.shared.apiClient.getProductsTabContent(params);
            if (!resp.success) throw new Error(resp.error || 'Błąd pobierania archiwum');
            this.consumePayload(resp.initial_data);
        } catch (err) {
            console.error('[ArchiveModule] fetchData failed:', err);
            this.showError(err.message || 'Błąd ładowania archiwum');
        } finally {
            this.state.isLoading = false;
            this.hideLoading();
        }
    }

    consumePayload(data) {
        this.state.products = data.products || [];
        this.state.filterOptions = data.filters || this.state.filterOptions;
        this.state.stats = data.stats || null;
        this.state.orders = this.groupProductsByOrder(this.state.products);
    }

    // ──────────────────────────────────────────────────────────────────────
    // GROUPING
    // ──────────────────────────────────────────────────────────────────────

    groupProductsByOrder(products) {
        const ordersMap = new Map();
        products.forEach(product => {
            const orderKey = product.internal_order_number
                || product.baselinker_order_id
                || `single-${product.id}`;

            if (!ordersMap.has(orderKey)) {
                ordersMap.set(orderKey, {
                    orderKey,
                    clientName: product.client_name || 'Brak danych',
                    baselinkerOrderId: product.baselinker_order_id,
                    clientOrderNumber: product.client_order_number,
                    internalOrderNumber: product.internal_order_number,
                    products: [],
                    totalVolume: 0,
                    totalValue: 0,
                    productCount: 0,
                    status: 'spakowane',
                    statusLabel: 'Spakowane',
                    completedAt: product.order_completed_at || null,
                    earliestCreatedAt: null,
                    realizationDays: null
                });
            }

            const order = ordersMap.get(orderKey);
            order.products.push(product);
            order.productCount += 1;
            order.totalVolume += (parseFloat(product.volume_m3) || 0) * (product.quantity || 1);
            order.totalValue += parseFloat(product.total_value_net) || 0;

            // completedAt: backend już ustawia order_completed_at = MAX(packaging_completed_at)
            if (product.order_completed_at && (!order.completedAt || product.order_completed_at > order.completedAt)) {
                order.completedAt = product.order_completed_at;
            }
            // earliestCreatedAt po stronie klienta (do liczenia czasu realizacji per-zamówienie)
            if (product.created_at) {
                if (!order.earliestCreatedAt || product.created_at < order.earliestCreatedAt) {
                    order.earliestCreatedAt = product.created_at;
                }
            }
        });

        // Per-zamówieniowy czas realizacji (dni)
        ordersMap.forEach(order => {
            if (order.completedAt && order.earliestCreatedAt) {
                const ms = new Date(order.completedAt) - new Date(order.earliestCreatedAt);
                if (ms >= 0) {
                    order.realizationDays = Math.round((ms / 86400000) * 10) / 10;
                }
            }
            order.totalVolume = Math.round(order.totalVolume * 10000) / 10000;
            order.totalValue = Math.round(order.totalValue * 100) / 100;
        });

        return Array.from(ordersMap.values());
    }

    // ──────────────────────────────────────────────────────────────────────
    // FILTERING / SORTING
    // ──────────────────────────────────────────────────────────────────────

    applyFiltersAndRender() {
        this.state.filteredOrders = this.state.orders.filter(o => this.orderPassesFilters(o));
        this.sortOrdersByCompletedDesc();
        this.renderActiveFiltersBadges();
        this.renderStats();
        this.renderOrders();
    }

    orderPassesFilters(order) {
        const f = this.state.filters;

        if (f.search) {
            const needle = f.search.toLowerCase();
            const hay = [
                order.clientName,
                order.internalOrderNumber,
                order.baselinkerOrderId ? `bl-${order.baselinkerOrderId}` : '',
                order.clientOrderNumber,
                ...order.products.map(p => p.original_product_name || ''),
                ...order.products.map(p => p.short_product_id || '')
            ].filter(Boolean).join(' ').toLowerCase();
            if (!hay.includes(needle)) return false;
        }

        if (f.woodSpecies.size && !order.products.some(p => f.woodSpecies.has(p.parsed_wood_species))) return false;
        if (f.technologies.size && !order.products.some(p => f.technologies.has(p.parsed_technology))) return false;
        if (f.woodClasses.size && !order.products.some(p => f.woodClasses.has(p.parsed_wood_class))) return false;
        if (f.thicknesses.size) {
            const hit = order.products.some(p => {
                if (!p.parsed_thickness_cm) return false;
                return f.thicknesses.has(`${p.parsed_thickness_cm}cm`);
            });
            if (!hit) return false;
        }

        return true;
    }

    sortOrdersByCompletedDesc() {
        this.state.filteredOrders.sort((a, b) => {
            if (!a.completedAt && !b.completedAt) return 0;
            if (!a.completedAt) return 1;
            if (!b.completedAt) return -1;
            return b.completedAt.localeCompare(a.completedAt);
        });
    }

    // ──────────────────────────────────────────────────────────────────────
    // RENDER: STATS
    // ──────────────────────────────────────────────────────────────────────

    renderStats() {
        const orders = this.state.filteredOrders;
        const productsCount = orders.reduce((acc, o) => acc + o.productCount, 0);
        const totalVolume = orders.reduce((acc, o) => acc + (o.totalVolume || 0), 0);
        const totalValue = orders.reduce((acc, o) => acc + (o.totalValue || 0), 0);

        const days = orders.map(o => o.realizationDays).filter(v => typeof v === 'number');
        const avgDays = days.length ? Math.round((days.reduce((a, b) => a + b, 0) / days.length) * 10) / 10 : null;

        if (this.elements.statOrders) this.elements.statOrders.textContent = orders.length;
        if (this.elements.statProducts) this.elements.statProducts.textContent = productsCount;
        if (this.elements.statVolume) this.elements.statVolume.textContent = `${totalVolume.toFixed(4)} m³`;
        if (this.elements.statValue) this.elements.statValue.textContent = `${totalValue.toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} zł`;
        if (this.elements.statAvgDays) {
            this.elements.statAvgDays.textContent = avgDays === null ? '— dni' : `${avgDays} dni`;
        }
    }

    // ──────────────────────────────────────────────────────────────────────
    // RENDER: ORDERS LIST
    // ──────────────────────────────────────────────────────────────────────

    renderOrders() {
        const container = this.elements.ordersList;
        if (!container) return;

        // Wyczyść poprzednie karty (stany loading/empty/error zostają)
        container.querySelectorAll('.arch-order-card').forEach(el => el.remove());

        if (!this.state.filteredOrders.length) {
            this.showEmpty();
            return;
        }
        this.hideEmpty();

        const fragment = document.createDocumentFragment();
        this.state.filteredOrders.forEach(order => {
            fragment.appendChild(this.createOrderCard(order));
        });
        container.appendChild(fragment);
    }

    createOrderCard(order) {
        const tpl = document.getElementById('arch-order-template');
        const card = tpl.content.cloneNode(true).firstElementChild;
        card.dataset.orderKey = order.orderKey;

        this.populateOrderHeader(card, order);
        this.populateOrderMeta(card, order);
        this.attachOrderListeners(card, order);

        return card;
    }

    populateOrderHeader(card, order) {
        const header = card.querySelector('.arch-order-header');

        // Status border-left (z definicji 'spakowane' → status-completed)
        header.classList.add(this.getStationClassFromStatus(order.status));

        // Client + IDs
        header.querySelector('.il-order-client').textContent = order.clientName;
        const idsContainer = header.querySelector('.il-order-ids');
        idsContainer.innerHTML = '';
        if (order.internalOrderNumber) {
            idsContainer.innerHTML += `<span class="il-order-id-tag">${this.escapeHtml(order.internalOrderNumber)}</span>`;
        }
        if (order.baselinkerOrderId) {
            idsContainer.innerHTML += `<span class="il-order-id-tag">BL-${order.baselinkerOrderId}</span>`;
        }
        if (order.clientOrderNumber) {
            idsContainer.innerHTML += `<span class="il-order-id-tag">${this.escapeHtml(order.clientOrderNumber)}</span>`;
        }

        header.querySelector('.il-order-positions').textContent = order.productCount;
        header.querySelector('.il-order-volume').textContent = `${order.totalVolume.toFixed(4)} m³`;
        header.querySelector('.il-order-value').textContent = `${order.totalValue.toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} zł`;

        // Status badge
        const badge = header.querySelector('.il-order-status-badge');
        badge.textContent = order.statusLabel;
        badge.className = `il-order-status-badge ${this.getStatusBadgeClass(order.status)}`;

        // Zakończono
        const completedEl = header.querySelector('.arch-order-completed');
        if (completedEl) {
            if (order.completedAt) {
                completedEl.textContent = this.formatDatePL(order.completedAt);
                if (order.realizationDays !== null) {
                    completedEl.title = `Czas realizacji: ${order.realizationDays} dni`;
                }
            } else {
                completedEl.textContent = '—';
            }
        }
    }

    populateOrderMeta(card, order) {
        const meta = card.querySelector('.il-order-card-meta');
        if (!meta) return;
        const parts = [];
        const metrics = [];
        if (order.totalVolume) metrics.push(`${order.totalVolume.toFixed(4)} m³`);
        if (order.totalValue) metrics.push(`${order.totalValue.toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} zł`);
        if (metrics.length) parts.push(`<span class="il-card-meta-metrics">${metrics.join(' · ')}</span>`);
        if (order.completedAt) {
            parts.push(`<span class="il-card-meta-deadline deadline-normal"><i class="fas fa-calendar-check"></i> Zakończono: ${this.formatDatePL(order.completedAt)}${order.realizationDays !== null ? ` (${order.realizationDays} dni)` : ''}</span>`);
        }
        meta.innerHTML = parts.join('');
    }

    attachOrderListeners(card, order) {
        const header = card.querySelector('.arch-order-header');
        const productsContainer = card.querySelector('.il-order-products');

        header.addEventListener('click', (e) => {
            if (e.target.closest('.il-order-actions')) return;
            const isExpanded = this.state.expandedOrders.has(order.orderKey);
            if (isExpanded) {
                this.state.expandedOrders.delete(order.orderKey);
                productsContainer.classList.add('collapsed');
                productsContainer.innerHTML = '';
                header.querySelector('.il-order-expand').textContent = '▶';
            } else {
                this.state.expandedOrders.add(order.orderKey);
                this.renderOrderProducts(productsContainer, order);
                productsContainer.classList.remove('collapsed');
                header.querySelector('.il-order-expand').textContent = '▼';
            }
        });

        // Akcje
        header.querySelectorAll('.il-order-action-btn').forEach(btn => {
            const action = btn.dataset.action;
            if (action === 'baselinker' && !order.baselinkerOrderId) {
                btn.classList.add('disabled');
                btn.setAttribute('disabled', 'true');
            }
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (btn.classList.contains('disabled')) return;
                if (action === 'baselinker' && order.baselinkerOrderId) {
                    window.open(`https://panel-f.baselinker.com/orders.php#order:${order.baselinkerOrderId}`, '_blank', 'noopener');
                } else if (action === 'details') {
                    this.openOrderDetails(order);
                }
            });
        });
    }

    /**
     * Otwiera modal szczegółów zamówienia (pierwsza pozycja).
     * Reużywa ProductsModule.showProductDetails — ładuje go jeśli jeszcze nie zainicjalizowany,
     * bo template modala jest częścią products-tab-content.html.
     */
    async openOrderDetails(order) {
        const firstProduct = order.products[0];
        if (!firstProduct) return;
        const productId = firstProduct.id || firstProduct.unique_id;

        try {
            if (!window.productsModule || typeof window.productsModule.showProductDetails !== 'function') {
                // Pre-load products tab (idempotentne — loadTabContent ma cache)
                if (window.ProductionApp && typeof window.ProductionApp.loadTabContent === 'function') {
                    await window.ProductionApp.loadTabContent('products-tab');
                }
            }
            if (window.productsModule && typeof window.productsModule.showProductDetails === 'function') {
                await window.productsModule.showProductDetails(productId);
            } else {
                console.warn('[ArchiveModule] productsModule.showProductDetails niedostępne');
                if (this.shared && this.shared.toastSystem) {
                    this.shared.toastSystem.show('Otwórz najpierw zakładkę "Lista produktów" aby załadować szczegóły', 'warning');
                }
            }
        } catch (err) {
            console.error('[ArchiveModule] openOrderDetails failed:', err);
        }
    }

    renderOrderProducts(container, order) {
        container.innerHTML = '';
        const tpl = document.getElementById('arch-product-template');
        const fragment = document.createDocumentFragment();
        order.products.forEach(p => {
            const row = tpl.content.cloneNode(true).firstElementChild;
            row.querySelector('.il-product-name-text').textContent = p.original_product_name || '(bez nazwy)';
            row.querySelector('.il-product-name-id').textContent = p.short_product_id || '';
            const specParts = [];
            if (p.parsed_wood_species) specParts.push(p.parsed_wood_species);
            if (p.parsed_technology) specParts.push(p.parsed_technology);
            if (p.parsed_wood_class) specParts.push(p.parsed_wood_class);
            if (p.parsed_length_cm && p.parsed_width_cm && p.parsed_thickness_cm) {
                specParts.push(`${p.parsed_length_cm}×${p.parsed_width_cm}×${p.parsed_thickness_cm} cm`);
            }
            row.querySelector('.il-product-spec').textContent = specParts.join(' · ');
            row.querySelector('.il-product-qty').textContent = `${p.quantity || 1} szt`;
            row.querySelector('.il-product-volume').textContent = `${(p.volume_m3 || 0).toFixed(4)} m³`;
            const badge = row.querySelector('.il-product-status-badge');
            badge.textContent = this.getStatusDisplayName(p.current_status);
            badge.className = `il-product-status-badge ${this.getStatusBadgeClass(p.current_status)}`;
            fragment.appendChild(row);
        });
        container.appendChild(fragment);
    }

    // ──────────────────────────────────────────────────────────────────────
    // FILTERS UI
    // ──────────────────────────────────────────────────────────────────────

    populateMultiselectOptions() {
        const opts = this.state.filterOptions;
        this.fillDropdown('wood-species', opts.wood_species);
        this.fillDropdown('technology', opts.technologies);
        this.fillDropdown('wood-class', opts.wood_classes);
        this.fillDropdown('thickness', opts.thicknesses);
    }

    fillDropdown(filterKey, values) {
        const ms = this.elements.multiselects[filterKey];
        if (!ms || !ms.dropdown) return;
        // Usuń poprzednie opcje (oprócz search-input i "zaznacz wszystkie")
        ms.dropdown.querySelectorAll('.il-multiselect-option').forEach((opt, idx) => {
            if (idx > 0) opt.remove();
        });
        (values || []).forEach(v => {
            const label = document.createElement('label');
            label.className = 'il-multiselect-option';
            label.innerHTML = `<input type="checkbox" value="${this.escapeHtml(v)}"> ${this.escapeHtml(v)}`;
            ms.dropdown.appendChild(label);
        });
    }

    attachEventListeners() {
        // Search (debounced)
        if (this.elements.search) {
            this.elements.search.addEventListener('input', (e) => {
                clearTimeout(this._searchDebounceTimer);
                this._searchDebounceTimer = setTimeout(() => {
                    this.state.filters.search = e.target.value.trim();
                    this.applyFiltersAndRender();
                }, 200);
            });
        }

        // Apply / clear
        if (this.elements.applyFiltersBtn) {
            this.elements.applyFiltersBtn.addEventListener('click', () => this.commitFiltersFromDOM(true));
        }
        if (this.elements.clearAllBtn) {
            this.elements.clearAllBtn.addEventListener('click', () => this.clearAllFilters());
        }
        if (this.elements.clearFiltersEmptyBtn) {
            this.elements.clearFiltersEmptyBtn.addEventListener('click', () => this.clearAllFilters());
        }
        if (this.elements.retryBtn) {
            this.elements.retryBtn.addEventListener('click', () => this.fetchData().then(() => this.applyFiltersAndRender()));
        }

        // Multiselects: open/close + checkboxes
        Object.entries(this.elements.multiselects).forEach(([key, ms]) => {
            if (!ms.container || !ms.dropdown) return;
            const trigger = ms.container.querySelector('.il-filter-dropdown');
            if (trigger) {
                trigger.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.closeAllDropdownsExcept(ms.dropdown);
                    ms.dropdown.style.display = ms.dropdown.style.display === 'none' ? 'block' : 'none';
                });
            }
            // search input wewnątrz dropdownu
            const dsrc = ms.dropdown.querySelector('.il-multiselect-search');
            if (dsrc) {
                dsrc.addEventListener('click', (e) => e.stopPropagation());
                dsrc.addEventListener('input', (e) => {
                    const q = e.target.value.toLowerCase();
                    ms.dropdown.querySelectorAll('.il-multiselect-option').forEach((opt, idx) => {
                        if (idx === 0) return; // "Zaznacz wszystkie"
                        const txt = opt.textContent.toLowerCase();
                        opt.style.display = txt.includes(q) ? '' : 'none';
                    });
                });
            }
            // checkboxy (delegacja)
            ms.dropdown.addEventListener('change', () => this.markPendingFilters());
        });

        // Globalne zamykanie dropdownów
        document.addEventListener('click', (e) => {
            if (!e.target.closest('#archive-module-container')) return;
            if (!e.target.closest('.il-multiselect')) {
                this.closeAllDropdownsExcept(null);
            }
        });

        // Date inputs
        if (this.elements.completedFrom) {
            this.elements.completedFrom.addEventListener('change', () => this.markPendingFilters());
        }
        if (this.elements.completedTo) {
            this.elements.completedTo.addEventListener('change', () => this.markPendingFilters());
        }

        // Date presets
        this.elements.datePresets.forEach(btn => {
            btn.addEventListener('click', () => this.applyDatePreset(btn.dataset.preset));
        });
    }

    markPendingFilters() {
        if (this.elements.applyFiltersBtn) {
            this.elements.applyFiltersBtn.classList.add('pending');
        }
    }

    closeAllDropdownsExcept(except) {
        Object.values(this.elements.multiselects).forEach(ms => {
            if (ms.dropdown && ms.dropdown !== except) {
                ms.dropdown.style.display = 'none';
            }
        });
    }

    commitFiltersFromDOM(refetchDates) {
        // Multiselecty → state
        const collect = (key) => {
            const ms = this.elements.multiselects[key];
            if (!ms || !ms.dropdown) return new Set();
            const values = new Set();
            ms.dropdown.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
                if (cb.value && cb.value !== '__all__') values.add(cb.value);
            });
            return values;
        };
        this.state.filters.woodSpecies = collect('wood-species');
        this.state.filters.technologies = collect('technology');
        this.state.filters.woodClasses = collect('wood-class');
        this.state.filters.thicknesses = collect('thickness');

        const fromVal = this.elements.completedFrom ? this.elements.completedFrom.value : '';
        const toVal = this.elements.completedTo ? this.elements.completedTo.value : '';
        const dateChanged = (fromVal !== this.state.filters.completedFrom) || (toVal !== this.state.filters.completedTo);
        this.state.filters.completedFrom = fromVal;
        this.state.filters.completedTo = toVal;

        if (this.elements.applyFiltersBtn) this.elements.applyFiltersBtn.classList.remove('pending');

        // Filtry dat są server-side — wymagają refetchu
        if (refetchDates && dateChanged) {
            this.fetchData().then(() => this.applyFiltersAndRender());
        } else {
            this.applyFiltersAndRender();
        }
    }

    clearAllFilters() {
        this.state.filters.search = '';
        this.state.filters.woodSpecies.clear();
        this.state.filters.technologies.clear();
        this.state.filters.woodClasses.clear();
        this.state.filters.thicknesses.clear();
        this.state.filters.completedFrom = '';
        this.state.filters.completedTo = '';

        if (this.elements.search) this.elements.search.value = '';
        if (this.elements.completedFrom) this.elements.completedFrom.value = '';
        if (this.elements.completedTo) this.elements.completedTo.value = '';
        Object.values(this.elements.multiselects).forEach(ms => {
            if (ms.dropdown) ms.dropdown.querySelectorAll('input[type="checkbox"]').forEach(cb => { cb.checked = false; });
        });
        this.fetchData().then(() => this.applyFiltersAndRender());
    }

    applyDatePreset(preset) {
        const today = new Date();
        const fmt = (d) => d.toISOString().slice(0, 10);
        let from = '';
        let to = '';
        if (preset === 'this-month') {
            from = fmt(new Date(today.getFullYear(), today.getMonth(), 1));
            to = fmt(today);
        } else if (preset === 'prev-month') {
            const first = new Date(today.getFullYear(), today.getMonth() - 1, 1);
            const last = new Date(today.getFullYear(), today.getMonth(), 0);
            from = fmt(first);
            to = fmt(last);
        } else if (preset === 'last-30') {
            const start = new Date(today);
            start.setDate(today.getDate() - 30);
            from = fmt(start);
            to = fmt(today);
        } else if (preset === 'clear') {
            from = '';
            to = '';
        }
        if (this.elements.completedFrom) this.elements.completedFrom.value = from;
        if (this.elements.completedTo) this.elements.completedTo.value = to;
        this.commitFiltersFromDOM(true);
    }

    renderActiveFiltersBadges() {
        const f = this.state.filters;
        const items = [];
        f.woodSpecies.forEach(v => items.push({ key: 'woodSpecies', value: v, label: `Gatunek: ${v}` }));
        f.technologies.forEach(v => items.push({ key: 'technologies', value: v, label: `Technologia: ${v}` }));
        f.woodClasses.forEach(v => items.push({ key: 'woodClasses', value: v, label: `Klasa: ${v}` }));
        f.thicknesses.forEach(v => items.push({ key: 'thicknesses', value: v, label: `Grubość: ${v}` }));
        if (f.completedFrom) items.push({ key: 'completedFrom', value: f.completedFrom, label: `Od: ${f.completedFrom}` });
        if (f.completedTo) items.push({ key: 'completedTo', value: f.completedTo, label: `Do: ${f.completedTo}` });

        if (!this.elements.activeFilters || !this.elements.filterBadges) return;
        if (!items.length) {
            this.elements.activeFilters.style.display = 'none';
            return;
        }
        this.elements.activeFilters.style.display = '';
        this.elements.filterBadges.innerHTML = '';
        items.forEach(it => {
            const tpl = document.getElementById('arch-filter-badge-template');
            const badge = tpl.content.cloneNode(true).firstElementChild;
            badge.querySelector('.il-filter-badge-text').textContent = it.label;
            badge.querySelector('.il-filter-badge-remove').addEventListener('click', () => this.removeFilter(it));
            this.elements.filterBadges.appendChild(badge);
        });
    }

    removeFilter(item) {
        const f = this.state.filters;
        let needRefetch = false;
        if (item.key === 'completedFrom') {
            f.completedFrom = '';
            if (this.elements.completedFrom) this.elements.completedFrom.value = '';
            needRefetch = true;
        } else if (item.key === 'completedTo') {
            f.completedTo = '';
            if (this.elements.completedTo) this.elements.completedTo.value = '';
            needRefetch = true;
        } else if (f[item.key] instanceof Set) {
            f[item.key].delete(item.value);
            // odznacz checkbox w odpowiednim multiselectcie
            const dropdownKey = {
                woodSpecies: 'wood-species',
                technologies: 'technology',
                woodClasses: 'wood-class',
                thicknesses: 'thickness'
            }[item.key];
            if (dropdownKey) {
                const ms = this.elements.multiselects[dropdownKey];
                if (ms && ms.dropdown) {
                    const cb = ms.dropdown.querySelector(`input[type="checkbox"][value="${CSS.escape(item.value)}"]`);
                    if (cb) cb.checked = false;
                }
            }
        }
        if (needRefetch) {
            this.fetchData().then(() => this.applyFiltersAndRender());
        } else {
            this.applyFiltersAndRender();
        }
    }

    // ──────────────────────────────────────────────────────────────────────
    // STATE: LOADING / EMPTY / ERROR
    // ──────────────────────────────────────────────────────────────────────

    showLoading() { if (this.elements.loading) this.elements.loading.style.display = ''; }
    hideLoading() { if (this.elements.loading) this.elements.loading.style.display = 'none'; }
    showEmpty() {
        if (!this.elements.empty) return;
        this.elements.empty.style.display = '';
        const hasFilters = this.hasActiveFilters();
        if (this.elements.emptyReason) {
            this.elements.emptyReason.textContent = hasFilters
                ? 'Brak zamówień pasujących do filtrów'
                : 'Brak zamówień w archiwum';
        }
        if (this.elements.clearFiltersEmptyBtn) {
            this.elements.clearFiltersEmptyBtn.style.display = hasFilters ? '' : 'none';
        }
    }
    hideEmpty() { if (this.elements.empty) this.elements.empty.style.display = 'none'; }
    showError(msg) {
        if (!this.elements.error) return;
        this.elements.error.style.display = '';
        if (this.elements.errorMessage) this.elements.errorMessage.textContent = msg;
    }

    hasActiveFilters() {
        const f = this.state.filters;
        return Boolean(
            f.search
            || f.woodSpecies.size
            || f.technologies.size
            || f.woodClasses.size
            || f.thicknesses.size
            || f.completedFrom
            || f.completedTo
        );
    }

    // ──────────────────────────────────────────────────────────────────────
    // HELPERS
    // ──────────────────────────────────────────────────────────────────────

    getStatusDisplayName(status) { return STATUS_DISPLAY_NAMES[status] || status || ''; }

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
            'spakowane': 'status-completed'
        };
        return map[status] || 'status-completed';
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
            'spakowane': 'badge-completed'
        };
        return map[status] || 'badge-completed';
    }

    formatDatePL(iso) {
        if (!iso) return '—';
        try {
            const d = new Date(iso);
            return d.toLocaleDateString('pl-PL', { day: '2-digit', month: '2-digit', year: 'numeric' });
        } catch (_) {
            return iso;
        }
    }

    escapeHtml(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }
}

window.ArchiveModule = ArchiveModule;
