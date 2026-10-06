/**
 * Production App Loader - Główny kontroler aplikacji - production-app-loader.js
 * ==================================================
 *
 * Odpowiedzialności:
 * - Inicjalizacja aplikacji
 * - Zarządzanie systemem tabów AJAX
 * - Ładowanie modułów na żądanie
 * - Koordynacja między modułami
 * - Zarządzanie stanem globalnym
 *
 * Autor: Konrad Kmiecik
 * Wersja: 2.0
 * Data: 2025-01-15
 */

// ============================================================================
// MAIN APPLICATION CLASS
// ============================================================================

console.log('[ProductionApp] Checking required dependencies...');
console.log('- ProductionShared:', typeof window.ProductionShared !== 'undefined');
console.log('- DashboardModule:', typeof DashboardModule !== 'undefined');
console.log('- ProductsModule:', typeof ProductsModule !== 'undefined');

// Jeśli DashboardModule nie istnieje, może trzeba go załadować dynamicznie
if (typeof DashboardModule === 'undefined') {
    console.warn('[ProductionApp] DashboardModule not found! Dashboard functionality will be limited.');
}

class ProductionApp {
    constructor() {
        this.shared = window.ProductionShared;

        this.state = {
            currentTab: null,
            isInitialized: false,
            loadedModules: new Map(),
            isLoading: false,
            tabCache: new Map(), // tracks which tabs have been loaded
        };

        this.modules = {};

        // Hot tabs loaded on page entry
        this.HOT_TABS = ['dashboard-tab', 'products-tab'];

        this.handleTabClick = this.handleTabClick.bind(this);
        this.handleVisibilityChange = this.handleVisibilityChange.bind(this);
        this.handleBeforeUnload = this.handleBeforeUnload.bind(this);
    }

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    async init() {
        if (this.state.isInitialized) {
            console.warn('[ProductionApp] Already initialized');
            return;
        }

        console.log('[ProductionApp] Initializing...');

        this.setupEventListeners();
        this.initTabSystem();

        // Determine initial tab from URL param or default
        const initialTab = this.getInitialTabFromURL();
        this.updateTabUI(initialTab);
        this.state.currentTab = initialTab;

        // Prefetch hot tabs in parallel
        await this.prefetchHotTabs(initialTab);

        this.state.isInitialized = true;
        this.shared.eventBus.emit('app:ready', { tab: initialTab });
        console.log('[ProductionApp] Initialized successfully');
    }

    // ========================================================================
    // URL SYNC
    // ========================================================================

    getInitialTabFromURL() {
        const params = new URLSearchParams(window.location.search);
        const tabParam = params.get('tab');
        if (tabParam) {
            const tabName = tabParam.endsWith('-tab') ? tabParam : `${tabParam}-tab`;
            const validTabs = ['dashboard-tab', 'products-tab', 'archive-tab',
                               'sawmill-tab', 'reports-tab', 'workers-tab', 'config-tab'];
            if (validTabs.includes(tabName)) {
                return tabName;
            }
        }
        return 'dashboard-tab';
    }

    updateURL(tabName) {
        const shortName = tabName.replace('-tab', '');
        const params = new URLSearchParams(window.location.search);
        if (shortName === 'dashboard') {
            params.delete('tab');
        } else {
            params.set('tab', shortName);
        }
        // `sub` (podzakładka Raportów) należy wyłącznie do Raportów. Bez tego
        // zostaje w pasku adresu po przejściu na inną zakładkę i wraca duchem
        // przy odświeżeniu strony.
        if (shortName !== 'reports') params.delete('sub');
        const newURL = params.toString()
            ? `${window.location.pathname}?${params.toString()}`
            : window.location.pathname;
        history.replaceState(null, '', newURL);
    }

    // ========================================================================
    // PREFETCH HOT TABS
    // ========================================================================

    async prefetchHotTabs(initialTab) {
        const isHot = this.HOT_TABS.includes(initialTab);

        // Always load the initial tab first (user sees it)
        console.log(`[ProductionApp] Loading initial tab: ${initialTab}`);
        await this.loadTabContent(initialTab);

        // Then prefetch remaining hot tabs in background
        const remainingHot = this.HOT_TABS.filter(t => t !== initialTab);
        if (remainingHot.length > 0) {
            console.log(`[ProductionApp] Prefetching hot tabs: ${remainingHot.join(', ')}`);
            Promise.all(remainingHot.map(tab => this.loadTabContent(tab))).catch(err => {
                console.warn('[ProductionApp] Background prefetch error:', err);
            });
        }
    }

    setupEventListeners() {
        // Tab navigation
        document.addEventListener('click', this.handleTabClick);

        // Page visibility changes
        document.addEventListener('visibilitychange', this.handleVisibilityChange);

        // Before page unload
        window.addEventListener('beforeunload', this.handleBeforeUnload);

        // Global shortcuts
        document.addEventListener('keydown', this.handleKeyboardShortcuts.bind(this));

        console.log('[ProductionApp] Global event listeners attached');
    }

    // ========================================================================
    // TAB SYSTEM
    // ========================================================================

    initTabSystem() {
        // Find all tab buttons
        const tabButtons = document.querySelectorAll('[data-bs-toggle="tab"]');

        tabButtons.forEach(button => {
            // Remove any existing listeners to avoid conflicts
            button.removeEventListener('click', this.handleTabClick);

            // Add our custom handler
            button.addEventListener('click', (e) => {
                e.preventDefault();
                const tabName = this.extractTabNameFromButton(button);
                if (tabName) {
                    this.switchToTab(tabName);
                }
            });
        });

        console.log(`[ProductionApp] Tab system initialized (${tabButtons.length} tabs)`);
    }

    extractTabNameFromButton(button) {
        const target = button.getAttribute('data-bs-target');
        if (target) {
            return target.replace('#', '').replace('-content', '');
        }
        return button.id?.replace('-tab', '') || null;
    }

    async switchToTab(tabName) {
        if (!tabName) {
            console.error('[ProductionApp] switchToTab called with null/undefined tabName');
            return;
        }

        if (this.state.isLoading) {
            console.log('[ProductionApp] Tab switch ignored - currently loading');
            return;
        }

        if (this.state.currentTab === tabName) {
            console.log(`[ProductionApp] Already on tab: ${tabName}`);
            return;
        }

        console.log(`[ProductionApp] Switching to ${tabName}`);

        try {
            // 1. Update UI immediately (tabs + panes)
            this.updateTabUI(tabName);
            this.state.currentTab = tabName;
            this.updateURL(tabName);

            // Powrót na Raporty z cache nie przeładowuje zakładki, więc nikt nie
            // odtworzyłby `?sub=` skasowanego przez updateURL przy wyjściu.
            // Tylko dla zakładki już zbudowanej — świeże wejście ustawia
            // podzakładkę samo, w initReportsTab.
            if (tabName === 'reports-tab' && this.state.tabCache.has(tabName)) {
                window.ReportsShared?.przywrocPodzakladke?.();
            }

            // 2. If tab not cached, load it
            if (!this.state.tabCache.has(tabName)) {
                this.state.isLoading = true;
                await this.loadTabContent(tabName);
            }

            // 3. Emit event
            this.shared.eventBus.emit('tab:changed', { tab: tabName });

        } catch (error) {
            console.error(`[ProductionApp] Error switching to tab ${tabName}:`, error);
            this.shared.toastSystem.show(`Błąd ładowania zakładki: ${error.message}`, 'error');
        } finally {
            this.state.isLoading = false;
        }
    }

    updateTabUI(tabName) {
        // Update tab buttons
        document.querySelectorAll('[data-bs-toggle="tab"]').forEach(button => {
            const buttonTabName = this.extractTabNameFromButton(button);
            if (buttonTabName === tabName) {
                button.classList.add('active');
                button.setAttribute('aria-selected', 'true');
            } else {
                button.classList.remove('active');
                button.setAttribute('aria-selected', 'false');
            }
        });

        // Update tab content containers
        document.querySelectorAll('.tab-pane').forEach(pane => {
            if (pane.id === `${tabName}-content`) {
                pane.classList.add('show', 'active');
            } else {
                pane.classList.remove('show', 'active');
            }
        });
    }

    async loadTabContent(tabName) {
        // Check if Baselinker sync modal is active
        if (typeof window.isBaselinkerSyncModalActive === 'function' && window.isBaselinkerSyncModalActive()) {
            console.log('[ProductionApp] Cannot load tab - sync modal active');
            return;
        }

        if (this.state.tabCache.has(tabName)) {
            console.log(`[ProductionApp] Tab ${tabName} already cached`);
            return;
        }

        console.log(`[ProductionApp] Loading tab content: ${tabName}`);

        const normalizedTabName = tabName.endsWith('-tab') ? tabName : `${tabName}-tab`;

        switch (normalizedTabName) {
            case 'dashboard-tab': await this.loadDashboardTab(); break;
            case 'products-tab': await this.loadProductsTab(); break;
            case 'archive-tab': await this.loadArchiveTab(); break;
            case 'sawmill-tab': await this.loadSawmillTab(); break;
            case 'reports-tab': await this.loadReportsTab(); break;
            case 'workers-tab': await this.loadWorkersTab(); break;
            case 'config-tab': await this.loadConfigTab(); break;
            default: throw new Error(`Unknown tab: ${normalizedTabName}`);
        }

        this.state.tabCache.set(tabName, true);
    }

    // ========================================================================
    // TAB LOADERS
    // ========================================================================

    async loadDashboardTab() {
        console.log('[ProductionApp] Loading dashboard tab...');
        try {
            const response = await this.shared.apiClient.getDashboardTabContent();
            if (!response.success) throw new Error(response.error || 'Failed to load dashboard');

            const wrapper = document.getElementById('dashboard-tab-wrapper');
            const skeleton = document.getElementById('dashboard-tab-skeleton');

            if (wrapper) {
                wrapper.innerHTML = response.html;
                wrapper.style.display = 'block';
                wrapper.classList.add('fade-in');
            }
            if (skeleton) skeleton.classList.add('hidden');

            await this.initializeDashboardModule();
            console.log('[ProductionApp] Dashboard tab loaded');
        } catch (error) {
            console.error('[ProductionApp] Dashboard loading failed:', error);
            this.showTabError('dashboard-tab', error.message);
            throw error;
        }
    }

    async loadProductsTab() {
        console.log('[ProductionApp] Loading products tab...');
        try {
            const response = await this.shared.apiClient.getProductsTabContent();
            if (!response.success) throw new Error(response.error || 'Failed to load products');

            const wrapper = document.getElementById('products-tab-wrapper');
            const skeleton = document.getElementById('products-tab-skeleton');

            if (wrapper) {
                wrapper.innerHTML = response.html;
                wrapper.style.display = 'block';
                wrapper.classList.add('fade-in');
            }
            if (skeleton) skeleton.classList.add('hidden');

            await this.initializeProductsModule();
            console.log('[ProductionApp] Products tab loaded');
        } catch (error) {
            console.error('[ProductionApp] Products loading failed:', error);
            this.showTabError('products-tab', error.message);
            throw error;
        }
    }

    async loadArchiveTab() {
        console.log('[ProductionApp] Loading archive tab...');
        try {
            const response = await this.shared.apiClient.getProductsTabContent({ view: 'archive' });
            if (!response.success) throw new Error(response.error || 'Failed to load archive');

            const wrapper = document.getElementById('archive-tab-wrapper');
            const skeleton = document.getElementById('archive-tab-skeleton');

            if (wrapper) {
                wrapper.innerHTML = response.html;
                wrapper.style.display = 'block';
                wrapper.classList.add('fade-in');
            }
            if (skeleton) skeleton.classList.add('hidden');

            await this.initializeArchiveModule(response.initial_data);
            console.log('[ProductionApp] Archive tab loaded');
        } catch (error) {
            console.error('[ProductionApp] Archive loading failed:', error);
            this.showTabError('archive-tab', error.message);
            throw error;
        }
    }

    /**
     * Ładowanie zakładki Trakownia. W przeciwieństwie do pozostałych tabów,
     * endpoint /production/api/sawmill/tab-content zwraca gotowy HTML
     * (render_template), NIE JSON {success, html} — trakownia ma własny
     * blueprint (sawmill_panel_bp) poza wspólnym ApiClient.request(), więc
     * pobieramy go bezpośrednio przez fetch() zamiast this.shared.apiClient.
     */
    async loadSawmillTab() {
        console.log('[ProductionApp] Loading sawmill tab...');
        try {
            const response = await fetch('/production/api/sawmill/tab-content', {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });

            if (!response.ok) {
                if (response.status === 403) {
                    throw new Error('Brak dostępu do modułu produkcji');
                }
                throw new Error(`HTTP ${response.status}`);
            }

            const html = await response.text();
            const container = document.getElementById('sawmill-tab-content');

            if (container) {
                container.innerHTML = html;
                // innerHTML nie wykonuje <script src="...">, więc trzeba je
                // ręcznie "odtworzyć" — tak samo jak w loadReportsTab().
                this.executeInlineScripts(container);
            }

            console.log('[ProductionApp] Sawmill tab loaded');
        } catch (error) {
            console.error('[ProductionApp] Sawmill loading failed:', error);
            this.showTabError('sawmill-tab', error.message);
            throw error;
        }
    }

    /**
     * Ładowanie zakładki Pracownicy. Jak trakownia: endpoint
     * /production/api/workers/tab-content zwraca gotowy HTML (render_template),
     * nie JSON {success, html}, więc pobieramy go zwykłym fetch().
     */
    async loadWorkersTab() {
        console.log('[ProductionApp] Loading workers tab...');
        try {
            const response = await fetch('/production/api/workers/tab-content', {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });

            if (!response.ok) {
                if (response.status === 403) {
                    throw new Error('Brak dostępu do modułu produkcji');
                }
                throw new Error(`HTTP ${response.status}`);
            }

            const html = await response.text();
            const container = document.getElementById('workers-tab-content');

            if (container) {
                container.innerHTML = html;
                // innerHTML nie wykonuje <script>, a obsługa CRUD siedzi inline
                // w templatce — bez tego przyciski byłyby martwe.
                this.executeInlineScripts(container);
            }

            console.log('[ProductionApp] Workers tab loaded');
        } catch (error) {
            console.error('[ProductionApp] Workers loading failed:', error);
            this.showTabError('workers-tab', error.message);
            throw error;
        }
    }

    async loadReportsTab() {
        console.log('[ProductionApp] Loading reports tab...');

        try {
            const response = await this.shared.apiClient.getReportsTabContent();

            if (response.success) {
                const wrapper = document.getElementById('reports-tab-wrapper');
                const loading = document.getElementById('reports-tab-loading');

                if (wrapper) {
                    wrapper.innerHTML = response.html;
                    wrapper.style.display = 'block';

                    // Wykonaj skrypty inline z załadowanego HTML
                    this.executeInlineScripts(wrapper);
                }

                if (loading) {
                    loading.style.display = 'none';
                }

                // Poczekaj chwilę na wykonanie skryptów, potem zainicjalizuj wykresy
                setTimeout(() => {
                    if (typeof initReportsTab === 'function') {
                        console.log('[ProductionApp] Initializing reports charts...');
                        initReportsTab();
                    } else {
                        console.error('[ProductionApp] initReportsTab function not found after script execution!');
                    }
                }, 50);
            } else {
                throw new Error(response.error || 'Failed to load reports');
            }
        } catch (error) {
            console.error('[ProductionApp] Reports loading failed:', error);
            this.showTabError('reports-tab', error.message);
            throw error;
        }
    }



    async loadConfigTab() {
        console.log('[ProductionApp] Loading config tab...');

        // Konfiguracja dostępna dla wszystkich użytkowników z dostępem do modułu production
        try {
            const response = await this.shared.apiClient.getConfigTabContent();

            if (response.success) {
                const wrapper = document.getElementById('config-tab-wrapper');
                const loading = document.getElementById('config-tab-loading');

                if (wrapper) {
                    wrapper.innerHTML = response.html;
                    wrapper.style.display = 'block';
                }

                if (loading) {
                    loading.style.display = 'none';
                }

                if (window.configModule) {
                    console.log('[ProductionApp] Triggering loadOriginalValuesFromDOM...');
                    window.configModule.loadOriginalValuesFromDOM();
                } else {
                    console.error('[ProductionApp] configModule not found!');
                }
            } else {
                throw new Error(response.error || 'Failed to load config');
            }
        } catch (error) {
            console.error('[ProductionApp] Config loading failed:', error);
            this.showTabError('config-tab', error.message);
            throw error;
        }
    }

    // ========================================================================
    // TAB LIFECYCLE
    // ========================================================================

    async cleanupTab(tabName) {
        // Sprawdź czy tabName nie jest null/undefined
        if (!tabName) {
            console.log('[ProductionApp] No tab to cleanup');
            return;
        }

        console.log(`[ProductionApp] Cleaning up tab: ${tabName}`);

        // NOWE: Określ nazwę modułu na podstawie taba
        let moduleName = tabName.replace('-tab', '');

        // Specjalne mapowanie jeśli potrzebne
        if (moduleName === 'dashboard') {
            moduleName = 'dashboard';
        }

        const module = this.state.loadedModules.get(moduleName);

        if (module && typeof module.unload === 'function') {
            try {
                await module.unload();
                this.state.loadedModules.delete(moduleName);
                console.log(`[ProductionApp] Module ${moduleName} unloaded and removed`);
            } catch (error) {
                console.warn(`[ProductionApp] Error unloading module ${moduleName}:`, error);
            }
        }

        // Hide any tab-specific loading/error states
        this.hideTabLoading(tabName);
        this.hideTabError(tabName);
    }

    showTabLoading(tabName) {
        const loadingElement = document.getElementById(`${tabName}-loading`);
        const wrapperElement = document.getElementById(`${tabName}-wrapper`);
        const errorElement = document.getElementById(`${tabName}-error`);

        if (loadingElement) loadingElement.style.display = 'block';
        if (wrapperElement) wrapperElement.style.display = 'none';
        if (errorElement) errorElement.style.display = 'none';
    }

    hideTabLoading(tabName) {
        const loadingElement = document.getElementById(`${tabName}-loading`);
        if (loadingElement) loadingElement.style.display = 'none';
    }

    showTabError(tabName, message) {
        const errorElement = document.getElementById(`${tabName}-error`);
        const messageElement = document.getElementById(`${tabName}-error-message`);

        if (errorElement) {
            errorElement.style.display = 'block';
            if (messageElement) {
                messageElement.textContent = message;
            }
        }
    }

    hideTabError(tabName) {
        const errorElement = document.getElementById(`${tabName}-error`);
        if (errorElement) errorElement.style.display = 'none';
    }

    /**
     * Wykonuje skrypty inline z dynamicznie załadowanego HTML
     * innerHTML nie wykonuje tagów <script>, trzeba je ręcznie przetworzyć
     */
    executeInlineScripts(container) {
        const scripts = container.querySelectorAll('script');
        scripts.forEach(oldScript => {
            const newScript = document.createElement('script');

            // Kopiuj atrybuty
            Array.from(oldScript.attributes).forEach(attr => {
                newScript.setAttribute(attr.name, attr.value);
            });

            // Kopiuj zawartość
            newScript.textContent = oldScript.textContent;

            // Zamień stary skrypt na nowy (to spowoduje wykonanie)
            oldScript.parentNode.replaceChild(newScript, oldScript);
        });

        console.log(`[ProductionApp] Executed ${scripts.length} inline scripts`);
    }

    // ========================================================================
    // MANUAL REFRESH (used by error recovery + forceRefresh)
    // ========================================================================

    async refreshActiveTab() {
        const tabName = this.state.currentTab;
        if (!tabName || this.state.isLoading) return;

        if (typeof window.isBaselinkerSyncModalActive === 'function' && window.isBaselinkerSyncModalActive()) {
            console.log('[ProductionApp] Skipping refresh - sync modal active');
            return;
        }

        console.log(`[ProductionApp] Refreshing active tab: ${tabName}`);

        try {
            // Delegate to module if it has a refresh method
            const moduleName = tabName.replace('-tab', '');
            const module = this.state.loadedModules.get(moduleName);
            if (module && typeof module.refresh === 'function') {
                await module.refresh();
            } else {
                // Fallback: reload tab HTML
                this.state.tabCache.delete(tabName);
                await this.loadTabContent(tabName);
            }
        } catch (error) {
            console.error(`[ProductionApp] Refresh failed for ${tabName}:`, error);
        }
    }

    // ========================================================================
    // EVENT HANDLERS
    // ========================================================================

    handleTabClick(event) {
        // Kliknięcie ikony "otwórz" na kafelku stanowiska w gridzie na
        // dashboardzie (np. kafelek trakowni, [data-goto-tab="sawmill-tab"]).
        // Obsługa musi siedzieć tu (delegacja na document, ten sam listener
        // co przełączanie zakładek w pasku nawigacji), a nie w module danego
        // stanowiska — dashboard-tab jest w HOT_TABS i renderuje się od razu,
        // zanim leniwie ładowany moduł stanowiska zdąży się załadować i
        // podpiąć własny listener. Działa też dla treści wstawianej AJAX-em
        // po fakcie, bo listener wisi na document, nie na elemencie kafelka.
        const gotoTabLink = event.target.closest('[data-goto-tab]');
        if (gotoTabLink) {
            event.preventDefault();
            const tabName = gotoTabLink.getAttribute('data-goto-tab');
            if (tabName) {
                this.switchToTab(tabName);
            }
            return;
        }

        // Let Bootstrap handle the visual tab switching
        // We'll override the content loading
        const button = event.target.closest('[data-bs-toggle="tab"]');
        if (!button) return;

        // Extract tab name and load content
        const tabName = this.extractTabNameFromButton(button);
        if (tabName && tabName !== this.state.currentTab) {
            // Prevent default Bootstrap behavior for content loading
            event.preventDefault();

            // Handle tab switch ourselves
            this.switchToTab(tabName);
        }
    }

    handleVisibilityChange() {
        if (document.hidden) {
            console.log('[ProductionApp] Page hidden');
        } else {
            console.log('[ProductionApp] Page visible');
        }
    }

    handleBeforeUnload(event) {
        // Cleanup loaded modules
        this.state.loadedModules.forEach(async (module, name) => {
            if (typeof module.cleanup === 'function') {
                try {
                    await module.cleanup();
                } catch (error) {
                    console.warn(`[ProductionApp] Cleanup error for ${name}:`, error);
                }
            }
        });
    }

    handleKeyboardShortcuts(event) {
        // Tab navigation shortcuts (Ctrl+1, Ctrl+2, etc.)
        if (event.ctrlKey && event.key >= '1' && event.key <= '6') {
            event.preventDefault();
            const tabIndex = parseInt(event.key) - 1;
            const tabs = ['dashboard-tab', 'products-tab', 'archive-tab',
                          'sawmill-tab', 'reports-tab', 'config-tab'];

            if (tabs[tabIndex]) {
                this.switchToTab(tabs[tabIndex]);
            }
        }
    }

    // ========================================================================
    // INITIALIZATION HELPERS
    // ========================================================================

    async initializeDashboardModule() {
        console.log('[ProductionApp] Initializing DashboardModule...');

        try {
            // Sprawdź czy DashboardModule jest dostępny
            if (typeof DashboardModule === 'undefined') {
                console.error('[ProductionApp] DashboardModule class not found! Make sure dashboard-module.js is loaded.');
                return;
            }

            // Usuń poprzednią instancję jeśli istnieje
            if (this.state.loadedModules.has('dashboard')) {
                const existingModule = this.state.loadedModules.get('dashboard');
                if (existingModule && typeof existingModule.unload === 'function') {
                    await existingModule.unload();
                }
            }

            // Utwórz nową instancję DashboardModule
            const dashboardModule = new DashboardModule(this.shared, this.config);

            // Załaduj moduł
            await dashboardModule.load();

            // Zapisz w state
            this.state.loadedModules.set('dashboard', dashboardModule);
            this.modules['dashboard-tab'] = dashboardModule;

            console.log('[ProductionApp] DashboardModule initialized successfully');

        } catch (error) {
            console.error('[ProductionApp] Failed to initialize DashboardModule:', error);
            throw error;
        }
    }

    async initializeArchiveModule(initialData) {
        console.log('[ProductionApp] Initializing ArchiveModule...');

        if (typeof ArchiveModule === 'undefined') {
            console.error('[ProductionApp] ArchiveModule not available');
            this.shared.toastSystem.show('ArchiveModule nie jest dostępny', 'error');
            return;
        }

        try {
            const archiveModule = new ArchiveModule(this.shared, this.config);
            await archiveModule.load(initialData);

            this.state.loadedModules.set('archive', archiveModule);
            this.modules['archive-tab'] = archiveModule;
            window.archiveModule = archiveModule;

            console.log('[ProductionApp] ArchiveModule initialized successfully');
        } catch (error) {
            console.error('[ProductionApp] Failed to initialize ArchiveModule:', error);
            this.shared.toastSystem.show('Błąd inicjalizacji archiwum: ' + error.message, 'error');
            throw error;
        }
    }

    async initializeProductsModule() {
        console.log('[ProductionApp] Initializing ProductsModule...');

        if (typeof ProductsModule === 'undefined') {
            console.error('[ProductionApp] ProductsModule not available');
            this.shared.toastSystem.show('ProductsModule nie jest dostępny', 'error');
            return;
        }

        try {
            const productsModule = new ProductsModule(this.shared, this.config);
            await productsModule.load();

            // Store reference to module
            this.state.loadedModules.set('products', productsModule);
            this.modules['products-tab'] = productsModule;

            console.log('[ProductsApp] ProductsModule initialized successfully');

            // Ustaw globalną referencję dla template onclick handlers
            window.productsModule = productsModule;

        } catch (error) {
            console.error('[ProductionApp] Failed to initialize ProductsModule:', error);
            this.shared.toastSystem.show('Błąd inicjalizacji modułu produktów: ' + error.message, 'error');
            throw error;
        }
    }

    // ========================================================================
    // PUBLIC API
    // ========================================================================

    getCurrentTab() {
        return this.state.currentTab;
    }

    getLoadedModules() {
        return Array.from(this.state.loadedModules.keys());
    }

    isTabLoaded(tabName) {
        return this.state.loadedModules.has(tabName.replace('-tab', ''));
    }

    async forceRefresh() {
        await this.refreshActiveTab();
    }

    debugModuleState() {
        console.log('[ProductionApp] Current module state:');
        console.log('- Loaded modules:', Array.from(this.state.loadedModules.keys()));
        console.log('- Current tab:', this.state.currentTab);
        console.log('- Is loading:', this.state.isLoading);
        console.log('- Tab cache:', Array.from(this.state.tabCache.keys()));

        // Sprawdź czy DashboardModule istnieje globalnie
        console.log('- DashboardModule available:', typeof DashboardModule !== 'undefined');

        // Sprawdź czy dashboard module jest załadowany
        const dashboardModule = this.state.loadedModules.get('dashboard');
        if (dashboardModule) {
            console.log('- Dashboard module loaded:', dashboardModule.isLoaded);
        } else {
            console.log('- Dashboard module: NOT LOADED');
        }
    }
}

// ============================================================================
// AUTO-INITIALIZATION
// ============================================================================

let productionApp = null;

function initProductionApp() {
    if (productionApp) {
        console.warn('[ProductionApp] Already initialized');
        return productionApp;
    }

    // Wait for shared services
    if (typeof window.ProductionShared === 'undefined') {
        console.error('[ProductionApp] Shared services not loaded');
        return null;
    }

    productionApp = new ProductionApp();

    // Make available globally for debugging
    window.ProductionApp = productionApp;

    // Initialize
    productionApp.init().catch(error => {
        console.error('[ProductionApp] Failed to initialize:', error);
    });

    return productionApp;
}

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initProductionApp);
} else {
    // DOM already loaded
    setTimeout(initProductionApp, 100);
}

// Export for manual initialization if needed
window.initProductionApp = initProductionApp;
