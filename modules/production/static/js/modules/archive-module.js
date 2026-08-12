/**
 * ArchiveModule — widok zamówień w pełni spakowanych.
 *
 * Niezależny od ProductsModule. Reużywa endpoint /products-tab-content z view=archive
 * oraz część stylów (.il-*) z products-tab.css; własny scope DOM przez prefix `arch-`.
 *
 * Bez: drag&drop, gwiazdki priorytetu, edycji statusu, recalc kolejki.
 * Zamiast: filtr zakresu dat, presety, statystyki archiwum (avg czas realizacji),
 *          kolumna "Zakończono" zamiast "Termin", sortowanie completedAt DESC.
 *
 * WAŻNE: filtrowanie, sortowanie i paginacja są PO STRONIE SERWERA. Ten moduł
 * trzyma w pamięci wyłącznie bieżącą stronę — do archiwum trafia cała historia
 * firmy (tysiące zamówień) i trzymanie jej w JS kosztowało kilka sekund na
 * każde wejście w zakładkę. Każda zmiana filtra lub strony = nowy request.
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
            pagination: {
                page: 1,
                perPage: 25,
                totalOrders: 0,
                totalPages: 1,
                hasPrev: false,
                hasNext: false
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

        this.attachEventListeners();
        this.render();

        this._initialized = true;
        console.log('[ArchiveModule] Loaded page', this.state.pagination.page,
            'of', this.state.pagination.totalPages,
            `(${this.state.pagination.totalOrders} zamówień w archiwum)`);
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
            // paginacja
            pagination: document.getElementById('arch-pagination'),
            paginationSummary: document.getElementById('arch-pagination-summary'),
            paginationPages: document.getElementById('arch-pagination-pages'),
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

    /**
     * Buduje komplet parametrów zapytania z aktualnego stanu filtrów.
     * Wszystkie sześć filtrów idzie na backend — przeglądarka dostaje już
     * tylko gotową stronę wyników.
     */
    buildQueryParams() {
        const f = this.state.filters;
        const params = { view: 'archive', page: this.state.pagination.page };
        if (f.search) params.search = f.search;
        if (f.completedFrom) params.completed_from = f.completedFrom;
        if (f.completedTo) params.completed_to = f.completedTo;
        if (f.woodSpecies.size) params.wood_species = Array.from(f.woodSpecies);
        if (f.technologies.size) params.technology = Array.from(f.technologies);
        if (f.woodClasses.size) params.wood_class = Array.from(f.woodClasses);
        if (f.thicknesses.size) params.thickness = Array.from(f.thicknesses);
        return params;
    }

    async fetchData() {
        if (this.state.isLoading) return;
        this.state.isLoading = true;
        this.showLoading();
        try {
            const resp = await this.shared.apiClient.getProductsTabContent(this.buildQueryParams());
            if (!resp.success) throw new Error(resp.error || 'Błąd pobierania archiwum');
            this.hideError();
            this.consumePayload(resp.initial_data);
        } catch (err) {
            console.error('[ArchiveModule] fetchData failed:', err);
            this.showError(err.message || 'Błąd ładowania archiwum');
        } finally {
            this.state.isLoading = false;
            this.hideLoading();
        }
    }

    /**
     * Pobiera dane i od razu przerysowuje widok. Zmiana filtra albo strony
     * NIE przeładowuje całej zakładki — tylko ten jeden request.
     */
    async reload({ resetPage = false } = {}) {
        if (resetPage) this.state.pagination.page = 1;
        await this.fetchData();
        this.render();
    }

    consumePayload(data) {
        this.state.products = data.products || [];
        this.state.filterOptions = data.filters || this.state.filterOptions;
        this.state.stats = data.stats || null;
        this.state.orders = this.groupProductsByOrder(this.state.products);

        const p = data.pagination || {};
        this.state.pagination = {
            page: p.page || 1,
            perPage: p.per_page || this.state.pagination.perPage,
            totalOrders: p.total_orders || 0,
            totalPages: p.total_pages || 1,
            hasPrev: Boolean(p.has_prev),
            hasNext: Boolean(p.has_next)
        };
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
                    quoteNumber: product.quote_number,
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
            if (product.quote_number && !order.quoteNumber) order.quoteNumber = product.quote_number;

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
    // RENDER
    // ──────────────────────────────────────────────────────────────────────

    render() {
        this.populateMultiselectOptions();
        this.renderActiveFiltersBadges();
        this.renderStats();
        this.renderOrders();
        this.renderPagination();
    }

    /**
     * Statystyki przychodzą policzone przez serwer dla CAŁEGO przefiltrowanego
     * archiwum. Liczenie ich z `this.state.orders` pokazałoby sumy z jednej
     * strony — czyli sumy „ostatnich 25 zamówień", nie te, o które pyta szef.
     */
    renderStats() {
        const a = (this.state.stats && this.state.stats.archive) || {};
        const ordersCount = a.orders_count || 0;
        const productsCount = a.products_count || 0;
        const totalVolume = a.total_volume || 0;
        const totalValue = a.total_value || 0;
        const avgDays = (typeof a.avg_realization_days === 'number') ? a.avg_realization_days : null;

        if (this.elements.statOrders) this.elements.statOrders.textContent = ordersCount;
        if (this.elements.statProducts) this.elements.statProducts.textContent = productsCount;
        if (this.elements.statVolume) this.elements.statVolume.textContent = `${totalVolume.toFixed(4)} m³`;
        if (this.elements.statValue) this.elements.statValue.textContent = `${totalValue.toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} zł`;
        if (this.elements.statAvgDays) {
            this.elements.statAvgDays.textContent = avgDays === null ? '— dni' : `${avgDays} dni`;
        }
    }

    // ──────────────────────────────────────────────────────────────────────
    // RENDER: PAGINACJA
    // ──────────────────────────────────────────────────────────────────────

    renderPagination() {
        const { pagination: el, paginationSummary, paginationPages } = this.elements;
        if (!el || !paginationPages || !paginationSummary) return;

        const p = this.state.pagination;
        if (!p.totalOrders) {
            el.style.display = 'none';
            return;
        }
        el.style.display = '';

        const from = (p.page - 1) * p.perPage + 1;
        const to = Math.min(p.page * p.perPage, p.totalOrders);
        paginationSummary.textContent = `Zamówienia ${from}–${to} z ${p.totalOrders}`;

        paginationPages.textContent = '';
        if (p.totalPages <= 1) return;

        paginationPages.appendChild(this.createPageButton('‹ Poprzednia', p.page - 1, !p.hasPrev));
        this.pageWindow(p.page, p.totalPages).forEach(item => {
            if (item === '…') {
                const gap = document.createElement('span');
                gap.className = 'arch-page-gap';
                gap.textContent = '…';
                paginationPages.appendChild(gap);
                return;
            }
            paginationPages.appendChild(
                this.createPageButton(String(item), item, false, item === p.page));
        });
        paginationPages.appendChild(this.createPageButton('Następna ›', p.page + 1, !p.hasNext));
    }

    /** Okno numerów stron: 1 … n-1 [n] n+1 … ostatnia. */
    pageWindow(current, total) {
        const pages = new Set([1, total, current, current - 1, current + 1]);
        const sorted = Array.from(pages).filter(n => n >= 1 && n <= total).sort((a, b) => a - b);
        const out = [];
        sorted.forEach((n, idx) => {
            if (idx > 0 && n - sorted[idx - 1] > 1) out.push('…');
            out.push(n);
        });
        return out;
    }

    createPageButton(label, targetPage, disabled, active = false) {
        // createElement + textContent zamiast innerHTML — nawet dla własnych
        // etykiet, żeby ten kawałek nie stał się kiedyś furtką na dane z bazy.
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'arch-page-btn' + (active ? ' active' : '');
        btn.textContent = label;
        if (disabled || active || this.state.isLoading) {
            btn.disabled = true;
        } else {
            btn.addEventListener('click', () => this.goToPage(targetPage));
        }
        return btn;
    }

    goToPage(page) {
        const p = this.state.pagination;
        if (page < 1 || page > p.totalPages || page === p.page) return;
        p.page = page;
        this.reload();
        // Powrót na górę listy — inaczej po zmianie strony użytkownik ląduje
        // w środku nowego zestawu kart.
        if (this.elements.root && this.elements.root.scrollIntoView) {
            this.elements.root.scrollIntoView({ block: 'start' });
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

        if (!this.state.orders.length) {
            this.showEmpty();
            return;
        }
        this.hideEmpty();

        const fragment = document.createDocumentFragment();
        this.state.orders.forEach(order => {
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

        // Zamówienie rozwinięte przed przeładowaniem listy ma zostać rozwinięte.
        // Bez tego stan i DOM się rozjeżdżają i pierwsze kliknięcie nic nie robi.
        if (this.state.expandedOrders.has(order.orderKey)) {
            this.expandOrderCard(card, order);
        }

        return card;
    }

    populateOrderHeader(card, order) {
        const header = card.querySelector('.arch-order-header');

        // Status border-left (z definicji 'spakowane' → status-completed)
        header.classList.add(this.getStationClassFromStatus(order.status));

        // Client + IDs
        header.querySelector('.il-order-client').textContent = order.clientName;
        const idsContainer = header.querySelector('.il-order-ids');
        idsContainer.textContent = '';
        // Wszystkie te wartości pochodzą z bazy (m.in. z BaseLinkera, czyli
        // spoza naszej kontroli) — dlatego trafiają przez textContent, nie
        // przez innerHTML. Brak escapowania w tym module był już podatnością XSS.
        const addTag = (value) => {
            if (!value && value !== 0) return;
            const tag = document.createElement('span');
            tag.className = 'il-order-id-tag';
            tag.textContent = String(value);
            idsContainer.appendChild(tag);
        };
        addTag(order.internalOrderNumber);
        if (order.baselinkerOrderId) addTag(`BL-${order.baselinkerOrderId}`);
        addTag(order.clientOrderNumber);
        addTag(order.quoteNumber);

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
        meta.textContent = '';

        const metrics = [];
        if (order.totalVolume) metrics.push(`${order.totalVolume.toFixed(4)} m³`);
        if (order.totalValue) metrics.push(`${order.totalValue.toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} zł`);
        if (metrics.length) {
            const span = document.createElement('span');
            span.className = 'il-card-meta-metrics';
            span.textContent = metrics.join(' · ');
            meta.appendChild(span);
        }

        if (order.completedAt) {
            // formatDatePL przy nieparsowalnej dacie zwraca surową wartość z bazy,
            // więc tekst budujemy przez textContent, nie przez sklejanie HTML-a.
            const span = document.createElement('span');
            span.className = 'il-card-meta-deadline deadline-normal';
            const icon = document.createElement('i');
            icon.className = 'fas fa-calendar-check';
            span.appendChild(icon);
            const days = order.realizationDays !== null ? ` (${order.realizationDays} dni)` : '';
            span.appendChild(document.createTextNode(
                ` Zakończono: ${this.formatDatePL(order.completedAt)}${days}`));
            meta.appendChild(span);
        }
    }

    expandOrderCard(card, order) {
        const header = card.querySelector('.arch-order-header');
        const productsContainer = card.querySelector('.il-order-products');
        this.renderOrderProducts(productsContainer, order);
        productsContainer.classList.remove('collapsed');
        header.querySelector('.il-order-expand').textContent = '▼';
    }

    collapseOrderCard(card) {
        const header = card.querySelector('.arch-order-header');
        const productsContainer = card.querySelector('.il-order-products');
        productsContainer.classList.add('collapsed');
        productsContainer.textContent = '';
        header.querySelector('.il-order-expand').textContent = '▶';
    }

    attachOrderListeners(card, order) {
        const header = card.querySelector('.arch-order-header');

        header.addEventListener('click', (e) => {
            if (e.target.closest('.il-order-actions')) return;
            if (this.state.expandedOrders.has(order.orderKey)) {
                this.state.expandedOrders.delete(order.orderKey);
                this.collapseOrderCard(card);
            } else {
                this.state.expandedOrders.add(order.orderKey);
                this.expandOrderCard(card, order);
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
        container.textContent = '';
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

    /**
     * Listy wartości przychodzą z backendu (jedno DISTINCT po całym archiwum
     * w wybranym zakresie dat) — przy paginacji nie da się ich już zebrać
     * z widocznych zamówień, bo widać tylko jedną stronę.
     */
    populateMultiselectOptions() {
        const opts = this.state.filterOptions;
        const f = this.state.filters;
        this.fillDropdown('wood-species', opts.wood_species, f.woodSpecies);
        this.fillDropdown('technology', opts.technologies, f.technologies);
        this.fillDropdown('wood-class', opts.wood_classes, f.woodClasses);
        this.fillDropdown('thickness', opts.thicknesses, f.thicknesses);
    }

    fillDropdown(filterKey, values, selected) {
        const ms = this.elements.multiselects[filterKey];
        if (!ms || !ms.dropdown) return;
        // Usuń poprzednie opcje (oprócz search-input i "zaznacz wszystkie")
        ms.dropdown.querySelectorAll('.il-multiselect-option').forEach((opt, idx) => {
            if (idx > 0) opt.remove();
        });

        // Zaznaczona wartość, której nie ma już na liście (np. po zawężeniu
        // zakresu dat), i tak musi się pokazać — inaczej filtr zostaje aktywny,
        // a użytkownik nie ma czym go odkliknąć.
        const all = Array.from(new Set([...(values || []), ...(selected || [])]));

        all.forEach(v => {
            const label = document.createElement('label');
            label.className = 'il-multiselect-option';
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = v;
            cb.checked = Boolean(selected && selected.has(v));
            label.appendChild(cb);
            // textContent, nie innerHTML — gatunek/technologia/klasa to dane z bazy
            label.appendChild(document.createTextNode(' ' + v));
            ms.dropdown.appendChild(label);
        });
    }

    attachEventListeners() {
        // Search (debounced) — szukanie jest server-side, więc dłuższy debounce
        // niż przy filtrowaniu w pamięci: 350 ms zamiast 200 ms.
        if (this.elements.search) {
            this.elements.search.addEventListener('input', (e) => {
                clearTimeout(this._searchDebounceTimer);
                const value = e.target.value.trim();
                this._searchDebounceTimer = setTimeout(() => {
                    if (value === this.state.filters.search) return;
                    this.state.filters.search = value;
                    this.reload({ resetPage: true });
                }, 350);
            });
        }

        // Apply / clear
        if (this.elements.applyFiltersBtn) {
            this.elements.applyFiltersBtn.addEventListener('click', () => this.commitFiltersFromDOM());
        }
        if (this.elements.clearAllBtn) {
            this.elements.clearAllBtn.addEventListener('click', () => this.clearAllFilters());
        }
        if (this.elements.clearFiltersEmptyBtn) {
            this.elements.clearFiltersEmptyBtn.addEventListener('click', () => this.clearAllFilters());
        }
        if (this.elements.retryBtn) {
            this.elements.retryBtn.addEventListener('click', () => this.reload());
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

    commitFiltersFromDOM() {
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

        this.state.filters.completedFrom = this.elements.completedFrom ? this.elements.completedFrom.value : '';
        this.state.filters.completedTo = this.elements.completedTo ? this.elements.completedTo.value : '';

        if (this.elements.applyFiltersBtn) this.elements.applyFiltersBtn.classList.remove('pending');

        // Każdy filtr jest server-side — zmiana zawsze oznacza nowy request
        // i powrót na pierwszą stronę (na stronie 12 nowego wyniku może nie być).
        this.reload({ resetPage: true });
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
        this.reload({ resetPage: true });
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
        this.commitFiltersFromDOM();
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
        this.elements.filterBadges.textContent = '';
        items.forEach(it => {
            const tpl = document.getElementById('arch-filter-badge-template');
            const badge = tpl.content.cloneNode(true).firstElementChild;
            // textContent — etykieta zawiera wartość z bazy (gatunek, klasa)
            badge.querySelector('.il-filter-badge-text').textContent = it.label;
            badge.querySelector('.il-filter-badge-remove').addEventListener('click', () => this.removeFilter(it));
            this.elements.filterBadges.appendChild(badge);
        });
    }

    removeFilter(item) {
        const f = this.state.filters;
        if (item.key === 'completedFrom') {
            f.completedFrom = '';
            if (this.elements.completedFrom) this.elements.completedFrom.value = '';
        } else if (item.key === 'completedTo') {
            f.completedTo = '';
            if (this.elements.completedTo) this.elements.completedTo.value = '';
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
        this.reload({ resetPage: true });
    }

    // ──────────────────────────────────────────────────────────────────────
    // STATE: LOADING / EMPTY / ERROR
    // ──────────────────────────────────────────────────────────────────────

    showLoading() {
        if (this.elements.loading) this.elements.loading.style.display = '';
        // Wygaszenie starej listy, żeby było widać, że wynik jeszcze się zmienia
        if (this.elements.ordersList) this.elements.ordersList.classList.add('arch-loading');
    }
    hideLoading() {
        if (this.elements.loading) this.elements.loading.style.display = 'none';
        if (this.elements.ordersList) this.elements.ordersList.classList.remove('arch-loading');
    }
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
    hideError() { if (this.elements.error) this.elements.error.style.display = 'none'; }

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
