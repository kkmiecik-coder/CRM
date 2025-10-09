// station-common.js - WSPÓLNE FUNKCJE DLA WSZYSTKICH STANOWISK
// Wersja 2.0 - Nowy interfejs z dark mode

/**
 * Global state dla stanowiska
 */
window.STATION_STATE = {
    config: null,
    refreshTimer: null,
    countdownTimers: new Map(),
    isRefreshing: false,
    lastRefreshTime: Date.now()
};

/* ============================================================================
   INITIALIZATION & CONFIG
   ============================================================================ */

/**
 * Load station config from window.STATION_CONFIG
 * @returns {Object|null} Config object
 */
function loadStationConfig() {
    if (!window.STATION_CONFIG) {
        console.error('[Station] STATION_CONFIG not found in window');
        return null;
    }

    const config = {
        stationCode: window.STATION_CONFIG.stationCode,
        stationName: window.STATION_CONFIG.stationName,
        refreshInterval: window.STATION_CONFIG.refreshInterval || 30,
        autoRefreshEnabled: true,
        debugMode: window.STATION_CONFIG.debugMode || false,
        apiBaseUrl: '/production/api',
        ajaxBaseUrl: '/production/stations/ajax'
    };

    window.STATION_STATE.config = config;
    console.log('[Station] Config loaded:', config);
    return config;
}

/* ============================================================================
   DATETIME & REFRESH
   ============================================================================ */

/**
 * Update current datetime display
 */
function updateCurrentDatetime() {
    const datetimeElement = document.getElementById('current-datetime');
    if (!datetimeElement) return;

    const now = new Date();
    const days = ['Niedziela', 'Poniedziałek', 'Wtorek', 'Środa', 'Czwartek', 'Piątek', 'Sobota'];
    const dayName = days[now.getDay()];

    const date = now.toLocaleDateString('pl-PL', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
    });

    const time = now.toLocaleTimeString('pl-PL', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });

    datetimeElement.textContent = `${date} • ${time}`;

    // Update label if needed
    const labelElement = datetimeElement.previousElementSibling;
    if (labelElement && labelElement.classList.contains('stat-label')) {
        labelElement.textContent = dayName;
    }
}

/**
 * Start refresh countdown
 * @returns {number} Timer ID
 */
function startRefreshCountdown() {
    const config = window.STATION_STATE.config;
    if (!config) return;

    // Clear existing countdown if any
    if (window.STATION_STATE.countdownTimer) {
        clearInterval(window.STATION_STATE.countdownTimer);
    }

    let secondsLeft = config.refreshInterval;
    const countdownElement = document.getElementById('refresh-countdown');
    const refreshIcon = document.querySelector('.refresh-icon');

    const updateCountdown = () => {
        if (countdownElement) {
            countdownElement.textContent = `${secondsLeft}s`;

            // Add warning class when < 10s
            if (secondsLeft <= 10) {
                countdownElement.classList.add('warning');
            } else {
                countdownElement.classList.remove('warning');
            }

            // Spin icon when < 5s
            if (secondsLeft <= 5) {
                if (refreshIcon) refreshIcon.classList.add('spinning');
            } else {
                if (refreshIcon) refreshIcon.classList.remove('spinning');
            }
        }
    };

    updateCountdown();

    window.STATION_STATE.countdownTimer = setInterval(() => {
        secondsLeft--;

        if (secondsLeft <= 0) {
            secondsLeft = config.refreshInterval;
        }

        updateCountdown();
    }, 1000);

    return window.STATION_STATE.countdownTimer;
}

/**
 * Start auto-refresh with callback
 * @param {Function} callback - Callback function to execute on refresh
 */
function startAutoRefresh(callback) {
    const config = window.STATION_STATE.config;
    if (!config || !config.autoRefreshEnabled) return;

    console.log(`[Station] Starting auto-refresh (${config.refreshInterval}s)`);

    // Start datetime updater (every second)
    setInterval(updateCurrentDatetime, 1000);
    updateCurrentDatetime();

    // Start refresh countdown
    startRefreshCountdown();

    // Start auto-refresh timer
    window.STATION_STATE.refreshTimer = setInterval(callback, config.refreshInterval * 1000);
}

/**
 * Stop auto-refresh
 */
function stopAutoRefresh() {
    if (window.STATION_STATE.refreshTimer) {
        clearInterval(window.STATION_STATE.refreshTimer);
        window.STATION_STATE.refreshTimer = null;
        console.log('[Station] Auto-refresh stopped');
    }
}

/* ============================================================================
   API CALLS
   ============================================================================ */

/**
 * Fetch products for station
 * @param {string} stationCode - Station code
 * @param {string} sortBy - Sort order
 * @returns {Promise<Object>} Products and stats
 */
async function fetchProducts(stationCode, sortBy = 'priority') {
    try {
        const config = window.STATION_STATE.config;
        const url = `${config.ajaxBaseUrl}/products/${stationCode}?sort=${sortBy}`;

        const response = await fetch(url, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Unknown error');
        }

        return data.data;
    } catch (error) {
        console.error('[Station] Failed to fetch products:', error);
        throw error;
    }
}

/**
 * Complete a task
 * @param {string} productId - Product ID (short_product_id)
 * @param {string} stationCode - Station code
 * @returns {Promise<Object>} Response
 */
async function completeTask(productId, stationCode) {
    try {
        const config = window.STATION_STATE.config;
        const url = `${config.apiBaseUrl}/complete-task`;

        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                product_id: productId,
                station_code: stationCode
            })
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Task completion failed');
        }

        return data;
    } catch (error) {
        console.error('[Station] Task completion error:', error);
        throw error;
    }
}

/**
 * Fetch today's completed m3 for a station
 * @param {string} stationCode - Station code (cutting/assembly/packaging)
 * @returns {Promise<number>} Today's m3 value
 */
async function fetchTodayM3(stationCode) {
    try {
        const config = window.STATION_STATE.config;
        const url = `${config.ajaxBaseUrl}/station-today-m3/${stationCode}`;

        console.log(`[Station] Fetching today m3 for ${stationCode}`);

        const response = await fetch(url, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Failed to fetch today m3');
        }

        const todayM3 = data.data.today_m3 || 0.0;
        console.log(`[Station] Today m3 for ${stationCode}: ${todayM3}`);

        // Update display
        updateTodayM3Display(todayM3);

        return todayM3;

    } catch (error) {
        console.error(`[Station] Failed to fetch today m3:`, error);
        // Don't throw - just log error and keep current value
        return null;
    }
}

/**
 * Update today m3 display element
 * @param {number} m3Value - M3 value to display
 */
function updateTodayM3Display(m3Value) {
    const todayM3Element = document.getElementById('today-m3');

    if (!todayM3Element) {
        console.warn('[Station] today-m3 element not found');
        return;
    }

    // Format to 4 decimal places
    const formattedValue = parseFloat(m3Value).toFixed(4);

    // Add animation class for visual feedback
    todayM3Element.classList.add('updating');

    // Update value
    todayM3Element.textContent = formattedValue;

    // Remove animation class after animation completes
    setTimeout(() => {
        todayM3Element.classList.remove('updating');
    }, 300);

    console.log(`[Station] Updated today-m3 display: ${formattedValue}`);
}

/**
 * Increment today m3 by a volume amount (optimistic update)
 * Call this immediately after successful task completion
 * @param {number} volumeToAdd - Volume in m3 to add
 */
function incrementTodayM3(volumeToAdd) {
    const todayM3Element = document.getElementById('today-m3');

    if (!todayM3Element) {
        console.warn('[Station] today-m3 element not found for increment');
        return;
    }

    // Get current value
    const currentValue = parseFloat(todayM3Element.textContent) || 0.0;

    // Add new volume
    const newValue = currentValue + volumeToAdd;

    console.log(`[Station] Incrementing today-m3: ${currentValue} + ${volumeToAdd} = ${newValue}`);

    // Update display with animation
    updateTodayM3Display(newValue);
}

/* ============================================================================
   DOM MANIPULATION
   ============================================================================ */

/**
 * Smart merge products - only add new, don't touch processing cards
 * @param {Array} products - Array of products from API
 */
function smartMergeProducts(products) {
    const grid = document.getElementById('products-grid');
    if (!grid) return;

    const existingCards = Array.from(grid.querySelectorAll('.product-card'));
    const existingIds = new Set(existingCards.map(card => card.dataset.productId));
    const cardsInProgress = existingCards.filter(card => card.dataset.inProgress === 'true');
    const inProgressIds = new Set(cardsInProgress.map(card => card.dataset.productId));

    console.log(`[Station] Smart merge: ${products.length} from API, ${existingIds.size} in DOM, ${inProgressIds.size} in progress`);

    products.forEach(product => {
        if (!existingIds.has(product.id) && !inProgressIds.has(product.id)) {
            const cardHTML = createProductCard(product);
            grid.insertAdjacentHTML('beforeend', cardHTML);

            const newCard = grid.lastElementChild;
            if (newCard && newCard.classList.contains('product-card')) {
                attachCardEventListeners(newCard);
            }
        }
    });

    const emptyState = grid.querySelector('.empty-state');
    if (emptyState && products.length > 0) {
        emptyState.remove();
    }
}

/**
 * Create product card HTML (NOWY LAYOUT)
 * @param {Object} product - Product object
 * @returns {string} HTML string
 */
function createProductCard(product) {
    const escapeHtml = (str) => {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    };

    // Użyj gotowych wymiarów z backendu
    const dimensions = product.dimensions || 'Brak wymiarów';

    // Badges
    const speciesBadge = product.wood_species
        ? `<div class="badge badge-species">${escapeHtml(product.wood_species)}</div>`
        : '';
    const techBadge = product.technology
        ? `<div class="badge badge-technology">${escapeHtml(product.technology)}</div>`
        : '';
    const classBadge = product.wood_class
        ? `<div class="badge badge-class">${escapeHtml(product.wood_class)}</div>`
        : '';

    return `
    <div class="product-card"
         data-product-id="${escapeHtml(product.id)}"
         data-in-progress="false"
         data-priority-rank="${product.priority_rank || 999}"
         data-species="${escapeHtml(product.wood_species || '')}"
         data-technology="${escapeHtml(product.technology || '')}"
         data-wood-class="${escapeHtml(product.wood_class || '')}">
        
        <div class="card-header">
            <div class="header-ids">
                <span class="id-short">${escapeHtml(product.id)}</span>
                <span class="id-baselinker">BL-${escapeHtml(product.baselinker_order_id)}</span>
            </div>
            <div class="header-volume">${(product.volume_m3 || 0).toFixed(4)} m³</div>
        </div>
        
        <div class="card-badges">
            ${speciesBadge}
            ${techBadge}
            ${classBadge}
        </div>
        
        <div class="card-dimensions">
            <div class="dimensions-box">${dimensions}</div>
        </div>
        
        <div class="card-action">
            <button class="btn-complete" data-action="complete">ZAKOŃCZ</button>
        </div>
    </div>
    `;
}

/**
 * Remove product card with animation
 * @param {string} productId - Product ID
 */
function removeProductCard(productId) {
    const card = document.querySelector(`[data-product-id="${productId}"]`);
    if (card) {
        card.classList.add('removing');
        setTimeout(() => {
            card.remove();
            console.log(`[Station] Removed card: ${productId}`);

            // Check if empty
            const grid = document.getElementById('products-grid');
            const remainingCards = grid ? grid.querySelectorAll('.product-card').length : 0;
            if (remainingCards === 0) {
                showEmptyState();
            }
        }, 300);
    }
}

/**
 * Show empty state
 */
function showEmptyState() {
    const grid = document.getElementById('products-grid');
    if (!grid) return;

    const emptyHTML = `
        <div class="empty-state">
            <div class="empty-state-icon">✅</div>
            <h2>Brak produktów</h2>
            <p>Świetna robota! Wszystkie produkty zostały przetworzone.</p>
        </div>
    `;

    grid.innerHTML = emptyHTML;
}

/**
 * Update stats bar (NOWY FORMAT)
 * @param {Object} stats - Stats object
 */
function updateStatsBar(stats) {
    // Products count
    const totalElement = document.getElementById('total-products');
    if (totalElement) {
        totalElement.textContent = stats.total_products || 0;
    }

    // High priority count
    const priorityElement = document.getElementById('high-priority');
    if (priorityElement) {
        priorityElement.textContent = stats.high_priority_count || 0;
    }

    // Overdue count
    const overdueElement = document.getElementById('overdue-count');
    if (overdueElement) {
        overdueElement.textContent = stats.overdue_count || 0;
    }

    // Total volume - UŻYJ Z API
    const volumeElement = document.getElementById('total-volume');
    if (volumeElement && stats.total_volume !== undefined) {
        volumeElement.textContent = stats.total_volume.toFixed(4);
    }
}

/**
 * Show loading skeleton
 */
function showLoadingSkeleton() {
    const skeleton = document.getElementById('loading-skeleton');
    const grid = document.getElementById('products-grid');

    if (skeleton) skeleton.style.display = 'grid';
    if (grid) grid.style.display = 'none';
}

/**
 * Hide loading skeleton
 */
function hideLoadingSkeleton() {
    const skeleton = document.getElementById('loading-skeleton');
    const grid = document.getElementById('products-grid');

    if (skeleton) skeleton.style.display = 'none';
    if (grid) grid.style.display = 'grid';
}

/* ============================================================================
   TOAST NOTIFICATIONS
   ============================================================================ */

function showToast(message, type = 'info') {
    console.log(`[Toast] ${type.toUpperCase()}: ${message}`);
    // Tu możesz dodać faktyczną implementację toastów jeśli chcesz
}

function showSuccess(message) { showToast(message, 'success'); }
function showError(message) { showToast(message, 'error'); }
function showWarning(message) { showToast(message, 'warning'); }
function showInfo(message) { showToast(message, 'info'); }

/* ============================================================================
   UTILITIES
   ============================================================================ */

function getAllCards() {
    return Array.from(document.querySelectorAll('.product-card'));
}

function getCardById(productId) {
    return document.querySelector(`[data-product-id="${productId}"]`);
}

function isOnline() {
    return navigator.onLine;
}

function attachCardEventListeners(card) {
    // Zostanie nadpisane przez station-specific JS
    console.warn('[Station] attachCardEventListeners should be overridden by station-specific code');
}

/* ============================================================================
   CONNECTION MANAGEMENT - Offline Mode Detection
   ============================================================================ */

/**
 * Connection state management
 */
const CONNECTION_STATE = {
    isOnline: true,
    lastCheck: null,
    heartbeatInterval: null,
    listeners: [],
    checkInProgress: false
};

/**
 * Initialize connection monitor
 * Starts heartbeat and sets up event listeners
 */
function initConnectionMonitor() {
    console.log('[Connection] Initializing connection monitor');
    
    // Set initial state
    CONNECTION_STATE.isOnline = navigator.onLine;
    CONNECTION_STATE.lastCheck = Date.now();
    
    // Listen for browser online/offline events
    window.addEventListener('online', handleOnlineEvent);
    window.addEventListener('offline', handleOfflineEvent);
    
    // Start heartbeat
    startHeartbeat();
    
    // Initial check
    checkHealth();
    
    console.log('[Connection] Monitor initialized, initial state:', CONNECTION_STATE.isOnline ? 'ONLINE' : 'OFFLINE');
}

/**
 * Start heartbeat ping every 15 seconds
 */
function startHeartbeat() {
    if (CONNECTION_STATE.heartbeatInterval) {
        clearInterval(CONNECTION_STATE.heartbeatInterval);
    }
    
    CONNECTION_STATE.heartbeatInterval = setInterval(() => {
        // Only ping if navigator says we're online
        if (navigator.onLine) {
            checkHealth();
        }
    }, 15000); // 15 seconds
    
    console.log('[Connection] Heartbeat started (15s interval)');
}

/**
 * Stop heartbeat
 */
function stopHeartbeat() {
    if (CONNECTION_STATE.heartbeatInterval) {
        clearInterval(CONNECTION_STATE.heartbeatInterval);
        CONNECTION_STATE.heartbeatInterval = null;
        console.log('[Connection] Heartbeat stopped');
    }
}

/**
 * Check backend health via /production/api/station-health
 * @returns {Promise<boolean>} True if online, false if offline
 */
async function checkHealth() {
    // Prevent concurrent checks
    if (CONNECTION_STATE.checkInProgress) {
        console.log('[Connection] Health check already in progress, skipping');
        return CONNECTION_STATE.isOnline;
    }
    
    CONNECTION_STATE.checkInProgress = true;
    
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000); // 5s timeout
        
        const response = await fetch('/production/api/station-health', {
            method: 'GET',
            headers: {
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            },
            signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        
        if (response.ok) {
            const data = await response.json();
            const isHealthy = data.status === 'OK';
            
            CONNECTION_STATE.lastCheck = Date.now();
            
            if (isHealthy && !CONNECTION_STATE.isOnline) {
                // Transition OFFLINE → ONLINE
                handleOnline();
            } else if (!isHealthy && CONNECTION_STATE.isOnline) {
                // Transition ONLINE → OFFLINE
                handleOffline();
            }
            
            console.log('[Connection] Health check:', isHealthy ? 'OK' : 'ERROR');
            return isHealthy;
        } else {
            // HTTP error
            if (CONNECTION_STATE.isOnline) {
                handleOffline();
            }
            return false;
        }
        
    } catch (error) {
        // Timeout or network error
        console.warn('[Connection] Health check failed:', error.message);
        
        if (CONNECTION_STATE.isOnline) {
            handleOffline();
        }
        
        return false;
    } finally {
        CONNECTION_STATE.checkInProgress = false;
    }
}

/**
 * Handle browser 'online' event
 */
function handleOnlineEvent() {
    console.log('[Connection] Browser event: online');
    // Don't trust navigator.onLine blindly - verify with ping
    checkHealth();
}

/**
 * Handle browser 'offline' event
 */
function handleOfflineEvent() {
    console.log('[Connection] Browser event: offline');
    // Instant offline
    handleOffline();
}

/**
 * Transition to ONLINE state
 */
function handleOnline() {
    if (CONNECTION_STATE.isOnline) return; // Already online
    
    console.log('[Connection] State: OFFLINE → ONLINE');
    CONNECTION_STATE.isOnline = true;
    
    updateConnectionUI();
    notifyListeners(true);
    
    // Show success toast
    showSuccess('Połączenie przywrócone - możesz kontynuować pracę');
}

/**
 * Transition to OFFLINE state
 */
function handleOffline() {
    if (!CONNECTION_STATE.isOnline) return; // Already offline
    
    console.log('[Connection] State: ONLINE → OFFLINE');
    CONNECTION_STATE.isOnline = false;
    
    updateConnectionUI();
    notifyListeners(false);
    
    // Banner will be shown, no toast needed
}

/**
 * Update connection UI (badge and banner)
 */
function updateConnectionUI() {
    const badge = document.getElementById('connection-status');
    const banner = document.getElementById('offline-banner');
    
    if (badge) {
        if (CONNECTION_STATE.isOnline) {
            badge.className = 'connection-status online';
            badge.textContent = '🟢 ONLINE';
        } else {
            badge.className = 'connection-status offline';
            badge.textContent = '🔴 OFFLINE';
        }
    }
    
    if (banner) {
        banner.style.display = CONNECTION_STATE.isOnline ? 'none' : 'block';
    }
}

/**
 * Notify all registered listeners
 * @param {boolean} isOnline - Current connection state
 */
function notifyListeners(isOnline) {
    CONNECTION_STATE.listeners.forEach(callback => {
        try {
            callback(isOnline);
        } catch (error) {
            console.error('[Connection] Listener error:', error);
        }
    });
}

/**
 * Register a listener for connection changes
 * @param {Function} callback - Called with (isOnline: boolean)
 */
function onConnectionChange(callback) {
    if (typeof callback === 'function') {
        CONNECTION_STATE.listeners.push(callback);
        console.log('[Connection] Listener registered, total:', CONNECTION_STATE.listeners.length);
    }
}

/**
 * Get current connection status
 * @returns {boolean} True if online
 */
function getConnectionStatus() {
    return CONNECTION_STATE.isOnline;
}

/**
 * Check if online (alias for getConnectionStatus)
 * @returns {boolean} True if online
 */
function isOnline() {
    return CONNECTION_STATE.isOnline;
}

/* ============================================================================
   EXPORTS
   ============================================================================ */

window.StationCommon = {
    loadStationConfig,
    fetchProducts,
    completeTask,
    startRefreshCountdown,
    startAutoRefresh,
    stopAutoRefresh,
    updateCurrentDatetime,
    smartMergeProducts,
    createProductCard,
    removeProductCard,
    updateStatsBar,
    showLoadingSkeleton,
    hideLoadingSkeleton,
    showToast,
    showSuccess,
    showError,
    showWarning,
    showInfo,
    getAllCards,
    getCardById,
    isOnline,
    attachCardEventListeners,
    fetchTodayM3,
    updateTodayM3Display,
    incrementTodayM3,
    initConnectionMonitor,
    getConnectionStatus,
    onConnectionChange,
    isOnline,
    checkHealth,
    startHeartbeat,
    stopHeartbeat
};

console.log('[Station] Common utilities loaded (v2.0)');