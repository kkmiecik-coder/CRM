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

                wrapper.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => new bootstrap.Tooltip(el));
            }

            // Inicjalizacja komponentów (tylko raz przy ładowaniu template)
            this.initializeWidgets();
            this.setupEventListeners();
            this.setupDataRefreshHandlers(); // NOWA METODA - będzie w kroku 3.5

            // Initialize charts for all users
            await this.initializePerformanceChart();

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
                // Update extended station data
                if (data.data.stations) {
                    // Trakownia ma własne metryki — odświeżamy ją niezależnie od formatu
                    // (słownik przy starcie, tablica przy cyklicznym odświeżeniu).
                    this.updateSawmillStation(
                        Array.isArray(data.data.stations)
                            ? data.data.stations.find(s => s.code === 'sawmill')
                            : data.data.stations.sawmill
                    );

                    if (Array.isArray(data.data.stations)) {
                        data.data.stations.forEach(s => {
                            if (s.code === 'sawmill') return;
                            this.updateElementText(`${s.code}-pending`, s.active_orders || 0);
                            if (s.tablet_status) this.updateStationTabletStatus(s.code, s.tablet_status);
                            if (s.completed_today !== undefined) {
                                this.updateElementText(`${s.code}-completed-today`, s.completed_today || 0);
                                this.updateElementText(`${s.code}-pending-m3`, (parseFloat(s.pending_m3) || 0).toFixed(4));
                                this.updateStationProgress(s.code, {pending_count: s.active_orders, completed_today: s.completed_today});
                            }
                        });
                    }
                }
                // Update in_production if available
                if (data.data.in_production) {
                    this.updateInProductionWidget(data.data.in_production);
                }
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

        // Handler dla statusu produkcji (aktualizuje sync date coloring w Status systemu)
        this.dataRefresh.registerRefreshHandler('production-status', async () => {
            const data = await this.shared.apiClient.getProductionStatusData();
            if (data.success && data.data) {
                // Update sync date coloring in dashboard
                const syncEl = document.querySelector('.sync-date-value');
                if (syncEl && data.data.last_sync) {
                    const syncTime = new Date(data.data.last_sync);
                    const hoursAgo = (Date.now() - syncTime.getTime()) / (1000 * 60 * 60);
                    syncEl.classList.remove('sync-fresh', 'sync-warning', 'sync-stale');
                    if (hoursAgo < 24) syncEl.classList.add('sync-fresh');
                    else if (hoursAgo < 48) syncEl.classList.add('sync-warning');
                    else syncEl.classList.add('sync-stale');
                    syncEl.textContent = data.data.last_sync.substring(0, 16).replace('T', ' ');
                }
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
                    name: key === 'cutting' ? 'Wycinanie - mikro' : key === 'assembly' ? 'Składanie - lite' : 'Pakowanie',
                    active_orders: initialData.stations[key].pending_count,
                    status: initialData.stations[key].status,
                    status_class: initialData.stations[key].status_class
                }));
                this.updateStationsWidget(stationsArray);
            }

            if (initialData.today_totals) {
                this.updateTotalsWidget({
                    total_orders: initialData.today_totals.total_orders || 0,
                    completed_orders: initialData.today_totals.completed_orders || 0,
                    completed_items: initialData.today_totals.completed_items || 0,
                    completed_products: initialData.today_totals.completed_products || 0,
                    total_m3: initialData.today_totals.total_m3 || 0,
                    pending_priority: 0,
                    errors_24h: initialData.system_health?.errors_24h || 0
                });
            }

            if (initialData.deadline_alerts) {
                this.updateAlertsWidget(initialData.deadline_alerts);
            }

            // Update "In Production Now" widget
            if (initialData.in_production) {
                this.updateInProductionWidget(initialData.in_production);
            }

            // Update station extended data (completed_today, pending_m3, tablet status, progress bars)
            if (initialData.stations) {
                // Trakownia celowo poza tą listą — ma własny zestaw metryk, patrz updateSawmillStation().
                this.updateSawmillStation(initialData.stations.sawmill);

                const stations = ['cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging'];
                stations.forEach(station => {
                    const stationData = initialData.stations[station];
                    if (stationData) {
                        this.updateElementText(`${station}-completed-today`, stationData.completed_today || 0);
                        this.updateElementText(`${station}-pending-m3`, (parseFloat(stationData.pending_m3) || 0).toFixed(4));
                        this.updateStationTabletStatus(station, stationData.tablet_status);
                        this.updateStationProgress(station, stationData);
                    }
                });
            }

        } catch (error) {
            console.error('[Dashboard Module] Error updating widgets with initial data:', error);
        }
    }

    updateTotalsWidget(statsData) {
        console.log('[Dashboard Module] Updating totals widget...', statsData);

        this.updateNumberWithAnimation(
            document.getElementById('today-completed-orders'),
            statsData.completed_orders || 0
        );
        this.updateNumberWithAnimation(
            document.getElementById('today-completed-items'),
            statsData.completed_items || 0
        );
        this.updateNumberWithAnimation(
            document.getElementById('today-completed-products'),
            statsData.completed_products || 0
        );
        const m3Value = statsData.total_m3 ?? statsData.total_volume_today_m3 ?? 0;
        const m3El = document.getElementById('today-total-m3');
        if (m3El) {
            this.updateNumberWithAnimation(m3El, parseFloat(m3Value).toFixed(4));
        }
    }

    async unload() {
        console.log('[Dashboard Module] Unloading dashboard...');

        // Użyj nowej metody destroy() zamiast duplikowania kodu
        this.destroy();

        console.log('[Dashboard Module] Dashboard unloaded');
    }

    async refresh() {
        console.log('[DashboardModule] Refresh triggered by ProductionApp');
        await this.refreshDataOnly();
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

            wrapper.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => new bootstrap.Tooltip(el));
        }

        // Store stats for widgets
        this.state.stats = response.stats;

        return response;
    }

    // ========================================================================
    // WIDGET MANAGEMENT
    // ========================================================================

    async initializeProductionStatus() {
        // Production status widget was removed from main template.
        // Sync date coloring is now handled by inline script in dashboard-tab-content.html
        // and by the production-status refresh handler in setupDataRefreshHandlers().
        console.log('[Dashboard Module] Production status initialized (sync date coloring)');
    }

    initializeWidgets() {
        console.log('[Dashboard Module] Initializing widgets...');

        // Initialize each widget
        this.components.stationsWidget = this.initStationsWidget();
        this.components.todayTotalsWidget = this.initTodayTotalsWidget();
        this.components.alertsWidget = this.initAlertsWidget();
        this.components.systemHealthWidget = this.initSystemHealthWidget();

        // Chart period buttons (Industrial Light template)
        const periodBtns = document.querySelectorAll('.il-chart-period');
        periodBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                periodBtns.forEach(b => { b.classList.remove('active'); b.classList.add('inactive'); });
                btn.classList.remove('inactive');
                btn.classList.add('active');
                const period = btn.getAttribute('data-period');
                this.loadChartData(parseInt(period));
            });
        });

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
        const stationsGrid = document.querySelector('.il-stations-grid') || document.querySelector('.stations-grid');
        if (!stationsGrid) return null;

        // Initialize station cards click handlers
        const stationCards = stationsGrid.querySelectorAll('.il-station') || stationsGrid.querySelectorAll('.station-card');
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
        const todayWidget = document.getElementById('today-completed-orders') ||
            document.querySelector('.widget.today-summary');
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
        const alertsWidget = document.getElementById('alerts-list') ||
            document.querySelector('.il-alert-list') ||
            document.querySelector('.widget.deadline-alerts');
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
        const healthWidget = document.querySelector('.il-system-list') ||
            document.querySelector('.widget.system-health');
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

    /**
     * Odświeża kafelek trakowni. Ma inny zestaw metryk niż pozostałe stanowiska,
     * bo liczy surowiec na tabelach prod_sawmill_*, a nie zlecenia produkcyjne.
     * Bez tej metody liczby trakowni pochodziły wyłącznie z renderu szablonu
     * i zostawały zamrożone na wartościach z chwili wejścia na stronę.
     */
    updateSawmillStation(dane) {
        if (!dane) return;

        this.updateElementText('sawmill-open', dane.open_orders || 0);
        this.updateElementText('sawmill-logs-today', dane.logs_today || 0);
        this.updateElementText('sawmill-m3-today', (parseFloat(dane.volume_today_m3) || 0).toFixed(3));
        this.updateElementText('sawmill-to-settle', dane.to_settle || 0);

        const procent = parseFloat(dane.progress_pct) || 0;
        const wypelnienie = document.getElementById('sawmill-bar-fill');
        if (wypelnienie) wypelnienie.style.width = `${procent}%`;
        this.updateElementText('sawmill-bar-pct', `${procent}%`);

        if (dane.tablet_status) {
            this.updateStationTabletStatus('sawmill', dane.tablet_status);
        }
    }

    updateStationsWidget(stationsData) {
        console.log('[Dashboard Module] Updating stations widget...', stationsData);

        stationsData.forEach(station => {
            // Trakownia nie przerabia zleceń ProductionItem, więc z założenia nie ma
            // pola "-pending" — ma własne metryki (otwarte / kłód dziś / m³ / do rozliczenia),
            // odświeżane przez updateSawmillStation(). Bez tego pominięcia leciało tu
            // mylące ostrzeżenie "Element sawmill-pending not found" przy każdym odświeżeniu.
            if (station.code === 'sawmill') {
                return;
            }

            // Aktualizuj liczby oczekujących dla każdej stacji
            const pendingElement = document.getElementById(`${station.code}-pending`);
            if (pendingElement) {
                console.log(`[Dashboard Module] Updating ${station.code}-pending to ${station.active_orders}`);
                this.updateNumberWithAnimation(pendingElement, station.active_orders);
            } else {
                console.warn(`[Dashboard Module] Element ${station.code}-pending not found`);
            }

            // Aktualizuj status badge tabletu
            const badgeElement = document.getElementById(`${station.code}-tablet-badge`);
            if (badgeElement) {
                // Aktualizuj klasę na podstawie liczby zamówień
                badgeElement.classList.remove('danger', 'warning');
                if (station.active_orders > 50) {
                    badgeElement.classList.add('danger');
                } else if (station.active_orders > 30) {
                    badgeElement.classList.add('warning');
                }
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

        this.updateTodayValue('today-completed-orders', totalsData.completed_orders || 0, 'liczba');
        this.updateTodayValue('today-completed-items', totalsData.completed_items || 0, 'liczba');
        this.updateTodayValue('today-completed-products', totalsData.completed_products || 0, 'liczba');
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
                // Try IL template first, fall back to old template
                if (document.querySelector('.il-alert-list') || alertsList.closest('[class*="il-"]')) {
                    alertsList.innerHTML = '<div class="il-no-alerts">Brak pilnych alertów</div>';
                } else {
                    alertsList.innerHTML = this.getNoAlertsHTML();
                }
            } else {
                // Detect which template is active
                const isIL = document.querySelector('.il-stations-grid') !== null;
                if (isIL) {
                    const alerts = alertsData;
                    const alertHtml = alerts.map(alert => {
                        const days = alert.days_remaining || 0;
                        let dotClass = 'info';
                        let daysColor = 'var(--il-status-info)';
                        if (days < 0) { dotClass = 'danger'; daysColor = 'var(--il-status-danger)'; }
                        else if (days <= 1) { dotClass = 'warn'; daysColor = 'var(--il-status-warn)'; }

                        const daysText = days < 0 ? `${days} dni` : days === 0 ? 'Dziś' : days === 1 ? '1 dzień' : `${days} dni`;
                        const count = alert.products_count || 1;
                        const prodLabel = count === 1 ? 'produkt' : (count >= 2 && count <= 4 ? 'produkty' : 'produktów');

                        // Pigułka stanowiska — wąskie gardło zamówienia, czyli pozycja
                        // najmniej zaawansowana; "+N" to liczba pozostałych stanowisk.
                        // Musi być identyczna jak w dashboard-tab-content.html, bo kafel
                        // renderuje się raz Jinją (wejście), raz stąd (odświeżanie).
                        const others = alert.other_stations_count || 0;
                        const stationHtml = alert.station_code
                            ? `<span class="il-alert-station" data-station="${alert.station_code}">${alert.station_label || ''}${others ? ` +${others}` : ''}</span>`
                            : '';

                        return `
                            <div class="il-alert-item">
                                <div class="il-alert-dot ${dotClass}"></div>
                                <div class="il-alert-info">
                                    <div class="il-alert-client">${alert.client_name || 'Brak danych'}</div>
                                    <div class="il-alert-order">
                                        <span>${alert.baselinker_order_id || ''} · ${count} ${prodLabel}</span>
                                        ${stationHtml}
                                    </div>
                                </div>
                                <div class="il-alert-right">
                                    <div class="il-alert-days" style="color: ${daysColor};">${daysText}</div>
                                    <div class="il-alert-date">${alert.deadline_date_formatted || ''}</div>
                                </div>
                            </div>
                        `;
                    }).join('');
                    alertsList.innerHTML = alertHtml || '<div class="il-no-alerts">Brak pilnych alertów</div>';
                } else {
                    alertsList.innerHTML = alertsData.map(alert =>
                        this.createAlertHTML(alert)
                    ).join('');
                }
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
    // PERFORMANCE CHART - For All Users
    // ============================================================================

    async initializePerformanceChart() {
        if (typeof Chart === 'undefined') {
            console.log('[Dashboard Module] Chart.js not available');
            return;
        }

        console.log('[Dashboard Module] Initializing performance chart...');

        try {
            const canvas = document.getElementById('performance-chart-canvas');
            const chartContainer = canvas ? canvas.closest('.dashboard-card') || canvas.closest('.widget.performance-chart') : null;
            if (!chartContainer) {
                console.warn('[Dashboard Module] Chart container not found');
                return;
            }

            // Pokaż loader od razu na początku inicjalizacji
            this.toggleChartLoader(true);

            // Initialize chart controls (już nie generujemy HTML, bo jest w template)
            this.initChartControls(chartContainer);

            // Load chart data
            await this.loadChartData(30); // Default 30 days

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
                    layout: {
                        padding: { top: 0, right: 0, bottom: 0, left: 0 }
                    },
                    interaction: {
                        mode: 'index',
                        intersect: false
                    },
                    plugins: {
                        title: {
                            display: false
                        },
                        legend: {
                            display: true,
                            position: 'top',
                            labels: {
                                usePointStyle: true,
                                padding: 10,
                                font: { size: 11, family: "'JetBrains Mono', monospace" }
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
        const canvas = document.getElementById('performance-chart-canvas');
        const chartContainer = canvas ? canvas.parentElement : document.querySelector('.widget.performance-chart .widget-content');
        if (chartContainer) {
            chartContainer.innerHTML = `
            <div class="alert alert-danger">
                <strong>Błąd wykresu:</strong> ${message}
            </div>
        `;
        }
    }

    toggleChartLoader(show) {
        const canvas = document.getElementById('performance-chart-canvas');
        const loader = canvas ? canvas.closest('.dashboard-card')?.querySelector('.chart-loader') : document.querySelector('.widget.performance-chart .chart-loader');

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

    // ========================================================================
    // INDUSTRIAL LIGHT WIDGET HELPERS
    // ========================================================================

    updateInProductionWidget(data) {
        this.updateElementText('in-production-orders', data.orders || 0);
        this.updateElementText('in-production-items', data.items || 0);
        this.updateElementText('in-production-products', data.products || 0);
        this.updateElementText('in-production-m3', data.m3 || 0);
    }

    updateStationTabletStatus(station, tabletStatus) {
        if (!tabletStatus) return;
        const badge = document.getElementById(`${station}-tablet-badge`);
        const card = badge ? badge.closest('.il-station') : null;
        if (badge) {
            badge.textContent = tabletStatus.status_label || 'Niedostępne';
            badge.className = 'il-station-badge ' + (tabletStatus.active ? 'active' : 'inactive');
        }
        if (card) {
            card.classList.toggle('station-inactive', !tabletStatus.active);
        }
    }

    updateStationProgress(station, data) {
        const barFill = document.getElementById(`${station}-bar-fill`);
        const barPct = document.getElementById(`${station}-bar-pct`);
        if (!barFill || !barPct) return;
        const pending = parseInt(data.pending_count) || 0;
        const completed = parseInt(data.completed_today) || 0;
        const total = pending + completed;
        const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
        barFill.style.width = pct + '%';
        barPct.textContent = pct + '%';
    }

    updateElementText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    createAlertHTML(alert) {
        const urgencyClass = alert.days_remaining <= 0 ? 'alert-overdue' :
            alert.days_remaining <= 1 ? 'alert-critical' :
                alert.days_remaining <= 2 ? 'alert-warning' : 'alert-normal';

        const urgencyIcon = alert.days_remaining <= 0 ? '🚨' :
            alert.days_remaining <= 1 ? '⚠️' :
                alert.days_remaining <= 2 ? '⏳' : '⏰';

        // Budowanie numerów zamówień w kolejności: BL, systemowy, wewnętrzny
        let idsHtml = '';
        if (alert.baselinker_order_id) {
            idsHtml += `<span class="alert-id baselinker">BL-${alert.baselinker_order_id}</span>`;
        }
        if (alert.short_product_id) {
            idsHtml += `<span class="alert-id system">${alert.short_product_id}</span>`;
        }
        if (alert.client_order_number) {
            idsHtml += `<span class="alert-id internal">${alert.client_order_number}</span>`;
        }

        return `
            <div class="alert-item ${urgencyClass}">
                <div class="alert-icon">${urgencyIcon}</div>
                <div class="alert-content">
                    <div class="alert-row-main">
                        <span class="alert-client-name">${alert.client_name || 'Brak danych'}</span>
                        <span class="alert-days">${alert.days_remaining} dni</span>
                    </div>
                    <div class="alert-row-ids">${idsHtml}</div>
                    ${alert.product_name ? `<div class="alert-row-product" title="${alert.product_name}">${alert.product_name}${alert.quantity > 1 ? ` - <strong>${alert.quantity} szt.</strong>` : ''}</div>` : ''}
                </div>
            </div>
        `;
    }
}