/**
 * Dashboard Baselinker Sync Modal - NOWY REFACTOR
 * app/modules/production/static/js/modules/dashboard_bl_sync_modal.js
 * 
 * 4-etapowy workflow synchronizacji z Baselinker:
 * 1. Formularz ustawień (zakres dni + statusy)
 * 2. Progress pobierania (strony API + zamówienia) 
 * 3. Lista zamówień (checkboxy + filtrowanie)
 * 4. Progress zapisu wybranych zamówień
 * 
 * Wzorowane na module reports z filtrowaniem produktów w JavaScript
 * 
 * Autor: System
 * Data: 2025-01-17
 * Wersja: 2.0 (Refactor)
 */

class DashboardBLSyncModal {
    constructor() {
        // Stan modalu
        this.modalElement = null;
        this.isOpen = false;
        this.currentStep = 1;
        this.syncInProgress = false;
        this.toastSystem = window.ProductionShared?.toastSystem || null;

        // Dane synchronizacji
        this.selectedDays = 7; // domyślnie 7 dni
        this.selectedStatuses = [];
        this.availableStatuses = [];
        this.fetchedOrders = [];
        this.selectedOrders = [];
        this.syncResults = null;

        // Statystyki
        this.stats = {
            apiPages: 0,
            ordersCount: 0,
            productsCount: 0,
            selectedOrdersCount: 0,
            selectedProductsCount: 0,
            savedOrders: 0,
            savedProducts: 0,
            skippedProducts: 0
        };

        // Logi synchronizacji
        this.syncLogs = [];
        this.logsVisible = false;

        // Konfiguracja filtrowania produktów (skopiowana z reports)
        this.productFilterKeywords = [
            'usługa', 'usługi', 'usługowa', 'usługowe',
            'deska', 'deski',
            'worek', 'worki', 'worków',
            'tarcica', 'tarcicy'
        ];

        // Elementy DOM
        this.elements = {};

        // Konfiguracja endpointów
        this.endpoints = {
            fetchStatuses: '/production/api/baselinker_statuses',
            fetchOrdersPreview: '/production/api/fetch_orders_preview',
            saveSelectedOrders: '/production/api/save_selected_orders',
            getConfigDaysRange: '/production/api/get_config_days_range'
        };

        console.log('[BL Sync Modal v2] Inicjalizacja nowego modalu');
        this.init();
    }

    /**
     * Inicjalizacja modalu
     */
    async init() {
        try {
            // Znajdź element modalu
            this.modalElement = document.getElementById('baselinkerSyncModal');
            if (!this.modalElement) {
                console.error('[BL Sync Modal v2] Element modalu nie znaleziony');
                return;
            }

            // Cachuj elementy DOM
            this.cacheElements();

            // Ustaw event listenery
            this.setupEventListeners();

            // Załaduj konfigurację domyślną
            await this.loadDefaultConfig();

            console.log('[BL Sync Modal v2] Modal zainicjalizowany pomyślnie');

        } catch (error) {
            console.error('[BL Sync Modal v2] Błąd inicjalizacji:', error);
        }
    }

    /**
     * Cachowanie elementów DOM
     */
    cacheElements() {
        this.elements = {
            // Modal główny
            modal: this.modalElement,
            overlay: this.modalElement.querySelector('.modal-bl-sync-overlay'),
            container: this.modalElement.querySelector('.modal-bl-sync-container'),

            // Kroki
            step1: document.getElementById('syncStep1'),
            step2: document.getElementById('syncStep2'),
            step3: document.getElementById('syncStep3'),
            step4: document.getElementById('syncStep4'),

            // Krok 1 - Konfiguracja
            syncDaysRange: document.getElementById('syncDaysRange'),
            syncDaysValue: document.getElementById('syncDaysValue'),
            dateFromPreview: document.getElementById('dateFromPreview'),
            dateToPreview: document.getElementById('dateToPreview'),
            statusesContainer: document.getElementById('syncStatusesContainer'),
            statusesLoading: document.getElementById('statusesLoading'),
            statusesList: document.getElementById('statusesList'),
            step1Cancel: document.getElementById('syncStep1Cancel'),
            step1Next: document.getElementById('syncStep1Next'),

            // Krok 2 - Progress pobierania
            statApiPages: document.getElementById('statApiPages'),
            statOrdersCount: document.getElementById('statOrdersCount'),
            syncStep2Subtitle: document.getElementById('syncStep2Subtitle'),
            step2DateFrom: document.getElementById('step2DateFrom'),
            step2DateTo: document.getElementById('step2DateTo'),
            syncProgressBarFill: document.getElementById('syncProgressBarFill'),
            syncProgressText: document.getElementById('syncProgressText'),
            syncLogsContent: document.getElementById('syncLogsContent'),
            syncLogsToggle: document.getElementById('syncLogsToggle'),
            step2Cancel: document.getElementById('syncStep2Cancel'),
            step2Next: document.getElementById('syncStep2Next'),

            // Krok 3 - Lista zamówień
            syncOrdersCount: document.getElementById('syncOrdersCount'),
            syncProductsCount: document.getElementById('syncProductsCount'),
            toggleSyncLogs: document.getElementById('toggleSyncLogs'),
            syncLogsSection: document.getElementById('syncLogsSection'),
            syncStep3Logs: document.getElementById('syncStep3Logs'),
            selectAllOrders: document.getElementById('selectAllOrders'),
            deselectAllOrders: document.getElementById('deselectAllOrders'),
            ordersListContainer: document.getElementById('ordersListContainer'),
            step3Back: document.getElementById('syncStep3Back'),
            step3Cancel: document.getElementById('syncStep3Cancel'),
            step3Save: document.getElementById('syncStep3Save'),

            // Krok 4 - Progress zapisu
            syncStep4Subtitle: document.getElementById('syncStep4Subtitle'),
            statSaveOrders: document.getElementById('statSaveOrders'),
            statSaveProducts: document.getElementById('statSaveProducts'),
            statSaveSkipped: document.getElementById('statSaveSkipped'),
            syncSaveProgressBarFill: document.getElementById('syncSaveProgressBarFill'),
            syncSaveProgressText: document.getElementById('syncSaveProgressText'),
            syncSaveResults: document.getElementById('syncSaveResults'),
            syncSaveResultsSummary: document.getElementById('syncSaveResultsSummary'),
            step4Finish: document.getElementById('syncStep4Finish'),

            // Przyciski zamknięcia
            closeButtons: this.modalElement.querySelectorAll('.modal-bl-sync-close, #syncModalClose, #syncStep3Close')
        };

        console.log('[BL Sync Modal v2] Elementy DOM zacachowane:', Object.keys(this.elements).length);
    }

    /**
     * Ustawienie event listenerów
     */
    setupEventListeners() {
        try {
            // Zamykanie modalu
            this.elements.closeButtons.forEach(btn => {
                btn.addEventListener('click', () => this.closeModal());
            });

            this.elements.overlay?.addEventListener('click', () => this.closeModal());

            // Escape key
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.isOpen) {
                    this.closeModal();
                }
            });

            // KROK 1 - Konfiguracja
            this.elements.syncDaysRange?.addEventListener('input', (e) => {
                this.onDaysRangeChange(parseInt(e.target.value));
            });

            this.elements.step1Cancel?.addEventListener('click', () => this.closeModal());
            this.elements.step1Next?.addEventListener('click', () => this.startFetchingOrders());

            // KROK 2 - Progress pobierania
            this.elements.syncLogsToggle?.addEventListener('click', () => this.toggleLogs());
            this.elements.step2Cancel?.addEventListener('click', () => this.cancelFetching());
            this.elements.step2Next?.addEventListener('click', () => this.goToStep(3));

            // KROK 3 - Lista zamówień
            this.elements.toggleSyncLogs?.addEventListener('click', () => this.toggleStep3Logs());
            this.elements.selectAllOrders?.addEventListener('click', () => this.selectAllOrders());
            this.elements.deselectAllOrders?.addEventListener('click', () => this.deselectAllOrders());
            this.elements.step3Back?.addEventListener('click', () => this.goToStep(2));
            this.elements.step3Cancel?.addEventListener('click', () => this.closeModal());
            this.elements.step3Save?.addEventListener('click', () => this.startSavingOrders());

            // KROK 4 - Progress zapisu
            this.elements.step4Finish?.addEventListener('click', () => this.closeModal());

            console.log('[BL Sync Modal v2] Event listenery ustawione');

        } catch (error) {
            console.error('[BL Sync Modal v2] Błąd ustawiania event listenerów:', error);
        }
    }

    // ============================================================================
    // PUBLICZNE METODY KONTROLUJĄCE MODAL
    // ============================================================================

    /**
     * Otwiera modal
     */
    async openModal() {
        if (this.isOpen) return;

        try {
            console.log('[BL Sync Modal v2] Otwieranie modalu');

            // Reset stanu
            this.resetModalState();

            // Idź do kroku 1
            await this.goToStep(1);

            // Pokaż modal
            this.elements.modal.style.display = 'block';
            this.isOpen = true;

            // Załaduj statusy z Baselinker
            await this.loadBaselinkerStatuses();

            // Animacja
            setTimeout(() => {
                this.elements.container?.classList.add('active');
            }, 10);

            console.log('[BL Sync Modal v2] Modal otwarty');

        } catch (error) {
            console.error('[BL Sync Modal v2] Błąd otwierania modalu:', error);
            if (this.toastSystem) {
                this.toastSystem.show(`Błąd otwierania modalu synchronizacji`, 'error');
            }
        }
    }

    /**
     * Zamyka modal
     */
    closeModal() {
        if (!this.isOpen) return;

        console.log('[BL Sync Modal v2] Zamykanie modalu');

        // Jeśli synchronizacja w toku, zapytaj o potwierdzenie
        if (this.syncInProgress) {
            if (!confirm('Synchronizacja jest w toku. Czy na pewno chcesz zamknąć modal?')) {
                return;
            }
        }

        // Animacja zamykania
        this.elements.container?.classList.remove('active');

        setTimeout(() => {
            this.elements.modal.style.display = 'none';
            this.isOpen = false;
            this.resetModalState();

            // FIX: Usuń Bootstrap backdrop jeśli istnieje
            this.removeBootstrapBackdrop();

            console.log('[BL Sync Modal v2] Modal zamknięty');
        }, 300);

        // POPRAWKA: Emit event + fallback
        setTimeout(() => {
            // Spróbuj EventBus
            const eventBus = window.ProductionShared?.eventBus;
            if (eventBus?.emit) {
                eventBus.emit('modal:baselinker:closed', { timestamp: new Date() });
                console.log('[BL Sync Modal v2] Event modal:baselinker:closed wyemitowany');
            }
            // Fallback: bezpośredni refresh
            else if (window.productionApp?.state?.loadedModules?.get('dashboard')?.refreshDataOnly) {
                window.productionApp.state.loadedModules.get('dashboard').refreshDataOnly();
                console.log('[BL Sync Modal v2] Dashboard refresh przez fallback');
            }
        }, 100); // Krótkie opóźnienie
    }

    /**
     * FIX: Usuwa Bootstrap backdrop pozostawiony przez inne modale
     */
    removeBootstrapBackdrop() {
        try {
            // Znajdź wszystkie backdrop'y Bootstrap (różne selektory)
            const backdrops = document.querySelectorAll('.modal-backdrop, .modal-backdrop.show, .modal-backdrop.fade');
            backdrops.forEach(backdrop => {
                backdrop.remove();
            });

            // Usuń klasy z body dodane przez Bootstrap
            document.body.classList.remove('modal-open');
            document.body.style.overflow = '';
            document.body.style.paddingRight = '';

            // FIX: Dodatkowe czyszczenie atrybutów body
            document.body.removeAttribute('style');

            console.log('[BL Sync Modal v2] Bootstrap backdrop usunięty');
        } catch (error) {
            console.warn('[BL Sync Modal v2] Problem z usuwaniem Bootstrap backdrop:', error);
        }
    }

    /**
     * Reset stanu modalu
     */
    resetModalState() {
        this.currentStep = 1;
        this.syncInProgress = false;
        this.selectedStatuses = [];
        this.fetchedOrders = [];
        this.selectedOrders = [];
        this.syncResults = null;
        this.syncLogs = [];
        this.logsVisible = false;

        // Reset statystyk
        this.stats = {
            apiPages: 0,
            ordersCount: 0,
            productsCount: 0,
            selectedOrdersCount: 0,
            selectedProductsCount: 0,
            savedOrders: 0,
            savedProducts: 0,
            skippedProducts: 0
        };

        // Reset UI
        this.updateProgressBar(0, 'Gotowy do synchronizacji');
        this.updateStats();
    }

    // ============================================================================
    // KROK 1: KONFIGURACJA SYNCHRONIZACJI
    // ============================================================================

    /**
     * Przejście do wybranego kroku
     */
    async goToStep(stepNumber) {
        console.log(`[BL Sync Modal v2] Przejście do kroku ${stepNumber}`);

        // Ukryj wszystkie kroki
        [1, 2, 3, 4].forEach(num => {
            const step = this.elements[`step${num}`];
            if (step) {
                step.style.display = 'none';
                step.classList.remove('active');
            }
        });

        // Pokaż wybrany krok
        const targetStep = this.elements[`step${stepNumber}`];
        if (targetStep) {
            targetStep.style.display = 'block';

            // FIX: Upewnij się że modal container jest widoczny
            if (this.elements.modal) {
                this.elements.modal.style.display = 'block';
            }

            // Krótkie opóźnienie dla animacji
            setTimeout(() => {
                targetStep.classList.add('active');
            }, 50);
        }

        this.currentStep = stepNumber;

        // Wykonaj specyficzne akcje dla kroku
        switch (stepNumber) {
            case 1:
                await this.initStep1();
                break;
            case 2:
                this.initStep2();
                break;
            case 3:
                this.initStep3();
                break;
            case 4:
                this.initStep4();
                break;
        }
    }

    /**
     * Inicjalizacja kroku 1
     */
    async initStep1() {
        console.log('[BL Sync Modal v2] Inicjalizacja kroku 1');

        // Ustaw domyślną wartość suwaka
        if (this.elements.syncDaysRange) {
            this.elements.syncDaysRange.value = this.selectedDays;
        }

        // Aktualizuj preview dat
        this.updateDatePreview();

        // Sprawdź czy statusy zostały załadowane
        if (this.availableStatuses.length === 0) {
            await this.loadBaselinkerStatuses();
        }
    }

    /**
     * Ładowanie konfiguracji domyślnej
     */
    async loadDefaultConfig() {
        try {
            console.log('[BL Sync Modal v2] Ładowanie domyślnej konfiguracji');

            // Spróbuj pobrać zakres dni z konfiguracji
            const response = await fetch(this.endpoints.getConfigDaysRange, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (response.ok) {
                const data = await response.json();
                this.selectedDays = data.days_range || 7;
                console.log(`[BL Sync Modal v2] Załadowano zakres dni: ${this.selectedDays}`);
            } else {
                console.warn('[BL Sync Modal v2] Nie udało się pobrać konfiguracji, używam domyślnej');
                this.selectedDays = 7;
            }

        } catch (error) {
            console.error('[BL Sync Modal v2] Błąd ładowania konfiguracji:', error);
            this.selectedDays = 7;
        }
    }

    /**
     * Zmiana zakresu dni
     */
    onDaysRangeChange(days) {
        this.selectedDays = days;

        // Aktualizuj wyświetlanie
        if (this.elements.syncDaysValue) {
            this.elements.syncDaysValue.textContent = days;
        }

        // Aktualizuj preview dat
        this.updateDatePreview();

        // Sprawdź czy można aktywować przycisk Next
        this.validateStep1();
    }

    /**
     * Aktualizacja podglądu dat
     */
    updateDatePreview() {
        const today = new Date();
        const fromDate = new Date(today.getTime() - (this.selectedDays * 24 * 60 * 60 * 1000));

        const formatDate = (date) => {
            return date.toLocaleDateString('pl-PL', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric'
            });
        };

        if (this.elements.dateFromPreview) {
            this.elements.dateFromPreview.textContent = formatDate(fromDate);
        }

        if (this.elements.dateToPreview) {
            this.elements.dateToPreview.textContent = formatDate(today);
        }
    }

    /**
     * Ładowanie statusów z Baselinker
     */
    async loadBaselinkerStatuses() {
        try {
            console.log('[BL Sync Modal v2] Ładowanie statusów Baselinker');

            // Pokaż loading
            if (this.elements.statusesLoading) {
                this.elements.statusesLoading.style.display = 'block';
            }
            if (this.elements.statusesList) {
                this.elements.statusesList.style.display = 'none';
            }

            const response = await fetch(this.endpoints.fetchStatuses, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.success && data.statuses) {
                this.availableStatuses = data.statuses;
                this.renderStatusesList();
                console.log(`[BL Sync Modal v2] Załadowano ${this.availableStatuses.length} statusów`);
            } else {
                throw new Error(data.error || 'Nie udało się pobrać statusów');
            }

        } catch (error) {
            console.error('[BL Sync Modal v2] Błąd ładowania statusów:', error);
            this.showStatusesError(error.message);
        } finally {
            // Ukryj loading
            if (this.elements.statusesLoading) {
                this.elements.statusesLoading.style.display = 'none';
            }
        }
    }

    /**
     * Renderowanie listy statusów
     */
    renderStatusesList() {
        if (!this.elements.statusesList || !this.availableStatuses.length) return;

        let html = '';

        // Domyślne statusy do zaznaczenia (można skonfigurować)
        const defaultStatuses = ['production', 'ready', 'packed'];

        this.availableStatuses.forEach(status => {
            const isChecked = defaultStatuses.includes(status.name.toLowerCase());
            if (isChecked) {
                this.selectedStatuses.push(status.id);
            }

            html += `
                <div class="sync-status-item">
                    <input type="checkbox" 
                           id="status_${status.id}" 
                           value="${status.id}"
                           ${isChecked ? 'checked' : ''}
                           onchange="window.dashboardBLSyncModal.onStatusChange(${status.id}, this.checked)">
                    <label for="status_${status.id}">
                        ${status.name} (ID: ${status.id})
                    </label>
                </div>
            `;
        });

        this.elements.statusesList.innerHTML = html;
        this.elements.statusesList.style.display = 'block';

        // Waliduj krok 1
        this.validateStep1();
    }

    /**
     * Zmiana statusu
     */
    onStatusChange(statusId, isChecked) {
        if (isChecked) {
            if (!this.selectedStatuses.includes(statusId)) {
                this.selectedStatuses.push(statusId);
            }
        } else {
            this.selectedStatuses = this.selectedStatuses.filter(id => id !== statusId);
        }

        console.log('[BL Sync Modal v2] Wybrane statusy:', this.selectedStatuses);
        this.validateStep1();
    }

    /**
     * Pokazanie błędu statusów
     */
    showStatusesError(errorMessage) {
        if (!this.elements.statusesList) return;

        this.elements.statusesList.innerHTML = `
            <div style="padding: 20px; text-align: center; color: #dc2626;">
                <i class="fas fa-exclamation-triangle" style="font-size: 24px; margin-bottom: 8px;"></i><br>
                <strong>Błąd ładowania statusów</strong><br>
                <small>${errorMessage}</small><br>
                <button onclick="window.dashboardBLSyncModal.loadBaselinkerStatuses()" 
                        style="margin-top: 12px; padding: 6px 12px; background: #FF8F33; color: white; border: none; border-radius: 4px; cursor: pointer;">
                    Spróbuj ponownie
                </button>
            </div>
        `;
        this.elements.statusesList.style.display = 'block';
    }

    /**
     * Walidacja kroku 1
     */
    validateStep1() {
        const isValid = this.selectedDays > 0 && this.selectedStatuses.length > 0;

        if (this.elements.step1Next) {
            this.elements.step1Next.disabled = !isValid;
        }

        return isValid;
    }

    // ============================================================================
    // KROK 2: POBIERANIE ZAMÓWIEŃ
    // ============================================================================

    /**
     * Rozpoczęcie pobierania zamówień
     */
    async startFetchingOrders() {
        if (!this.validateStep1()) {
            if (this.toastSystem) {
                this.toastSystem.show(`Wybierz zakres dni i przynajmniej jeden status`, 'warning');
            }
            return;
        }

        console.log('[BL Sync Modal v2] Rozpoczynanie pobierania zamówień');

        // Przejdź do kroku 2
        await this.goToStep(2);

        // Rozpocznij pobieranie
        await this.fetchOrdersFromBaselinker();
    }

    /**
     * Inicjalizacja kroku 2
     */
    initStep2() {
        console.log('[BL Sync Modal v2] Inicjalizacja kroku 2');

        // Reset progress
        this.updateProgressBar(0, 'Przygotowanie do pobierania...');
        this.updateStats();

        // Ukryj przycisk Next
        if (this.elements.step2Next) {
            this.elements.step2Next.style.display = 'none';
        }

        // Aktywuj przycisk Cancel
        if (this.elements.step2Cancel) {
            this.elements.step2Cancel.disabled = false;
        }

        // Ustaw daty w headerze
        this.updateStep2DateRange();

        // Reset logów
        this.syncLogs = [];
        this.updateLogsDisplay();
    }

    /**
     * Aktualizacja zakresu dat w kroku 2
     */
    updateStep2DateRange() {
        const today = new Date();
        const fromDate = new Date(today.getTime() - (this.selectedDays * 24 * 60 * 60 * 1000));

        const formatDate = (date) => {
            return date.toLocaleDateString('pl-PL', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric'
            });
        };

        if (this.elements.step2DateFrom) {
            this.elements.step2DateFrom.textContent = formatDate(fromDate);
        }

        if (this.elements.step2DateTo) {
            this.elements.step2DateTo.textContent = formatDate(today);
        }
    }

    /**
     * Pobieranie zamówień z Baselinker
     */
    async fetchOrdersFromBaselinker() {
        try {
            this.syncInProgress = true;
            this.addLog('info', 'Rozpoczynanie pobierania zamówień z Baselinker');

            // Aktualizuj subtitle
            if (this.elements.syncStep2Subtitle) {
                this.elements.syncStep2Subtitle.textContent = 'Łączenie z Baselinker API...';
            }

            this.updateProgressBar(10, 'Wysyłanie zapytania do Baselinker...');

            const requestData = {
                days_range: this.selectedDays,
                status_ids: this.selectedStatuses
            };

            this.addLog('info', `Parametry: ${this.selectedDays} dni, statusy: ${this.selectedStatuses.join(', ')}`);

            const response = await fetch(this.endpoints.fetchOrdersPreview, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestData)
            });

            this.updateProgressBar(30, 'Otrzymano odpowiedź z Baselinker...');

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            this.updateProgressBar(50, 'Przetwarzanie otrzymanych danych...');

            if (data.success) {
                this.fetchedOrders = data.orders || [];
                this.stats.apiPages = data.pages_processed || 0;
                this.stats.ordersCount = this.fetchedOrders.length;

                // Policz produkty i przefiltruj
                this.processOrdersData();

                this.addLog('info', `Pobrano ${this.stats.ordersCount} zamówień z ${this.stats.apiPages} stron API`);
                this.updateProgressBar(80, 'Filtrowanie produktów...');

                // Symuluj krótkie opóźnienie dla UX
                await this.delay(1000);

                this.updateProgressBar(100, 'Pobieranie zakończone!');
                this.addLog('success', 'Pobieranie zamówień zakończone pomyślnie');

                // Pokaż przycisk Next
                if (this.elements.step2Next) {
                    this.elements.step2Next.style.display = 'block';
                }

                // Aktualizuj subtitle
                if (this.elements.syncStep2Subtitle) {
                    this.elements.syncStep2Subtitle.textContent = `Pobrano ${this.stats.ordersCount} zamówień`;
                }

            } else {
                throw new Error(data.error || 'Nieznany błąd pobierania');
            }

        } catch (error) {
            console.error('[BL Sync Modal v2] Błąd pobierania zamówień:', error);
            this.addLog('error', `Błąd pobierania: ${error.message}`);
            this.updateProgressBar(0, 'Błąd pobierania zamówień');
            if (this.toastSystem) {
                this.toastSystem.show(`Błąd pobierania zamówień: ${error.message}`, 'error');
            }

            // Aktywuj przycisk Cancel jako "Zamknij"
            if (this.elements.step2Cancel) {
                this.elements.step2Cancel.textContent = 'Zamknij';
                this.elements.step2Cancel.disabled = false;
            }

        } finally {
            this.syncInProgress = false;

            // Aktualizuj statystyki
            this.updateStats();
        }
    }

    /**
     * Przetwarzanie danych zamówień
     */
    processOrdersData() {
        let totalProducts = 0;

        this.fetchedOrders.forEach(order => {
            if (order.products) {
                const filteredProducts = order.products.filter(product =>
                    !this.isProductFiltered(product)
                );
                order.originalProducts = [...order.products];
                order.filteredProducts = filteredProducts;
                totalProducts += filteredProducts.length;
                order.filteredCount = order.products.length - filteredProducts.length;
            }
        });

        this.stats.productsCount = totalProducts;
        this.selectedOrders = [...this.fetchedOrders];
        this.updateSelectedStats();

        // FIX: Wywołaj update przycisku z opóźnieniem
        setTimeout(() => {
            this.updateStep3SaveButton();
        }, 100);

        console.log(`[BL Sync Modal v2] Przetworzono ${this.fetchedOrders.length} zamówień, ${totalProducts} produktów`);
    }

    /**
     * Sprawdzanie czy produkt jest filtrowany (logika skopiowana z reports)
     */
    isProductFiltered(product) {
        if (!product || !product.name) return false;

        const productName = product.name.toLowerCase().trim();

        // Sprawdź czy nazwa produktu zawiera słowa kluczowe do filtrowania
        return this.productFilterKeywords.some(keyword =>
            productName.includes(keyword.toLowerCase())
        );
    }

    /**
     * Anulowanie pobierania
     */
    cancelFetching() {
        if (this.syncInProgress) {
            this.syncInProgress = false;
            this.addLog('warning', 'Pobieranie anulowane przez użytkownika');
        }

        this.closeModal();
    }

    // ============================================================================
    // KROK 3: LISTA ZAMÓWIEŃ DO ZAZNACZENIA
    // ============================================================================

    /**
     * Inicjalizacja kroku 3
     */
    initStep3() {
        console.log('[BL Sync Modal v2] Inicjalizacja kroku 3');

        // Renderuj listę zamówień
        this.renderOrdersList();

        // Aktualizuj statystyki w headerze
        this.updateStep3Stats();

        // Skopiuj logi z kroku 2
        this.copyLogsToStep3();

        // Reset widoczności logów
        this.logsVisible = false;
        this.updateStep3LogsVisibility();

        // FIX: Wymuszenie aktualizacji UI z opóźnieniem
        setTimeout(() => {
            this.updateAllOrdersUI();
            this.updateSelectedStats();
            this.updateStep3SaveButton();
        }, 200);
    }

    /**
     * Renderowanie listy zamówień
     */
    renderOrdersList() {
        if (!this.elements.ordersListContainer) return;

        if (this.fetchedOrders.length === 0) {
            this.elements.ordersListContainer.innerHTML = `
                <div class="sync-no-orders">
                    <i class="fas fa-inbox" style="font-size: 48px; color: #9ca3af; margin-bottom: 16px;"></i>
                    <h3 style="color: #6b7280; margin-bottom: 8px;">Brak zamówień</h3>
                    <p style="color: #9ca3af; font-size: 14px;">
                        Nie znaleziono zamówień w wybranym zakresie dat i statusach.
                    </p>
                </div>
            `;
            return;
        }

        let html = '';

        this.fetchedOrders.forEach((order, index) => {
            const isSelected = this.selectedOrders.includes(order);
            const hasFilteredProducts = order.filteredCount > 0;

            html += `
                <div class="sync-order-item ${isSelected ? 'selected' : ''}" data-order-id="${order.id || index}">
                    <div class="sync-order-header" onclick="window.dashboardBLSyncModal.toggleOrderSelection(${index})">
                        <input type="checkbox" 
                               class="sync-order-checkbox" 
                               ${isSelected ? 'checked' : ''}
                               onclick="event.stopPropagation(); window.dashboardBLSyncModal.toggleOrderSelection(${index})">
                        
                        <div class="sync-order-info">
                            <div class="sync-order-main">
                                <div class="sync-order-id">
                                    Zamówienie #${order.baselinker_order_id || order.id || `TEMP-${index}`}
                                </div>
                                <div class="sync-order-customer">
                                    ${order.customer_name || order.delivery_fullname || 'Brak nazwy klienta'}
                                </div>
                            </div>
                            
                            <div class="sync-order-meta">
                                <div class="sync-order-status status-${this.getStatusClass(order.status_id)}">
                                    ${this.getStatusName(order.status_id)}
                                </div>
                                <div class="sync-order-date">
                                    ${this.formatDate(order.date_add || order.order_date)}
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="sync-order-products">
                        ${this.renderOrderProducts(order)}
                    </div>
                </div>
            `;
        });

        this.elements.ordersListContainer.innerHTML = html;
        console.log(`[BL Sync Modal v2] Wyrenderowano ${this.fetchedOrders.length} zamówień`);
    }

    /**
     * Renderowanie produktów zamówienia
     */
    renderOrderProducts(order) {
        if (!order.products || order.products.length === 0) {
            return '<div class="sync-no-products">Brak produktów</div>';
        }

        let html = '';
        let totalQuantity = 0;
        let totalValue = 0;

        order.products.forEach(product => {
            const isFiltered = this.isProductFiltered(product);
            const quantity = parseFloat(product.quantity || 0);
            const price = parseFloat(product.price || 0);
            const value = quantity * price;

            if (!isFiltered) {
                totalQuantity += quantity;
                totalValue += value;
            }

            html += `
                <div class="sync-product-item ${isFiltered ? 'filtered' : ''}">
                    <div class="sync-product-info">
                        <div class="sync-product-name">
                            ${product.name || 'Bez nazwy'}
                            ${isFiltered ? ' <small style="color: #dc2626;">(pominięty)</small>' : ''}
                        </div>
                        <div class="sync-product-details">
                            ${product.sku ? `SKU: ${product.sku}` : ''}
                            ${product.variant ? ` • Wariant: ${product.variant}` : ''}
                        </div>
                    </div>
                    
                    <div class="sync-product-quantity">
                        ${quantity}${product.unit ? ` ${product.unit}` : ' szt.'}
                    </div>
                    
                    <div class="sync-product-price">
                        ${value.toFixed(2)} zł
                    </div>
                </div>
            `;
        });

        // Dodaj podsumowanie
        if (totalQuantity > 0) {
            html += `
                <div class="sync-order-summary">
                    <span><strong>Razem:</strong> ${totalQuantity} produktów • ${totalValue.toFixed(2)} zł</span>
                    ${order.filteredCount > 0 ? ` <span style="color: #dc2626;">(pominięto ${order.filteredCount} poz.)</span>` : ''}
                </div>
            `;
        }

        return html;
    }

    /**
     * Przełączanie zaznaczenia zamówienia
     */
    toggleOrderSelection(orderIndex) {
        const order = this.fetchedOrders[orderIndex];
        if (!order) return;

        const isSelected = this.selectedOrders.includes(order);

        if (isSelected) {
            // Usuń z zaznaczonych
            this.selectedOrders = this.selectedOrders.filter(o => o !== order);
        } else {
            // Dodaj do zaznaczonych
            this.selectedOrders.push(order);
        }

        // Aktualizuj UI
        this.updateOrderItemUI(orderIndex, !isSelected);
        this.updateSelectedStats();
        this.updateStep3SaveButton();

        console.log(`[BL Sync Modal v2] Zamówienie ${orderIndex} ${!isSelected ? 'zaznaczone' : 'odznaczone'}`);
    }

    /**
     * Aktualizacja UI elementu zamówienia
     */
    updateOrderItemUI(orderIndex, isSelected) {
        const orderElement = this.elements.ordersListContainer?.querySelector(`[data-order-id="${this.fetchedOrders[orderIndex]?.id || orderIndex}"]`);
        if (!orderElement) return;

        const checkbox = orderElement.querySelector('.sync-order-checkbox');

        if (isSelected) {
            orderElement.classList.add('selected');
            if (checkbox) checkbox.checked = true;
        } else {
            orderElement.classList.remove('selected');
            if (checkbox) checkbox.checked = false;
        }
    }

    /**
     * Zaznaczenie wszystkich zamówień
     */
    selectAllOrders() {
        this.selectedOrders = [...this.fetchedOrders];
        this.updateAllOrdersUI();
        this.updateSelectedStats();
        this.updateStep3SaveButton();
        console.log('[BL Sync Modal v2] Zaznaczono wszystkie zamówienia');
    }

    /**
     * Odznaczenie wszystkich zamówień
     */
    deselectAllOrders() {
        this.selectedOrders = [];
        this.updateAllOrdersUI();
        this.updateSelectedStats();
        this.updateStep3SaveButton();
        console.log('[BL Sync Modal v2] Odznaczono wszystkie zamówienia');
    }

    /**
     * Aktualizacja UI wszystkich zamówień
     */
    updateAllOrdersUI() {
        const orderElements = this.elements.ordersListContainer?.querySelectorAll('.sync-order-item');
        if (!orderElements) return;

        orderElements.forEach((element, index) => {
            const order = this.fetchedOrders[index];
            const isSelected = this.selectedOrders.includes(order);
            const checkbox = element.querySelector('.sync-order-checkbox');

            if (isSelected) {
                element.classList.add('selected');
                if (checkbox) checkbox.checked = true;
            } else {
                element.classList.remove('selected');
                if (checkbox) checkbox.checked = false;
            }
        });
    }

    /**
     * Aktualizacja statystyk wybranych zamówień
     */
    updateSelectedStats() {
        let selectedProductsCount = 0;

        this.selectedOrders.forEach(order => {
            if (order.filteredProducts) {
                selectedProductsCount += order.filteredProducts.length;
            }
        });

        this.stats.selectedOrdersCount = this.selectedOrders.length;
        this.stats.selectedProductsCount = selectedProductsCount;
    }

    /**
     * Aktualizacja statystyk w kroku 3
     */
    updateStep3Stats() {
        if (this.elements.syncOrdersCount) {
            this.elements.syncOrdersCount.textContent = `${this.stats.ordersCount} zamówień`;
        }

        if (this.elements.syncProductsCount) {
            this.elements.syncProductsCount.textContent = `${this.stats.productsCount} produktów`;
        }
    }

    /**
     * Aktualizacja przycisku zapisz
     */
    updateStep3SaveButton() {
        if (this.elements.step3Save) {
            const count = this.stats.selectedOrdersCount;
            this.elements.step3Save.disabled = count === 0;
            this.elements.step3Save.innerHTML = `
                <i class="fas fa-save"></i>
                Zapisz zamówienia (${count})
            `;
        }
    }

    /**
     * Toggle widoczności logów w kroku 3
     */
    toggleStep3Logs() {
        this.logsVisible = !this.logsVisible;
        this.updateStep3LogsVisibility();

        if (this.elements.toggleSyncLogs) {
            this.elements.toggleSyncLogs.innerHTML = `
                <i class="fas fa-eye${this.logsVisible ? '-slash' : ''}"></i>
                ${this.logsVisible ? 'Ukryj' : 'Pokaż'} logi
            `;

            if (this.logsVisible) {
                this.elements.toggleSyncLogs.classList.add('active');
            } else {
                this.elements.toggleSyncLogs.classList.remove('active');
            }
        }
    }

    /**
     * Aktualizacja widoczności logów w kroku 3
     */
    updateStep3LogsVisibility() {
        if (this.elements.syncLogsSection) {
            this.elements.syncLogsSection.style.display = this.logsVisible ? 'block' : 'none';
        }
    }

    /**
     * Kopiowanie logów do kroku 3
     */
    copyLogsToStep3() {
        if (this.elements.syncStep3Logs && this.syncLogs.length > 0) {
            const logsText = this.syncLogs.map(log =>
                `[${log.time}] ${log.message}`
            ).join('<br>');

            this.elements.syncStep3Logs.innerHTML = logsText;
        }
    }

    // ============================================================================
    // KROK 4: ZAPISYWANIE WYBRANYCH ZAMÓWIEŃ
    // ============================================================================

    /**
     * Rozpoczęcie zapisywania zamówień
     */
    async startSavingOrders() {
        if (this.selectedOrders.length === 0) {
            if (this.toastSystem) {
                this.toastSystem.show('Wybierz przynajmniej jedno zamówienie do zapisania', 'warning');
            }
            return;
        }

        console.log(`[BL Sync Modal v2] Rozpoczynanie zapisu ${this.selectedOrders.length} zamówień`);

        // Przejdź do kroku 4
        await this.goToStep(4);

        // Rozpocznij zapis
        await this.saveSelectedOrders();
    }

    /**
     * Inicjalizacja kroku 4
     */
    initStep4() {
        console.log('[BL Sync Modal v2] Inicjalizacja kroku 4');

        // Reset progress
        this.updateSaveProgressBar(0, 'Przygotowanie do zapisu...');

        // Ukryj wyniki
        if (this.elements.syncSaveResults) {
            this.elements.syncSaveResults.style.display = 'none';
        }

        // Ukryj przycisk Finish
        if (this.elements.step4Finish) {
            this.elements.step4Finish.style.display = 'none';
        }

        // Reset statystyk zapisu
        this.stats.savedOrders = 0;
        this.stats.savedProducts = 0;
        this.stats.skippedProducts = 0;
        this.updateSaveStats();
    }

    /**
     * Zapisywanie wybranych zamówień
     */
    async saveSelectedOrders() {
        try {
            this.syncInProgress = true;
            this.addLog('info', `Rozpoczynanie zapisu ${this.selectedOrders.length} zamówień`);

            // Aktualizuj subtitle
            if (this.elements.syncStep4Subtitle) {
                this.elements.syncStep4Subtitle.textContent = 'Tworzenie pozycji produkcyjnych...';
            }

            this.updateSaveProgressBar(10, 'Przygotowanie danych...');

            // Przygotuj dane do wysłania
            const orderIds = this.selectedOrders.map(order => order.id || order.baselinker_order_id).filter(id => id);

            this.addLog('info', `Wysyłanie ${orderIds.length} zamówień do zapisu`);

            const requestData = {
                order_ids: orderIds,
                days_range: this.selectedDays,
                status_ids: this.selectedStatuses
            };

            this.updateSaveProgressBar(30, 'Wysyłanie do serwera...');

            const response = await fetch(this.endpoints.saveSelectedOrders, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestData)
            });

            this.updateSaveProgressBar(50, 'Przetwarzanie na serwerze...');

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            console.log('[Modal Debug] API Response:', data);
            console.log('[Modal Debug] orders_created:', data.orders_created);
            console.log('[Modal Debug] products_created:', data.products_created);

            this.updateSaveProgressBar(80, 'Finalizowanie...');

            if (data.success) {
                this.syncResults = data;
                this.stats.savedOrders = data.orders_created || 0;
                this.stats.savedProducts = data.products_created || 0;
                this.stats.skippedProducts = data.products_skipped || 0;

                this.addLog('success', `Zapisano pomyślnie: ${this.stats.savedOrders} zamówień, ${this.stats.savedProducts} produktów`);

                // Symuluj krótkie opóźnienie dla UX
                await this.delay(1000);

                this.updateSaveProgressBar(100, 'Zapis zakończony!');

                // Pokaż wyniki
                this.showSaveResults();

                // Aktualizuj subtitle
                if (this.elements.syncStep4Subtitle) {
                    this.elements.syncStep4Subtitle.textContent = 'Synchronizacja zakończona pomyślnie';
                }

                // Pokaż toast sukcesu
                if (this.toastSystem) {
                    this.toastSystem.show(`Zapisano ${this.stats.savedProducts} produktów z ${this.stats.savedOrders} zamówień`, 'success');
                }

            } else {
                throw new Error(data.error || 'Nieznany błąd zapisu');
            }

        } catch (error) {
            console.error('[BL Sync Modal v2] Błąd zapisu zamówień:', error);
            this.addLog('error', `Błąd zapisu: ${error.message}`);
            this.updateSaveProgressBar(0, 'Błąd zapisu zamówień');
            if (this.toastSystem) {
                this.toastSystem.show(`Błąd zapisu zamówień: ${error.message}`, 'error');
            }

            // Pokaż przycisk Finish jako "Zamknij"
            if (this.elements.step4Finish) {
                this.elements.step4Finish.innerHTML = '<i class="fas fa-times"></i> Zamknij';
                this.elements.step4Finish.style.display = 'block';
            }

        } finally {
            this.syncInProgress = false;
            this.updateSaveStats();
        }
    }

    /**
     * Pokazanie wyników zapisu
     */
    showSaveResults() {
        if (!this.elements.syncSaveResults) return;

        // Przygotuj podsumowanie
        let summaryHTML = `
            <div style="margin-bottom: 16px;">
                <div style="font-size: 18px; margin-bottom: 8px;">
                    ✅ <strong>${this.stats.savedOrders}</strong> zamówień utworzonych<br>
                    ✅ <strong>${this.stats.savedProducts}</strong> produktów dodanych do produkcji
                </div>
        `;

        if (this.stats.skippedProducts > 0) {
            summaryHTML += `
                <div style="color: #d97706; margin-top: 8px;">
                    ⚠️ ${this.stats.skippedProducts} produktów pominięto (filtrowanie)
                </div>
            `;
        }

        summaryHTML += '</div>';

        if (this.syncResults && this.syncResults.summary) {
            summaryHTML += `<div style="font-size: 14px; color: #6b7280; text-align: left;">${this.syncResults.summary}</div>`;
        }

        if (this.elements.syncSaveResultsSummary) {
            this.elements.syncSaveResultsSummary.innerHTML = summaryHTML;
        }

        // Pokaż sekcję wyników
        this.elements.syncSaveResults.style.display = 'block';

        // Pokaż przycisk Finish
        if (this.elements.step4Finish) {
            this.elements.step4Finish.innerHTML = '<i class="fas fa-check"></i> Zakończ';
            this.elements.step4Finish.style.display = 'block';
        }
    }

    // ============================================================================
    // METODY POMOCNICZE
    // ============================================================================

    /**
     * Aktualizacja progress bara (krok 2)
     */
    updateProgressBar(percentage, message) {
        if (this.elements.syncProgressBarFill) {
            this.elements.syncProgressBarFill.style.width = `${percentage}%`;
        }

        if (this.elements.syncProgressText) {
            this.elements.syncProgressText.textContent = message || '';
        }
    }

    /**
     * Aktualizacja progress bara zapisu (krok 4)
     */
    updateSaveProgressBar(percentage, message) {
        if (this.elements.syncSaveProgressBarFill) {
            this.elements.syncSaveProgressBarFill.style.width = `${percentage}%`;
        }

        if (this.elements.syncSaveProgressText) {
            this.elements.syncSaveProgressText.textContent = message || '';
        }
    }

    /**
     * Aktualizacja statystyk (krok 2)
     */
    updateStats() {
        if (this.elements.statApiPages) {
            this.elements.statApiPages.textContent = this.stats.apiPages;
        }

        if (this.elements.statOrdersCount) {
            this.elements.statOrdersCount.textContent = this.stats.ordersCount;
        }
    }

    /**
     * Aktualizacja statystyk zapisu (krok 4)
     */
    updateSaveStats() {
        console.log('[Modal Debug] updateSaveStats called with:', {
            savedOrders: this.stats.savedOrders,
            savedProducts: this.stats.savedProducts,
            allStats: this.stats
        });

        if (this.elements.statSaveOrders) {
            this.elements.statSaveOrders.textContent = this.stats.savedOrders;
        }

        if (this.elements.statSaveProducts) {
            this.elements.statSaveProducts.textContent = this.stats.savedProducts;
        }

        if (this.elements.statSaveSkipped) {
            this.elements.statSaveSkipped.textContent = this.stats.skippedProducts;
        }
    }

    /**
     * Dodanie wpisu do logów
     */
    addLog(type, message) {
        const timestamp = new Date().toLocaleTimeString('pl-PL');
        const logEntry = {
            type: type, // 'info', 'success', 'warning', 'error'
            time: timestamp,
            message: message
        };

        this.syncLogs.push(logEntry);

        // Ogranicz liczbę logów
        if (this.syncLogs.length > 100) {
            this.syncLogs = this.syncLogs.slice(-100);
        }

        // Aktualizuj wyświetlanie
        this.updateLogsDisplay();

        console.log(`[BL Sync Modal v2] Log [${type}]: ${message}`);
    }

    /**
     * Aktualizacja wyświetlania logów
     */
    updateLogsDisplay() {
        if (!this.elements.syncLogsContent) return;

        const logsHTML = this.syncLogs.map(log => `
            <div class="sync-log-entry ${log.type}">
                <span class="sync-log-time">${log.time}</span>
                <span class="sync-log-message">${log.message}</span>
            </div>
        `).join('');

        this.elements.syncLogsContent.innerHTML = logsHTML;

        // Przewiń na dół
        this.elements.syncLogsContent.scrollTop = this.elements.syncLogsContent.scrollHeight;
    }

    /**
     * Toggle widoczności logów (krok 2)
     */
    toggleLogs() {
        const logsContainer = this.elements.syncLogsContent?.parentElement;
        if (!logsContainer) return;

        const isVisible = logsContainer.style.maxHeight !== '0px';

        if (isVisible) {
            logsContainer.style.maxHeight = '0px';
            logsContainer.style.padding = '0 16px';
        } else {
            logsContainer.style.maxHeight = '200px';
            logsContainer.style.padding = '';
        }

        // Aktualizuj ikonę przycisku
        if (this.elements.syncLogsToggle) {
            const icon = this.elements.syncLogsToggle.querySelector('i');
            if (icon) {
                icon.className = isVisible ? 'fas fa-eye' : 'fas fa-eye-slash';
            }
        }
    }

    /**
     * Formatowanie daty
     */
    formatDate(dateString) {
        if (!dateString) return '—';

        try {
            const date = new Date(dateString);
            return date.toLocaleDateString('pl-PL', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric'
            });
        } catch (error) {
            return '—';
        }
    }

    /**
     * Pobieranie nazwy statusu
     */
    getStatusName(statusId) {
        const status = this.availableStatuses.find(s => s.id === statusId);
        return status ? status.name : `Status ${statusId}`;
    }

    /**
     * Pobieranie klasy CSS statusu
     */
    getStatusClass(statusId) {
        const status = this.availableStatuses.find(s => s.id === statusId);
        if (!status) return 'unknown';

        const statusName = status.name.toLowerCase();

        if (statusName.includes('new-paid') || statusName.includes('nowe - opłacone')) return 'new-paid';

        if (statusName.includes('new-topay') || statusName.includes('nowe - nieopłacone')) return 'new-topaid';

        if (statusName.includes('new-topay') || statusName.includes('nowe - nieopłacone')) return 'new-topaid';

        if (statusName.includes('production') || statusName.includes('w produkcj')) return 'production';

        if (statusName.includes('ready') || statusName.includes('produkcja zakończona')) return 'ready';

        if (statusName.includes('tosend') || statusName.includes('paczka zgłoszona')) return 'to-send';

        if (statusName.includes('shipped') || statusName.includes('wysłan') || statusName.includes('odbiór osobisty')) return 'shipped';

        if (statusName.includes('odebrane') || statusName.includes('dostarcz')) return 'delivered';

        if (statusName.includes('odebrane') || statusName.includes('dostarcz')) return 'delivered';

        return 'other';
    }

    /**
     * Pokazanie toast notification
     */
    showToast(message, type = 'info') {
        // Sprawdź czy istnieje globalna funkcja toast
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
            return;
        }

        // Fallback - użyj alert
        if (type === 'error') {
            alert(`Błąd: ${message}`);
        } else if (type === 'success') {
            alert(`Sukces: ${message}`);
        } else {
            alert(message);
        }
    }

    /**
     * Opóźnienie (dla UX)
     */
    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// ============================================================================
// GLOBALNA INSTANCJA I FUNKCJE
// ============================================================================

/**
 * Globalna instancja modalu
 */
let dashboardBLSyncModal = null;

/**
 * Inicjalizacja po załadowaniu DOM z opóźnieniem
 */
function initializeBLSyncModal() {
    console.log('[BL Sync Modal v2] Inicjalizacja z opóźnieniem...');

    try {
        // FIX: Zawsze sprawdź czy modal istnieje w DOM - może zniknąć po odświeżeniu dashboard
        const modalElement = document.getElementById('baselinkerSyncModal');
        if (!modalElement) {
            console.warn('[BL Sync Modal v2] Element modalu nie znaleziony - prawdopodobnie po odświeżeniu dashboard');

            // Reset globalnej instancji jeśli modal zniknął
            if (dashboardBLSyncModal) {
                dashboardBLSyncModal = null;
                window.dashboardBLSyncModal = null;
            }

            return false;
        }

        // FIX: Jeśli modal istnieje ale instancja została utracona, utwórz nową
        if (!dashboardBLSyncModal) {
            dashboardBLSyncModal = new DashboardBLSyncModal();

            // Przypisz do window dla dostępu globalnego
            window.dashboardBLSyncModal = dashboardBLSyncModal;

            console.log('[BL Sync Modal v2] Modal zainicjalizowany i gotowy');
            return true;
        }

        // FIX: Jeśli instancja istnieje ale modalElement się zmienił, odśwież referencję
        if (dashboardBLSyncModal.modalElement !== modalElement) {
            console.log('[BL Sync Modal v2] Odświeżanie referencji do modalu po odświeżeniu dashboard');
            dashboardBLSyncModal.modalElement = modalElement;
            dashboardBLSyncModal.cacheElements();
            dashboardBLSyncModal.setupEventListeners();
        }

        return true;
    } catch (error) {
        console.error('[BL Sync Modal v2] Błąd inicjalizacji:', error);
        return false;
    }
}

/**
 * Globalne funkcje API
 */

/**
 * Pokazuje modal synchronizacji z Baselinkerem
 */
window.showBaselinkerSyncModal = function () {
    console.log('[BL Sync Modal v2] Wywołano showBaselinkerSyncModal()');

    if (!dashboardBLSyncModal) {
        console.warn('[BL Sync Modal v2] Modal nie zainicjalizowany, próba opóźnionej inicjalizacji...');

        // Spróbuj zainicjalizować z małym opóźnieniem
        setTimeout(() => {
            if (initializeBLSyncModal()) {
                dashboardBLSyncModal.openModal();
            } else {
                console.error('[BL Sync Modal v2] Nie udało się zainicjalizować modalu');
                alert('Modal synchronizacji nie jest dostępny. Spróbuj odświeżyć stronę.');
            }
        }, 100);
        return;
    }

    dashboardBLSyncModal.openModal();
};

/**
 * Ukrywa modal synchronizacji
 */
window.hideBaselinkerSyncModal = function () {
    console.log('[BL Sync Modal v2] Wywołano hideBaselinkerSyncModal()');

    if (dashboardBLSyncModal) {
        dashboardBLSyncModal.closeModal();
    }
};

/**
 * Sprawdza czy modal jest aktywny
 */
window.isBaselinkerSyncModalActive = function () {
    return dashboardBLSyncModal ? dashboardBLSyncModal.isOpen : false;
};

/**
 * Sprawdza czy synchronizacja jest w toku
 */
window.isBaselinkerSyncInProgress = function () {
    return dashboardBLSyncModal ? dashboardBLSyncModal.syncInProgress : false;
};

// ============================================================================
// INTEGRACJA Z DASHBOARD REFRESH - FIX dla problemu po odświeżeniu
// ============================================================================

/**
 * Nasłuchuje na event dashboard:refreshed i reinicjalizuje modal
 */
function setupDashboardRefreshListener() {
    // FIX: EventBus jest pod window.ProductionShared.eventBus (małe 'e')
    let eventBus = null;

    if (window.ProductionShared?.eventBus) {
        eventBus = window.ProductionShared.eventBus;
        console.log('[BL Sync Modal v2] EventBus znaleziony w ProductionShared.eventBus');
    } else if (window.ProductionShared?.EventBus) {
        eventBus = window.ProductionShared.EventBus;
        console.log('[BL Sync Modal v2] EventBus znaleziony w ProductionShared.EventBus');
    } else if (window.SharedServices?.EventBus) {
        eventBus = window.SharedServices.EventBus;
        console.log('[BL Sync Modal v2] EventBus znaleziony w SharedServices');
    } else if (window.EventBus) {
        eventBus = window.EventBus;
        console.log('[BL Sync Modal v2] EventBus znaleziony w window');
    }

    if (eventBus) {
        eventBus.on('dashboard:refreshed', function () {
            console.log('[BL Sync Modal v2] Dashboard odświeżony - sprawdzanie modalu...');

            setTimeout(() => {
                const modalExists = document.getElementById('baselinkerSyncModal');
                if (modalExists && !dashboardBLSyncModal) {
                    console.log('[BL Sync Modal v2] Reinicjalizacja po odświeżeniu dashboard');
                    initializeBLSyncModal();
                    integratWithDashboardModule();
                    attachToSyncButtons();
                } else if (!modalExists) {
                    console.warn('[BL Sync Modal v2] Modal zniknął po odświeżeniu dashboard');
                    dashboardBLSyncModal = null;
                    window.dashboardBLSyncModal = null;
                }
            }, 500);
        });

        console.log('[BL Sync Modal v2] Nasłuch na dashboard:refreshed skonfigurowany');
    } else {
        console.log('[BL Sync Modal v2] EventBus niedostępny - sprawdź obiekty window');
    }
}

/**
 * Integracja z istniejącym DashboardModule
 * Zastąp metodę handleManualSync przekierowaniem do nowego modalu
 */
function integratWithDashboardModule() {
    if (typeof window.DashboardModule !== 'undefined') {
        console.log('[BL Sync Modal v2] Integracja z DashboardModule');

        // Zachowaj oryginalną metodę jako backup
        if (window.DashboardModule.handleManualSync) {
            window.DashboardModule.originalHandleManualSync = window.DashboardModule.handleManualSync;
        }

        // Zastąp metodę nową implementacją
        window.DashboardModule.handleManualSync = function () {
            console.log('[Dashboard Module] handleManualSync przekierowane do nowego modalu v2');
            window.showBaselinkerSyncModal();
        };

        console.log('[BL Sync Modal v2] Integracja z DashboardModule ukończona');
    } else {
        console.log('[BL Sync Modal v2] DashboardModule nie znaleziony - modal będzie działał niezależnie');
    }
}

// ============================================================================
// AUTOMATYCZNE PODŁĄCZANIE DO PRZYCISKÓW SYNCHRONIZACJI
// ============================================================================

/**
 * Automatyczne podłączanie do przycisków synchronizacji w DOM
 */
function attachToSyncButtons() {
    const syncButtons = document.querySelectorAll(
        '#manual-sync-btn, .manual-sync-btn, [data-action="manual-sync"], [data-sync="baselinker"]'
    );

    if (syncButtons.length > 0) {
        console.log(`[BL Sync Modal v2] Znaleziono ${syncButtons.length} przycisk(ów) synchronizacji`);

        syncButtons.forEach((btn, index) => {
            // Usuń poprzednie event listenery
            const newBtn = btn.cloneNode(true);
            btn.parentNode.replaceChild(newBtn, btn);

            // Dodaj nowy event listener
            newBtn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();

                console.log(`[BL Sync Modal v2] Kliknięto przycisk synchronizacji #${index}`);
                window.showBaselinkerSyncModal();
            });
        });

        console.log('[BL Sync Modal v2] Przyciski synchronizacji podłączone');
    } else {
        console.warn('[BL Sync Modal v2] Nie znaleziono przycisków synchronizacji do podłączenia');
    }
}

// ============================================================================
// INICJALIZACJA I STARTUP
// ============================================================================

/**
 * Główna funkcja startup z opóźnieniem dla template rendering
 */
function startupBLSyncModal() {
    console.log('[BL Sync Modal v2] Startup modalu z opóźnieniem 1s...');

    // Opóźnienie 1s na renderowanie template przez Flask/Jinja
    setTimeout(() => {
        console.log('[BL Sync Modal v2] Rozpoczynanie inicjalizacji po opóźnieniu...');

        // 1. Inicjalizuj modal
        const modalInitialized = initializeBLSyncModal();

        if (modalInitialized) {
            // 2. Integracja z DashboardModule (tylko jeśli modal się zainicjalizował)
            integratWithDashboardModule();

            // 3. Podłącz do przycisków
            attachToSyncButtons();

            // 4. FIX: Skonfiguruj nasłuch na refresh dashboard
            setupDashboardRefreshListener();

            console.log('[BL Sync Modal v2] Startup ukończony pomyślnie');
        } else {
            console.warn('[BL Sync Modal v2] Startup nieudany - modal nie został znaleziony');

            // Dodatkowe fallback po kolejnych 2 sekundach
            setTimeout(() => {
                console.log('[BL Sync Modal v2] Final retry startup...');
                const finalTry = initializeBLSyncModal();

                if (finalTry) {
                    integratWithDashboardModule();
                    attachToSyncButtons();
                    setupDashboardRefreshListener();
                    console.log('[BL Sync Modal v2] Startup ukończony w final retry');
                } else {
                    console.error('[BL Sync Modal v2] Final startup failed - template może nie być wyrenderowany');
                }
            }, 2000);
        }

    }, 1000); // 1 sekunda opóźnienia na renderowanie template
}

// ============================================================================
// EVENT LISTENERS I AUTO-STARTUP Z OPÓŹNIENIEM
// ============================================================================

// Startup po załadowaniu DOM
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startupBLSyncModal);
} else {
    // DOM już załadowany - uruchom z opóźnieniem
    startupBLSyncModal();
}

// Usuwamy stare fallbacki - mamy teraz kontrolowane opóźnienie w startupBLSyncModal

// ============================================================================
// DEBUG FUNCTIONS (dostępne w konsoli deweloperskiej)
// ============================================================================

if (typeof window.debugMode !== 'undefined' && window.debugMode) {
    window.debugBLSyncModalV2 = {
        showModal: () => window.showBaselinkerSyncModal(),
        hideModal: () => window.hideBaselinkerSyncModal(),
        getInstance: () => dashboardBLSyncModal,
        isActive: () => window.isBaselinkerSyncModalActive(),
        isInProgress: () => window.isBaselinkerSyncInProgress(),
        resetModal: () => dashboardBLSyncModal?.resetModalState(),
        getStats: () => dashboardBLSyncModal?.stats,
        getLogs: () => dashboardBLSyncModal?.syncLogs,
        getCurrentStep: () => dashboardBLSyncModal?.currentStep,
        getSelectedOrders: () => dashboardBLSyncModal?.selectedOrders,
        getFetchedOrders: () => dashboardBLSyncModal?.fetchedOrders,

        // Test functions
        testStep: (stepNumber) => dashboardBLSyncModal?.goToStep(stepNumber),
        testLog: (type, message) => dashboardBLSyncModal?.addLog(type, message),
        testProgress: (percentage, message) => dashboardBLSyncModal?.updateProgressBar(percentage, message),
        testToast: (message, type) => dashboardBLSyncModal?.showToast(message, type)
    };

    console.log('[BL Sync Modal v2] Debug functions dostępne w window.debugBLSyncModalV2');
    console.log('Dostępne metody debugowania:', Object.keys(window.debugBLSyncModalV2));
}

// ============================================================================
// EXPORT DLA MODUŁÓW ES6 (jeśli potrzebne)
// ============================================================================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        DashboardBLSyncModal,
        showBaselinkerSyncModal: window.showBaselinkerSyncModal,
        hideBaselinkerSyncModal: window.hideBaselinkerSyncModal,
        isBaselinkerSyncModalActive: window.isBaselinkerSyncModalActive
    };
}

console.log('[BL Sync Modal v2] Plik załadowany pomyślnie - wersja 2.0 (Refactor Complete)');