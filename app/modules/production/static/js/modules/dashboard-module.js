/**
 * dashboard-module.js
 * ========================================================================
 * 
 * Odpowiedzialności:
 * - Ładowanie i renderowanie dashboard content
 * - Zarządzanie widgetami dashboard
 * - Obsługa systemu wykresów (dla adminów)
 * - Refresh management dla dashboard
 * - System health monitoring
 * 
 * Autor: Konrad Kmiecik
 * Wersja: 1.0 - Wyciągnięcie z production-dashboard.js
 * Data: 2025-01-15
 */

class DashboardModule {
    constructor(shared, config) {
        this.shared = shared;
        this.config = config;
        this.isLoaded = false;

        this.templateLoaded = false;  // Czy template HTML został załadowany
        this.dataRefresh = null;      // Instance DataRefreshService - inicjalizowane w load()

        this.autoRefreshInterval = null;
        this.productionStatusInterval = null;
        this.chartInstance = null;
        this.systemErrorsModalInstance = null;
        this.systemErrorsModalElement = null;
        this.systemErrorsHiddenListenerAttached = false;

        // Bound handlers
        this.onManualSyncClick = this.handleManualSync.bind(this);
        this.onShowErrorsClick = this.showSystemErrorsModal.bind(this);
        this.onClearErrorsClick = this.clearSystemErrors.bind(this);
        this.onClearAllErrorsClick = this.clearAllSystemErrors.bind(this);
        this.onSystemErrorsModalHidden = this.resetSystemErrorsModal.bind(this);
        this.onSystemErrorsModalCloseClick = this.handleSystemErrorsModalClose.bind(this);
        this.onRefreshSystemClick = this.handleRefreshSystem.bind(this);

        this.autoRefreshTimer = null; // Timer pokazujący pozostały czas do auto-refresh
        this.autoRefreshCountdown = 60; // 60 sekund (1 minuta)
        this.refreshDuration = 0; // Czas trwania ostatniego odświeżenia

        // State
        this.state = {
            lastRefresh: null,
            widgetStates: {},
            chartData: null,
            isRefreshing: false,
            lastManualRefresh: null
        };

        // Components registry
        this.components = {
            stationsWidget: null,
            todayTotalsWidget: null,
            alertsWidget: null,
            systemHealthWidget: null,
            performanceChart: null
        };
    }

    // ========================================================================
    // LIFECYCLE METHODS
    // ========================================================================

    async load() {
        console.log('[Dashboard Module] Loading dashboard...');

        // Inicjalizuj DataRefreshService jeśli jeszcze nie ma
        if (!this.dataRefresh) {
            this.dataRefresh = new DataRefreshService(this.shared.apiClient);
            console.log('[Dashboard Module] DataRefreshService initialized');
        }

        if (!this.templateLoaded) {
            // PIERWSZY RAZ - ładuj template HTML + dane
            console.log('[Dashboard Module] First load - loading template...');
            await this.loadDashboardTemplate();
            this.templateLoaded = true;
        } else {
            // KOLEJNE RAZY - tylko odśwież dane
            console.log('[Dashboard Module] Template already loaded - refreshing data only...');
            await this.refreshDataOnly();
        }

        this.isLoaded = true;
        this.state.lastRefresh = new Date();
        console.log('[Dashboard Module] Dashboard loaded successfully');
    }

    async loadDashboardTemplate() {
        console.log('[Dashboard Module] Loading HTML template for first time...');

        try {
            // Załaduj template z parametrem initial_load=true
            const response = await this.shared.apiClient.getDashboardTabContent(true);

            if (!response.success) {
                throw new Error(response.error || 'Failed to load dashboard template');
            }

            // Update DOM with template HTML
            const wrapper = document.getElementById('dashboard-tab-wrapper');
            if (wrapper) {
                wrapper.innerHTML = response.html;
                wrapper.style.display = 'block';

                // Reset modal references because DOM has been replaced
                this.systemErrorsModalInstance = null;
                this.systemErrorsModalElement = null;
                this.systemErrorsHiddenListenerAttached = false;
            }

            // Inicjalizacja komponentów (tylko raz przy ładowaniu template)
            this.initializeWidgets();
            this.setupEventListeners();
            this.setupDataRefreshHandlers(); // NOWA METODA - będzie w kroku 3.5

            // Setup auto-refresh
            this.setupAutoRefresh();

            // Initialize charts for admins
            if (this.config.user?.isAdmin) {
                await this.initializePerformanceChart();
            }

            // Initialize production status
            await this.initializeProductionStatus();

            // Załaduj początkowe dane jeśli są dostępne
            if (response.initial_data) {
                console.log('[Dashboard Module] Loading initial data from template response');
                await this.updateWidgetsWithInitialData(response.initial_data); // NOWA METODA - będzie w kroku 3.6
            }

            console.log('[Dashboard Module] Template loaded and initialized successfully');

        } catch (error) {
            console.error('[Dashboard Module] Failed to load dashboard template:', error);
            throw error;
        }
    }

    async refreshDataOnly() {
        console.log('[Dashboard Module] Refreshing data without template reload...');

        try {
            // Użyj DataRefreshService do odświeżenia wszystkich widgetów
            await this.dataRefresh.refreshAllWidgets();

            this.state.lastRefresh = new Date();

            // Emit event o odświeżeniu danych (bez przeładowania template)
            this.shared.eventBus.emit('dashboard:data-refreshed', {
                timestamp: this.state.lastRefresh
            });

            console.log('[Dashboard Module] Data refresh completed successfully');

        } catch (error) {
            console.error('[Dashboard Module] Data refresh failed:', error);
            this.shared.toastSystem.show(
                'Błąd odświeżania danych: ' + error.message,
                'warning'
            );
            throw error;
        }
    }

    setupDataRefreshHandlers() {
        console.log('[Dashboard Module] Setting up data refresh handlers...');

        // Handler dla widgetu stacji
        this.dataRefresh.registerRefreshHandler('stations', async () => {
            const data = await this.shared.apiClient.getDashboardData();
            if (data.success) {
                this.updateStationsWidget(data.data.stations);
            }
        });

        // Handler dla statystyk/totals
        this.dataRefresh.registerRefreshHandler('totals', async () => {
            const data = await this.shared.apiClient.getDashboardStatsData();
            if (data.success) {
                this.updateTotalsWidget(data.data);
            }
        });

        // Handler dla alertów
        this.dataRefresh.registerRefreshHandler('alerts', async () => {
            const data = await this.shared.apiClient.getDashboardData();
            if (data.success) {
                this.updateAlertsWidget(data.data.alerts);
            }
        });

        // Handler dla statusu produkcji
        this.dataRefresh.registerRefreshHandler('production-status', async () => {
            const data = await this.shared.apiClient.getProductionStatusData();
            if (data.success) {
                this.updateProductionStatusWidget(data.data);
            }
        });

        console.log(`[Dashboard Module] Registered ${this.dataRefresh.getRegisteredWidgets().length} refresh handlers`);

        this.setupModalRefreshListener();
    }

    setupModalRefreshListener() {
        console.log('[Dashboard Module] Setting up modal refresh listener...');
        
        // Nasłuchuj na event zamknięcia modala baselinker
        if (this.shared.eventBus) {
            this.shared.eventBus.on('modal:baselinker:closed', async () => {
                console.log('[Dashboard Module] Baselinker modal closed - refreshing data...');
                try {
                    // Wyczyść cache żeby mieć pewność że pobierzemy świeże dane
                    this.shared.apiClient.clearCache();
                    
                    // Odśwież wszystkie dane
                    await this.refreshDataOnly();
                    
                    console.log('[Dashboard Module] Data refreshed after modal close');
                    
                    // Pokaż toast
                    this.shared.toastSystem.show(
                        'Dane zaktualizowane po synchronizacji',
                        'info'
                    );
                    
                } catch (error) {
                    console.error('[Dashboard Module] Failed to refresh after modal close:', error);
                }
            });
        }
        
        // Alternatywnie - nasłuchuj bezpośrednio na DOM event
        const modal = document.getElementById('baselinkerSyncModal');
        if (modal) {
            modal.addEventListener('hidden.bs.modal', async () => {
                console.log('[Dashboard Module] Modal hidden event - refreshing data...');
                try {
                    this.shared.apiClient.clearCache();
                    await this.refreshDataOnly();
                    console.log('[Dashboard Module] Data refreshed via DOM event');
                } catch (error) {
                    console.error('[Dashboard Module] DOM event refresh failed:', error);
                }
            });
            
            console.log('[Dashboard Module] Modal DOM listener attached');
        }
    }

    // ========================================================================
    // WIDGET UPDATE METHODS - NOWE
    // ========================================================================

    async updateWidgetsWithInitialData(initialData) {
        console.log('[Dashboard Module] Updating widgets with initial data...');

        try {
            if (initialData.stations) {
                // Konwertuj format ze słownika na array dla updateStationsWidget
                const stationsArray = Object.keys(initialData.stations).map(key => ({
                    code: key,
                    name: key === 'cutting' ? 'Wycinanie' : key === 'assembly' ? 'Składanie' : 'Pakowanie',
                    active_orders: initialData.stations[key].pending_count,
                    status: initialData.stations[key].status,
                    status_class: initialData.stations[key].status_class
                }));
                this.updateStationsWidget(stationsArray);
            }

            if (initialData.today_totals) {
                this.updateTotalsWidget({
                    total_orders: initialData.today_totals.total_orders || 0,
                    completed_today: initialData.today_totals.completed_orders || 0,
                    pending_priority: 0, // Będzie aktualizowane przez osobny handler
                    errors_24h: initialData.system_health?.errors_24h || 0
                });
            }

            if (initialData.deadline_alerts) {
                this.updateAlertsWidget(initialData.deadline_alerts);
            }

        } catch (error) {
            console.error('[Dashboard Module] Error updating widgets with initial data:', error);
        }
    }

    updateTotalsWidget(statsData) {
        console.log('[Dashboard Module] Updating totals widget...', statsData);

        // Aktualizuj liczby z animacją
        this.updateNumberWithAnimation(
            document.getElementById('today-completed'),
            statsData.completed_today || 0
        );
    }

    updateAlertsWidget(alertsData) {
        console.log('[Dashboard Module] Updating alerts widget...', alertsData);

        const alertsList = document.getElementById('alerts-list');
        const alertsCount = document.getElementById('alerts-count');

        // Aktualizuj licznik alertów
        if (alertsCount) {
            alertsCount.textContent = alertsData ? alertsData.length : 0;
        }

        if (!alertsData || alertsData.length === 0) {
            if (alertsList) {
                alertsList.innerHTML = `
                    <div class="no-alerts-state" id="alerts-empty">
                        <div class="no-alerts-icon">✅</div>
                        <p class="no-alerts-text">Brak pilnych alertów</p>
                        <small class="text-muted">Wszystkie produkty zgodne z terminem</small>
                    </div>
                `;
            }
        } else {
            if (alertsList) {
                // NOWA LOGIKA - obsługuje format z API dashboard-data
                alertsList.innerHTML = alertsData.map(alert => {
                    // Format z API: {type, icon, message, time}
                    const alertType = alert.type || 'info';
                    const alertIcon = this.getAlertIcon(alert.icon);
                    const message = alert.message || 'Brak opisu';
                    const time = alert.time || 'nieznany czas';
                    
                    return `
                        <div class="alert-item alert-${alertType}">
                            <div class="alert-icon">${alertIcon}</div>
                            <div class="alert-content">
                                <div class="alert-header">
                                    <span class="alert-message">${message}</span>
                                </div>
                                <div class="alert-details">
                                    <span class="alert-time">${time}</span>
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');
            }
        }
    }

    // DODAJ NOWĄ FUNKCJĘ POMOCNICZĄ:
    getAlertIcon(iconName) {
        const iconMap = {
            'clock': '⏰',
            'warning': '⚠️',
            'error': '🚨',
            'info': 'ℹ️',
            'exclamation-triangle': '⚠️'
        };
        
        return iconMap[iconName] || '⚠️';
    }

    updateProductionStatusWidget(statusData) {
        console.log('[Dashboard Module] Updating production status widget...', statusData);

        // Aktualizuj wskaźnik statusu w header
        const indicator = document.getElementById('status-indicator');
        const text = document.getElementById('status-text');

        if (indicator) {
            indicator.className = `status-indicator ${statusData.indicator_class || 'status-idle'}`;
        }

        if (text) {
            text.textContent = statusData.status_text || 'Status nieznany';
        }
    }

    async unload() {
        console.log('[Dashboard Module] Unloading dashboard...');

        // Użyj nowej metody destroy() zamiast duplikowania kodu
        this.destroy();

        console.log('[Dashboard Module] Dashboard unloaded');
    }

    async refresh() {
        console.log('[Dashboard Module] Refresh called...');

        // NOWA LOGIKA - sprawdź czy template jest załadowany
        if (!this.templateLoaded) {
            console.log('[Dashboard Module] Template not loaded yet - doing full load');
            return this.load(); // Pierwsze ładowanie
        } else {
            console.log('[Dashboard Module] Template already loaded - refreshing data only');
            return this.refreshDataOnly(); // Tylko dane
        }
    }

    // ========================================================================
    // CONTENT LOADING
    // ========================================================================

    async loadDashboardContent() {
        const response = await this.shared.apiClient.getDashboardTabContent();

        if (!response.success) {
            throw new Error(response.error || 'Failed to load dashboard content');
        }

        // Update DOM with new content
        const wrapper = document.getElementById('dashboard-tab-wrapper');
        if (wrapper) {
            wrapper.innerHTML = response.html;
            wrapper.style.display = 'block';

            // Reset modal references because DOM has been replaced
            this.systemErrorsModalInstance = null;
            this.systemErrorsModalElement = null;
            this.systemErrorsHiddenListenerAttached = false;
        }

        // Store stats for widgets
        this.state.stats = response.stats;

        return response;
    }

    // ========================================================================
    // WIDGET MANAGEMENT
    // ========================================================================

    async initializeProductionStatus() {
        console.log('[Dashboard Module] Initializing production status...');
        
        try {
            await this.updateProductionStatus();
        } catch (error) {
            console.error('[Dashboard Module] Failed to initialize production status:', error);
            this.showProductionStatusError('Błąd ładowania statusu systemu');
        }
    }

    initializeWidgets() {
        console.log('[Dashboard Module] Initializing widgets...');

        // Initialize each widget
        this.components.stationsWidget = this.initStationsWidget();
        this.components.todayTotalsWidget = this.initTodayTotalsWidget();
        this.components.alertsWidget = this.initAlertsWidget();
        this.components.systemHealthWidget = this.initSystemHealthWidget();

        // POPRAWKA: Użyj setTimeout żeby DOM był w pełni gotowy
        setTimeout(() => {
            console.log('[Dashboard Module] DOM ready, updating widgets...');
            this.updateWidgets();

            // DODAJ: Wymuszenie aktualizacji daty jeśli nie została zaktualizowana
            const dateElement = document.getElementById('today-date');
            if (dateElement && !dateElement.classList.contains('date-updated')) {
                console.log('[Dashboard Module] Forcing today-date update...');
                this.updateTodayDate();
            }
        }, 100); // 100ms opóźnienia
    }

    initStationsWidget() {
        const stationsGrid = document.querySelector('.stations-grid');
        if (!stationsGrid) return null;

        // Initialize station cards click handlers
        const stationCards = stationsGrid.querySelectorAll('.station-card');
        stationCards.forEach(card => {
            card.addEventListener('click', () => {
                const stationUrl = card.getAttribute('data-station-url');
                if (stationUrl) {
                    window.location.href = stationUrl;
                }
            });
        });

        return {
            element: stationsGrid,
            update: this.updateStationsWidget.bind(this),
            destroy: () => {
                // Cleanup if needed
            }
        };
    }

    initTodayTotalsWidget() {
        const todayWidget = document.querySelector('.widget.today-summary');
        if (!todayWidget) return null;

        return {
            element: todayWidget,
            update: this.updateTodayTotalsWidget.bind(this),
            destroy: () => {
                // Cleanup if needed
            }
        };
    }

    initAlertsWidget() {
        const alertsWidget = document.querySelector('.widget.deadline-alerts');
        if (!alertsWidget) return null;

        return {
            element: alertsWidget,
            update: this.updateAlertsWidget.bind(this),
            destroy: () => {
                // Cleanup if needed
            }
        };
    }

    initSystemHealthWidget() {
        const healthWidget = document.querySelector('.widget.system-health');
        if (!healthWidget) return null;

        return {
            element: healthWidget,
            update: this.updateSystemHealthWidget.bind(this),
            destroy: () => {
                // Cleanup if needed
            }
        };
    }

    updateWidgets() {
        if (!this.state.stats) return;

        console.log('[Dashboard Module] Updating widgets with fresh data...');

        // Update each widget with current stats
        if (this.components.stationsWidget) {
            this.components.stationsWidget.update(this.state.stats.stations);
        }

        if (this.components.todayTotalsWidget) {
            this.components.todayTotalsWidget.update(this.state.stats.today_totals);
        }

        if (this.components.alertsWidget) {
            this.components.alertsWidget.update(this.state.stats.deadline_alerts);
        }

        if (this.components.systemHealthWidget) {
            this.components.systemHealthWidget.update(this.state.stats.system_health);
        }

        // POPRAWKA: Dodaj aktualizację elementów które się nie odświeżają
        this.updateTodayDate();
        this.updateLastRefreshTime('stations-updated');
    }

    async updateProductionStatus() {
        console.log('[Dashboard Module] Starting production status update...');
        
        try {
            console.log('[Dashboard Module] Calling getSystemHealth API...');
            const response = await this.shared.apiClient.getSystemHealth();
            
            console.log('[Dashboard Module] Raw API response:', response);
            
            if (response.success) {
                console.log('[Dashboard Module] API success, health data:', response.health);
                
                this.renderProductionStatus(response.health);
            } else {
                throw new Error(response.error || 'Błąd pobierania statusu systemu');
            }
            
        } catch (error) {
            console.error('[Dashboard Module] Production status update failed:', error);
            this.showProductionStatusError('Błąd połączenia z systemem');
        }
    }

    // ========================================================================
    // WIDGET UPDATE METHODS - Przeniesione z production-dashboard.js
    // ========================================================================

    updateStationsWidget(stationsData) {
        console.log('[Dashboard Module] Updating stations widget...', stationsData);

        stationsData.forEach(station => {
            // Aktualizuj liczby oczekujących dla każdej stacji
            const pendingElement = document.getElementById(`${station.code}-pending`);
            if (pendingElement) {
                console.log(`[Dashboard Module] Updating ${station.code}-pending to ${station.active_orders}`);
                this.updateNumberWithAnimation(pendingElement, station.active_orders);
            } else {
                console.warn(`[Dashboard Module] Element ${station.code}-pending not found`);
            }

            // Aktualizuj status dot
            const statusElement = document.getElementById(`${station.code}-status`);
            if (statusElement) {
                const statusDot = statusElement.querySelector('.status-dot');
                if (statusDot) {
                    // Usuń poprzednie klasy statusu
                    statusDot.classList.remove('active', 'warning', 'danger');

                    // Dodaj nową klasę na podstawie liczby zamówień
                    if (station.active_orders > 15) {
                        statusDot.classList.add('danger');
                    } else if (station.active_orders > 5) {
                        statusDot.classList.add('warning');
                    } else if (station.active_orders > 0) {
                        statusDot.classList.add('active');
                    }
                    
                    console.log(`[Dashboard Module] Updated status for ${station.code}: ${station.active_orders} orders`);
                }
            } else {
                console.warn(`[Dashboard Module] Status element ${station.code}-status not found`);
            }
        });

        // Aktualizuj timestamp ostatniej aktualizacji stacji
        const stationsUpdatedElement = document.getElementById('stations-updated');
        if (stationsUpdatedElement) {
            const now = new Date();
            const timeString = now.toLocaleTimeString('pl-PL', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
            stationsUpdatedElement.textContent = `Aktualizacja: ${timeString}`;
        }
    }

    updateSingleStationCard(stationType, stationData) {
        if (!stationData) return;

        // Update pending count
        const pendingElement = document.getElementById(`${stationType}-pending`);
        if (pendingElement) {
            this.updateNumberWithAnimation(pendingElement, stationData.pending_count || 0);
        }

        // Update volume
        const volumeElement = document.getElementById(`${stationType}-today-m3`);
        if (volumeElement) {
            const volume = this.cleanBackendValue(stationData.today_m3);
            this.updateNumberWithAnimation(volumeElement, volume.toFixed(4));
        }

        // Update status indicator
        const statusElement = document.getElementById(`${stationType}-status`);
        if (statusElement) {
            this.updateStationStatus(statusElement, stationData);
        }
    }

    updateTodayTotalsWidget(totalsData) {
        if (!totalsData) return;

        this.updateTodayValue('today-completed', totalsData.completed_orders || 0, 'liczba');
        this.updateTodayValue('today-total-m3', totalsData.total_m3 || 0, 'm3');
        this.updateTodayValue('today-avg-deadline', totalsData.avg_deadline_distance || 0, 'dni');
    }

    updateAlertsWidget(alertsData) {
        const alertsCount = document.getElementById('alerts-count');
        const alertsList = document.getElementById('alerts-list');

        if (alertsCount) {
            alertsCount.textContent = alertsData ? alertsData.length : 0;
        }

        if (alertsList) {
            if (!alertsData || alertsData.length === 0) {
                alertsList.innerHTML = this.getNoAlertsHTML();
            } else {
                alertsList.innerHTML = alertsData.map(alert =>
                    this.createAlertHTML(alert)
                ).join('');
            }
        }
    }

    updateSystemHealthWidget(healthData) {
        if (!healthData) return;

        this.updateHealthIndicator(healthData);
        this.updateLastSync(healthData.last_sync, healthData.sync_status);
        this.updateDatabaseStatus(healthData.database_status);
        this.updateSystemErrors(healthData.errors_24h);
    }

    // ============================================================================
    // PERFORMANCE CHART - For Admins
    // ============================================================================

    async initializePerformanceChart() {
        if (!this.config.user?.isAdmin || typeof Chart === 'undefined') {
            console.log('[Dashboard Module] Performance chart not available');
            return;
        }

        console.log('[Dashboard Module] Initializing performance chart...');

        try {
            const chartContainer = document.querySelector('.widget.performance-chart');
            if (!chartContainer) {
                console.warn('[Dashboard Module] Chart container not found');
                return;
            }

            // Pokaż loader od razu na początku inicjalizacji
            this.toggleChartLoader(true);

            // Initialize chart controls (już nie generujemy HTML, bo jest w template)
            this.initChartControls(chartContainer);

            // Load chart data
            await this.loadChartData(7); // Default 7 days

        } catch (error) {
            console.error('[Dashboard Module] Chart initialization failed:', error);
            this.toggleChartLoader(false);
            this.showChartError('Błąd inicjalizacji wykresu: ' + error.message);
        }
    }

    initChartControls(container) {
        // Nie generujemy HTML - kontrolki są już w template
        // Tylko podpinamy event listenery

        const periodSelect = document.getElementById('chart-period-select');
        const refreshBtn = document.getElementById('chart-refresh-btn');

        if (periodSelect) {
            periodSelect.addEventListener('change', (e) => {
                const period = parseInt(e.target.value);
                console.log('[Dashboard Module] Period changed to:', period);
                this.loadChartData(period);
            });
        }

        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                const period = parseInt(periodSelect?.value || 7);
                console.log('[Dashboard Module] Manual chart refresh, period:', period);

                // Animacja rotacji ikony refresh
                const icon = refreshBtn.querySelector('i');
                if (icon) {
                    icon.style.animation = 'spin 1s linear';
                    setTimeout(() => {
                        icon.style.animation = '';
                    }, 1000);
                }

                this.loadChartData(period);
            });
        }
    }

    async loadChartData(period) {
        this.toggleChartLoader(true);

        try {
            const response = await this.shared.apiClient.request(`/chart-data?period=${period}`, {
                skipCache: true
            });

            if (response.success) {
                // ZMIANA: przekazujemy period jako trzeci parametr
                this.createOrUpdateChart(response.chart_data, response.summary, period);
                this.state.chartData = response;
            } else {
                throw new Error(response.error || 'Błąd ładowania danych wykresu');
            }

        } catch (error) {
            console.error('[Dashboard Module] Chart data loading failed:', error);
            this.showChartError('Błąd ładowania danych wykresu');
        } finally {
            this.toggleChartLoader(false);
        }
    }

    createOrUpdateChart(chartData, summary, period) {
        const canvas = document.getElementById('performance-chart-canvas');
        if (!canvas) {
            console.warn('[Dashboard Module] Canvas element not found for chart');
            return;
        }

        console.log('[Dashboard Module] Creating/updating chart for period:', period, 'days');

        // Bardziej agresywne niszczenie istniejącego wykresu
        if (this.chartInstance) {
            console.log('[Dashboard Module] Destroying existing chart instance');
            try {
                this.chartInstance.destroy();
            } catch (destroyError) {
                console.warn('[Dashboard Module] Error destroying chart:', destroyError);
            }
            this.chartInstance = null;
        }

        // Sprawdź czy canvas nie ma już przypisanego wykresu Chart.js
        if (canvas.chart) {
            console.log('[Dashboard Module] Found existing chart on canvas, destroying...');
            try {
                canvas.chart.destroy();
            } catch (canvasError) {
                console.warn('[Dashboard Module] Error destroying canvas chart:', canvasError);
            }
            delete canvas.chart;
        }

        // Wyczyść canvas context jako dodatkowe zabezpieczenie
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        try {
            // Określ tytuł i etykietę osi X na podstawie okresu
            let chartTitle = 'Wydajność produkcji';
            let xAxisLabel = 'Data';

            if (period <= 30) {
                chartTitle += ` (${period} dni)`;
                xAxisLabel = 'Dzień';
            } else if (period === 90) {
                chartTitle += ' (3 miesiące - agregacja tygodniowa)';
                xAxisLabel = 'Tydzień';
            } else if (period === 180) {
                chartTitle += ' (6 miesięcy - agregacja miesięczna)';
                xAxisLabel = 'Miesiąc';
            } else if (period === 365) {
                chartTitle += ' (12 miesięcy - agregacja miesięczna)';
                xAxisLabel = 'Miesiąc';
            }

            // Create new chart
            this.chartInstance = new Chart(ctx, {
                type: 'line',
                data: chartData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        intersect: false
                    },
                    plugins: {
                        title: {
                            display: true,
                            text: chartTitle,
                            font: { size: 14, weight: 'bold' },
                            padding: { top: 10, bottom: 20 }
                        },
                        legend: {
                            display: true,
                            position: 'top',
                            labels: {
                                usePointStyle: true,
                                padding: 15,
                                font: { size: 12 }
                            }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0, 0, 0, 0.8)',
                            padding: 12,
                            titleFont: { size: 13, weight: 'bold' },
                            bodyFont: { size: 12 },
                            callbacks: {
                                label: function (context) {
                                    let label = context.dataset.label || '';
                                    if (label) {
                                        label += ': ';
                                    }
                                    label += context.parsed.y.toFixed(2) + ' m³';
                                    return label;
                                },
                                footer: function (tooltipItems) {
                                    let sum = 0;
                                    tooltipItems.forEach(item => {
                                        sum += item.parsed.y;
                                    });
                                    return 'Suma: ' + sum.toFixed(2) + ' m³';
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            title: {
                                display: true,
                                text: xAxisLabel,
                                font: { size: 12, weight: 'bold' }
                            },
                            ticks: {
                                maxRotation: 45,
                                minRotation: 0,
                                autoSkip: true,
                                maxTicksLimit: period > 90 ? 12 : 15
                            },
                            grid: {
                                display: true,
                                drawBorder: true
                            }
                        },
                        y: {
                            title: {
                                display: true,
                                text: 'Objętość (m³)',
                                font: { size: 12, weight: 'bold' }
                            },
                            beginAtZero: true,
                            ticks: {
                                callback: function (value) {
                                    return value.toFixed(1) + ' m³';
                                }
                            },
                            grid: {
                                display: true,
                                drawBorder: true
                            }
                        }
                    }
                }
            });

            console.log('[Dashboard Module] Chart created successfully with ID:', this.chartInstance.id);

        } catch (chartError) {
            console.error('[Dashboard Module] Failed to create chart:', chartError);
            this.showChartError('Błąd tworzenia wykresu: ' + chartError.message);
        }
    }

    showChartError(message) {
        const chartContainer = document.querySelector('.widget.performance-chart .widget-content');
        if (chartContainer) {
            chartContainer.innerHTML = `
            <div class="alert alert-danger">
                <strong>Błąd wykresu:</strong> ${message}
            </div>
        `;
        }
    }

    toggleChartLoader(show) {
        const loader = document.querySelector('.widget.performance-chart .chart-loader');
        const canvas = document.getElementById('performance-chart-canvas');

        console.log('[Dashboard Module] Toggle chart loader:', show);

        if (loader) {
            if (show) {
                loader.style.display = 'flex';
                loader.classList.add('is-visible');
                loader.setAttribute('aria-hidden', 'false');
                console.log('[Dashboard Module] Chart loader shown');
            } else {
                loader.style.display = 'none';
                loader.classList.remove('is-visible');
                loader.setAttribute('aria-hidden', 'true');
                console.log('[Dashboard Module] Chart loader hidden');
            }
        } else {
            console.warn('[Dashboard Module] Chart loader element not found');
        }

        if (canvas) {
            canvas.style.opacity = show ? '0.35' : '1';
            canvas.setAttribute('aria-busy', show ? 'true' : 'false');
        }
    }

    // ========================================================================
    // EVENT LISTENERS
    // ========================================================================

    setupEventListeners() {
        // Ensure previous listeners are removed before attaching new ones
        this.removeEventListeners();

        // Manual sync button
        const manualSyncBtn = document.getElementById('manual-sync-btn');
        if (manualSyncBtn) {
            manualSyncBtn.addEventListener('click', this.onManualSyncClick);
        }

        // System errors modal buttons
        const showErrorsBtn = document.getElementById('show-errors-btn');
        if (showErrorsBtn) {
            showErrorsBtn.addEventListener('click', this.onShowErrorsClick);
        }

        const clearErrorsBtn = document.getElementById('clear-errors-btn');
        if (clearErrorsBtn) {
            clearErrorsBtn.addEventListener('click', this.onClearErrorsClick);
        }

        const clearAllErrorsBtn = document.getElementById('clear-all-errors-btn');
        if (clearAllErrorsBtn) {
            clearAllErrorsBtn.addEventListener('click', this.onClearAllErrorsClick);
        }

        const refreshSystemBtn = document.getElementById('refresh-system-btn');
        if (refreshSystemBtn) {
            refreshSystemBtn.addEventListener('click', this.onRefreshSystemClick);
            console.log('[Dashboard Module] Refresh system button listener attached');
        } else {
            console.warn('[Dashboard Module] Refresh system button not found');
        }

        const modalElement = document.getElementById('systemErrorsModal');
        if (modalElement) {
            this.systemErrorsModalElement = modalElement;

            const closeButtons = modalElement.querySelectorAll('[data-bs-dismiss="modal"]');

            if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
                modalElement.addEventListener('hidden.bs.modal', this.onSystemErrorsModalHidden);
                this.systemErrorsHiddenListenerAttached = true;

                closeButtons.forEach(button => {
                    button.removeEventListener('click', this.onSystemErrorsModalCloseClick);
                });
            } else {
                closeButtons.forEach(button => {
                    button.addEventListener('click', this.onSystemErrorsModalCloseClick);
                });
            }
        }

        console.log('[Dashboard Module] Event listeners setup complete');
    }

    removeEventListeners() {
        console.log('[Dashboard Module] Removing event listeners...');

        // Manual sync button
        const manualSyncBtn = document.getElementById('manual-sync-btn');
        if (manualSyncBtn) {
            manualSyncBtn.removeEventListener('click', this.onManualSyncClick);
        }

        // System errors modal buttons
        const showErrorsBtn = document.getElementById('show-errors-btn');
        if (showErrorsBtn) {
            showErrorsBtn.removeEventListener('click', this.onShowErrorsClick);
        }

        const clearErrorsBtn = document.getElementById('clear-errors-btn');
        if (clearErrorsBtn) {
            clearErrorsBtn.removeEventListener('click', this.onClearErrorsClick);
        }

        const clearAllErrorsBtn = document.getElementById('clear-all-errors-btn');
        if (clearAllErrorsBtn) {
            clearAllErrorsBtn.removeEventListener('click', this.onClearAllErrorsClick);
        }

        // DODAJ: Refresh system button
        const refreshSystemBtn = document.getElementById('refresh-system-btn');
        if (refreshSystemBtn) {
            refreshSystemBtn.removeEventListener('click', this.onRefreshSystemClick);
            console.log('[Dashboard Module] Refresh system button listener removed');
        }

        // System errors modal
        if (this.systemErrorsModalElement) {
            if (this.systemErrorsHiddenListenerAttached) {
                this.systemErrorsModalElement.removeEventListener('hidden.bs.modal', this.onSystemErrorsModalHidden);
                this.systemErrorsHiddenListenerAttached = false;
            }

            // Usuń listenery z przycisków zamykania
            const closeButtons = this.systemErrorsModalElement.querySelectorAll('[data-bs-dismiss="modal"]');
            closeButtons.forEach(button => {
                button.removeEventListener('click', this.onSystemErrorsModalCloseClick);
            });
        }

        console.log('[Dashboard Module] All event listeners removed');
    }

    // ========================================================================
    // EVENT HANDLERS
    // ========================================================================

    async handleManualSync() {
        console.log('[Dashboard Module] Przekierowanie do modalu synchronizacji');

        // Sprawdź czy modal jest dostępny
        if (typeof window.showBaselinkerSyncModal === 'function') {
            window.showBaselinkerSyncModal();
        } else {
            console.error('[Dashboard Module] Modal synchronizacji nie jest dostępny');
            alert('Modal synchronizacji nie jest dostępny. Odśwież stronę i spróbuj ponownie.');
        }
    }

    async showSystemErrorsModal(event = null) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }

        const modalInstance = this.ensureSystemErrorsModal();

        if (!this.systemErrorsModalElement) {
            this.shared.toastSystem.show('Modal błędów systemu jest niedostępny', 'error');
            return;
        }

        this.resetSystemErrorsModal();
        this.toggleSystemErrorsLoading(true);

        if (modalInstance && typeof modalInstance.show === 'function') {
            modalInstance.show();
        } else {
            this.systemErrorsModalElement.classList.add('show');
            this.systemErrorsModalElement.style.display = 'block';
            this.systemErrorsModalElement.removeAttribute('aria-hidden');
        }

        try {
            const response = await this.shared.apiClient.getSystemErrors();

            if (response.success) {
                this.renderSystemErrors(response.errors || []);
            } else {
                throw new Error(response.error || 'Nie udało się pobrać błędów systemu');
            }

        } catch (error) {
            console.error('[Dashboard Module] Failed to load system errors:', error);
            this.showSystemErrorsError('Nie udało się pobrać błędów systemu. Spróbuj ponownie później.');
            this.shared.toastSystem.show('Nie udało się pobrać błędów systemu', 'error');
        } finally {
            this.toggleSystemErrorsLoading(false);
        }
    }

    async clearSystemErrors(event = null, options = {}) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }

        const { closeModal = false, refreshModal = false } = options;

        try {
            this.shared.loadingManager.show('clear-system-errors', 'Czyszczenie błędów systemu...');

            const response = await this.shared.apiClient.clearSystemErrors();

            if (response.success) {
                const message = response.message || 'Wyczyszczono błędy systemu';
                this.shared.toastSystem.show(message, 'success');

                if (this.state.stats?.system_health) {
                    this.state.stats.system_health.errors_24h = 0;
                    if ('pending_errors' in this.state.stats.system_health) {
                        this.state.stats.system_health.pending_errors = 0;
                    }
                    this.updateSystemHealthWidget(this.state.stats.system_health);
                } else {
                    this.updateSystemErrors(0);
                }

                if (refreshModal) {
                    this.renderSystemErrors([]);
                }

                if (closeModal) {
                    this.closeSystemErrorsModal();
                }

            } else {
                throw new Error(response.error || 'Nie udało się wyczyścić błędów systemu');
            }

        } catch (error) {
            console.error('[Dashboard Module] Clear system errors failed:', error);
            this.shared.toastSystem.show('Błąd podczas czyszczenia błędów: ' + error.message, 'error');
        } finally {
            this.shared.loadingManager.hide('clear-system-errors');
        }
    }

    async clearAllSystemErrors(event = null) {
        await this.clearSystemErrors(event, { refreshModal: true, closeModal: false });
    }

    handleSystemErrorsModalClose(event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }

        this.closeSystemErrorsModal();
    }

    closeSystemErrorsModal() {
        if (this.systemErrorsModalInstance && typeof this.systemErrorsModalInstance.hide === 'function') {
            this.systemErrorsModalInstance.hide();
            return;
        }

        if (this.systemErrorsModalElement) {
            this.systemErrorsModalElement.classList.remove('show');
            this.systemErrorsModalElement.style.display = 'none';
            this.systemErrorsModalElement.setAttribute('aria-hidden', 'true');
        }
    }

    ensureSystemErrorsModal() {
        const modalElement = document.getElementById('systemErrorsModal');

        if (!modalElement) {
            return null;
        }

        if (this.systemErrorsModalElement !== modalElement) {
            if (this.systemErrorsModalElement && this.systemErrorsHiddenListenerAttached) {
                if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
                    this.systemErrorsModalElement.removeEventListener('hidden.bs.modal', this.onSystemErrorsModalHidden);
                }
                this.systemErrorsHiddenListenerAttached = false;
            }

            this.systemErrorsModalElement = modalElement;
            this.systemErrorsModalInstance = null;
        }

        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
            if (!this.systemErrorsModalInstance || !(this.systemErrorsModalInstance instanceof bootstrap.Modal)) {
                this.systemErrorsModalInstance = new bootstrap.Modal(modalElement, { backdrop: true });

                if (!this.systemErrorsHiddenListenerAttached) {
                    modalElement.addEventListener('hidden.bs.modal', this.onSystemErrorsModalHidden);
                    this.systemErrorsHiddenListenerAttached = true;
                }
            }

            return this.systemErrorsModalInstance;
        }

        if (!this.systemErrorsModalInstance) {
            this.systemErrorsModalInstance = {
                show: () => {
                    modalElement.classList.add('show');
                    modalElement.style.display = 'block';
                    modalElement.removeAttribute('aria-hidden');
                },
                hide: () => {
                    modalElement.classList.remove('show');
                    modalElement.style.display = 'none';
                    modalElement.setAttribute('aria-hidden', 'true');
                    this.resetSystemErrorsModal();
                }
            };
        }

        return this.systemErrorsModalInstance;
    }

    resetSystemErrorsModal() {
        const listElement = document.getElementById('errors-list');
        const emptyElement = document.getElementById('errors-empty');

        if (listElement) {
            listElement.innerHTML = '';
            listElement.style.display = 'none';
        }

        if (emptyElement) {
            emptyElement.style.display = 'none';
        }

        this.toggleSystemErrorsLoading(false);
    }

    toggleSystemErrorsLoading(isLoading) {
        const loadingElement = document.getElementById('errors-loading');
        const listElement = document.getElementById('errors-list');
        const emptyElement = document.getElementById('errors-empty');

        if (loadingElement) {
            loadingElement.style.display = isLoading ? 'block' : 'none';
        }

        if (isLoading) {
            if (listElement) {
                listElement.style.display = 'none';
            }

            if (emptyElement) {
                emptyElement.style.display = 'none';
            }
        }
    }

    renderSystemErrors(errors) {
        const listElement = document.getElementById('errors-list');
        const emptyElement = document.getElementById('errors-empty');

        if (!listElement || !emptyElement) return;

        listElement.innerHTML = '';

        if (!errors || errors.length === 0) {
            emptyElement.style.display = 'block';
            listElement.style.display = 'none';
            return;
        }

        emptyElement.style.display = 'none';
        listElement.style.display = 'flex';

        const fragment = document.createDocumentFragment();

        errors.forEach(error => {
            fragment.appendChild(this.createSystemErrorElement(error));
        });

        listElement.appendChild(fragment);
    }

    renderProductionStatus(healthData) {
        const statusElement = document.getElementById('production-status');
        if (!statusElement) {
            console.warn('[Dashboard Module] Production status element not found');
            return;
        }

        // Określ status systemu na podstawie danych
        const systemStatus = this.determineSystemStatus(healthData);
        
        // Wyczyść istniejące klasy CSS
        statusElement.classList.remove('status-healthy', 'status-processing', 'status-warning', 'status-critical');
        
        // Dodaj odpowiednią klasę CSS
        statusElement.classList.add(`status-${systemStatus.level}`);
        
        // Jeśli to błąd krytyczny, dodaj czerwone tło
        if (systemStatus.level === 'critical') {
            statusElement.style.backgroundColor = '#fef2f2';
            statusElement.style.border = '1px solid #fecaca';
            statusElement.style.borderRadius = '8px';
            statusElement.style.padding = '12px';
        } else {
            // Usuń czerwone tło dla innych statusów
            statusElement.style.backgroundColor = '';
            statusElement.style.border = '';
            statusElement.style.borderRadius = '';
            statusElement.style.padding = '';
        }
        
        // Zaktualizuj zawartość HTML
        statusElement.innerHTML = `
            <div class="status-indicator">
                <span class="status-dot ${systemStatus.level}"></span>
                <div class="status-content">
                    <div class="status-title">${systemStatus.title}</div>
                    <div class="status-message">${systemStatus.message}</div>
                    <div class="status-details">${systemStatus.details}</div>
                </div>
            </div>
        `;
        
        console.log(`[Dashboard Module] Production status updated: ${systemStatus.level}`);
    }

    // Dodaj więcej debugowania w determineSystemStatus() w dashboard-module.js

    determineSystemStatus(healthData) {
        console.log('[Dashboard Module] Determining system status from data:', healthData);

        const errors24h = healthData.errors_24h || 0;
        const totalErrors = healthData.total_unresolved_errors || 0;
        const dbStatus = healthData.database_status;
        const syncStatus = healthData.sync_status;
        const lastSync = healthData.last_sync;

        console.log('[Dashboard Module] Status check variables:');
        console.log('- errors24h:', errors24h);
        console.log('- totalErrors:', totalErrors);
        console.log('- dbStatus:', dbStatus, typeof dbStatus);
        console.log('- syncStatus:', syncStatus);
        console.log('- lastSync:', lastSync);
        console.log('- lastSync type:', typeof lastSync);

        // POPRAWKA: Lepsze debugowanie czasu synchronizacji
        let syncAge = 0;
        let syncMinutes = 0;
        let syncMessage = 'System aktywny';

        if (lastSync) {
            console.log('[Dashboard Module] Processing lastSync:', lastSync);

            // Backend wysyła czas w formacie ISO
            const lastSyncTime = new Date(lastSync);
            const now = new Date();

            console.log('[Dashboard Module] Time parsing:');
            console.log('- lastSyncTime (parsed):', lastSyncTime);
            console.log('- lastSyncTime (ISO):', lastSyncTime.toISOString());
            console.log('- now (ISO):', now.toISOString());
            console.log('- isValid lastSyncTime:', !isNaN(lastSyncTime.getTime()));

            // Sprawdź czy parsing się udał
            if (isNaN(lastSyncTime.getTime())) {
                console.warn('[Dashboard Module] Invalid lastSync date:', lastSync);
                syncMessage = 'Błąd parsowania daty sync';
            } else {
                // Oblicz różnicę w milisekundach, minutach i godzinach
                const timeDiffMs = now - lastSyncTime;
                syncMinutes = Math.floor(timeDiffMs / (1000 * 60));
                syncAge = Math.floor(timeDiffMs / (1000 * 60 * 60));

                console.log('[Dashboard Module] Time calculations:');
                console.log('- timeDiffMs:', timeDiffMs);
                console.log('- syncMinutes:', syncMinutes);
                console.log('- syncAge (hours):', syncAge);

                // POPRAWKA: Lepsze formatowanie komunikatu
                if (syncMinutes < 1) {
                    syncMessage = 'Ostatnia synchronizacja: przed chwilą';
                } else if (syncMinutes < 60) {
                    syncMessage = `Ostatnia synchronizacja: ${syncMinutes} min. temu`;
                } else if (syncAge < 24) {
                    syncMessage = `Ostatnia synchronizacja:: ${syncAge}h temu`;
                } else {
                    const syncDays = Math.floor(syncAge / 24);
                    syncMessage = `Ostatnia synchronizacja: ${syncDays} dni temu`;
                }

                console.log('[Dashboard Module] Final sync message:', syncMessage);

                // DODATKOWA WALIDACJA: jeśli syncAge jest ujemne, coś jest nie tak
                if (timeDiffMs < 0) {
                    console.warn('[Dashboard Module] Negative time diff detected - sync time in future!');
                    syncMessage = 'Ostatnia synchronizacja: dane w przyszłości (błąd czasu)';
                    syncAge = 0;
                }
            }
        } else {
            console.log('[Dashboard Module] No lastSync data available');
            syncMessage = 'Brak danych o ostatniej sync';
        }

        console.log('- final syncAge (hours):', syncAge);
        console.log('- final syncMessage:', syncMessage);

        // CZERWONY - Błędy krytyczne (tylko naprawdę krytyczne problemy)
        if (dbStatus !== 'ok' && dbStatus !== 'connected') {
            console.log('[Dashboard Module] CRITICAL: Database status check failed');
            return {
                level: 'critical',
                title: 'Błąd systemu',
                message: 'Problemy z bazą danych',
                details: `Status DB: ${dbStatus}`
            };
        }

        if (errors24h > 10) {
            console.log('[Dashboard Module] CRITICAL: Too many errors in 24h');
            return {
                level: 'critical',
                title: 'Błędy systemu',
                message: `${errors24h} błędów w ostatnich 24h`,
                details: 'Wymagana interwencja administratora'
            };
        }

        // ŻÓŁTY - Ostrzeżenia (w tym stara synchronizacja)
        if (syncAge > 25) {
            console.log('[Dashboard Module] WARNING: Sync age too old (moved from critical)');
            return {
                level: 'warning',
                title: 'Synchronizacja przestarzała',
                message: `Ostatnia synchronizacja: ${Math.floor(syncAge / 24)} dni temu`,
                details: syncAge > 168 ? 'Synchronizacja ponad tydzień temu' : `Synchronizacja ${syncAge}h temu`
            };
        }

        if (syncStatus !== 'success' && syncStatus !== 'completed') {
            console.log('[Dashboard Module] WARNING: Sync status not successful');
            return {
                level: 'warning',
                title: 'Ostrzeżenie synchronizacji',
                message: 'Problemy z pobieraniem danych',
                details: `Status: ${syncStatus}`
            };
        }

        if (errors24h > 0 || totalErrors > 0) {
            console.log('[Dashboard Module] WARNING: Some errors detected');
            return {
                level: 'warning',
                title: 'Błędy w pamięci',
                message: `${totalErrors} nierozwiązanych błędów`,
                details: `${errors24h} nowych w ciągu 24h`
            };
        }

        if (syncAge > 2) {
            console.log('[Dashboard Module] WARNING: Sync slightly delayed');
            return {
                level: 'warning',
                title: 'Synchronizacja opóźniona',
                message: `Ostatnie pobranie: ${syncAge}h temu`,
                details: 'Zalecane pobieranie co 1-2h'
            };
        }

        // NIEBIESKI - Procesy w toku
        if (syncStatus === 'running') {
            console.log('[Dashboard Module] PROCESSING: Sync in progress');
            return {
                level: 'processing',
                title: 'Synchronizacja w toku',
                message: 'Pobieranie nowych zamówień...',
                details: 'Proszę czekać na zakończenie'
            };
        }

        // ZIELONY - Wszystko OK
        console.log('[Dashboard Module] HEALTHY: All checks passed');

        return {
            level: 'healthy',
            title: 'System działa prawidłowo',
            message: 'Wszystkie komponenty sprawne',
            details: syncMessage  // TUTAJ POWINIEN BYĆ CZAS SYNC
        };
    }

    showProductionStatusError(message) {
        const statusElement = document.getElementById('production-status');
        if (!statusElement) return;
        
        statusElement.classList.remove('status-healthy', 'status-processing', 'status-warning', 'status-critical');
        statusElement.classList.add('status-critical');
        
        statusElement.style.backgroundColor = '#fef2f2';
        statusElement.style.border = '1px solid #fecaca';
        statusElement.style.borderRadius = '8px';
        statusElement.style.padding = '12px';
        
        statusElement.innerHTML = `
            <div class="status-indicator">
                <span class="status-dot critical"></span>
                <div class="status-content">
                    <div class="status-title">Błąd systemu</div>
                    <div class="status-message">${message}</div>
                    <div class="status-details">Spróbuj odświeżyć stronę</div>
                </div>
            </div>
        `;
    }

    createSystemErrorElement(error) {
        const item = document.createElement('div');
        item.classList.add('system-error-item');
        item.classList.add(error.is_resolved ? 'resolved' : 'unresolved');

        const header = document.createElement('div');
        header.className = 'system-error-header';

        const title = document.createElement('div');
        title.className = 'system-error-title';
        title.textContent = error.error_message || 'Nieznany błąd systemu';

        const status = document.createElement('span');
        status.className = `system-error-status badge ${error.is_resolved ? 'bg-success' : 'bg-danger'}`;
        status.textContent = error.is_resolved ? 'Rozwiązany' : 'Nierozwiązany';

        header.append(title, status);
        item.appendChild(header);

        const meta = document.createElement('div');
        meta.className = 'system-error-meta';

        const metaEntries = [
            error.id ? `ID: ${error.id}` : null,
            error.error_type ? `Typ: ${error.error_type}` : null,
            `Zgłoszono: ${this.formatErrorDate(error.error_occurred_at)}`,
            error.error_location ? `Obszar: ${error.error_location}` : null,
            error.related_order_id ? `Zamówienie: ${error.related_order_id}` : null,
            error.related_product_id ? `Produkt: ${error.related_product_id}` : null
        ].filter(Boolean);

        metaEntries.forEach(entry => {
            const span = document.createElement('span');
            span.textContent = entry;
            meta.appendChild(span);
        });

        if (metaEntries.length > 0) {
            item.appendChild(meta);
        }

        const detailsEntries = this.prepareErrorDetailsEntries(error.error_details);

        if (detailsEntries.length > 0) {
            const detailsContainer = document.createElement('div');
            detailsContainer.className = 'system-error-details';

            detailsEntries.forEach(([key, value]) => {
                const detailRow = document.createElement('div');
                detailRow.className = 'system-error-detail';

                const label = document.createElement('span');
                label.className = 'system-error-detail-key';
                label.textContent = `${key}:`;
                detailRow.appendChild(label);

                const formattedValue = this.formatDetailValue(value);

                if (typeof value === 'object' || formattedValue.includes('\n')) {
                    const pre = document.createElement('pre');
                    pre.className = 'system-error-detail-value';
                    pre.textContent = formattedValue;
                    detailRow.appendChild(pre);
                } else {
                    const valueSpan = document.createElement('span');
                    valueSpan.className = 'system-error-detail-value';
                    valueSpan.textContent = formattedValue;
                    detailRow.appendChild(valueSpan);
                }

                detailsContainer.appendChild(detailRow);
            });

            item.appendChild(detailsContainer);
        }

        return item;
    }

    prepareErrorDetailsEntries(details) {
        if (!details) {
            return [];
        }

        let normalizedDetails = details;

        if (typeof normalizedDetails === 'string') {
            try {
                normalizedDetails = JSON.parse(normalizedDetails);
            } catch (error) {
                return [['Szczegóły', normalizedDetails]];
            }
        }

        if (Array.isArray(normalizedDetails)) {
            return normalizedDetails.map((value, index) => [`Pozycja ${index + 1}`, value]);
        }

        if (typeof normalizedDetails === 'object') {
            return Object.entries(normalizedDetails);
        }

        return [['Wartość', String(normalizedDetails)]];
    }

    formatDetailValue(value) {
        if (value === null || value === undefined) {
            return '-';
        }

        if (typeof value === 'object') {
            try {
                return JSON.stringify(value, null, 2);
            } catch (error) {
                return String(value);
            }
        }

        return String(value);
    }

    formatErrorDate(dateString) {
        if (!dateString) {
            return 'Brak daty';
        }

        try {
            const date = new Date(dateString);
            return date.toLocaleString('pl-PL', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch (error) {
            return dateString;
        }
    }

    showSystemErrorsError(message) {
        const listElement = document.getElementById('errors-list');
        const emptyElement = document.getElementById('errors-empty');

        if (!listElement) {
            return;
        }

        listElement.innerHTML = '';

        const alert = document.createElement('div');
        alert.className = 'alert alert-danger';
        alert.textContent = message;

        listElement.appendChild(alert);
        listElement.style.display = 'block';

        if (emptyElement) {
            emptyElement.style.display = 'none';
        }
    }

    async handleRefreshSystem() {
        console.log('[Dashboard Module] Manual refresh system triggered');

        if (this.state.isRefreshing) {
            console.log('[Dashboard Module] Refresh already in progress, ignoring request');
            return;
        }

        const refreshBtn = document.getElementById('refresh-system-btn');
        const refreshIcon = refreshBtn?.querySelector('.refresh-icon');
        const refreshText = refreshBtn?.querySelector('.refresh-text');
        const refreshTimer = document.getElementById('refresh-timer');

        // Reset countdown po ręcznym refresh
        this.autoRefreshCountdown = 60;

        const startTime = Date.now();
        let durationTimer;

        try {
            // Ustaw stan odświeżania
            this.state.isRefreshing = true;
            this.refreshDuration = 0;

            // Aktualizuj UI przycisku
            if (refreshBtn) {
                refreshBtn.disabled = true;
                refreshBtn.style.opacity = '0.7';
            }

            if (refreshIcon) {
                refreshIcon.style.animation = 'spin 1s linear infinite';
                refreshIcon.style.transformOrigin = 'center';
            }

            // Timer pokazujący czas trwania refresh (aktualizowany co 0.1s)
            durationTimer = setInterval(() => {
                this.refreshDuration = (Date.now() - startTime) / 1000;
                this.updateRefreshButtonText();
            }, 100);

            console.log('[Dashboard Module] Starting manual data refresh...');

            // Wyczyść cache API
            this.shared.apiClient.clearCache();

            // Wykonaj odświeżenie danych
            await this.refreshDataOnly();

            // Zapisz czas ostatniego ręcznego odświeżenia
            this.state.lastManualRefresh = new Date();

            const totalDuration = (Date.now() - startTime) / 1000;

            // Pokaż toast o sukcesie z czasem
            this.shared.toastSystem.show(
                `Dane zostały odświeżone pomyślnie (${totalDuration.toFixed(1)}s)`,
                'success'
            );

            console.log(`[Dashboard Module] Manual refresh completed in ${totalDuration.toFixed(1)}s`);

        } catch (error) {
            console.error('[Dashboard Module] Manual refresh failed:', error);

            this.shared.toastSystem.show(
                'Błąd podczas odświeżania: ' + error.message,
                'error'
            );
        } finally {
            // Wyczyść timer duration
            if (durationTimer) {
                clearInterval(durationTimer);
            }

            // Przywróć stan przycisku
            this.state.isRefreshing = false;

            if (refreshBtn) {
                refreshBtn.disabled = false;
                refreshBtn.style.opacity = '1';
            }

            if (refreshIcon) {
                refreshIcon.style.animation = 'none';
            }

            // Przywróć normalny tekst (z countdown)
            this.updateRefreshButtonText();
        }
    }

    // ========================================================================
    // AUTO REFRESH
    // ========================================================================

    setupAutoRefresh() {
        console.log('[Dashboard Module] Setting up auto-refresh with countdown...');

        // Wyczyść poprzednie timery jeśli istnieją
        if (this.autoRefreshInterval) {
            clearInterval(this.autoRefreshInterval);
        }
        if (this.productionStatusInterval) {
            clearInterval(this.productionStatusInterval);
        }
        if (this.autoRefreshTimer) {
            clearInterval(this.autoRefreshTimer);
        }

        // Timer odliczający do następnego auto-refresh (aktualizowany co sekundę)
        this.setupAutoRefreshCountdown();

        // Główny auto-refresh co minutę
        this.autoRefreshInterval = setInterval(() => {
            if (!document.hidden && !this.state.isLoading && this.templateLoaded && !this.state.isRefreshing) {
                console.log('[Dashboard Module] Auto-refresh: starting...');
                this.performAutoRefresh();
            }
        }, 60 * 1000); // 60 sekund = 1 minuta

        // Production status refresh co 30 sekund  
        this.productionStatusInterval = setInterval(() => {
            if (!document.hidden && !this.state.isLoading && this.templateLoaded && !this.state.isRefreshing) {
                console.log('[Dashboard Module] Auto-refresh: production status...');
                this.dataRefresh.refreshWidget('production-status').catch(error => {
                    console.error('[Dashboard Module] Production status refresh failed:', error);
                });
            }
        }, 30000); // 30 sekund

        console.log('[Dashboard Module] Auto-refresh setup complete');
    }

    setupAutoRefreshCountdown() {
        this.autoRefreshCountdown = 60; // Reset countdown

        this.autoRefreshTimer = setInterval(() => {
            if (!this.state.isRefreshing) {
                this.autoRefreshCountdown--;
                this.updateRefreshButtonText();

                if (this.autoRefreshCountdown <= 0) {
                    this.autoRefreshCountdown = 60; // Reset na kolejny cykl
                }
            }
        }, 1000); // Co sekundę
    }

    // NOWA metoda - aktualizacja tekstu przycisku
    updateRefreshButtonText() {
        const refreshText = document.querySelector('.refresh-text');
        const refreshTimer = document.getElementById('refresh-timer');

        if (!refreshText || !refreshTimer) return;

        if (this.state.isRefreshing) {
            // Podczas refresh - pokaż czas trwania
            refreshText.textContent = 'Odświeżanie...';
            const duration = Math.floor(this.refreshDuration);
            refreshTimer.textContent = `(${duration}s)`;
            refreshTimer.style.display = 'inline';
        } else {
            // Normalny stan - pokaż countdown do auto-refresh
            refreshText.textContent = 'Odśwież system';
            refreshTimer.textContent = `(auto za ${this.autoRefreshCountdown}s)`;
            refreshTimer.style.display = 'inline';
            refreshTimer.style.color = '#ffffff';
            refreshTimer.style.opacity = '0.8';
        }
    }

    // NOWA metoda - wykonanie auto-refresh z pomiarem czasu
    async performAutoRefresh() {
        const startTime = Date.now();

        try {
            console.log('[Dashboard Module] Starting auto-refresh...');

            // Wyczyść cache API
            this.shared.apiClient.clearCache();

            // Wykonaj odświeżenie danych
            await this.refreshDataOnly();

            const duration = (Date.now() - startTime) / 1000;
            console.log(`[Dashboard Module] Auto-refresh completed in ${duration.toFixed(1)}s`);

            // Pokaż krótką informację o sukcesie (tylko w konsoli)
            console.log('[Dashboard Module] Auto-refresh successful');

        } catch (error) {
            console.error('[Dashboard Module] Auto-refresh failed:', error);
        }
    }

    // NOWA METODA - destroy() (główna metoda cleanup)
    destroy() {
        console.log('[Dashboard Module] Destroying dashboard module...');

        try {
            // Wyczyść wszystkie timery
            this.clearAllTimers();

            // Wyczyść DataRefreshService
            if (this.dataRefresh) {
                this.dataRefresh.clearAllHandlers();
                this.dataRefresh = null;
            }

            // Zniszcz wykres Chart.js
            this.destroyChart();

            // Wyczyść komponenty
            this.destroyComponents();

            // Usuń event listenery
            this.removeEventListeners();

            // Wyczyść modals
            this.cleanupModals();

            // Reset stanu
            this.resetState();

            console.log('[Dashboard Module] Dashboard module destroyed successfully');

        } catch (error) {
            console.error('[Dashboard Module] Error during cleanup:', error);
        }
    }

    // NOWA METODA - wyczyść wszystkie timery
    clearAllTimers() {
        console.log('[Dashboard Module] Clearing all timers...');

        // Główne timery auto-refresh
        if (this.autoRefreshInterval) {
            clearInterval(this.autoRefreshInterval);
            this.autoRefreshInterval = null;
            console.log('[Dashboard Module] Auto-refresh interval cleared');
        }

        if (this.productionStatusInterval) {
            clearInterval(this.productionStatusInterval);
            this.productionStatusInterval = null;
            console.log('[Dashboard Module] Production status interval cleared');
        }

        // Timer countdown do auto-refresh (z nowego kodu)
        if (this.autoRefreshTimer) {
            clearInterval(this.autoRefreshTimer);
            this.autoRefreshTimer = null;
            console.log('[Dashboard Module] Auto-refresh timer cleared');
        }

        // Ewentualne inne timery
        if (this.chartRefreshTimer) {
            clearInterval(this.chartRefreshTimer);
            this.chartRefreshTimer = null;
        }

        // Wyczyść timer z refresh przycisku
        const refreshTimer = document.getElementById('refresh-timer');
        if (refreshTimer && refreshTimer._refreshInterval) {
            clearInterval(refreshTimer._refreshInterval);
            delete refreshTimer._refreshInterval;
        }
    }

    // NOWA METODA - zniszcz wykres Chart.js
    destroyChart() {
        if (this.chartInstance) {
            console.log('[Dashboard Module] Destroying chart instance...');
            try {
                this.chartInstance.destroy();
            } catch (error) {
                console.warn('[Dashboard Module] Error destroying chart:', error);
            }
            this.chartInstance = null;
        }

        // Wyczyść canvas chart reference
        const canvas = document.getElementById('performance-chart-canvas');
        if (canvas && canvas.chart) {
            try {
                canvas.chart.destroy();
            } catch (error) {
                console.warn('[Dashboard Module] Error destroying canvas chart:', error);
            }
            delete canvas.chart;
        }
    }

    // NOWA METODA - zniszcz komponenty widgetów  
    destroyComponents() {
        console.log('[Dashboard Module] Destroying widget components...');

        Object.keys(this.components).forEach(componentName => {
            const component = this.components[componentName];
            if (component && typeof component.destroy === 'function') {
                try {
                    component.destroy();
                    console.log(`[Dashboard Module] Component ${componentName} destroyed`);
                } catch (error) {
                    console.warn(`[Dashboard Module] Error destroying component ${componentName}:`, error);
                }
            }
            this.components[componentName] = null;
        });
    }

    // NOWA METODA - wyczyść modals
    cleanupModals() {
        console.log('[Dashboard Module] Cleaning up modals...');

        // Zamknij i wyczyść system errors modal
        this.closeSystemErrorsModal();

        if (this.systemErrorsModalInstance) {
            try {
                this.systemErrorsModalInstance.dispose();
            } catch (error) {
                console.warn('[Dashboard Module] Error disposing modal:', error);
            }
            this.systemErrorsModalInstance = null;
        }

        this.systemErrorsModalElement = null;
        this.systemErrorsHiddenListenerAttached = false;
    }

    // NOWA METODA - reset stanu
    resetState() {
        console.log('[Dashboard Module] Resetting state...');

        this.isLoaded = false;
        this.templateLoaded = false;

        this.state = {
            lastRefresh: null,
            widgetStates: {},
            chartData: null,
            isRefreshing: false,
            lastManualRefresh: null
        };

        // Reset właściwości z nowego kodu timerów
        this.autoRefreshCountdown = 60;
        this.refreshDuration = 0;
    }

    // ========================================================================
    // UTILITY METHODS
    // ========================================================================

    startRefreshTimer(timerElement) {
        if (!timerElement) return;

        let seconds = 0;
        const interval = setInterval(() => {
            seconds++;
            timerElement.textContent = `(${seconds}s)`;

            // Zatrzymaj timer po 30 sekundach (fallback)
            if (seconds >= 30 || !this.state.isRefreshing) {
                clearInterval(interval);
                timerElement.textContent = '';
            }
        }, 1000);

        // Przechowaj referencję do intervalu w przypadku potrzeby wcześniejszego zatrzymania
        timerElement._refreshInterval = interval;
    }

    cleanBackendValue(value) {
        if (value === "-" || value === null || value === undefined || value === "") {
            return 0;
        }

        if (typeof value === 'string' && !isNaN(parseFloat(value))) {
            return parseFloat(value);
        }

        if (typeof value === 'number') {
            return value;
        }

        return 0;
    }

    updateNumberWithAnimation(element, newValue) {
        if (!element) return;

        const currentValue = parseFloat(element.textContent) || 0;
        const targetValue = parseFloat(newValue) || 0;

        if (currentValue === targetValue) return;

        // Simple animation
        const duration = 800;
        const steps = 20;
        const stepValue = (targetValue - currentValue) / steps;
        const stepTime = duration / steps;

        let currentStep = 0;

        const animate = () => {
            currentStep++;
            const intermediateValue = currentValue + (stepValue * currentStep);

            if (currentStep < steps) {
                element.textContent = typeof newValue === 'string' && newValue.includes('.')
                    ? intermediateValue.toFixed(4)
                    : Math.round(intermediateValue);
                setTimeout(animate, stepTime);
            } else {
                element.textContent = newValue;
            }
        };

        animate();
    }

    updateTodayValue(elementId, value, type) {
        const element = document.getElementById(elementId);
        if (!element) return;

        const cleanValue = this.cleanBackendValue(value);
        let displayValue;

        switch (type) {
            case 'liczba':
                displayValue = cleanValue;
                break;
            case 'm3':
                displayValue = cleanValue.toFixed(4);
                break;
            case 'dni':
                displayValue = Math.round(cleanValue);
                break;
            default:
                displayValue = cleanValue;
        }

        this.updateNumberWithAnimation(element, displayValue);
    }

    updateTodayDate() {
        console.log('[Dashboard Module] Attempting to update today-date element...');

        const dateElement = document.getElementById('today-date');
        console.log('[Dashboard Module] Found today-date element:', dateElement);

        if (dateElement) {
            const today = new Date();
            const dateString = today.toLocaleDateString('pl-PL', {
                weekday: 'long',
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            });

            console.log('[Dashboard Module] Setting date to:', dateString);
            dateElement.textContent = dateString;

            // Dodaj wizualną klasę, żeby sprawdzić czy element jest aktualizowany
            dateElement.classList.add('date-updated');

            console.log('[Dashboard Module] Today date updated successfully');
        } else {
            console.error('[Dashboard Module] Element today-date not found!');
            // Sprawdź czy jakiś podobny element istnieje
            const allDateElements = document.querySelectorAll('[id*="date"], .date-info, [class*="date"]');
            console.log('[Dashboard Module] Available date-related elements:',
                Array.from(allDateElements).map(el => ({ id: el.id, class: el.className, text: el.textContent }))
            );
        }
    }

    updateLastRefreshTime(elementId) {
        const element = document.getElementById(elementId);
        if (element) {
            const now = new Date();
            const timeString = now.toLocaleTimeString('pl-PL', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
            element.textContent = `Aktualizacja: ${timeString}`;
        }
    }

    updateStationStatus(statusElement, stationData) {
        const statusDot = statusElement.querySelector('.status-dot');
        if (!statusDot) return;

        const pendingCount = stationData.pending_count || 0;

        // Reset classes
        statusDot.classList.remove('active', 'warning', 'danger');

        // Apply status based on pending count
        if (pendingCount === 0) {
            // No class = default gray
        } else if (pendingCount > 25) {
            statusDot.classList.add('danger');
        } else if (pendingCount > 15) {
            statusDot.classList.add('warning');
        } else {
            statusDot.classList.add('active');
        }
    }

    updateHealthIndicator(health) {
        console.log('[Dashboard Module] Updating health indicator with data:', health);

        const indicator = document.getElementById('health-indicator');
        if (!indicator) {
            console.warn('[Dashboard Module] Health indicator element not found');
            return;
        }

        // Znajdź kropkę health-dot w środku wskaźnika
        const healthDot = indicator.querySelector('.health-dot');
        if (!healthDot) {
            console.warn('[Dashboard Module] Health dot element not found');
            return;
        }

        let overallStatus = 'success'; // Domyślnie zielony
        let statusText = 'System działa poprawnie';
        let dotClass = 'success'; // Dla health-dot

        // Określ status na podstawie danych
        if (health.database_status !== 'connected') {
            overallStatus = 'critical';
            statusText = 'Problemy z bazą danych';
            dotClass = 'error';
        } else if (health.sync_status !== 'success') {
            overallStatus = 'warning';
            statusText = 'Problemy z synchronizacją';
            dotClass = 'warning';
        } else if (health.errors_24h && health.errors_24h > 5) {
            overallStatus = 'warning';
            statusText = 'Wykryto błędy systemu';
            dotClass = 'warning';
        }

        // Aktualizuj klasy wskaźnika
        indicator.className = `health-indicator health-${overallStatus}`;

        // Aktualizuj klasy kropki - usuń stare i dodaj nową
        healthDot.classList.remove('success', 'warning', 'error');
        healthDot.classList.add(dotClass);

        console.log(`[Dashboard Module] Health indicator updated: status=${overallStatus}, dotClass=${dotClass}`);

        // Opcjonalnie: dodaj tekst statusu jeśli jest miejsce w UI
        indicator.setAttribute('title', statusText); // Tooltip
    }

    updateLastSync(lastSync, syncStatus) {
        const element = document.getElementById('last-sync-time');
        if (!element) return;

        if (lastSync) {
            const syncDate = new Date(lastSync);
            const timeText = syncDate.toLocaleString('pl-PL', {
                day: '2-digit',
                month: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
            element.textContent = timeText;
        } else {
            element.textContent = 'Brak danych';
        }
    }

    updateDatabaseStatus(dbStatus) {
        const element = document.getElementById('db-response-time');
        if (element) {
            element.textContent = dbStatus === 'connected' ? 'Połączona' : 'Rozłączona';
        }
    }

    updateSystemErrors(errorCount) {
        const element = document.getElementById('error-count');
        const countValue = errorCount || 0;

        if (element) {
            element.textContent = countValue;
        }

        const statusElement = document.getElementById('errors-status');
        if (statusElement) {
            statusElement.classList.remove('status-success', 'status-warning', 'status-error');

            if (countValue === 0) {
                statusElement.classList.add('status-success');
                statusElement.textContent = 'OK';
            } else if (countValue > 5) {
                statusElement.classList.add('status-error');
                statusElement.textContent = 'HIGH';
            } else {
                statusElement.classList.add('status-warning');
                statusElement.textContent = 'MEDIUM';
            }
        }
    }

    getNoAlertsHTML() {
        return `
            <div class="no-alerts-state">
                <div class="no-alerts-icon">✅</div>
                <p class="no-alerts-text">Brak pilnych alertów</p>
                <small class="text-muted">Wszystkie produkty zgodne z terminem</small>
            </div>
        `;
    }

    createAlertHTML(alert) {
        const urgencyClass = alert.days_remaining <= 0 ? 'alert-overdue' :
            alert.days_remaining <= 1 ? 'alert-critical' :
                alert.days_remaining <= 2 ? 'alert-warning' : 'alert-normal';

        const urgencyIcon = alert.days_remaining <= 0 ? '🚨' :
            alert.days_remaining <= 1 ? '⚠️' :
                alert.days_remaining <= 2 ? '⏳' : '⏰';

        return `
            <div class="alert-item ${urgencyClass}">
                <div class="alert-icon">${urgencyIcon}</div>
                <div class="alert-content">
                    <div class="alert-header">
                        <span class="alert-product-id">${alert.short_product_id}</span>
                        <span class="alert-days">${alert.days_remaining} dni</span>
                    </div>
                    <div class="alert-details">
                        <span class="alert-deadline">Termin: ${alert.deadline_date}</span>
                    </div>
                </div>
            </div>
        `;
    }
}