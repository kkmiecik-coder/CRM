// modules/reports/static/js/reports.js
/**
 * Główny manager modułu Reports
 * Odpowiedzialny za inicjalizację i koordynację wszystkich komponentów
 */

const MAIN_STATS_CONFIG = [
    // AKTYWNE - wyświetlane na głównym dashboard i w podsumowaniu modala
    { key: 'unique_orders', label: 'Zamówienia', format: 'number' },
    { key: 'value_net', label: 'Sprzedaż netto', format: 'currency' },
    { key: 'klejonka_value_net', label: 'Sprzedaż klejonek netto', format: 'currency' },
    { key: 'total_m3', label: 'TTL m³ klejonki', format: 'volume' },
    { key: 'production_volume', label: 'Ilość m³ w produkcji', format: 'volume' },
    
    // DOSTĘPNE - odkomentuj żeby aktywować
    // { key: 'order_amount_net', label: 'Kwota zamówień netto', format: 'currency' },
    // { key: 'avg_price_per_m3', label: 'Średnia cena m³ netto', format: 'currency' },
    // { key: 'balance_due', label: 'Do zapłaty netto', format: 'currency' },
];

const MODAL_STATS_CONFIG = {
    basic: {
        label: 'Podstawowe',
        icon: '📊',
        stats: [
            { key: 'unique_orders', label: 'Zamówienia', format: 'number' },
            // { key: 'order_amount_net', label: 'Kwota zamówień netto', format: 'currency' },
            { key: 'value_net', label: 'Sprzedaż netto', format: 'currency' },
            { key: 'avg_price_per_m3', label: 'Średnia cena m³ netto', format: 'currency' },
            { key: 'paid_amount_net', label: 'Zapłacono TTL netto', format: 'currency' },
            { key: 'balance_due', label: 'Do zapłaty netto', format: 'currency' }
        ]
    },
    products: {
        label: 'Produkty',
        icon: '🏭',
        stats: [
            { key: 'value_net', label: 'Sprzedaż netto', format: 'currency' },
            { key: 'klejonka_value_net', label: 'Sprzedaż klejonek netto', format: 'currency' },
            { key: 'total_m3', label: 'TTL m³ klejonki', format: 'volume' },
            { key: 'deska_value_net', label: 'Sprzedaż deski netto', format: 'currency' },
            { key: 'deska_total_m3', label: 'TTL m³ deski', format: 'volume' },
            { key: 'drying_total_m3', label: 'TTL m³ suszenia', format: 'volume' },
            { key: 'services_value_net', label: 'Sprzedaż usług netto', format: 'currency' },
            { key: 'suszenie_value_net', label: '↳ Suszenie', format: 'currency', indented: true },
            { key: 'klejenie_value_net', label: '↳ Klejenie', format: 'currency', indented: true }
        ]
    },
    production: {
        label: 'Produkcja',
        icon: '⚙️',
        stats: [
            { key: 'production_volume', label: 'Ilość m³ w produkcji', format: 'volume' },
            { key: 'production_value_net', label: 'Wartość netto w produkcji', format: 'currency' },
            { key: 'ready_pickup_volume', label: 'Wyprodukowane', format: 'volume' },
            { key: 'ready_pickup_value_net', label: 'Wyprodukowana netto', format: 'currency' },
            { key: 'pickup_ready_volume', label: 'Do odbioru', format: 'volume' }
        ]
    },
    finishing: {
        label: 'Wykończenie',
        icon: '🎨',
        stats: [
            { key: 'olejowanie_surface', label: 'Olejowanie m²', format: 'surface' },
            { key: 'lakierowanie_surface', label: 'Lakierowanie m²', format: 'surface' }
        ]
    }
};

class ReportsManager {

    constructor() {
        this.currentData = [];
        this.currentStats = {};
        this.currentComparison = {};
        this.currentFilters = {};
        this.dateFrom = null;
        this.dateTo = null;
        this.isLoading = false;

        // Referencias do elementów DOM
        this.elements = {};
        this.quotesCache = new Map();

        // Dodaj sortowanie tabeli
        this.tableSorting = null;

        console.log('[ReportsManager] Initialized');
    }

    /**
     * Inicjalizacja managera
     */
    init() {
        console.log('[ReportsManager] Starting initialization...');

        this.cacheElements();
        this.setupEventListeners();
        this.setDefaultDates();

        // NOWE: Inicjalizuj sortowanie
        this.initTableSorting();

        this.loadInitialData();

        window.reportsManager = this;

        // Inicjalizacja VoivodeshipsManager
        if (typeof VoivodeshipsManager !== 'undefined') {
            window.voivodeshipsManager = new VoivodeshipsManager();
            window.voivodeshipsManager.init();
        }

        console.log('[ReportsManager] Initialization complete');
    }

    /**
     * Cache elementów DOM - POPRAWKA: Dodano nowe elementy statystyk
     */
    cacheElements() {
        this.elements = {
            dateFrom: document.getElementById('filterDateFrom'),
            dateTo: document.getElementById('filterDateTo'),
            syncBtn: document.getElementById('syncBtn'),
            syncStatusesBtn: document.getElementById('syncStatusesBtn'),
            addManualRowBtn: document.getElementById('addManualRowBtn'),
            exportExcelBtn: document.getElementById('exportExcelBtn'),
            clearFiltersBtn: document.getElementById('clearFiltersBtn'),

            loadingOverlay: document.getElementById('loadingOverlay'),
            syncLoadingOverlay: document.getElementById('syncLoadingOverlay'),
            syncLoadingText: document.getElementById('syncLoadingText'),

            statUniqueOrders: document.getElementById('statUniqueOrders'),
            statTotalM3: document.getElementById('statTotalM3'),
            statOrderAmountNet: document.getElementById('statOrderAmountNet'),
            statValueNet: document.getElementById('statValueNet'),
            statPricePerM3: document.getElementById('statPricePerM3'),
            statDeliveryCostNet: document.getElementById('statDeliveryCostNet'),
            statPaidAmountNet: document.getElementById('statPaidAmountNet'),
            statBalanceDue: document.getElementById('statBalanceDue'),
            statProductionVolume: document.getElementById('statProductionVolume'),
            statProductionValueNet: document.getElementById('statProductionValueNet'),
            statReadyPickupVolume: document.getElementById('statReadyPickupVolume'),
            statReadyPickupValueNet: document.getElementById('statReadyPickupValueNet'),
            statPickupReady: document.getElementById('statPickupReady'),
            statKlejonkaValueNet: document.getElementById('statKlejonkaValueNet'),
            statDeskaValueNet: document.getElementById('statDeskaValueNet'),
            statDeskaTotalM3: document.getElementById('statDeskaTotalM3'),
            statDryingTotalM3: document.getElementById('statDryingTotalM3'),
            statServicesValueNet: document.getElementById('statServicesValueNet'),
            statSuszenieValueNet: document.getElementById('statSuszenieValueNet'),
            statKlejenieValueNet: document.getElementById('statKlejenieValueNet'),
            statOlejowanieSurface: document.getElementById('statOlejowanieSurface'),
            statLakierowanieSurface: document.getElementById('statLakierowanieSurface'),

            statOrdersProducts: document.getElementById('statOrdersProducts'),
            statOlejowanieVolume: document.getElementById('statOlejowanieVolume'),
            statLakierowanieVolume: document.getElementById('statLakierowanieVolume'),

            compUniqueOrders: document.getElementById('compUniqueOrders'),
            compTotalM3: document.getElementById('compTotalM3'),
            compOrderAmountNet: document.getElementById('compOrderAmountNet'),
            compValueNet: document.getElementById('compValueNet'),
            compPricePerM3: document.getElementById('compPricePerM3'),
            compDeliveryCostNet: document.getElementById('compDeliveryCostNet'),
            compPaidAmountNet: document.getElementById('compPaidAmountNet'),
            compBalanceDue: document.getElementById('compBalanceDue'),
            compProductionVolume: document.getElementById('compProductionVolume'),
            compProductionValueNet: document.getElementById('compProductionValueNet'),
            compReadyPickupVolume: document.getElementById('compReadyPickupVolume'),
            compReadyPickupValueNet: document.getElementById('compReadyPickupValueNet'),
            compPickupReady: document.getElementById('compPickupReady'),
            compKlejonkaValueNet: document.getElementById('compKlejonkaValueNet'),
            compDeskaValueNet: document.getElementById('compDeskaValueNet'),
            compDeskaTotalM3: document.getElementById('compDeskaTotalM3'),
            compDryingTotalM3: document.getElementById('compDryingTotalM3'),
            compServicesValueNet: document.getElementById('compServicesValueNet'),
            compSuszenieValueNet: document.getElementById('compSuszenieValueNet'),
            compKlejenieValueNet: document.getElementById('compKlejenieValueNet'),
            compOlejowanieSurface: document.getElementById('compOlejowanieSurface'),
            compLakierowanieSurface: document.getElementById('compLakierowanieSurface'),

            compOrdersProducts: document.getElementById('compOrdersProducts'),

            reportsTable: document.getElementById('reportsTable'),
            reportsTableBody: document.getElementById('reportsTableBody'),

            activeFilters: document.getElementById('activeFilters'),
            activeFiltersList: document.getElementById('activeFiltersList'),

            // DODAJ w this.elements obiekt:
            mainStatsContainer: document.getElementById('mainStatsContainer')
        };

        console.log('[ReportsManager] Elements cached');
    }

    
    /**
     * Ustawienie event listenerów - POPRAWKA: Poprawiono obsługę dat
     */
    setupEventListeners() {
        // POPRAWKA: Zmiana dat - używamy filterDateFrom/To zamiast dateFrom/To
        if (this.elements.dateFrom) {
            this.elements.dateFrom.addEventListener('change', () => {
                this.dateFrom = this.elements.dateFrom.value;
                this.loadData();
            });
        }

        if (this.elements.dateTo) {
            this.elements.dateTo.addEventListener('change', () => {
                this.dateTo = this.elements.dateTo.value;
                this.loadData();
            });
        }

        // Synchronizacja z Baselinker
        if (this.elements.syncBtn) {
            this.elements.syncBtn.addEventListener('click', () => {
                this.handleSyncClick();
            });
        }

        // Synchronizacja statusów
        if (this.elements.syncStatusesBtn) {
            this.elements.syncStatusesBtn.addEventListener('click', () => {
                this.handleSyncStatusesClick();
            });
        }

        // Dodawanie ręcznego wiersza
        if (this.elements.addManualRowBtn) {
            this.elements.addManualRowBtn.addEventListener('click', () => {
                this.handleAddManualRow();
            });
        }

        // Eksport do Excel
        if (this.elements.exportExcelBtn) {
            this.elements.exportExcelBtn.addEventListener('click', () => {
                this.handleExportExcel();
            });
        }

        // Czyszczenie filtrów
        if (this.elements.clearFiltersBtn) {
            this.elements.clearFiltersBtn.addEventListener('click', () => {
                this.clearAllFilters();
            });
        }

        // Delegacja eventów dla tabeli (edit, links)
        if (this.elements.reportsTable) {
            this.elements.reportsTable.addEventListener('click', (e) => {
                this.handleTableClick(e);
            });
        }

        // Excel export - normalny tryb
        const exportExcelOption = document.getElementById('exportExcelOption');
        if (exportExcelOption) {
            exportExcelOption.addEventListener('click', (e) => {
                e.preventDefault();
                this.handleExportExcel();
            });
        }

        // Excel export - fullscreen
        const fullscreenExportExcelOption = document.getElementById('fullscreenExportExcelOption');
        if (fullscreenExportExcelOption) {
            fullscreenExportExcelOption.addEventListener('click', (e) => {
                e.preventDefault();
                this.handleExportExcel();
            });
        }

        // Routimo export - normalny tryb
        const exportRoutimoOption = document.getElementById('exportRoutimoOption');
        if (exportRoutimoOption) {
            exportRoutimoOption.addEventListener('click', (e) => {
                e.preventDefault();
                this.handleExportRoutimo();
            });
        }

        // Routimo export - fullscreen
        const fullscreenExportRoutimoOption = document.getElementById('fullscreenExportRoutimoOption');
        if (fullscreenExportRoutimoOption) {
            fullscreenExportRoutimoOption.addEventListener('click', (e) => {
                e.preventDefault();
                this.handleExportRoutimo();
            });
        }

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            this.handleKeyboardShortcuts(e);
            if (e.key === 'Escape') {
                this.closeStatsModal();
            }
        });

        // NOWE: Obsługa resize z fullscreen
        window.addEventListener('resize', () => {
            this.handleFullscreenResize();
        });

        console.log('[ReportsManager] Event listeners setup complete');
    }

    // NOWA METODA: Inicjalizacja sortowania
    initTableSorting() {
        if (typeof TableSorting !== 'undefined') {
            this.tableSorting = new TableSorting();
            this.tableSorting.init();
            console.log('[ReportsManager] Sortowanie tabeli zainicjowane');
        } else {
            console.warn('[ReportsManager] TableSorting nie jest dostępny');
        }
    }

    /**
     * Ustawienie domyślnych dat (początek bieżącego miesiąca)
     */
    setDefaultDates() {
        // Sprawdź czy są domyślne daty z serwera
        const serverDateFrom = window.reportsConfig?.default_date_from;
        const serverDateTo = window.reportsConfig?.default_date_to;

        if (serverDateFrom && serverDateTo) {
            this.dateFrom = serverDateFrom;
            this.dateTo = serverDateTo;
        } else {
            // Fallback - ostatni miesiąc
            const today = new Date();
            const lastMonth = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());

            this.dateFrom = lastMonth.toISOString().split('T')[0];
            this.dateTo = today.toISOString().split('T')[0];
        }

        // POPRAWKA: Ustaw wartości w prawidłowych elementach
        if (this.elements.dateFrom) {
            this.elements.dateFrom.value = this.dateFrom;
        }
        if (this.elements.dateTo) {
            this.elements.dateTo.value = this.dateTo;
        }

        console.log('[ReportsManager] Default dates set:', this.dateFrom, 'to', this.dateTo);
    }

    /**
     * Resetowanie do domyślnych dat (publiczna metoda)
     */
    resetToDefaultDates() {
        this.setDefaultDates();
        this.loadData();
    }

    /**
     * Ładowanie początkowych danych - POPRAWKA: Ulepszona obsługa błędów
     */
    async loadInitialData() {
        console.log('[ReportsManager] Loading initial data...');

        try {
            // Najpierw wyczyść statystyki i porównania
            this.clearStatistics();
            this.clearComparisons();

            // Załaduj dane z API
            await this.loadData();

            // Tylko jeśli nie mamy danych z API, użyj window.reportsConfig
            if (this.currentData.length === 0 && window.reportsConfig) {
                if (window.reportsConfig.stats && Object.keys(window.reportsConfig.stats).length > 0) {
                    this.updateStatistics(window.reportsConfig.stats);
                }
                if (window.reportsConfig.comparison && Object.keys(window.reportsConfig.comparison).length > 0) {
                    this.updateComparisons(window.reportsConfig.comparison);
                }
            }

        } catch (error) {
            console.error('[ReportsManager] Error loading initial data:', error);
            // W przypadku błędu wyczyść wszystko
            this.clearStatistics();
            this.clearComparisons();
        }
    }

    /**
     * Czyszczenie statystyk
     */
    clearStatistics() {
        console.log('[ReportsManager] Clearing statistics...');

        const emptyStats = {
            unique_orders: 0,
            total_m3: 0,
            order_amount_net: 0,
            value_net: 0,
            avg_price_per_m3: 0,
            delivery_cost_net: 0,
            paid_amount_net: 0,
            balance_due: 0,
            production_volume: 0,
            production_value_net: 0,
            ready_pickup_volume: 0,
            drying_total_m3: 0,
            services_value_net: 0,
            suszenie_value_net: 0,
            klejenie_value_net: 0,
            ready_pickup_value_net: 0,
            olejowanie_surface: 0,
            lakierowanie_surface: 0
        };

        this.updateStatistics(emptyStats);
    }

    /**
     * Czyszczenie porównań
     */
    clearComparisons() {
        console.log('[ReportsManager] Clearing comparisons...');
        const elementMap = {
            'total_m3': 'compTotalM3',
            'unique_orders': 'compUniqueOrders',                    // POPRAWKA: zmienione z compOrdersProducts
            'order_amount_net': 'compOrderAmountNet',
            'value_net': 'compValueNet',                            // DODANE: dla sprzedaży netto
            'avg_price_per_m3': 'compPricePerM3',
            'delivery_cost_net': 'compDeliveryCostNet',
            'paid_amount_net': 'compPaidAmountNet',
            'balance_due': 'compBalanceDue',
            'production_volume': 'compProductionVolume',
            'production_value_net': 'compProductionValueNet',
            'ready_pickup_volume': 'compReadyPickupVolume',
            'ready_pickup_value_net': 'compReadyPickupValueNet',
            'klejonka_value_net': 'compKlejonkaValueNet',           // DODANE: klejonka
            'deska_value_net': 'compDeskaValueNet',                 // DODANE: deska wartość
            'drying_total_m3': 'compDryingTotalM3',               // POPRAWKA 2: suszenie m³
            'deska_total_m3': 'compDeskaTotalM3',                   // DODANE: deska m³
            'services_value_net': 'compServicesValueNet',           // DODANE: usługi
            'pickup_ready_volume': 'compPickupReady'                // DODANE: do odbioru
        };

        // Wyczyść porównania - ustaw puste teksty
        Object.keys(elementMap).forEach(field => {
            const elementId = elementMap[field];
            const element = this.elements[elementId];
            if (element) {
                element.textContent = '';
                element.className = 'stats-comparison';             // POPRAWKA: zmienione z stat-comparison
                element.style.display = 'none';                     // DODANE: ukryj element
            }
        });

        const surfaceElements = ['compOlejowanieSurface', 'compLakierowanieSurface'];
        surfaceElements.forEach(elementId => {
            const element = document.getElementById(elementId);
            if (element) {
                element.textContent = '';
                element.className = 'stats-comparison';             // POPRAWKA: zmienione z stat-comparison
                element.style.display = 'none';                     // DODANE: ukryj element
            }
        });
    }

    /**
     * Ładowanie danych z API
     */
    async loadData() {
        if (this.isLoading) {
            console.log('[ReportsManager] Already loading, skipping...');
            return;
        }

        this.showLoading();
        this.isLoading = true;

        try {
            console.log('[ReportsManager] Loading data...', {
                dateFrom: this.dateFrom,
                dateTo: this.dateTo,
                filters: this.currentFilters
            });

            // Przygotuj parametry
            const params = new URLSearchParams();

            // Dodaj daty
            if (this.dateFrom) {
                params.append('date_from', this.dateFrom);
            }
            if (this.dateTo) {
                params.append('date_to', this.dateTo);
            }

            // Dodaj filtry kolumn (obsługa multiple values)
            for (const [key, values] of Object.entries(this.currentFilters)) {
                if (values && Array.isArray(values) && values.length > 0) {
                    values.forEach(value => {
                        if (value && value.trim()) {
                            params.append(`filter_${key}`, value.trim());
                        }
                    });
                }
            }

            // Wykonaj zapytanie
            const response = await fetch(`/reports/api/data?${params}`);

            // POPRAWKA: Sprawdź czy odpowiedź jest OK
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();

            if (!result.success) {
                throw new Error(result.error || 'Błąd ładowania danych');
            }

            // Aktualizuj dane
            this.currentData = result.data || [];
            this.currentStats = result.stats || {};
            this.currentComparison = result.comparison || {};

            // DODAJ TĘ LINIĘ: Resetuj sortowanie przy nowych danych
            if (this.tableSorting) {
                this.tableSorting.resetSort();
            }

            // Aktualizuj interfejs
            this.updateTable();
            this.updateStatistics(this.currentStats);
            this.updateComparisons(this.currentComparison);
            this.updateActiveFilters();

            console.log('[ReportsManager] Data loaded successfully', {
                recordsCount: this.currentData.length,
                stats: this.currentStats,
                comparison: this.currentComparison
            });

        } catch (error) {
            console.error('[ReportsManager] Error loading data:', error);
            this.showError('Błąd ładowania danych: ' + error.message);
        } finally {
            this.hideLoading();
            this.isLoading = false;
        }
    }

    // NOWA METODA: Reset sortowania (publiczna)
    resetTableSort() {
        if (this.tableSorting) {
            this.tableSorting.resetSort();
        }
    }

    /**
    * Aktualizacja tabeli
    */
    updateTable() {
        if (!this.elements.reportsTableBody) {
            console.error('[ReportsManager] Table body element not found');
            return;
        }

        // DEBUG: Sprawdź dane przed grupowaniem
        const manualRecords = this.currentData.filter(r => r.is_manual);
        this.currentData.slice(0, 10).forEach((record, i) => {
        });

        if (this.currentData.length === 0) {
            this.elements.reportsTableBody.innerHTML = `
            <tr>
                <td colspan="41" class="text-center text-muted" style="padding: 2rem;">
                    <i class="fas fa-inbox fa-2x mb-2"></i><br>
                    Brak danych do wyświetlenia
                </td>
            </tr>
        `;
            return;
        }

        // Grupuj dane - NOWA STRUKTURA
        const { grouped, ordersOrder } = this.groupDataByOrder(this.currentData);
        ordersOrder.slice(0, 10).forEach((key, i) => {
            const orders = grouped.get(key);
            const firstOrder = orders[0];
        });

        // POPRAWKA: Iteruj przez ordersOrder zamiast Object.entries
        let html = '';
        ordersOrder.forEach(key => {
            const orders = grouped.get(key);
            html += this.renderOrderRows(orders);
        });

        this.elements.reportsTableBody.innerHTML = html;

        // Dodaj hover effect dla grupowanych zamówień
        this.setupOrderHoverEffects();

        // NOWE: Odśwież layout w fullscreen
        if (this.isInFullscreenMode()) {
            setTimeout(() => {
                this.refreshTableLayout();
            }, 100);
        }

        // DODANE: Asynchronicznie sprawdź wyceny dla zamówień
        setTimeout(() => {
            if (this.checkQuotesForRenderedOrders) {
                this.checkQuotesForRenderedOrders();
            }
        }, 100);

        console.log('[ReportsManager] Table updated with corrected grouping order');
    }

    /**
     * Grupowanie danych według zamówienia
     */
    groupDataByOrder(data) {
        const grouped = new Map();
        const ordersOrder = [];

        data.forEach(record => {
            // POPRAWKA: Używaj ZAWSZE prefiksów tekstowych, żeby uniknąć sortowania numerycznego
            const key = record.baselinker_order_id
                ? `bl_${record.baselinker_order_id}`
                : `manual_${record.id}`;

            if (!grouped.has(key)) {
                grouped.set(key, []);
                ordersOrder.push(key); // Zapisz kolejność pierwszego wystąpienia
            }

            grouped.get(key).push(record);
        });

        // WAŻNE: Użyj Map.entries() zamiast konwersji na object
        return { grouped, ordersOrder };
    }

    /**
     * Renderowanie wierszy zamówienia z merge cells
     */
    renderOrderRows(orders) {
        let html = '';
        const orderCount = orders.length;
        const baselinkerOrderId = orders[0].baselinker_order_id;

        // NOWA LOGIKA: Oblicz łączną objętość TTL M3 dla całego zamówienia
        const totalOrderM3 = orders.reduce((sum, order) => {
            return sum + (parseFloat(order.total_volume) || 0);
        }, 0);

        orders.forEach((order, index) => {
            const isFirst = index === 0;
            const isLast = index === orderCount - 1;

            html += `
        <tr data-record-id="${order.id}" 
            data-baselinker-id="${baselinkerOrderId || `manual_${order.id}`}"
            data-order-group="${baselinkerOrderId || `manual_${order.id}`}"
            ${order.is_manual ? 'data-manual="true"' : ''}
            ${isFirst ? 'class="order-group-start"' : ''}
            ${isLast ? 'class="order-group-end"' : ''}>
            ${this.renderMergedCell(order.date_created, orderCount, isFirst, 'cell-date')}
            ${this.renderMergedCell(this.formatNumber(totalOrderM3, 4), orderCount, isFirst, 'cell-number')}
            ${this.renderMergedCell(this.formatCurrency(order.order_amount_net), orderCount, isFirst, 'cell-currency')}
            ${this.renderMergedCell(order.baselinker_order_id || '', orderCount, isFirst, 'cell-number')}
            ${this.renderMergedCell(order.internal_order_number || '', orderCount, isFirst, 'cell-text')}
            ${this.renderMergedCell(order.customer_name || '', orderCount, isFirst, 'cell-text')}
            ${this.renderMergedCell(order.delivery_address || '', orderCount, isFirst, 'cell-text')}
            ${this.renderMergedCell(order.delivery_city || '', orderCount, isFirst, 'cell-text')}
            ${this.renderMergedCell(order.delivery_postcode || '', orderCount, isFirst, 'cell-text')}
            ${this.renderMergedCell(order.delivery_state || '', orderCount, isFirst, 'cell-text')}
            ${this.renderMergedCell(order.phone || '', orderCount, isFirst, 'cell-text')}
            ${this.renderMergedCell(order.caretaker || '', orderCount, isFirst, 'cell-text')}
            ${this.renderMergedCell(order.delivery_method || '', orderCount, isFirst, 'cell-text')}
            ${this.renderMergedCell(order.order_source || '', orderCount, isFirst, 'cell-text')}
            <td class="cell-text">${order.group_type || ''}</td>
            <td class="cell-text">${order.product_type || ''}</td>
            <td class="cell-text">${order.finish_state || ''}</td>
            <td class="cell-text">${order.wood_species || ''}</td>
            <td class="cell-text">${order.technology || ''}</td>
            <td class="cell-text">${order.wood_class || ''}</td>
            <td class="cell-number">${this.formatNumber(order.length_cm, 2)}</td>
            <td class="cell-number">${this.formatNumber(order.width_cm, 2)}</td>
            <td class="cell-number">${this.formatNumber(order.thickness_cm, 2)}</td>
            <td class="cell-number">${order.quantity || 0}</td>
            <td class="cell-currency">${this.formatCurrency(order.price_gross)}</td>
            <td class="cell-currency">${this.formatCurrency(order.price_net)}</td>
            <td class="cell-currency">${this.formatCurrency(order.value_gross)}</td>
            <td class="cell-currency">${this.formatCurrency(order.value_net)}</td>
            <td class="cell-number">${this.formatNumber(order.volume_per_piece, 4)}</td>
            <td class="cell-number">${this.formatNumber(order.total_volume, 4)}</td>
            <td class="cell-currency">${this.formatCurrency(order.price_per_m3)}</td>
            ${this.renderMergedCell(this.formatCurrency(order.avg_order_price_per_m3), orderCount, isFirst, 'cell-currency')}
            <td class="cell-date">${order.realization_date || ''}</td>
            <td class="cell-status ${this.getStatusClass(order.current_status)}">${order.current_status || ''}</td>
            ${this.renderMergedCell(this.formatCurrency(order.delivery_cost), orderCount, isFirst, 'cell-currency')}
            ${this.renderMergedCell(this.formatCurrency(order.delivery_cost / 1.23), orderCount, isFirst, 'cell-currency')}
            ${this.renderMergedCell(order.payment_method || '', orderCount, isFirst, 'cell-text')}
            ${this.renderMergedCell(this.formatCurrency(order.paid_amount_net), orderCount, isFirst, 'cell-currency')}
            ${this.renderMergedCell(this.formatCurrencyWithSign(order.balance_due), orderCount, isFirst, 'cell-currency')}
            <td class="cell-number">${this.formatNumber(order.production_volume, 4)}</td>
            <td class="cell-currency">${this.formatCurrency(order.production_value_net)}</td>
            <td class="cell-number">${this.formatNumber(order.ready_pickup_volume, 4)}</td>
            <td class="cell-currency">${this.formatCurrency(order.ready_pickup_value_net)}</td>
            <td class="cell-number">${order.current_status && order.current_status.toLowerCase() === 'czeka na odbiór osobisty' ? this.formatNumber(order.total_volume, 4) : '0.00'}</td>
            ${this.renderMergedCell(this.renderActionButtons(order), orderCount, isFirst, 'cell-actions')}
        </tr>
    `;
        });

        return html;
    }

    /**
     * Renderowanie merged cell
     */
    renderMergedCell(content, rowspan, isFirst, cssClass = '') {
        if (isFirst && rowspan > 1) {
            const mergedClass = `merged-cell merged-cell-first ${cssClass}`;
            return `<td rowspan="${rowspan}" class="${mergedClass}">${content}</td>`;
        } else if (isFirst) {
            return `<td class="${cssClass}">${content}</td>`;
        } else {
            return ''; // Komórka nie renderowana (merged)
        }
    }

    /**
     * Renderowanie przycisków akcji
     */
    renderActionButtons(order) {
        const buttons = [];

        // ===== PRZYCISK BASELINKER - NOWA LOGIKA =====

        // Sprawdź czy ma numer zamówienia Baselinker (z API lub wpisany ręcznie)
        const hasBaselinkerNumber = isValidBaselinkerOrderNumber(order.baselinker_order_id);

        if (hasBaselinkerNumber) {
            const baselinkerUrl = `https://panel.baselinker.com/orders.php#order:${order.baselinker_order_id}`;

            // Określ źródło numeru dla celów debugowania
            const source = order.is_manual ? 'ręczny wpis' : 'z Baselinker API';

            buttons.push(`
            <a href="${baselinkerUrl}" 
               target="_blank" 
               class="action-btn action-btn-baselinker"
               title="Otwórz zamówienie #${order.baselinker_order_id} w Baselinker (${source})">
                <i class="fas fa-external-link-alt"></i>
                Baselinker
            </a>
        `);

            // Debug log dla zamówień ręcznych z numerem Baselinker
            if (order.is_manual) {
                console.log(`[renderActionButtons] Dodano przycisk Baselinker dla ręcznego zamówienia:`, {
                    recordId: order.id,
                    baselinkerOrderId: order.baselinker_order_id,
                    customerName: order.customer_name
                });
            }
        }

        // ===== PRZYCISK WYCENA - POZOSTAJE BEZ ZMIAN =====

        if (order.baselinker_order_id) {
            // Sprawdź cache czy mamy info o wycenie
            const cachedQuote = this.quotesCache.get(order.baselinker_order_id);

            if (cachedQuote?.hasQuote) {
                // Wycena istnieje - aktywny przycisk z przekierowaniem do modala
                buttons.push(`
                <button class="action-btn action-btn-quote" 
                        onclick="window.reportsManager.redirectToQuoteByOrderId('${order.baselinker_order_id}')"
                        title="Przejdź do wyceny ${cachedQuote.quoteNumber || ''}">
                    <i class="fas fa-file-invoice"></i>
                    Wycena
                </button>
            `);
            } else if (cachedQuote?.hasQuote === false) {
                // Sprawdzono i nie ma wyceny
                buttons.push(`
                <button disabled class="action-btn action-btn-quote" title="Brak wyceny w systemie">
                    <i class="fas fa-file-invoice"></i>
                    Wycena
                </button>
            `);
            } else {
                // Nie sprawdzano jeszcze - przycisk w stanie loading
                buttons.push(`
                <button class="action-btn action-btn-quote action-btn-checking" 
                        data-order-id="${order.baselinker_order_id}"
                        title="Sprawdzanie dostępności wyceny...">
                    <i class="fas fa-spinner fa-spin"></i>
                    Sprawdzam...
                </button>
            `);
            }
        }

        // ===== PRZYCISK EDYCJI - POZOSTAJE BEZ ZMIAN =====

        buttons.push(`
        <button class="action-btn action-btn-edit" data-action="edit" data-record-id="${order.id}" 
                title="${order.is_manual ? 'Edytuj ręczny rekord' : 'Edytuj rekord z Baselinker'}">
            <i class="fas fa-edit"></i>
            Edytuj
        </button>
    `);

        // ===== PRZYCISK USUWANIA - TYLKO DLA RĘCZNYCH =====

        if (order.is_manual) {
            buttons.push(`
            <button class="action-btn action-btn-delete" data-action="delete" data-record-id="${order.id}" 
                    title="Usuń ręczny rekord">
                <i class="fas fa-trash"></i>
                Usuń
            </button>
        `);
        }

        return `
        <div class="action-buttons">
            ${buttons.join('')}
        </div>
    `;
    }

    /**
    * Obsługa usuwania rekordu z potwierdzeniem
    */
    handleDeleteManualRow(recordId) {
        console.log('[ReportsManager] Delete record:', recordId, 'type:', typeof recordId);

        try {
            // Konwertuj recordId na liczbę jeśli to string
            const numericRecordId = typeof recordId === 'string' ?
                parseInt(recordId, 10) : recordId;

            if (isNaN(numericRecordId)) {
                console.error('[ReportsManager] Invalid recordId:', recordId);
                this.showError('Nieprawidłowy ID rekordu');
                return;
            }

            // Znajdź rekord w aktualnych danych
            const record = this.currentData.find(r => {
                return r.id === numericRecordId || r.id === recordId ||
                    String(r.id) === String(recordId);
            });

            if (!record) {
                console.error('[ReportsManager] Record not found:', numericRecordId);
                this.showError('Nie znaleziono rekordu do usunięcia');
                return;
            }

            // Sprawdź czy to zamówienie z Baselinker ma wiele produktów
            let relatedRecords = [];
            if (record.baselinker_order_id) {
                relatedRecords = this.currentData.filter(r =>
                    r.baselinker_order_id === record.baselinker_order_id
                );
            }

            // Przygotuj komunikat potwierdzenia
            let confirmMessage;
            if (relatedRecords.length > 1) {
                confirmMessage = `Czy na pewno chcesz usunąć całe zamówienie "${record.customer_name}" z ${relatedRecords.length} produktami?\n\nTa operacja jest nieodwracalna i zostanie usunięte na zawsze.`;
            } else {
                confirmMessage = `Czy na pewno chcesz usunąć rekord dla klienta "${record.customer_name}"?\n\nTa operacja jest nieodwracalna i rekord zostanie usunięty na zawsze.`;
            }

            // Pokaż dialog potwierdzenia
            this.showDeleteConfirmation(confirmMessage, () => {
                // Wywołaj usuwanie po potwierdzeniu
                this.executeDelete(numericRecordId, relatedRecords);
            });

        } catch (error) {
            console.error('[ReportsManager] Error in handleDeleteManualRow:', error);
            this.showError('Błąd podczas przygotowania usuwania: ' + error.message);
        }
    }

    /**
     * Pokazanie modala potwierdzenia usunięcia
     */
    showDeleteConfirmation(message, onConfirm) {
        // Utwórz modal potwierdzenia jeśli nie istnieje
        let modal = document.getElementById('deleteConfirmationModal');

        if (!modal) {
            modal = this.createDeleteConfirmationModal();
        }

        // Ustaw komunikat
        const messageElement = modal.querySelector('.delete-confirmation-message');
        if (messageElement) {
            messageElement.textContent = message;
        }

        // Ustaw event listenery
        const confirmBtn = modal.querySelector('.delete-confirm-btn');
        const cancelBtn = modal.querySelector('.delete-cancel-btn');
        const closeBtn = modal.querySelector('.delete-modal-close');

        // Usuń stare event listenery (jeśli istnieją)
        const newConfirmBtn = confirmBtn.cloneNode(true);
        const newCancelBtn = cancelBtn.cloneNode(true);
        const newCloseBtn = closeBtn.cloneNode(true);

        confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
        cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);
        closeBtn.parentNode.replaceChild(newCloseBtn, closeBtn);

        // Dodaj nowe event listenery
        newConfirmBtn.addEventListener('click', () => {
            this.hideDeleteConfirmation();
            onConfirm();
        });

        newCancelBtn.addEventListener('click', () => {
            this.hideDeleteConfirmation();
        });

        newCloseBtn.addEventListener('click', () => {
            this.hideDeleteConfirmation();
        });

        // Pokaż modal
        modal.style.display = 'block';
        modal.classList.add('show');

        // Zablokuj scroll na body
        document.body.style.overflow = 'hidden';

        // Focus na przycisk anuluj (bezpieczniejszy domyślny wybór)
        setTimeout(() => {
            newCancelBtn.focus();
        }, 100);
    }

    /**
     * Ukrycie modala potwierdzenia
     */
    hideDeleteConfirmation() {
        const modal = document.getElementById('deleteConfirmationModal');
        if (modal) {
            modal.style.display = 'none';
            modal.classList.remove('show');
        }

        // Przywróć scroll
        document.body.style.overflow = '';
    }

    /**
     * Utworzenie modala potwierdzenia usunięcia
     */
    createDeleteConfirmationModal() {
        const modal = document.createElement('div');
        modal.id = 'deleteConfirmationModal';
        modal.className = 'modal fade';
        modal.setAttribute('tabindex', '-1');
        modal.setAttribute('role', 'dialog');

        modal.innerHTML = `
        <div class="modal-dialog modal-dialog-centered" role="document">
            <div class="modal-content">
                <div class="modal-header bg-danger text-white">
                    <h5 class="modal-title">
                        <i class="fas fa-exclamation-triangle me-2"></i>
                        Potwierdzenie usunięcia
                    </h5>
                    <button type="button" class="close delete-modal-close" aria-label="Zamknij">
                        <span aria-hidden="true" class="text-white">&times;</span>
                    </button>
                </div>
                <div class="modal-body">
                    <div class="text-center">
                        <i class="fas fa-trash-alt fa-3x text-danger mb-3"></i>
                        <p class="delete-confirmation-message fw-bold fs-5"></p>
                        <div class="alert alert-warning mt-3">
                            <i class="fas fa-info-circle me-2"></i>
                            <strong>Uwaga:</strong> Ta operacja jest nieodwracalna!
                        </div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary delete-cancel-btn">
                        <i class="fas fa-times me-2"></i>Anuluj
                    </button>
                    <button type="button" class="btn btn-danger delete-confirm-btn">
                        <i class="fas fa-trash me-2"></i>Usuń na zawsze
                    </button>
                </div>
            </div>
        </div>
    `;

        document.body.appendChild(modal);
        return modal;
    }

    /**
     * Wykonanie usuwania rekordu
     */
    async executeDelete(recordId, relatedRecords = []) {
        console.log('[ReportsManager] Executing delete for record:', recordId);

        try {
            // Pokaż loading
            this.setDeleteLoadingState(true);

            // Wyślij zapytanie do API
            const response = await fetch('/reports/api/delete-manual-row', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    record_id: recordId,
                    delete_all_products: relatedRecords.length > 1
                })
            });

            console.log('[ReportsManager] Delete response status:', response.status);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('[ReportsManager] Delete response data:', result);

            if (result.success) {
                console.log('[ReportsManager] Delete successful');

                // Odśwież dane
                this.refreshData();

                // Pokaż komunikat sukcesu
                const deletedCount = result.deleted_count || 1;
                const successMessage = deletedCount > 1 ?
                    `Usunięto zamówienie z ${deletedCount} produktami` :
                    'Rekord został usunięty';

                this.showMessage(successMessage, 'success');

            } else {
                throw new Error(result.error || 'Błąd usuwania rekordu');
            }

        } catch (error) {
            console.error('[ReportsManager] Delete error:', error);
            this.showError('Błąd usuwania: ' + error.message);
        } finally {
            this.setDeleteLoadingState(false);
        }
    }

    /**
     * Ustawienie stanu loading dla operacji usuwania
     */
    setDeleteLoadingState(loading) {
        const modal = document.getElementById('deleteConfirmationModal');
        if (!modal) return;

        const confirmBtn = modal.querySelector('.delete-confirm-btn');
        const cancelBtn = modal.querySelector('.delete-cancel-btn');

        if (confirmBtn) {
            confirmBtn.disabled = loading;
            confirmBtn.innerHTML = loading ?
                '<i class="fas fa-spinner fa-spin me-2"></i>Usuwanie...' :
                '<i class="fas fa-trash me-2"></i>Usuń na zawsze';
        }

        if (cancelBtn) {
            cancelBtn.disabled = loading;
        }
    }

    /**
     * Pokazywanie komunikatów użytkownikowi
     */
    showMessage(message, type = 'info') {
        console.log(`[ReportsManager] ${type.toUpperCase()}:`, message);

        // Utwórz lub znajdź kontener na komunikaty
        let messageContainer = document.getElementById('reports-message-container');

        if (!messageContainer) {
            messageContainer = this.createMessageContainer();
        }

        // Utwórz element komunikatu
        const messageElement = document.createElement('div');
        messageElement.className = `alert alert-${this.getBootstrapClass(type)} alert-dismissible fade show message-item`;
        messageElement.setAttribute('role', 'alert');

        messageElement.innerHTML = `
        <i class="fas ${this.getMessageIcon(type)} me-2"></i>
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Zamknij"></button>
    `;

        // Dodaj komunikat do kontenera
        messageContainer.appendChild(messageElement);

        // Automatycznie usuń komunikat po 5 sekundach (tylko success i info)
        if (type === 'success' || type === 'info') {
            setTimeout(() => {
                if (messageElement.parentNode) {
                    messageElement.classList.remove('show');
                    setTimeout(() => {
                        if (messageElement.parentNode) {
                            messageElement.remove();
                        }
                    }, 150); // Czas na animację fade
                }
            }, 5000);
        }

        // Przewiń do komunikatu
        messageElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    /**
     * Pokazywanie komunikatu błędu (alias dla showMessage)
     */
    showError(message) {
        this.showMessage(message, 'error');
    }

    /**
     * Tworzenie kontenera na komunikaty
     */
    createMessageContainer() {
        const container = document.createElement('div');
        container.id = 'reports-message-container';
        container.className = 'message-container position-fixed';
        container.style.cssText = `
        top: 80px;
        right: 20px;
        z-index: 1055;
        max-width: 400px;
    `;

        document.body.appendChild(container);
        return container;
    }

    /**
     * Mapowanie typów komunikatów na klasy Bootstrap
     */
    getBootstrapClass(type) {
        const classMap = {
            'success': 'success',
            'error': 'danger',
            'warning': 'warning',
            'info': 'info'
        };
        return classMap[type] || 'info';
    }

    /**
     * Mapowanie typów komunikatów na ikony Font Awesome
     */
    getMessageIcon(type) {
        const iconMap = {
            'success': 'fa-check-circle',
            'error': 'fa-exclamation-circle',
            'warning': 'fa-exclamation-triangle',
            'info': 'fa-info-circle'
        };
        return iconMap[type] || 'fa-info-circle';
    }

    /**
     * Asynchroniczne sprawdzenie wycen dla zamówień po renderowaniu tabeli
     */
    async checkQuotesForRenderedOrders() {
        console.log('[checkQuotesForRenderedOrders] Sprawdzanie wycen dla wyrenderowanych zamówień');

        // Znajdź wszystkie przyciski w stanie "sprawdzania"
        const checkingButtons = document.querySelectorAll('.action-btn-checking');

        if (checkingButtons.length === 0) {
            console.log('[checkQuotesForRenderedOrders] Brak przycisków do sprawdzenia');
            return;
        }

        console.log(`[checkQuotesForRenderedOrders] Znaleziono ${checkingButtons.length} przycisków do sprawdzenia`);

        // Sprawdź każdy przycisk asynchronicznie
        const promises = Array.from(checkingButtons).map(async (button) => {
            const orderID = button.dataset.orderId;

            if (!orderID) {
                console.warn('[checkQuotesForRenderedOrders] Brak orderID w przycisku');
                return;
            }

            try {
                const hasQuote = await this.checkIfOrderHasQuote(orderID);
                const cachedData = this.quotesCache.get(orderID);

                // Aktualizuj przycisk na podstawie wyniku
                if (hasQuote && cachedData?.quoteId) {
                    button.outerHTML = `
                    <button class="action-btn action-btn-quote" 
                            onclick="window.reportsManager.redirectToQuoteByOrderId('${orderID}')"
                            title="Przejdź do wyceny ${cachedData.quoteNumber || ''}">
                        <i class="fas fa-file-invoice"></i>
                        Wycena
                    </button>
                `;
                } else {
                    button.outerHTML = `
                    <button disabled class="action-btn action-btn-quote" title="Brak wyceny w systemie">
                        <i class="fas fa-file-invoice"></i>
                        Wycena
                    </button>
                `;
                }

            } catch (error) {
                console.error(`[checkQuotesForRenderedOrders] Błąd dla orderID ${orderID}:`, error);

                // W przypadku błędu pokaż przycisk nieaktywny
                button.outerHTML = `
                <button disabled class="action-btn action-btn-quote" title="Błąd sprawdzania wyceny">
                    <i class="fas fa-exclamation-triangle"></i>
                    Błąd
                </button>
            `;
            }
        });

        // Poczekaj na wszystkie sprawdzenia
        await Promise.all(promises);
        console.log('[checkQuotesForRenderedOrders] Zakończono sprawdzanie wszystkich wycen');
    }

    /**
     * Sprawdzenie czy zamówienie ma wycenę w systemie
     * @param {string|number} orderID - ID zamówienia z Baselinker
     * @returns {boolean} - true jeśli zamówienie ma wycenę
     */
    async checkIfOrderHasQuote(orderID) {
        if (!orderID) {
            console.log('[checkIfOrderHasQuote] Brak orderID');
            return false;
        }

        // Sprawdź cache
        if (this.quotesCache.has(orderID)) {
            const cachedResult = this.quotesCache.get(orderID);
            console.log(`[checkIfOrderHasQuote] Cache hit dla ${orderID}:`, cachedResult);
            return cachedResult.hasQuote;
        }

        try {
            // Wywołaj endpoint API do sprawdzenia czy istnieje wycena z tym base_linker_order_id
            const response = await fetch(`/quotes/api/check-quote-by-order/${orderID}`);

            if (!response.ok) {
                console.warn(`[checkIfOrderHasQuote] API error: ${response.status}`);
                return false;
            }

            const data = await response.json();

            // Zapisz w cache wynik
            this.quotesCache.set(orderID, {
                hasQuote: data.hasQuote,
                quoteId: data.quoteId,
                quoteNumber: data.quoteNumber,
                timestamp: Date.now()
            });

            return data.hasQuote;

        } catch (error) {
            console.error(`[checkIfOrderHasQuote] Błąd podczas sprawdzania wyceny dla ${orderID}:`, error);
            return false;
        }
    }

    /**
     * Funkcja do przekierowania do modułu quotes z otwarciem modala wyceny
     * @param {string|number} orderID - ID zamówienia z Baselinker
     */
    async redirectToQuoteByOrderId(orderID) {
        console.log(`[redirectToQuoteByOrderId] Przekierowanie do wyceny dla zamówienia: ${orderID}`);

        if (!orderID) {
            console.error("[redirectToQuoteByOrderId] Brak orderID");
            return;
        }

        try {
            // Sprawdź cache najpierw
            let quoteData = this.quotesCache.get(orderID);

            if (!quoteData || !quoteData.quoteId) {
                // Jeśli nie ma w cache, wywołaj API
                const response = await fetch(`/quotes/api/check-quote-by-order/${orderID}`);

                if (!response.ok) {
                    console.error(`[redirectToQuoteByOrderId] API error: ${response.status}`);
                    alert('Nie udało się znaleźć wyceny dla tego zamówienia');
                    return;
                }

                const data = await response.json();

                if (!data.hasQuote) {
                    alert('To zamówienie nie ma powiązanej wyceny w systemie');
                    return;
                }

                quoteData = {
                    quoteId: data.quoteId,
                    quoteNumber: data.quoteNumber
                };
            }

            console.log(`[redirectToQuoteByOrderId] Przekierowanie do wyceny ID: ${quoteData.quoteId}`);

            // Zapisz ID wyceny w sessionStorage (tak samo jak w calculator)
            sessionStorage.setItem('openQuoteId', quoteData.quoteId);
            console.log(`[redirectToQuoteByOrderId] Zapisano do sessionStorage: openQuoteModal=${quoteData.quoteId}`);

            // Przekieruj do modułu quotes
            window.location.href = '/quotes/';

        } catch (error) {
            console.error(`[redirectToQuoteByOrderId] Błąd podczas przekierowania:`, error);
            alert('Wystąpił błąd podczas przekierowania do wyceny');
        }
    }

    /**
     * Pobieranie klasy CSS dla statusu
     */
    getStatusClass(status) {
        if (!status) return '';

        const statusMap = {
            'Nowe - nieopłacone': 'status-nowe-nieopłacone',
            'Nowe - opłacone': 'status-nowe-opłacone',
            'W produkcji - surowe': 'status-w-produkcji-surowe',
            'W produkcji - lakierowanie': 'status-w-produkcji-lakierowanie',
            'W produkcji - bejcowanie': 'status-w-produkcji-bejcowanie',
            'W produkcji - olejowanie': 'status-w-produkcji-olejowanie',
            'W produkcji - suszenie usługowe': 'status-w-produkcji-suszenie',
            'Produkcja zakończona': 'status-produkcja-zakończona',
            'Zamówienie spakowane': 'status-zamówienie-spakowane',
            'Paczka zgłoszona do wysyłki': 'status-paczka-zgloszona-do-wysylki',
            'Wysłane - kurier': 'status-wysłane-kurier',
            'Wysłane - transport WoodPower': 'status-wysłane-transport-woodpower',
            'Dostarczona - kurier': 'status-dostarczona-kurier',
            'Dostarczona - trans. WoodPower': 'status-dostarczona-trans-woodpower',
            'Czeka na odbiór osobisty': 'status-czeka-na-odbiór-osobisty',
            'Odebrane': 'status-odebrane',
            'Zamówienie anulowane': 'status-zamówienie-anulowane'
        };

        return statusMap[status] || '';
    }

    /**
     * Oblicza statystyki powierzchni według wykończenia
     */
    calculateFinishStatistics(data) {
        let olejowanieSurface = 0;
        let lakierowanieSurface = 0;

        console.log('[calculateFinishStatistics] Rozpoczynam obliczenia powierzchni dla', data.length, 'rekordów');

        // Iteruj przez wszystkie rekordy danych
        data.forEach(record => {
            if (!record.finish_state || !record.total_surface_m2) {
                return; // Pomiń rekordy bez wykończenia lub powierzchni
            }

            const finishState = String(record.finish_state).toLowerCase().trim();
            const surface = parseFloat(record.total_surface_m2) || 0;

            console.log(`[calculateFinishStatistics] Rekord ID ${record.id}: finish_state="${finishState}", surface=${surface}`);

            // Sprawdź czy to olejowanie (różne warianty)
            if (finishState.includes('olejowa') ||
                finishState.includes('olejowanie') ||
                finishState.includes('olej') ||
                finishState.includes('olejowany')) {
                olejowanieSurface += surface;
                console.log(`[calculateFinishStatistics] Dodano olejowanie: ${surface} m² (${finishState})`);
            }

            // Sprawdź czy to lakierowanie (różne warianty)
            if (finishState.includes('lakierowa') ||
                finishState.includes('lakierowanie') ||
                finishState.includes('lakier') ||
                finishState.includes('lakierowany')) {
                lakierowanieSurface += surface;
                console.log(`[calculateFinishStatistics] Dodano lakierowanie: ${surface} m² (${finishState})`);
            }
        });

        console.log(`[calculateFinishStatistics] Podsumowanie - Olejowanie: ${olejowanieSurface} m², Lakierowanie: ${lakierowanieSurface} m²`);

        return {
            olejowanie_surface: olejowanieSurface,
            lakierowanie_surface: lakierowanieSurface
        };
    }

    /**
     * Aktualizacja statystyk
     */
    updateStatistics(stats) {
        if (!stats) return;

        // Zapisz dane do modala
        this.currentModalStats = stats;

        // Zachowaj pozostałą logikę dla szczegółowych statystyk
        this.updateStat('statTotalM3', stats.total_m3, 4, ' m³');
        this.updateStat('statOrderAmountNet', stats.order_amount_net, 2, ' PLN');
        this.updateStat('statValueNet', stats.value_net, 2, ' PLN');
        this.updateStat('statPricePerM3', stats.avg_price_per_m3, 2, ' PLN');
        this.updateStat('statPaidAmountNet', stats.paid_amount_net, 2, ' PLN');
        this.updateStat('statBalanceDue', stats.balance_due, 2, ' PLN');
        this.updateStat('statProductionVolume', stats.production_volume, 4, ' m³');
        this.updateStat('statProductionValueNet', stats.production_value_net, 2, ' PLN');
        this.updateStat('statReadyPickupVolume', stats.ready_pickup_volume, 4, ' m³');
        this.updateStat('statReadyPickupValueNet', stats.ready_pickup_value_net, 2, ' PLN');
        this.updateStat('statPickupReady', stats.pickup_ready_volume, 4, ' m³');

        // POPRAWKA 1: Wartość klejonek netto
        this.updateStat('statKlejonkaValueNet', stats.klejonka_value_net, 2, ' PLN');

        // POPRAWKI 3 i 4: Statystyki dla deski
        this.updateStat('statDeskaValueNet', stats.deska_value_net, 2, ' PLN');
        this.updateStat('statDeskaTotalM3', stats.deska_total_m3, 4, ' m³');

        this.updateStat('statDryingTotalM3', stats.drying_total_m3, 4, ' m³');

        this.updateStat('statSuszenieValueNet', stats.suszenie_value_net, 2, ' PLN');
        this.updateStat('statKlejenieValueNet', stats.klejenie_value_net, 2, ' PLN');

        // POPRAWKA 5: Wartość usług netto
        this.updateStat('statServicesValueNet', stats.services_value_net, 2, ' PLN');

        // NOWA STRUKTURA: Obsługa statystyki "Zamówienia" (bez pozycji)
        this.updateStat('statUniqueOrders', stats.unique_orders || 0, 0, ''); // Bez miejsc po przecinku dla liczby zamówień

        // ZACHOWANE dla kompatybilności wstecznej: Zamówienia/Pozycje (jeśli jeszcze istnieje)
        if (this.elements.statOrdersProducts) {
            this.elements.statOrdersProducts.textContent = `${stats.unique_orders || 0} / ${stats.products_count || 0}`;
        }

        // NOWE - oblicz i aktualizuj statystyki wykończenia
        if (this.currentData && this.currentData.length > 0) {
            const finishStats = this.calculateFinishStatistics(this.currentData);
            stats.olejowanie_surface = finishStats.olejowanie_surface;
            stats.lakierowanie_surface = finishStats.lakierowanie_surface;
            this.updateStat('statOlejowanieSurface', finishStats.olejowanie_surface, 4, ' m²');
            this.updateStat('statLakierowanieSurface', finishStats.lakierowanie_surface, 4, ' m²');
        }

        console.log('[ReportsManager] Statystyki zaktualizowane', stats);
    }

    createCompactStat(label, value) {
        const statDiv = document.createElement('div');
        statDiv.className = 'compact-stat';
        statDiv.innerHTML = `
            <div class="compact-stat-label">${label}</div>
            <div class="compact-stat-value">${value}</div>
        `;
        return statDiv;
    }

    formatStatValue(value, format) {
        if (value === null || value === undefined) return '0';
        
        const numValue = parseFloat(value) || 0;
        
        switch (format) {
            case 'currency':
                return numValue.toLocaleString('pl-PL', { 
                    minimumFractionDigits: 2, 
                    maximumFractionDigits: 2 
                }) + ' PLN';
            case 'volume':
                return numValue.toLocaleString('pl-PL', { 
                    minimumFractionDigits: 4, 
                    maximumFractionDigits: 4 
                }) + ' m³';
            case 'surface':
                return numValue.toLocaleString('pl-PL', { 
                    minimumFractionDigits: 4, 
                    maximumFractionDigits: 4 
                }) + ' m²';
            case 'number':
                return Math.round(numValue).toString();
            default:
                return numValue.toString();
        }
    }

    /**
     * Ustawienie hover effects dla grupowanych zamówień
     */
    setupOrderHoverEffects() {
        if (!this.elements.reportsTableBody) return;

        const rows = this.elements.reportsTableBody.querySelectorAll('tr[data-order-group]');

        rows.forEach(row => {
            const orderGroup = row.dataset.orderGroup;

            row.addEventListener('mouseenter', () => {
                // Podświetl TYLKO wiersze z tym samym order-group (to samo zamówienie)
                const relatedRows = this.elements.reportsTableBody.querySelectorAll(`tr[data-order-group="${orderGroup}"]`);
                relatedRows.forEach(relatedRow => {
                    relatedRow.classList.add('hover-group');
                });
            });

            row.addEventListener('mouseleave', () => {
                // Usuń podświetlenie TYLKO z wierszy z tym samym order-group
                const relatedRows = this.elements.reportsTableBody.querySelectorAll(`tr[data-order-group="${orderGroup}"]`);
                relatedRows.forEach(relatedRow => {
                    relatedRow.classList.remove('hover-group');
                });
            });
        });
    }

    /**
     * Aktualizacja porównań - POPRAWKA: Ulepszona obsługa
     */
    updateComparisons(comparison) {
        if (!comparison || Object.keys(comparison).length === 0) {
            this.clearComparisons();
            return;
        }

        this.currentComparison = comparison;

        const fields = [
            'total_m3', 'order_amount_net', 'value_net',
            'avg_price_per_m3', 'paid_amount_net', 'balance_due',
            'production_volume', 'production_value_net', 'ready_pickup_volume', 'ready_pickup_value_net',
            'olejowanie_surface', 'lakierowanie_surface',
            'klejonka_value_net',
            'deska_value_net', 'deska_total_m3',
            'drying_total_m3',
            'services_value_net',
            'suszenie_value_net',
            'klejenie_value_net',
            'unique_orders'
        ];

        const elementMap = {
            'total_m3': 'compTotalM3',
            'unique_orders': 'compUniqueOrders',
            'order_amount_net': 'compOrderAmountNet',
            'value_net': 'compValueNet',
            'avg_price_per_m3': 'compPricePerM3',
            'paid_amount_net': 'compPaidAmountNet',
            'balance_due': 'compBalanceDue',
            'production_volume': 'compProductionVolume',
            'production_value_net': 'compProductionValueNet',
            'olejowanie_surface': 'compOlejowanieSurface',
            'lakierowanie_surface': 'compLakierowanieSurface',
            'ready_pickup_volume': 'compReadyPickupVolume',
            'ready_pickup_value_net': 'compReadyPickupValueNet',
            'klejonka_value_net': 'compKlejonkaValueNet',
            'deska_value_net': 'compDeskaValueNet',
            'deska_total_m3': 'compDeskaTotalM3',
            'drying_total_m3': 'compDryingTotalM3',
            'services_value_net': 'compServicesValueNet',
            'suszenie_value_net': 'compSuszenieValueNet',
            'klejenie_value_net': 'compKlejenieValueNet'
        };

        fields.forEach(field => {
            const elementId = elementMap[field];
            const element = this.elements[elementId];
            const compData = comparison[field];

            if (element) {
                if (compData && compData.change_percent !== undefined) {
                    const changePercent = compData.change_percent;
                    const isPositive = compData.is_positive;

                    if (Math.abs(changePercent) > 0.1) {
                        const sign = isPositive ? '+' : '';
                        element.textContent = `${sign}${changePercent}%`;
                        element.className = `stats-comparison ${isPositive ? 'positive' : 'negative'}`;
                        element.style.display = '';
                    } else {
                        element.textContent = '';
                        element.className = 'stats-comparison';
                        element.style.display = 'none';
                    }
                } else {
                    element.textContent = '';
                    element.className = 'stats-comparison';
                    element.style.display = 'none';
                }
            }
        });
    }

    /**
     * Aktualizacja pojedynczej statystyki
     */
    updateStat(elementId, value, decimals = 2, suffix = '') {
        const element = document.getElementById(elementId);
        if (!element) return;

        // Użyj nowego formatowania z separatorami tysięcy
        const formatted = this.formatStatNumber(value, decimals, suffix);
        element.textContent = formatted;
    }

    /**
     * Aktualizacja aktywnych filtrów
     */
    updateActiveFilters() {
        if (!this.elements.activeFilters || !this.elements.activeFiltersList) return;

        const activeFiltersCount = Object.keys(this.currentFilters).reduce((count, key) => {
            const values = this.currentFilters[key];
            return count + (values && Array.isArray(values) ? values.length : 0);
        }, 0);

        if (activeFiltersCount === 0) {
            this.elements.activeFilters.style.display = 'none';
            return;
        }

        // Pokaż sekcję aktywnych filtrów
        this.elements.activeFilters.style.display = 'block';

        // Wygeneruj tagi filtrów
        let tagsHtml = '';
        for (const [key, values] of Object.entries(this.currentFilters)) {
            if (values && Array.isArray(values) && values.length > 0) {
                const filterLabel = this.getFilterLabel(key);
                values.forEach(value => {
                    tagsHtml += `
                        <span class="active-filter-tag" data-filter="${key}" data-value="${value}">
                            ${filterLabel}: ${value}
                            <span class="active-filter-remove" data-filter="${key}" data-value="${value}">×</span>
                        </span>
                    `;
                });
            }
        }

        this.elements.activeFiltersList.innerHTML = tagsHtml;

        // Dodaj event listenery do usuwania filtrów
        this.elements.activeFiltersList.querySelectorAll('.active-filter-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const filter = btn.dataset.filter;
                const value = btn.dataset.value;
                this.removeFilter(filter, value);
            });
        });
    }

    /**
     * Pobieranie etykiety filtra
     */
    getFilterLabel(filterKey) {
        const labels = {
            'customer_name': 'Klient',
            'delivery_state': 'Województwo',
            'wood_species': 'Gatunek',
            'current_status': 'Status',
            'finish_state': 'Wykończenie'
        };
        return labels[filterKey] || filterKey;
    }

    /**
     * Usuwanie pojedynczego filtra
     */
    removeFilter(filterKey, value) {
        if (this.currentFilters[filterKey] && Array.isArray(this.currentFilters[filterKey])) {
            const index = this.currentFilters[filterKey].indexOf(value);
            if (index > -1) {
                this.currentFilters[filterKey].splice(index, 1);
                if (this.currentFilters[filterKey].length === 0) {
                    delete this.currentFilters[filterKey];
                }
            }
        }

        // Odśwież dane i aktywne filtry
        this.loadData();

        // Powiadom TableManager o zmianie
        if (window.tableManager) {
            window.tableManager.updateFilterCheckboxes(filterKey, value, false);
        }
    }

    handleEditManualRow(recordId) {
        console.log('[ReportsManager] Edit record:', recordId, 'type:', typeof recordId);

        try {
            // POPRAWKA: Konwertuj recordId i porównuj różne typy
            const numericRecordId = typeof recordId === 'string' ? parseInt(recordId, 10) : recordId;

            const record = this.currentData.find(r => {
                return r.id === numericRecordId || r.id === recordId || String(r.id) === String(recordId);
            });

            if (!record) {
                console.error('[ReportsManager] Record not found. Available records:',
                    this.currentData.slice(0, 3).map(r => ({ id: r.id, type: typeof r.id })));
                this.showError('Nie znaleziono rekordu do edycji');
                return;
            }

            console.log(`[ReportsManager] Found record ${record.id}. Opening edit modal for ${record.is_manual ? 'manual' : 'Baselinker'} record`);

            if (window.tableManager) {
                // Przekaż obsługę do TableManager z poprawnym ID
                window.tableManager.handleEditButtonClick(record.id, {
                    preventDefault: () => { },
                    stopPropagation: () => { }
                });
            } else {
                console.error('[ReportsManager] TableManager not available');
                this.showError('TableManager nie jest dostępny');
            }
        } catch (error) {
            console.error('[ReportsManager] Error in handleEditManualRow:', error);
            this.showError('Błąd podczas otwierania edycji: ' + error.message);
        }
    }

    /**
     * Obsługa kliknięć w tabeli
     */
    handleTableClick(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;
        const recordId = target.dataset.recordId;

        switch (action) {
            case 'edit':
                this.handleEditManualRow(recordId);
                break;
            default:
                console.log('[ReportsManager] Unknown table action:', action);
        }
    }

    /**
     * Obsługa skrótów klawiaturowych
     */
    handleKeyboardShortcuts(e) {
        // Ctrl+R - Odśwież dane
        if (e.ctrlKey && e.key === 'r') {
            e.preventDefault();
            this.loadData();
        }

        // Ctrl+E - Eksport Excel
        if (e.ctrlKey && e.key === 'e') {
            e.preventDefault();
            this.handleExportExcel();
        }

        // Ctrl+N - Nowy wiersz
        if (e.ctrlKey && e.key === 'n') {
            e.preventDefault();
            this.handleAddManualRow();
        }

        // NOWE: F11 - Fullscreen toggle
        if (e.key === 'F11') {
            e.preventDefault();
            this.toggleFullscreen();
        }

        // NOWE: Escape - Wyjście z fullscreen (jeśli aktywny)
        if (e.key === 'Escape' && this.isInFullscreenMode()) {
            // Pozwól FullscreenManager obsłużyć to pierwsze
            // ReportsManager nie robi nic - to tylko backup
        }
    }

    /**
     * Obsługa kliknięcia synchronizacji
     */
    handleSyncClick() {
        console.log('[ReportsManager] Sync button clicked');

        if (window.syncManager) {
            window.syncManager.showSyncModal();
        } else {
            console.error('[ReportsManager] SyncManager not available');
            this.showError('SyncManager nie jest dostępny');
        }
    }

    /**
     * Obsługa dodawania ręcznego wiersza
     */
    handleAddManualRow() {
        console.log('[ReportsManager] Add manual row clicked');

        if (window.tableManager) {
            window.tableManager.showManualRowModal();
        } else {
            console.error('[ReportsManager] TableManager not available');
            this.showError('TableManager nie jest dostępny');
        }
    }

    /**
     * Obsługa edycji rekordu - dla wszystkich typów
     */
    handleTableClick(e) {
        const target = e.target;

        // Przycisk edycji
        if (target.matches('.action-btn-edit') || target.closest('.action-btn-edit')) {
            const button = target.matches('.action-btn-edit') ? target : target.closest('.action-btn-edit');
            const recordId = button.getAttribute('data-record-id');

            console.log('[ReportsManager] Edit button clicked, raw recordId:', recordId, 'type:', typeof recordId);

            if (recordId) {
                // POPRAWKA: Konwertuj string na number przed przekazaniem
                const numericRecordId = parseInt(recordId, 10);
                console.log('[ReportsManager] Converted to numeric:', numericRecordId);

                if (!isNaN(numericRecordId)) {
                    this.handleEditManualRow(numericRecordId);
                } else {
                    console.error('[ReportsManager] Invalid recordId:', recordId);
                    this.showError('Nieprawidłowy ID rekordu');
                }
            }
            return;
        }

        // Przycisk usuwania ręcznego wiersza
        if (target.matches('.action-btn-delete') || target.closest('.action-btn-delete')) {
            const button = target.matches('.action-btn-delete') ? target : target.closest('.action-btn-delete');
            const recordId = parseInt(button.getAttribute('data-record-id'), 10);

            if (recordId && !isNaN(recordId)) {
                this.handleDeleteManualRow(recordId);
            }
            return;
        }

        // Links do Baselinker i wycen - pozostają bez zmian
        if (target.matches('a[href*="baselinker.com"]')) {
            // Link do Baselinker - pozwól na standardowe działanie
            return;
        }

        if (target.matches('a[href*="/quotes/"]')) {
            // Link do wycen - pozwól na standardowe działanie  
            return;
        }
    }

    /**
     * Obsługa eksportu Excel - ZAKTUALIZOWANE dla dropdown
     */
    handleExportExcel() {
        console.log('[ReportsManager] Export Excel clicked');

        if (window.exportManager) {
            window.exportManager.exportToExcel();
        } else {
            console.error('[ReportsManager] ExportManager not available');
            this.showError('ExportManager nie jest dostępny');
        }
    }

    /**
     * NOWA METODA - Obsługa eksportu Routimo
     */
    handleExportRoutimo() {
        console.log('[ReportsManager] Export Routimo clicked');

        if (window.exportManager) {
            window.exportManager.exportToRoutimo();
        } else {
            console.error('[ReportsManager] ExportManager not available');
            this.showError('ExportManager nie jest dostępny');
        }
    }

    /**
     * NOWA METODA - Generyczna obsługa eksportu
     */
    handleExport(type) {
        console.log('[ReportsManager] Export requested:', type);

        if (!window.exportManager) {
            console.error('[ReportsManager] ExportManager not available');
            this.showError('ExportManager nie jest dostępny');
            return;
        }

        switch (type) {
            case 'excel':
                window.exportManager.exportToExcel();
                break;
            case 'routimo':
                window.exportManager.exportToRoutimo();
                break;
            default:
                console.error('[ReportsManager] Unknown export type:', type);
                this.showError(`Nieznany typ eksportu: ${type}`);
        }
    }

    /**
     * Czyszczenie wszystkich filtrów
     */
    clearAllFilters() {
        console.log('[ReportsManager] Clearing all filters');

        this.currentFilters = {};

        if (window.tableManager) {
            window.tableManager.clearFilters();
        }

        this.resetToDefaultDates();
    }

    /**
     * Ustawienie filtra - POPRAWKA: Lepsze logowanie
     */
    setFilter(column, values) {
        console.log('[ReportsManager] Setting filter:', column, values);

        if (values && Array.isArray(values) && values.length > 0) {
            // Filtruj puste wartości
            const filteredValues = values.filter(v => v && v.trim());
            if (filteredValues.length > 0) {
                this.currentFilters[column] = filteredValues;
            } else {
                delete this.currentFilters[column];
            }
        } else {
            delete this.currentFilters[column];
        }

        this.loadData();
    }

    /**
     * Dodawanie wartości do filtra
     */
    addFilterValue(column, value) {
        if (!value || !value.trim()) return;

        if (!this.currentFilters[column]) {
            this.currentFilters[column] = [];
        }

        if (!this.currentFilters[column].includes(value)) {
            this.currentFilters[column].push(value);
            this.loadData();
        }
    }

    /**
     * Usuwanie wartości z filtra
     */
    removeFilterValue(column, value) {
        if (this.currentFilters[column] && Array.isArray(this.currentFilters[column])) {
            const index = this.currentFilters[column].indexOf(value);
            if (index > -1) {
                this.currentFilters[column].splice(index, 1);
                if (this.currentFilters[column].length === 0) {
                    delete this.currentFilters[column];
                }
                this.loadData();
            }
        }
    }

    /**
     * Pokazywanie loading
     */
    showLoading(message = 'Pobieranie danych...') {
        if (this.elements.loadingOverlay) {
            this.elements.loadingOverlay.classList.remove('hidden');

            // Aktualizuj tekst loading
            const loadingText = document.getElementById('loadingText');
            if (loadingText) {
                loadingText.textContent = message;
            }

            // W trybie fullscreen - wyższy z-index
            if (this.isInFullscreenMode()) {
                this.elements.loadingOverlay.style.zIndex = '10001';
            } else {
                this.elements.loadingOverlay.style.zIndex = '9999';
            }
        }
    }

    /**
     * Ukrywanie loading
     */
    hideLoading() {
        if (this.elements.loadingOverlay) {
            this.elements.loadingOverlay.classList.add('hidden');
            this.elements.loadingOverlay.style.zIndex = ''; // Reset z-index
        }
    }

    /**
     * Pokazywanie błędu
     */
    showError(message) {
        console.error('[ReportsManager] Error:', message);
        this.showMessage(message, 'error'); // TODO: Lepszy system notyfikacji
    }

    /**
     * Formatowanie liczb z separatorami tysięcy
     */
    formatNumber(value, decimals = 2) {
        if (value === null || value === undefined || value === '') {
            return '0' + ',0000'.substring(0, decimals + 1);
        }

        const num = parseFloat(value);
        if (isNaN(num)) {
            return '0' + ',0000'.substring(0, decimals + 1);
        }

        // Dla pól objętości zawsze używaj 4 miejsca po przecinku
        const fixedDecimals = decimals === 4 ? 4 : decimals;

        return num.toLocaleString('pl-PL', {
            minimumFractionDigits: fixedDecimals,
            maximumFractionDigits: fixedDecimals
        });
    }

    /**
     * Formatowanie waluty z separatorami tysięcy
     */
    formatCurrency(value) {
        const formatted = this.formatNumber(value, 2);
        return formatted + ' PLN';
    }

    /**
     * Formatowanie waluty ze znakiem (dla sald) z separatorami tysięcy
     */
    formatCurrencyWithSign(value) {
        const num = parseFloat(value || 0);
        const formatted = this.formatNumber(Math.abs(num), 2);

        if (num > 0) {
            return `+${formatted} PLN`;
        } else if (num < 0) {
            return `-${formatted} PLN`;
        } else {
            return formatted + ' PLN';
        }
    }

    /**
     * NOWA: Formatowanie liczb dla statystyk (bez waluty)
     */
    formatStatNumber(value, decimals = 2, suffix = '') {
        const formatted = this.formatNumber(value, decimals);
        return formatted + suffix;
    }

    /**
     * POPRAWKA: Ustawienie dat programowo - lepsze logowanie
     */
    setDateRange(dateFrom, dateTo) {
        console.log('[ReportsManager] Setting date range:', dateFrom, dateTo);

        this.dateFrom = dateFrom;
        this.dateTo = dateTo;

        if (this.elements.dateFrom) {
            this.elements.dateFrom.value = dateFrom || '';
        }
        if (this.elements.dateTo) {
            this.elements.dateTo.value = dateTo || '';
        }

        this.loadData();
    }

    /**
     * Pobieranie bieżących dat dla innych managerów
     */
    getCurrentDateRange() {
        return {
            date_from: this.dateFrom,
            date_to: this.dateTo
        };
    }

    /**
     * Publiczne API dla innych managerów
     */
    refreshData() {
        console.log('[ReportsManager] Manual data refresh requested');
        this.loadData();
    }

    getCurrentData() {
        return this.currentData;
    }

    getCurrentStats() {
        return this.currentStats;
    }

    getCurrentFilters() {
        return { ...this.currentFilters };
    }

    getDateFrom() {
        return this.dateFrom;
    }

    getDateTo() {
        return this.dateTo;
    }

    /**
     * NOWA METODA - Sprawdzenie czy dane są ładowane
     */
    isDataLoading() {
        return this.isLoading;
    }

    /**
     * NOWA METODA - Sprawdzenie czy jesteśmy w trybie fullscreen
     */
    isInFullscreenMode() {
        if (window.fullscreenManager && typeof window.fullscreenManager.isFullscreenActive === 'function') {
            return window.fullscreenManager.isFullscreenActive();
        }
        return false;
    }

    /**
     * NOWA METODA - Przełączenie trybu fullscreen
     */
    toggleFullscreen() {
        if (window.fullscreenManager && typeof window.fullscreenManager.toggle === 'function') {
            window.fullscreenManager.toggle();
        } else {
            console.warn('[ReportsManager] FullscreenManager not available');
        }
    }

    /**
     * NOWA METODA - Wymuszenie wyjścia z fullscreen
     */
    exitFullscreen() {
        if (window.fullscreenManager && typeof window.fullscreenManager.exitFullscreen === 'function') {
            window.fullscreenManager.exitFullscreen();
        }
    }

    /**
     * NOWA METODA - Resetowanie filtrów bez resetowania dat
     */
    clearFiltersOnly() {
        console.log('[ReportsManager] Clearing filters only (keeping dates)');

        this.currentFilters = {};

        if (window.tableManager) {
            window.tableManager.clearFilters();
        }

        this.loadData();
    }

    /**
     * NOWA METODA - Sprawdzenie czy są aktywne filtry
     */
    hasActiveFilters() {
        return Object.keys(this.currentFilters).length > 0;
    }

    /**
     * NOWA METODA - Pobieranie liczby rekordów
     */
    getRecordsCount() {
        return this.currentData.length;
    }

    /**
     * NOWA METODA - Obsługa zmiany trybu fullscreen
     */
    onFullscreenChange(isFullscreen) {
        console.log('[ReportsManager] Fullscreen mode changed:', isFullscreen);

        // Odśwież layout po zmianie trybu
        setTimeout(() => {
            // Powiadom o zmianie rozmiaru okna
            window.dispatchEvent(new Event('resize'));

            // Odśwież tabele jeśli potrzeba
            if (this.elements.reportsTable) {
                this.refreshTableLayout();
            }
        }, 300);

        // Aktualizuj inne managery o zmianie
        this.notifyManagersAboutFullscreen(isFullscreen);
    }

    /**
     * NOWA METODA - Powiadomienie managerów o zmianie fullscreen
     */
    notifyManagersAboutFullscreen(isFullscreen) {
        // Powiadom TableManager
        if (window.tableManager && typeof window.tableManager.onFullscreenChange === 'function') {
            window.tableManager.onFullscreenChange(isFullscreen);
        }

        // Powiadom ExportManager
        if (window.exportManager && typeof window.exportManager.onFullscreenChange === 'function') {
            window.exportManager.onFullscreenChange(isFullscreen);
        }

        // Powiadom SyncManager
        if (window.syncManager && typeof window.syncManager.onFullscreenChange === 'function') {
            window.syncManager.onFullscreenChange(isFullscreen);
        }
    }

    /**
     * NOWA METODA - Odświeżenie layoutu tabeli
     */
    refreshTableLayout() {
        if (!this.elements.reportsTable) return;

        // POPRAWKA: Nie używamy display: none, który resetuje scroll
        if (this.isInFullscreenMode()) {
            // W fullscreen używamy delikatnego odświeżenia
            const tableWrapper = document.querySelector('.fullscreen-table-container .table-wrapper');
            if (tableWrapper) {
                // Zapisz pozycję scroll
                const scrollTop = tableWrapper.scrollTop;
                const scrollLeft = tableWrapper.scrollLeft;

                // Wymusz repaint
                tableWrapper.style.transform = 'translateZ(0)';

                requestAnimationFrame(() => {
                    tableWrapper.style.transform = '';
                    // Przywróć pozycję scroll
                    tableWrapper.scrollTop = scrollTop;
                    tableWrapper.scrollLeft = scrollLeft;
                });
            }
        } else {
            // W normalnym trybie można użyć standardowego odświeżenia
            this.elements.reportsTable.style.display = 'none';
            this.elements.reportsTable.offsetHeight; // Trigger reflow
            this.elements.reportsTable.style.display = '';
        }

        // Odśwież hover effects dla grupowanych zamówień
        this.setupOrderHoverEffects();
    }

    /**
     * NOWA METODA - Sprawdzenie dostępności opcji eksportu
     */
    getAvailableExportOptions() {
        if (window.exportManager && typeof window.exportManager.getExportOptions === 'function') {
            return window.exportManager.getExportOptions();
        }

        return {
            excel: { available: true, label: 'Excel' },
            routimo: { available: false, label: 'Routimo' }
        };
    }

    /**
     * NOWA METODA - Sprawdzenie czy eksport jest w toku
     */
    isExportInProgress() {
        if (window.exportManager && typeof window.exportManager.isExportInProgress === 'function') {
            return window.exportManager.isExportInProgress();
        }

        return false;
    }

    /**
     * NOWA METODA - Weryfikacja stanu managera
     */
    validateState() {
        const issues = [];

        if (!this.elements.reportsTableBody) {
            issues.push('Missing table body element');
        }

        if (!this.elements.dateFrom || !this.elements.dateTo) {
            issues.push('Missing date filter elements');
        }

        if (!this.dateFrom || !this.dateTo) {
            issues.push('Date range not set');
        }

        // NOWE: Sprawdź dostępność FullscreenManager
        if (!window.fullscreenManager) {
            issues.push('FullscreenManager not available');
        }

        return {
            isValid: issues.length === 0,
            issues: issues
        };
    }

    /**
     * NOWA METODA - Publiczne API dla fullscreen
     */

    // Aktywuj fullscreen
    activateFullscreen() {
        if (window.fullscreenManager && typeof window.fullscreenManager.activate === 'function') {
            window.fullscreenManager.activate();
        }
    }

    // Deaktywuj fullscreen
    deactivateFullscreen() {
        if (window.fullscreenManager && typeof window.fullscreenManager.deactivate === 'function') {
            window.fullscreenManager.deactivate();
        }
    }

    // Pobierz stan fullscreen
    getFullscreenState() {
        if (window.fullscreenManager && typeof window.fullscreenManager.getState === 'function') {
            return window.fullscreenManager.getState();
        }
        return { isFullscreen: false, isCompatible: false };
    }

    /**
     * NOWA METODA - Obsługa resize w fullscreen
     */
    handleFullscreenResize() {
        if (this.isInFullscreenMode()) {
            // POPRAWKA: Delikatne odświeżenie bez resetowania scroll
            setTimeout(() => {
                // Powiadom FullscreenManager o resize
                if (window.fullscreenManager && typeof window.fullscreenManager.handleFullscreenResize === 'function') {
                    window.fullscreenManager.handleFullscreenResize();
                }
            }, 150);
        }
    }

    /**
     * Debug info
     */
    getDebugInfo() {
        const validation = this.validateState();

        return {
            currentData: this.currentData.length,
            currentStats: this.currentStats,
            currentComparison: this.currentComparison,
            currentFilters: this.currentFilters,
            dateFrom: this.dateFrom,
            dateTo: this.dateTo,
            isLoading: this.isLoading,
            hasActiveFilters: this.hasActiveFilters(),
            isFullscreen: this.isInFullscreenMode(), // NOWE
            validation: validation,
            elements: {
                cached: Object.keys(this.elements).length,
                missing: Object.keys(this.elements).filter(key => !this.elements[key]).length
            },
            // NOWE: Informacje o fullscreen
            fullscreenManager: {
                available: !!window.fullscreenManager,
                active: this.isInFullscreenMode()
            }
        };
    }

    /**
     * Modal potwierdzenia zastępujący confirm()
     */
    showConfirmDialog(message, title = 'Potwierdzenie') {
        return new Promise((resolve) => {
            const modal = document.createElement('div');
            modal.style.cssText = `
                position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                background: rgba(0, 0, 0, 0.5); z-index: 9999;
                display: flex; align-items: center; justify-content: center; border-radius: 8px;
            `;

            modal.innerHTML = `
                <div style="
                    background: white; border-radius: 8px; max-width: 500px; width: 90%;
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
                ">
                    <div style="
                        padding: 20px; border-bottom: 1px solid #dee2e6;
                        display: flex; justify-content: space-between; align-items: center;
                    ">
                        <h5 style="margin: 0; font-weight: 600;">${title}</h5>
                        <button type="button" class="modal-close" style="
                            background: none; border: none; font-size: 24px; cursor: pointer;
                            color: #666; padding: 0; width: 30px; height: 30px;
                        ">×</button>
                    </div>
                    <div style="
                        padding: 20px; font-size: 16px; line-height: 1.5; color: #555;
                        white-space: pre-line;
                    ">${message}</div>
                    <div style="
                        padding: 15px 20px; display: flex; gap: 10px; justify-content: flex-end;
                        background: #f8f9fa; border-top: 1px solid #dee2e6; border-radius: 0 0 8px 8px;
                    ">
                        <button type="button" class="confirm-cancel" style="
                            padding: 8px 20px; border-radius: 6px; font-weight: 500;
                            background: #6c757d; border: 1px solid #6c757d; color: white;
                            cursor: pointer; transition: all 0.2s ease;
                        ">Anuluj</button>
                        <button type="button" class="confirm-ok" style="
                            padding: 8px 20px; border-radius: 6px; font-weight: 500;
                            background: #007bff; border: 1px solid #007bff; color: white;
                            cursor: pointer; transition: all 0.2s ease;
                        ">OK</button>
                    </div>
                </div>
            `;

            const closeModal = (result) => {
                modal.remove();
                resolve(result);
            };

            modal.querySelector('.modal-close').addEventListener('click', () => closeModal(false));
            modal.querySelector('.confirm-cancel').addEventListener('click', () => closeModal(false));
            modal.querySelector('.confirm-ok').addEventListener('click', () => closeModal(true));

            const handleKeydown = (e) => {
                if (e.key === 'Escape') {
                    closeModal(false);
                    document.removeEventListener('keydown', handleKeydown);
                }
            };
            document.addEventListener('keydown', handleKeydown);

            modal.addEventListener('click', (e) => {
                if (e.target === modal) closeModal(false);
            });

            document.body.appendChild(modal);
            setTimeout(() => modal.querySelector('.confirm-ok').focus(), 100);
        });
    }

    /**
     * Obsługa synchronizacji statusów
     */
    async handleSyncStatusesClick() {
        console.log('[ReportsManager] Sync statuses button clicked');

        if (this.isLoading) {
            this.showError('Trwa już ładowanie danych. Proszę czekać...');
            return;
        }

        // Walidacja dat
        if (!this.dateFrom || !this.dateTo) {
            this.showError('Wybierz zakres dat w filtrach przed synchronizacją.');
            return;
        }

        const confirmed = await this.showConfirmDialog(
            `Zsynchronizować zamówienia z Baselinker dla zakresu ${this.dateFrom} - ${this.dateTo}?\n\nTo może potrwać chwilę.`,
            'Potwierdzenie synchronizacji'
        );

        if (!confirmed) {
            return;
        }

        this.isLoading = true;
        this.showLoading('Przygotowywanie synchronizacji...');

        try {
            const response = await fetch('/reports/api/sync-statuses-stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    date_from: this.dateFrom,
                    date_to: this.dateTo
                })
            });

            if (!response.ok) {
                let errorBody = '';
                try { errorBody = await response.text(); } catch (e) {}
                throw new Error(`HTTP ${response.status}: ${response.statusText}. ${errorBody}`);
            }

            // Parsuj SSE stream
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let finalResult = null;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;

                    try {
                        const event = JSON.parse(line.slice(6));
                        console.log('[ReportsManager] SSE sync:', event.type, event.message);

                        if (event.type === 'progress' || event.type === 'saving' || event.type === 'start') {
                            this.showLoading(event.message);
                        } else if (event.type === 'done') {
                            finalResult = event;
                        } else if (event.type === 'error') {
                            throw new Error(event.message);
                        }
                    } catch (e) {
                        if (e.message && !e.message.includes('Unexpected token')) throw e;
                        console.warn('[ReportsManager] SSE parse error:', e);
                    }
                }
            }

            if (finalResult) {
                let message = `Synchronizacja zakończona pomyślnie!\n\n`;
                message += `Pobrano z API: ${finalResult.orders_processed} z ${finalResult.total_orders} zamówień\n`;
                message += `Zaktualizowano: ${finalResult.records_updated} rekordów`;

                this.showMessage(message, 'success');
                this.refreshData();
            } else {
                throw new Error('Stream zakończony bez danych końcowych');
            }

        } catch (error) {
            console.error('[ReportsManager] Sync statuses error:', error);
            this.showError(`Błąd synchronizacji: ${error.message}`);
        } finally {
            this.isLoading = false;
            this.hideLoading();
        }
    }

}

/**
 * Manager dla modala "Analiza województw"
 */
class VoivodeshipsManager {
    constructor() {
        this.modal = null;
        this.tooltip = null;
        this.currentData = {};
        this.colorRanges = [];

        // Lista wszystkich województw
        this.voivodeships = [
            'dolnoslaskie', 'kujawsko-pomorskie', 'lubelskie', 'lubuskie',
            'lodzkie', 'malopolskie', 'mazowieckie', 'opolskie',
            'podkarpackie', 'podlaskie', 'pomorskie', 'slaskie',
            'swietokrzyskie', 'warminsko-mazurskie', 'wielkopolskie',
            'zachodniopomorskie'
        ];

        // Mapowanie nazw województw
        this.voivodeshipNames = {
            'dolnoslaskie': 'Dolnośląskie',
            'kujawsko-pomorskie': 'Kujawsko-Pomorskie',
            'lubelskie': 'Lubelskie',
            'lubuskie': 'Lubuskie',
            'lodzkie': 'Łódzkie',
            'malopolskie': 'Małopolskie',
            'mazowieckie': 'Mazowieckie',
            'opolskie': 'Opolskie',
            'podkarpackie': 'Podkarpackie',
            'podlaskie': 'Podlaskie',
            'pomorskie': 'Pomorskie',
            'slaskie': 'Śląskie',
            'swietokrzyskie': 'Świętokrzyskie',
            'warminsko-mazurskie': 'Warmińsko-Mazurskie',
            'wielkopolskie': 'Wielkopolskie',
            'zachodniopomorskie': 'Zachodniopomorskie'
        };
    }

    /**
     * Inicjalizacja managera
     */
    init() {
        this.cacheElements();
        this.bindEvents();
        this.createTooltip();
        console.log('[VoivodeshipsManager] Zainicjalizowany');
    }

    /**
     * Cache elementów DOM
     */
    cacheElements() {
        this.modal = document.getElementById('voivodeshipsModal');
        this.closeButton = document.getElementById('closeVoivodeshipsModal');
        this.tableBody = document.getElementById('voivodeshipsTableBody');

        // Elementy legendy
        this.legendRanges = {
            1: document.getElementById('legendRange1'),
            2: document.getElementById('legendRange2'),
            3: document.getElementById('legendRange3'),
            4: document.getElementById('legendRange4'),
            5: document.getElementById('legendRange5')
        };
    }

    /**
     * Podpinanie event listenerów
     */
    bindEvents() {
        // Zamknięcie modala
        if (this.closeButton) {
            this.closeButton.addEventListener('click', () => this.closeModal());
        }

        // Zamknięcie przez kliknięcie w overlay
        if (this.modal) {
            this.modal.addEventListener('click', (e) => {
                if (e.target === this.modal) {
                    this.closeModal();
                }
            });
        }

        // Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal && this.modal.style.display !== 'none') {
                this.closeModal();
            }
        });

        // Event listenery dla województw
        this.voivodeships.forEach(voivodeship => {
            const element = document.getElementById(voivodeship);
            if (element) {
                element.addEventListener('mouseenter', (e) => this.onVoivodeshipHover(e, voivodeship));
                element.addEventListener('mousemove', (e) => this.onVoivodeshipMouseMove(e, voivodeship));
                element.addEventListener('mouseleave', () => this.onVoivodeshipLeave());
                element.addEventListener('click', () => this.onVoivodeshipClick(voivodeship));
            }
        });
    }

    /**
     * Tworzenie tooltipa
     */
    createTooltip() {
        this.tooltip = document.createElement('div');
        this.tooltip.className = 'voivodeship-tooltip';
        document.body.appendChild(this.tooltip);
    }

    /**
     * Otwieranie modala
     */
    async openModal() {
        if (!this.modal) return;

        console.log('[VoivodeshipsManager] Otwieranie modala...');

        // Pokaż modal
        this.modal.style.display = 'flex';

        // Dodaj klasę po krótkim opóźnieniu dla animacji
        setTimeout(() => {
            this.modal.classList.add('open');
        }, 10);

        // Zablokuj scroll na body
        document.body.style.overflow = 'hidden';

        // Załaduj dane
        await this.loadData();
    }

    /**
     * Zamykanie modala
     */
    closeModal() {
        if (!this.modal) return;

        console.log('[VoivodeshipsManager] Zamykanie modala...');

        // Usuń klasę open dla animacji
        this.modal.classList.remove('open');

        // Ukryj modal po animacji
        setTimeout(() => {
            this.modal.style.display = 'none';
        }, 300);

        // Odblokuj scroll na body
        document.body.style.overflow = '';
    }

    /**
     * Ładowanie danych z serwera
     */
    async loadData() {
        try {
            console.log('[VoivodeshipsManager] Ładowanie danych...');

            // Pokaż loading indicator (opcjonalnie)
            this.showLoading();

            // Pobierz aktualne filtry dat z głównego modułu (jeśli istnieją)
            const dateFrom = window.reportsManager?.getCurrentDateFrom?.();
            const dateTo = window.reportsManager?.getCurrentDateTo?.();

            // Zbuduj URL z parametrami
            const params = new URLSearchParams();
            if (dateFrom) {
                params.append('date_from', dateFrom);
            }
            if (dateTo) {
                params.append('date_to', dateTo);
            }

            const url = `/reports/api/map-statistics${params.toString() ? '?' + params.toString() : ''}`;

            console.log('[VoivodeshipsManager] Pobieranie z URL:', url);

            // Wywołaj API
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();

            if (result.status !== 'success') {
                throw new Error(result.message || 'Błąd API');
            }

            // Zapisz dane
            this.currentData = result.data;
            this.summaryData = result.summary;

            // Aktualizuj interface
            this.updateMap();
            this.updateTable();
            this.updateLegend();

            // Ukryj loading
            this.hideLoading();

            console.log('[VoivodeshipsManager] Dane załadowane:', {
                data: result.data,
                summary: result.summary
            });

        } catch (error) {
            console.error('[VoivodeshipsManager] Błąd ładowania danych:', error);
            this.hideLoading();
            this.showError(`Błąd podczas ładowania danych mapy: ${error.message}`);

            // Fallback do danych testowych w przypadku błędu
            console.warn('[VoivodeshipsManager] Używam danych testowych jako fallback');
            this.currentData = this.generateMockData();
            this.updateMap();
            this.updateTable();
            this.updateLegend();
        }
    }

    showLoading() {
        // Znajdź sekcję z mapą i tabelą
        const mapContainer = document.querySelector('.voivodeships-map-container');
        const tableContainer = document.querySelector('.voivodeships-table-container');

        if (mapContainer) {
            mapContainer.style.opacity = '0.5';
            mapContainer.style.pointerEvents = 'none';
        }
        if (tableContainer) {
            tableContainer.style.opacity = '0.5';
            tableContainer.style.pointerEvents = 'none';
        }

        // Dodaj spinner (opcjonalnie)
        if (!document.getElementById('voivodeshipsSpinner')) {
            const spinner = document.createElement('div');
            spinner.id = 'voivodeshipsSpinner';
            spinner.innerHTML = `
                <div style="
                    position: absolute;
                    top: 50%;
                    left: 50%;
                    transform: translate(-50%, -50%);
                    background: rgba(255,255,255,0.9);
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                    z-index: 1000;
                    display: flex;
                    align-items: center;
                    gap: 10px;
                ">
                    <div style="
                        width: 20px;
                        height: 20px;
                        border: 2px solid #ff9800;
                        border-top: 2px solid transparent;
                        border-radius: 50%;
                        animation: spin 1s linear infinite;
                    "></div>
                    <span style="color: #333; font-weight: 600;">Ładowanie danych...</span>
                </div>
            `;

            // Dodaj animację CSS jeśli nie istnieje
            if (!document.getElementById('spinnerStyles')) {
                const style = document.createElement('style');
                style.id = 'spinnerStyles';
                style.textContent = `
                    @keyframes spin {
                        0% { transform: rotate(0deg); }
                        100% { transform: rotate(360deg); }
                    }
                `;
                document.head.appendChild(style);
            }

            this.modal.appendChild(spinner);
        }
    }

    hideLoading() {
        const mapContainer = document.querySelector('.voivodeships-map-container');
        const tableContainer = document.querySelector('.voivodeships-table-container');
        const spinner = document.getElementById('voivodeshipsSpinner');

        if (mapContainer) {
            mapContainer.style.opacity = '1';
            mapContainer.style.pointerEvents = 'auto';
        }
        if (tableContainer) {
            tableContainer.style.opacity = '1';
            tableContainer.style.pointerEvents = 'auto';
        }
        if (spinner) {
            spinner.remove();
        }
    }

    /**
     * Generowanie danych testowych
     */
    generateMockData() {
        const mockData = {};

        this.voivodeships.forEach(voivodeship => {
            const productionVolume = Math.random() * 200;
            const readyVolume = Math.random() * 150;
            const productionValue = productionVolume * (800 + Math.random() * 400);
            const readyValue = readyVolume * (800 + Math.random() * 400);

            mockData[voivodeship] = {
                production_volume: productionVolume,
                ready_volume: readyVolume,
                total_volume: productionVolume + readyVolume,
                production_value_net: productionValue,
                ready_value_net: readyValue,
                total_value_net: productionValue + readyValue
            };
        });

        return mockData;
    }

    /**
     * Aktualizacja mapy
     */
    updateMap() {
        // Oblicz przedziały kolorów
        this.calculateColorRanges();

        // Aktualizuj każde województwo
        this.voivodeships.forEach(voivodeship => {
            const data = this.currentData[voivodeship] || {
                total_volume: 0,
                production_volume: 0,
                ready_volume: 0,
                total_value_net: 0
            };

            // Aktualizuj tekst na mapie
            const textElement = document.getElementById(`text-${voivodeship}`);
            if (textElement) {
                textElement.textContent = this.formatVolume(data.total_volume);
            }

            // Aktualizuj kolor
            const pathElement = document.getElementById(voivodeship);
            if (pathElement) {
                const colorLevel = this.getColorLevel(data.total_volume);

                // Usuń poprzednie klasy kolorów
                for (let i = 1; i <= 5; i++) {
                    pathElement.classList.remove(`level-${i}`);
                }

                // Dodaj nową klasę koloru
                pathElement.classList.add(`level-${colorLevel}`);
            }
        });
    }

    /**
     * Obliczanie przedziałów kolorów
     */
    calculateColorRanges() {
        // Znajdź maksymalną wartość
        const volumes = this.voivodeships.map(v =>
            (this.currentData[v] && this.currentData[v].total_volume) || 0
        );

        const maxVolume = Math.max(...volumes);
        const rangeSize = maxVolume / 5;

        this.colorRanges = [];
        for (let i = 0; i < 5; i++) {
            const min = i * rangeSize;
            const max = (i + 1) * rangeSize;
            this.colorRanges.push({ min, max });
        }

        console.log('[VoivodeshipsManager] Przedziały kolorów:', this.colorRanges);
    }

    /**
     * Określenie poziomu koloru dla danej wartości
     */
    getColorLevel(volume) {
        if (!this.colorRanges || this.colorRanges.length === 0) return 1;

        for (let i = 0; i < this.colorRanges.length; i++) {
            const range = this.colorRanges[i];
            if (volume >= range.min && (volume <= range.max || i === this.colorRanges.length - 1)) {
                return i + 1;
            }
        }
        return 1;
    }

    /**
     * Aktualizacja tabeli - DODAJ SORTOWANIE
     */
    updateTable() {
        // Przekonwertuj dane na tablicę z nazwami województw
        const voivodeshipsArray = this.voivodeships.map(voivodeship => {
            const data = this.currentData[voivodeship] || {
                production_volume: 0,
                ready_volume: 0,
                total_volume: 0,
                production_value_net: 0,
                ready_value_net: 0,
                total_value_net: 0
            };

            return {
                id: voivodeship,
                name: this.voivodeshipNames[voivodeship] || voivodeship,
                ...data
            };
        });

        // NOWE: Sortuj według total_volume (malejąco)
        voivodeshipsArray.sort((a, b) => b.total_volume - a.total_volume);

        // Renderuj posortowane wiersze
        voivodeshipsArray.forEach(voivodeshipData => {
            const row = document.querySelector(`tr[data-voivodeship="${voivodeshipData.id}"]`);
            if (!row) return;

            // Aktualizuj komórki
            const productionVolumeCell = row.querySelector('.production-volume');
            const readyVolumeCell = row.querySelector('.ready-volume');
            const totalVolumeCell = row.querySelector('.total-volume');
            const productionValueCell = row.querySelector('.production-value');
            const readyValueCell = row.querySelector('.ready-value');
            const totalValueCell = row.querySelector('.total-value');

            if (productionVolumeCell) {
                productionVolumeCell.textContent = this.formatVolume(voivodeshipData.production_volume);
            }
            if (readyVolumeCell) {
                readyVolumeCell.textContent = this.formatVolume(voivodeshipData.ready_volume);
            }
            if (totalVolumeCell) {
                totalVolumeCell.textContent = this.formatVolume(voivodeshipData.total_volume);
            }
            if (productionValueCell) {
                productionValueCell.textContent = this.formatCurrency(voivodeshipData.production_value_net);
            }
            if (readyValueCell) {
                readyValueCell.textContent = this.formatCurrency(voivodeshipData.ready_value_net);
            }
            if (totalValueCell) {
                totalValueCell.textContent = this.formatCurrency(voivodeshipData.total_value_net);
            }

            // NOWE: Przenies wiersz w tabeli według nowej kolejności
            const tableBody = document.getElementById('voivodeshipsTableBody');
            if (tableBody) {
                tableBody.appendChild(row);
            }
        });
    }

    /**
     * Aktualizacja legendy
     */
    updateLegend() {
        if (!this.colorRanges || this.colorRanges.length === 0) return;

        this.colorRanges.forEach((range, index) => {
            const legendElement = this.legendRanges[index + 1];
            if (legendElement) {
                const min = Math.round(range.min * 10) / 10;
                const max = Math.round(range.max * 10) / 10;

                if (index === this.colorRanges.length - 1) {
                    legendElement.textContent = `${min}+`;
                } else {
                    legendElement.textContent = `${min}-${max}`;
                }
            }
        });
    }

    /**
     * Event handler - hover nad województwem
     */
    onVoivodeshipHover(event, voivodeship) {
        const data = this.currentData[voivodeship] || {
            total_volume: 0,
            production_volume: 0,
            ready_volume: 0
        };

        const name = this.voivodeshipNames[voivodeship] || voivodeship;

        this.tooltip.innerHTML = `
            <strong>${name}</strong><br>
            W produkcji: ${this.formatVolume(data.production_volume)}<br>
            Wyprodukowane: ${this.formatVolume(data.ready_volume)}<br>
            <strong>Łącznie: ${this.formatVolume(data.total_volume)}</strong>
        `;

        this.tooltip.classList.add('show');
        this.onVoivodeshipMouseMove(event, voivodeship);
    }

    /**
     * Event handler - ruch myszy nad województwem
     */
    onVoivodeshipMouseMove(event, voivodeship) {
        if (!this.tooltip.classList.contains('show')) return;

        this.tooltip.style.left = (event.pageX + 10) + 'px';
        this.tooltip.style.top = (event.pageY - 10) + 'px';
    }

    /**
     * Event handler - opuszczenie województwa
     */
    onVoivodeshipLeave() {
        this.tooltip.classList.remove('show');
    }

    /**
     * Event handler - kliknięcie w województwo
     */
    onVoivodeshipClick(voivodeship) {
        console.log('[VoivodeshipsManager] Kliknięto w województwo:', voivodeship);

        // Podświetl wiersz w tabeli
        const row = document.querySelector(`tr[data-voivodeship="${voivodeship}"]`);
        if (row) {
            row.scrollIntoView({ behavior: 'smooth', block: 'center' });
            row.style.backgroundColor = '#fff3e0';

            setTimeout(() => {
                row.style.backgroundColor = '';
            }, 2000);
        }
    }

    /**
     * Formatowanie objętości
     */
    formatVolume(volume) {
        if (volume === null || volume === undefined) return '0.0000 m³';
        return parseFloat(volume).toFixed(4) + ' m³';
    }

    /**
     * Formatowanie waluty
     */
    formatCurrency(value) {
        if (value === null || value === undefined) return '0.00 PLN';
        return parseFloat(value).toLocaleString('pl-PL', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }) + ' PLN';
    }

    /**
     * Pokazanie błędu
     */
    showError(message) {
        // Utwórz lepszy komunikat błędu
        const errorDiv = document.createElement('div');
        errorDiv.className = 'voivodeships-error';
        errorDiv.innerHTML = `
        <div style="
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            border-left: 4px solid #f39c12;
            padding: 15px 20px;
            margin: 20px;
            border-radius: 8px;
            color: #856404;
        ">
            <strong>⚠️ Błąd:</strong> ${message}
            <button onclick="this.parentElement.parentElement.remove()" style="
                float: right;
                background: none;
                border: none;
                font-size: 18px;
                cursor: pointer;
                color: #856404;
                padding: 0 5px;
            ">×</button>
        </div>
    `;

        // Wstaw na górę modala
        const modalBody = document.querySelector('.voivodeships-modal-body');
        if (modalBody) {
            modalBody.insertBefore(errorDiv, modalBody.firstChild);

            // Automatycznie usuń po 10 sekundach
            setTimeout(() => {
                if (errorDiv.parentElement) {
                    errorDiv.remove();
                }
            }, 10000);
        }
    }
}

function openVoivodeshipsModal() {
    if (window.voivodeshipsManager) {
        window.voivodeshipsManager.openModal();
    } else {
        console.error('VoivodeshipsManager nie jest zainicjalizowany');
    }
}

// Export dla global scope
window.ReportsManager = ReportsManager;


/**
 * Sprawdza czy wartość jest prawidłowym numerem zamówienia Baselinker
 * @param {*} value - Wartość do sprawdzenia
 * @returns {boolean} - true jeśli to prawidłowy numer
 */
function isValidBaselinkerOrderNumber(value) {
    // Sprawdź czy wartość istnieje i nie jest null/undefined
    if (!value) {
        return false;
    }

    // Konwertuj na string i usuń białe znaki
    const stringValue = String(value).trim();

    // Sprawdź czy to tylko cyfry (może być z zerem na początku)
    const isNumeric = /^\d+$/.test(stringValue);

    // Sprawdź czy nie jest pustym stringiem
    const isNotEmpty = stringValue.length > 0;

    // Sprawdź czy po konwersji na liczbę to nadal sensowna wartość
    const numericValue = parseInt(stringValue, 10);
    const isValidNumber = !isNaN(numericValue) && numericValue > 0;

    return isNumeric && isNotEmpty && isValidNumber;
}

function testBaselinkerValidation() {
    const testCases = [
        // Prawidłowe wartości
        { input: 123456, expected: true, description: "Liczba całkowita" },
        { input: "123456", expected: true, description: "String z cyframi" },
        { input: "000123", expected: true, description: "Z zerem na początku" },
        { input: "  123456  ", expected: true, description: "Z białymi znakami" },

        // Nieprawidłowe wartości
        { input: null, expected: false, description: "null" },
        { input: undefined, expected: false, description: "undefined" },
        { input: "", expected: false, description: "Pusty string" },
        { input: "   ", expected: false, description: "Same białe znaki" },
        { input: "abc", expected: false, description: "Tekst" },
        { input: "123abc", expected: false, description: "Cyfry z tekstem" },
        { input: "abc123", expected: false, description: "Tekst z cyframi" },
        { input: "12.34", expected: false, description: "Liczba dziesiętna" },
        { input: "-123", expected: false, description: "Liczba ujemna" },
        { input: "0", expected: false, description: "Zero" },
        { input: 0, expected: false, description: "Liczba zero" },
        { input: [], expected: false, description: "Pusta tablica" },
        { input: {}, expected: false, description: "Pusty obiekt" }
    ];

    console.log("🧪 TESTY WALIDACJI NUMERU BASELINKER:");
    console.log("=====================================");

    let passed = 0;
    let failed = 0;

    testCases.forEach((testCase, index) => {
        const result = isValidBaselinkerOrderNumber(testCase.input);
        const status = result === testCase.expected ? "✅ PASS" : "❌ FAIL";

        console.log(`${index + 1}. ${status} | ${testCase.description}`);
        console.log(`   Input: ${JSON.stringify(testCase.input)} → Output: ${result} (Expected: ${testCase.expected})`);

        if (result === testCase.expected) {
            passed++;
        } else {
            failed++;
            console.error(`   ❌ Test failed for: ${testCase.description}`);
        }
    });

    console.log("=====================================");
    console.log(`📊 WYNIKI: ${passed} przeszło, ${failed} nie przeszło`);

    if (failed === 0) {
        console.log("🎉 Wszystkie testy przeszły pomyślnie!");
    } else {
        console.error(`⚠️ ${failed} testów nie przeszło. Sprawdź implementację.`);
    }

    return { passed, failed, total: testCases.length };
}