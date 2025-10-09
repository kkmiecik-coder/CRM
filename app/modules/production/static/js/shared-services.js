/**
 * Shared Services dla Production Module - shared-services.js
 * ====================================
 * 
 * Wspólne serwisy używane przez wszystkie moduły:
 * - ApiClient: Unified API communication
 * - ToastSystem: Notifications system
 * - LoadingManager: Loading states management
 * - EventBus: Inter-module communication
 * 
 * Autor: Konrad Kmiecik
 * Wersja: 1.0
 * Data: 2025-01-15
 */

// ============================================================================
// EVENT BUS - Komunikacja między modułami
// ============================================================================

class EventBus {
    constructor() {
        this.events = new Map();
        this.debugMode = false;
    }

    on(eventName, handler, context = null) {
        if (!this.events.has(eventName)) {
            this.events.set(eventName, []);
        }

        const listener = { handler, context };
        this.events.get(eventName).push(listener);

        if (this.debugMode) {
            console.log(`[EventBus] Registered listener for: ${eventName}`);
        }

        // Return unsubscribe function
        return () => {
            const listeners = this.events.get(eventName);
            if (listeners) {
                const index = listeners.indexOf(listener);
                if (index > -1) {
                    listeners.splice(index, 1);
                }
            }
        };
    }

    emit(eventName, data = null) {
        if (this.debugMode) {
            console.log(`[EventBus] Emitting event: ${eventName}`, data);
        }

        const listeners = this.events.get(eventName);
        if (!listeners) return;

        listeners.forEach(({ handler, context }) => {
            try {
                if (context) {
                    handler.call(context, data);
                } else {
                    handler(data);
                }
            } catch (error) {
                console.error(`[EventBus] Error in event handler for ${eventName}:`, error);
            }
        });
    }

    off(eventName, handler = null) {
        if (!handler) {
            // Remove all listeners for event
            this.events.delete(eventName);
        } else {
            // Remove specific handler
            const listeners = this.events.get(eventName);
            if (listeners) {
                const filtered = listeners.filter(l => l.handler !== handler);
                this.events.set(eventName, filtered);
            }
        }
    }

    clear() {
        this.events.clear();
    }

    enableDebug() {
        this.debugMode = true;
    }
}

// ============================================================================
// API CLIENT - Unified API communication
// ============================================================================

class ApiClient {
    constructor() {
        this.baseUrl = '/production/api';
        this.defaultHeaders = {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        };
        this.requestCache = new Map();
        this.cacheTimeout = 30000; // 30 seconds
    }

    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const config = {
            headers: { ...this.defaultHeaders, ...options.headers },
            ...options
        };

        // Check cache for GET requests
        if ((!options.method || options.method === 'GET') && !options.skipCache) {
            const cached = this.getFromCache(url);
            if (cached) {
                return cached;
            }
        }

        try {
            const response = await fetch(url, config);
            const result = await this.handleResponse(response);

            // Cache successful GET responses
            if ((!options.method || options.method === 'GET') && result.success) {
                this.setCache(url, result);
            }

            return result;

        } catch (error) {
            console.error(`[ApiClient] Request failed: ${endpoint}`, error);
            throw error;
        }
    }

    async getSystemHealth() {
        try {
            const response = await this.request('/health');
            
            // Przekształć format odpowiedzi
            return {
                success: true,
                health: {
                    database_status: response.components?.database === 'error' ? 'error' : 'connected',
                    sync_status: response.status === 'healthy' ? 'completed' : 'warning', 
                    errors_24h: response.pending_errors || 0,
                    total_unresolved_errors: response.pending_errors || 0,
                    last_sync: response.last_sync,
                    baselinker_api_avg_ms: 0
                }
            };
        } catch (error) {
            return { success: false, error: error.message };
        }
    }

    async requestAdmin(endpoint, options = {}) {
        const url = `/production/admin${endpoint}`;
        const config = {
            headers: { ...this.defaultHeaders, ...options.headers },
            ...options
        };

        try {
            const response = await fetch(url, config);
            return await this.handleResponse(response);
        } catch (error) {
            console.error(`[ApiClient] Admin request failed: ${endpoint}`, error);
            throw error;
        }
    }

    async handleResponse(response) {
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errorText}`);
        }

        const contentType = response.headers.get('Content-Type');
        if (contentType && contentType.includes('application/json')) {
            return await response.json();
        } else {
            return { success: true, data: await response.text() };
        }
    }

    getFromCache(url) {
        const cached = this.requestCache.get(url);
        if (cached && (Date.now() - cached.timestamp) < this.cacheTimeout) {
            console.log(`[ApiClient] Using cached response for: ${url}`);
            return cached.data;
        }
        return null;
    }

    setCache(url, data) {
        this.requestCache.set(url, {
            data: data,
            timestamp: Date.now()
        });
    }

    clearCache() {
        this.requestCache.clear();
    }

    // Convenience methods for common endpoints
    async getDashboardStats() {
        return this.request('/dashboard-stats');
    }

    /**
     * Pobiera zawartość taba dashboard
     * @param {boolean} initialLoad - czy to pierwsze ładowanie (template + dane) czy tylko dane
     */
    async getDashboardTabContent(initialLoad = false) {
        const params = initialLoad ? '?initial_load=true' : '';
        const endpoint = `/dashboard-tab-content${params}`;

        console.log(`[ApiClient] Pobieranie dashboard tab content (initialLoad: ${initialLoad})`);
        return this.request(endpoint);
    }

    async getProductsTabContent(filters = {}) {
        const params = new URLSearchParams();
        Object.entries(filters).forEach(([key, value]) => {
            if (value !== null && value !== '' && value !== 'all') {
                params.append(key, value);
            }
        });

        const endpoint = `/products-tab-content${params.toString() ? '?' + params.toString() : ''}`;
        return this.request(endpoint);
    }

    async getStationsTabContent() {
        return this.request('/stations-tab-content');
    }

    async getReportsTabContent() {
        return this.request('/reports-tab-content');  
    }

    async getConfigTabContent() {
        return this.request('/config-tab-content');
    }

    async getFilteredProducts(filters) {
        const params = new URLSearchParams();
        Object.entries(filters).forEach(([key, value]) => {
            if (value !== null && value !== '' && value !== 'all') {
                params.append(key, value);
            }
        });

        return this.request(`/products-filtered?${params.toString()}`);
    }

    async updateProductPriority(productId, priority) {
        return this.request('/update-priority', {
            method: 'POST',
            body: JSON.stringify({
                product_id: productId,
                new_priority: priority
            })
        });
    }

    async triggerManualSync(options = {}) {
        const {
            syncType = 'incremental',
            targetStatusIds = null,
            limit = null
        } = options;
        
        const payload = {
            sync_type: syncType,
            initiated_by: 'dashboard_manual_trigger',
            timestamp: new Date().toISOString()
        };
        
        // Dodaj opcjonalne parametry jeśli zostały podane
        if (targetStatusIds && Array.isArray(targetStatusIds)) {
            payload.target_status_ids = targetStatusIds;
        }
        
        if (limit && typeof limit === 'number') {
            payload.limit = limit;
        }
        
        try {
            console.log('[ApiClient] Triggering manual sync with payload:', payload);
            
            const response = await this.request('/manual-sync', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });
            
            console.log('[ApiClient] Manual sync response:', response);
            return response;
            
        } catch (error) {
            console.error('[ApiClient] Manual sync failed:', error);
            
            // Przekaż bardziej szczegółowy błąd
            if (error.message.includes('HTTP 500')) {
                throw new Error('Błąd serwera podczas synchronizacji. Sprawdź logi backendu.');
            } else if (error.message.includes('HTTP 400')) {
                throw new Error('Nieprawidłowe parametry synchronizacji.');
            } else if (error.message.includes('HTTP 409')) {
                throw new Error('Synchronizacja jest już w toku.');
            }
            
            throw error;
        }
    }

    async getSystemErrors() {
        return this.requestAdmin('/ajax/system-errors', {
            method: 'GET',
            headers: { Accept: 'application/json' }
        });
    }

    async clearSystemErrors() {
        return this.requestAdmin('/ajax/clear-system-errors', {
            method: 'POST'
        });
    }

    // ============================================================================
    // NOWE METODY - dla refaktoryzacji odświeżania dashboard
    // ============================================================================

    /**
     * Pobiera dane dashboard bez HTML (tylko JSON)
     */
    async getDashboardData() {
        console.log('[ApiClient] Pobieranie danych dashboard...');
        return this.request('/dashboard-data');
    }

    /**
     * Pobiera status produkcji bez HTML (tylko JSON)
     */
    async getProductionStatusData() {
        console.log('[ApiClient] Pobieranie statusu produkcji...');
        return this.request('/production-status-data');
    }

    /**
     * Pobiera statystyki dashboard bez HTML (tylko JSON)
     */
    async getDashboardStatsData() {
        console.log('[ApiClient] Pobieranie statystyk dashboard...');
        return this.request('/dashboard-stats-data');
    }
}

// ============================================================================
// TOAST SYSTEM - Unified notifications
// ============================================================================

class ToastSystem {
    constructor() {
        this.container = null;
        this.toasts = new Map();
        this.nextId = 1;
        this.maxToasts = 5;
        this.defaultDuration = 5000;

        this.init();
    }

    init() {
        this.createContainer();
        this.addStyles();
    }

    createContainer() {
        if (document.getElementById('toast-container')) return;

        this.container = document.createElement('div');
        this.container.id = 'toast-container';
        this.container.className = 'toast-container';
        this.container.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10000;
            max-width: 400px;
            pointer-events: none;
        `;

        document.body.appendChild(this.container);
    }

    addStyles() {
        if (document.getElementById('toast-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'toast-styles';
        styles.textContent = `
            .toast-item {
                pointer-events: auto;
                background: white;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                margin-bottom: 10px;
                padding: 16px;
                display: flex;
                align-items: flex-start;
                gap: 12px;
                opacity: 0;
                transform: translateX(100%);
                transition: all 0.3s ease;
                border-left: 4px solid #ddd;
                word-wrap: break-word;
            }
            
            .toast-item.show {
                opacity: 1;
                transform: translateX(0);
            }
            
            .toast-item.success { border-left-color: #10b981; }
            .toast-item.error { border-left-color: #ef4444; }
            .toast-item.warning { border-left-color: #f59e0b; }
            .toast-item.info { border-left-color: #3b82f6; }
            
            .toast-icon {
                flex-shrink: 0;
                width: 24px;
                height: 24px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            
            .toast-icon.success { background: #10b981; }
            .toast-icon.error { background: #ef4444; }
            .toast-icon.warning { background: #f59e0b; }
            .toast-icon.info { background: #3b82f6; }
            
            .toast-content {
                flex: 1;
                min-width: 0;
            }
            
            .toast-title {
                font-weight: 600;
                font-size: 14px;
                color: #1f2937;
                margin-bottom: 4px;
            }
            
            .toast-message {
                font-size: 13px;
                color: #6b7280;
                line-height: 1.4;
            }
            
            .toast-close {
                position: absolute;
                top: 8px;
                right: 8px;
                background: none;
                border: none;
                color: #9ca3af;
                cursor: pointer;
                font-size: 16px;
                line-height: 1;
                padding: 4px;
                border-radius: 4px;
                transition: color 0.2s ease;
            }
            
            .toast-close:hover {
                color: #ef4444;
                background: #fef2f2;
            }
        `;

        document.head.appendChild(styles);
    }

    show(message, type = 'info', options = {}) {
        const id = this.nextId++;
        const duration = options.duration || this.defaultDuration;

        const toast = this.createToast(id, message, type, options);
        this.toasts.set(id, toast);

        this.container.appendChild(toast.element);

        // Animate in
        setTimeout(() => {
            toast.element.classList.add('show');
        }, 50);

        // Auto-hide
        if (duration > 0 && !options.persistent) {
            setTimeout(() => {
                this.hide(id);
            }, duration);
        }

        this.enforceMaxToasts();

        return id;
    }

    createToast(id, message, type, options) {
        const element = document.createElement('div');
        element.className = `toast-item ${type}`;
        element.style.position = 'relative';

        const icons = {
            success: '✓',
            error: '✕',
            warning: '⚠',
            info: 'ℹ'
        };

        const titles = {
            success: 'Sukces',
            error: 'Błąd',
            warning: 'Ostrzeżenie',
            info: 'Informacja'
        };

        element.innerHTML = `
            <div class="toast-icon ${type}">${icons[type] || icons.info}</div>
            <div class="toast-content">
                <div class="toast-title">${titles[type] || titles.info}</div>
                <div class="toast-message">${message}</div>
            </div>
            <button class="toast-close" onclick="ProductionShared.toastSystem.hide(${id})">×</button>
        `;

        return {
            id,
            element,
            type,
            message,
            persistent: options.persistent
        };
    }

    hide(id) {
        const toast = this.toasts.get(id);
        if (!toast) return;

        toast.element.classList.remove('show');

        setTimeout(() => {
            if (toast.element.parentNode) {
                toast.element.parentNode.removeChild(toast.element);
            }
            this.toasts.delete(id);
        }, 300);
    }

    enforceMaxToasts() {
        if (this.toasts.size <= this.maxToasts) return;

        const sortedToasts = Array.from(this.toasts.values())
            .filter(toast => !toast.persistent)
            .sort((a, b) => a.id - b.id);

        const toRemove = sortedToasts.slice(0, this.toasts.size - this.maxToasts);
        toRemove.forEach(toast => this.hide(toast.id));
    }

    clearAll() {
        Array.from(this.toasts.keys()).forEach(id => this.hide(id));
    }
}

// ============================================================================
// LOADING MANAGER - Loading states management
// ============================================================================

class LoadingManager {
    constructor() {
        this.activeLoaders = new Set();
        this.globalSpinner = null;
        this.createGlobalSpinner();
    }

    createGlobalSpinner() {
        if (document.getElementById('global-spinner')) return;

        this.globalSpinner = document.createElement('div');
        this.globalSpinner.id = 'global-spinner';
        this.globalSpinner.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.5);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 9999;
        `;

        this.globalSpinner.innerHTML = `
            <div style="
                display: flex;
                flex-direction: column;
                padding: 24px 32px;
                gap: 20px;
                color: #314254;
                align-items: center;
                background-color: #fff;
                border-radius: var(--border-radius-lg);
                    ">
                    <div style="
                        width: 50px;
                        height: 50px;
                        border: 4px solid #f3f3f3;
                        border-top: 4px solid #3498db;
                        border-radius: 50%;
                        animation: spin 1s linear infinite;
                    "></div>
                    <div id="spinner-message" style="
                        color: #314254;
                        font-size: 16px;
                        font-weight: 500;
                        font-family: Poppins, sans-serif;
                    ">Ładowanie...</div>
            </div>
        `;

        // Add spin animation
        const style = document.createElement('style');
        style.textContent = `
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
        `;
        document.head.appendChild(style);

        document.body.appendChild(this.globalSpinner);
    }

    show(context, message = 'Ładowanie...') {
        this.activeLoaders.add(context);

        const messageElement = document.getElementById('spinner-message');
        if (messageElement) {
            messageElement.textContent = message;
        }

        this.globalSpinner.style.display = 'flex';

        console.log(`[LoadingManager] Loading started: ${context}`);
    }

    hide(context) {
        this.activeLoaders.delete(context);

        if (this.activeLoaders.size === 0) {
            this.globalSpinner.style.display = 'none';
        }

        console.log(`[LoadingManager] Loading finished: ${context}`);
    }

    isLoading(context = null) {
        if (context) {
            return this.activeLoaders.has(context);
        }
        return this.activeLoaders.size > 0;
    }

    clear() {
        this.activeLoaders.clear();
        this.globalSpinner.style.display = 'none';
    }
}

// ============================================================================
// DATA REFRESH SERVICE - Nowa klasa dla refaktoryzacji odświeżania
// ============================================================================

/**
 * Serwis zarządzania odświeżaniem danych widgetów
 * Rozdziela odświeżanie danych od ładowania template
 */
class DataRefreshService {
    constructor(apiClient) {
        this.apiClient = apiClient;
        this.refreshHandlers = new Map();
        this.isRefreshing = false;
        this.lastRefresh = null;
    }

    /**
     * Rejestracja handlera odświeżania dla konkretnego widgetu
     * @param {string} widgetName - nazwa widgetu (np. 'stations', 'totals')
     * @param {function} handler - funkcja odświeżająca dane widgetu
     */
    registerRefreshHandler(widgetName, handler) {
        if (typeof handler !== 'function') {
            console.error(`[DataRefreshService] Handler dla ${widgetName} musi być funkcją`);
            return;
        }

        this.refreshHandlers.set(widgetName, handler);
        console.log(`[DataRefreshService] Zarejestrowano handler dla widgetu: ${widgetName}`);
    }

    /**
     * Odświeżenie konkretnego widgetu
     * @param {string} widgetName - nazwa widgetu do odświeżenia
     */
    async refreshWidget(widgetName) {
        const handler = this.refreshHandlers.get(widgetName);
        if (!handler) {
            console.warn(`[DataRefreshService] Brak handlera dla widgetu: ${widgetName}`);
            return;
        }

        try {
            console.log(`[DataRefreshService] Odświeżanie widgetu: ${widgetName}`);
            await handler();
            console.log(`[DataRefreshService] Widget ${widgetName} odświeżony pomyślnie`);
        } catch (error) {
            console.error(`[DataRefreshService] Błąd odświeżania widgetu ${widgetName}:`, error);
            throw error;
        }
    }

    /**
     * Odświeżenie wszystkich zarejestrowanych widgetów
     */
    async refreshAllWidgets() {
        if (this.isRefreshing) {
            console.log('[DataRefreshService] Odświeżanie już w toku, pomijam');
            return;
        }

        this.isRefreshing = true;
        const startTime = Date.now();

        try {
            console.log(`[DataRefreshService] Rozpoczynam odświeżanie ${this.refreshHandlers.size} widgetów`);

            const refreshPromises = [];
            for (const [widgetName, handler] of this.refreshHandlers) {
                refreshPromises.push(
                    this.refreshWidget(widgetName).catch(error => {
                        console.error(`[DataRefreshService] Widget ${widgetName} failed:`, error);
                        return { widgetName, error }; // Nie przerywamy innych
                    })
                );
            }

            const results = await Promise.allSettled(refreshPromises);
            const duration = Date.now() - startTime;

            // Policz sukcesy i błędy
            const successful = results.filter(r => r.status === 'fulfilled' && !r.value?.error).length;
            const failed = results.filter(r => r.status === 'rejected' || r.value?.error).length;

            this.lastRefresh = new Date();

            console.log(`[DataRefreshService] Odświeżanie zakończone: ${successful} sukces, ${failed} błędów (${duration}ms)`);

            if (failed > 0) {
                throw new Error(`${failed} widgetów nie udało się odświeżyć`);
            }

        } finally {
            this.isRefreshing = false;
        }
    }

    /**
     * Sprawdza czy jest w trakcie odświeżania
     */
    isCurrentlyRefreshing() {
        return this.isRefreshing;
    }

    /**
     * Zwraca czas ostatniego odświeżenia
     */
    getLastRefreshTime() {
        return this.lastRefresh;
    }

    /**
     * Usuwa handler dla widgetu
     */
    unregisterRefreshHandler(widgetName) {
        if (this.refreshHandlers.has(widgetName)) {
            this.refreshHandlers.delete(widgetName);
            console.log(`[DataRefreshService] Usunięto handler dla widgetu: ${widgetName}`);
        }
    }

    /**
     * Czyści wszystkie handlery
     */
    clearAllHandlers() {
        const count = this.refreshHandlers.size;
        this.refreshHandlers.clear();
        console.log(`[DataRefreshService] Wyczyszczono ${count} handlerów`);
    }

    /**
     * Zwraca listę zarejestrowanych widgetów
     */
    getRegisteredWidgets() {
        return Array.from(this.refreshHandlers.keys());
    }
}

// ============================================================================
// GLOBAL NAMESPACE - Shared services
// ============================================================================

window.ProductionShared = {
    eventBus: new EventBus(),
    apiClient: new ApiClient(),
    toastSystem: new ToastSystem(),
    loadingManager: new LoadingManager(),

    // Utility functions
    utils: {
        debounce(func, wait) {
            let timeout;
            return function executedFunction(...args) {
                const later = () => {
                    clearTimeout(timeout);
                    func(...args);
                };
                clearTimeout(timeout);
                timeout = setTimeout(later, wait);
            };
        },

        formatDate(dateString) {
            if (!dateString) return '-';
            try {
                const date = new Date(dateString);
                return date.toLocaleDateString('pl-PL');
            } catch (error) {
                return dateString;
            }
        },

        formatCurrency(amount) {
            if (amount === null || amount === undefined) return '-';
            try {
                return new Intl.NumberFormat('pl-PL', {
                    style: 'currency',
                    currency: 'PLN'
                }).format(amount);
            } catch (error) {
                return amount + ' PLN';
            }
        }
    }
};

// Enable debug mode if needed
if (window.PRODUCTION_CONFIG && window.PRODUCTION_CONFIG.debug) {
    ProductionShared.eventBus.enableDebug();
}

console.log('[Shared Services] Initialized successfully');