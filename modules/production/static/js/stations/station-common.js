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
    // Orders count
    const totalOrdersElement = document.getElementById('total-orders');
    if (totalOrdersElement) {
        totalOrdersElement.textContent = stats.total_orders || 0;
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

/* ============================================================================
   NOTES MODAL - Popup z uwagami do zamówienia
   ============================================================================ */

/**
 * Otwiera modal z uwagami
 * @param {string} notesContent - Treść uwag
 */
function openNotesModal(notesContent) {
    const modal = document.getElementById('notesModal');
    const contentDiv = document.getElementById('notesModalContent');

    if (!modal || !contentDiv) {
        console.warn('[Notes] Modal elements not found');
        return;
    }

    contentDiv.textContent = notesContent;
    modal.classList.add('active');

    // Zamknij przy kliknięciu w tło
    modal.onclick = function(e) {
        if (e.target === modal) {
            closeNotesModal();
        }
    };

    // Zamknij przy ESC
    document.addEventListener('keydown', handleNotesModalEsc);
}

/**
 * Zamyka modal z uwagami
 */
function closeNotesModal() {
    const modal = document.getElementById('notesModal');
    if (modal) {
        modal.classList.remove('active');
    }
    document.removeEventListener('keydown', handleNotesModalEsc);
}

/**
 * Handler dla ESC w modalu uwag
 */
function handleNotesModalEsc(e) {
    if (e.key === 'Escape') {
        closeNotesModal();
    }
}

/**
 * Inicjalizuje event listenery dla ikon uwag
 */
function initNotesIcons() {
    document.querySelectorAll('.notes-icon-wrapper').forEach(wrapper => {
        wrapper.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const notes = this.dataset.notes;
            if (notes) {
                openNotesModal(notes);
            }
        });
    });
    console.log('[Notes] Icons initialized');
}

// Eksportuj do globalnego scope
window.openNotesModal = openNotesModal;
window.closeNotesModal = closeNotesModal;
window.initNotesIcons = initNotesIcons;

// Auto-init przy załadowaniu DOM
document.addEventListener('DOMContentLoaded', function() {
    initNotesIcons();
});

/* ============================================================================
   FULLSCREEN ORDER MODE - Powiększony widok zamówienia
   ============================================================================ */

/**
 * Stan fullscreen mode
 */
const FULLSCREEN_STATE = {
    isActive: false,
    sourceCard: null,
    sourceOrderNumber: null,
    overlay: null,
    container: null
};

/**
 * SVG ikona powiększenia (strzałki rozchodzące się do rogów)
 */
const EXPAND_ICON_SVG = `
<svg class="header-icon" width="18" height="18"><use href="${window.STATION_CONFIG ? window.STATION_CONFIG.iconsUrl : ''}#icon-expand"/></svg>`;

/**
 * SVG ikona pomniejszenia (strzałki zbiegające się do środka)
 */
const COLLAPSE_ICON_SVG = `
<svg class="header-icon" width="18" height="18"><use href="${window.STATION_CONFIG ? window.STATION_CONFIG.iconsUrl : ''}#icon-collapse"/></svg>`;

/**
 * Otwiera zamówienie w trybie fullscreen
 * @param {HTMLElement} sourceCard - Oryginalna karta zamówienia
 */
function openFullscreenOrder(sourceCard) {
    if (FULLSCREEN_STATE.isActive) {
        console.warn('[Fullscreen] Already active');
        return;
    }

    const orderNumber = sourceCard.dataset.orderNumber;
    const productId = sourceCard.dataset.productId;
    console.log(`[Fullscreen] Opening order: ${orderNumber || productId}`);

    // Zapisz stan
    FULLSCREEN_STATE.isActive = true;
    FULLSCREEN_STATE.sourceCard = sourceCard;
    FULLSCREEN_STATE.sourceOrderNumber = orderNumber;
    FULLSCREEN_STATE.sourceProductId = productId;

    // Przyciemnij oryginalną kartę
    sourceCard.classList.add('fullscreen-source');

    // Stwórz overlay
    const overlay = document.createElement('div');
    overlay.className = 'fullscreen-overlay';
    document.body.appendChild(overlay);
    FULLSCREEN_STATE.overlay = overlay;

    // Stwórz kontener dla powiększonej karty
    const container = document.createElement('div');
    container.className = 'fullscreen-order-container';
    document.body.appendChild(container);
    FULLSCREEN_STATE.container = container;

    // Sklonuj kartę
    const clonedCard = sourceCard.cloneNode(true);
    clonedCard.classList.remove('fullscreen-source');
    clonedCard.dataset.fullscreenClone = 'true';
    container.appendChild(clonedCard);

    // Zamień ikonę powiększenia na pomniejszenie
    const expandIcon = clonedCard.querySelector('.expand-icon-wrapper');
    if (expandIcon) {
        expandIcon.innerHTML = COLLAPSE_ICON_SVG;
        expandIcon.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            closeFullscreenOrder();
        };
    }

    // Ponownie podepnij event listenery do sklonowanej karty
    reinitializeClonedCard(clonedCard, sourceCard);

    console.log(`[Fullscreen] Order ${orderNumber} opened`);
}

/**
 * Zamyka tryb fullscreen
 */
function closeFullscreenOrder() {
    if (!FULLSCREEN_STATE.isActive) {
        return;
    }

    console.log(`[Fullscreen] Closing order: ${FULLSCREEN_STATE.sourceOrderNumber}`);

    // Usuń klasę przyciemnienia z oryginalnej karty
    if (FULLSCREEN_STATE.sourceCard) {
        FULLSCREEN_STATE.sourceCard.classList.remove('fullscreen-source');
    }

    // Usuń overlay
    if (FULLSCREEN_STATE.overlay) {
        FULLSCREEN_STATE.overlay.remove();
    }

    // Usuń kontener z powiększoną kartą
    if (FULLSCREEN_STATE.container) {
        FULLSCREEN_STATE.container.remove();
    }

    // Wyczyść observer jeśli aktywny
    if (FULLSCREEN_STATE._actionObserver) {
        FULLSCREEN_STATE._actionObserver.disconnect();
        FULLSCREEN_STATE._actionObserver = null;
    }

    // Resetuj stan
    FULLSCREEN_STATE.isActive = false;
    FULLSCREEN_STATE.sourceCard = null;
    FULLSCREEN_STATE.sourceOrderNumber = null;
    FULLSCREEN_STATE.sourceProductId = null;
    FULLSCREEN_STATE.overlay = null;
    FULLSCREEN_STATE.container = null;

    console.log('[Fullscreen] Closed');
}

/**
 * Zamyka fullscreen po pomyślnym zakończeniu zamówienia
 * @param {string} orderNumber - Numer zamówienia
 */
function closeFullscreenIfActive(identifier) {
    if (FULLSCREEN_STATE.isActive &&
        (FULLSCREEN_STATE.sourceOrderNumber === identifier || FULLSCREEN_STATE.sourceProductId === identifier)) {
        closeFullscreenOrder();
    }
}

/**
 * Synchronizuje stan między sklonowaną a oryginalną kartą
 * @param {HTMLElement} clonedCard - Sklonowana karta
 * @param {HTMLElement} sourceCard - Oryginalna karta
 */
function reinitializeClonedCard(clonedCard, sourceCard) {
    // Przyciski quantity (+/-)
    const qtyButtons = clonedCard.querySelectorAll('.btn-qty');
    qtyButtons.forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            const productId = this.dataset.productId;
            const action = this.dataset.action;

            // Natychmiastowa aktualizacja UI klona
            const counterEl = clonedCard.querySelector('.quantity-counter .qty-done') ||
                              (productId ? clonedCard.querySelector(`[data-product-id="${productId}"] .qty-done`) : null);
            const totalEl = clonedCard.querySelector('.quantity-counter .qty-total') ||
                            (productId ? clonedCard.querySelector(`[data-product-id="${productId}"] .qty-total`) : null);

            if (counterEl && totalEl) {
                let done = parseInt(counterEl.textContent) || 0;
                const total = parseInt(totalEl.textContent) || 1;
                if (action === 'increment' && done < total) done++;
                else if (action === 'decrement' && done > 0) done--;
                else if (action === 'increment10' && done + 10 <= total) done += 10;
                else if (action === 'decrement10' && done >= 10) done -= 10;
                counterEl.textContent = done;
            }

            // Deleguj do source card (API call + pełna logika)
            const originalBtn = sourceCard.querySelector(`.btn-qty[data-product-id="${productId}"][data-action="${action}"]`);
            if (originalBtn) {
                originalBtn.click();
                // Pełna synchronizacja po API response
                setTimeout(() => {
                    syncClonedCardUI(clonedCard, sourceCard);
                }, 500);
            }
        });
    });

    // Przycisk complete — synchronizuj UI countdown/saving z source do klona
    const completeBtn = clonedCard.querySelector('.btn-complete[data-action="complete"]');
    if (completeBtn) {
        completeBtn.addEventListener('click', function(e) {
            e.preventDefault();

            const originalCompleteBtn = sourceCard.querySelector('.btn-complete[data-action="complete"]');
            if (originalCompleteBtn && !originalCompleteBtn.disabled) {
                originalCompleteBtn.click();

                // Obserwuj zmiany w order-action source i kopiuj do klona
                const sourceAction = sourceCard.querySelector('.order-action');
                const clonedAction = clonedCard.querySelector('.order-action');
                if (sourceAction && clonedAction) {
                    const observer = new MutationObserver(() => {
                        clonedAction.innerHTML = sourceAction.innerHTML;
                        // Podepnij cancel na klonie
                        const clonedCancel = clonedAction.querySelector('.btn-cancel');
                        if (clonedCancel) {
                            clonedCancel.addEventListener('click', () => {
                                const sourceCancel = sourceAction.querySelector('.btn-cancel');
                                if (sourceCancel) sourceCancel.click();
                            });
                        }
                    });
                    observer.observe(sourceAction, { childList: true, subtree: true, characterData: true });
                    // Zatrzymaj po zamknięciu fullscreen
                    FULLSCREEN_STATE._actionObserver = observer;
                }
            }
        });
    }

    // Ikony załączników
    const attachmentIcons = clonedCard.querySelectorAll('.attachment-icon-wrapper');
    attachmentIcons.forEach(icon => {
        icon.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            if (typeof window.openAttachmentModal === 'function') {
                const url = this.dataset.attachmentUrl;
                const name = this.dataset.attachmentName;
                const type = this.dataset.attachmentType;
                window.openAttachmentModal(url, name, type);
            }
        });
    });

    // Ikony notatek
    const notesIcons = clonedCard.querySelectorAll('.notes-icon-wrapper');
    notesIcons.forEach(icon => {
        icon.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const notes = this.dataset.notes;
            if (notes && typeof window.openNotesModal === 'function') {
                window.openNotesModal(notes);
            }
        });
    });
}

/**
 * Synchronizuje UI sklonowanej karty z oryginalną
 * @param {HTMLElement} clonedCard - Sklonowana karta
 * @param {HTMLElement} sourceCard - Oryginalna karta
 */
function syncClonedCardUI(clonedCard, sourceCard) {
    // Synchronizuj quantity counters - order-grouped (packaging/formatting)
    const sourceRows = sourceCard.querySelectorAll('.product-row');
    sourceRows.forEach(sourceRow => {
        const productId = sourceRow.dataset.productId;
        const clonedRow = clonedCard.querySelector(`[data-product-id="${productId}"]`);

        if (clonedRow) {
            const sourceQtyDone = sourceRow.querySelector('.qty-done');
            const clonedQtyDone = clonedRow.querySelector('.qty-done');
            if (sourceQtyDone && clonedQtyDone) {
                clonedQtyDone.textContent = sourceQtyDone.textContent;
            }

            clonedRow.dataset.quantityDone = sourceRow.dataset.quantityDone;

            if (sourceRow.classList.contains('product-complete')) {
                clonedRow.classList.add('product-complete');
            } else {
                clonedRow.classList.remove('product-complete');
            }

            const sourceButtons = sourceRow.querySelectorAll('.btn-qty');
            sourceButtons.forEach(sourceBtn => {
                const action = sourceBtn.dataset.action;
                const clonedBtn = clonedRow.querySelector(`.btn-qty[data-action="${action}"]`);
                if (clonedBtn) {
                    clonedBtn.disabled = sourceBtn.disabled;
                }
            });
        }
    });

    // Synchronizuj quantity counters - flat stations (cutting/assembly/gluing/finishing)
    if (sourceRows.length === 0) {
        // Flat station: qty-done/qty-total bezpośrednio w karcie
        const sourceQtyDones = sourceCard.querySelectorAll('.qty-done');
        const clonedQtyDones = clonedCard.querySelectorAll('.qty-done');
        sourceQtyDones.forEach((src, i) => {
            if (clonedQtyDones[i]) clonedQtyDones[i].textContent = src.textContent;
        });

        // Synchronizuj stany przycisków
        const sourceButtons = sourceCard.querySelectorAll('.btn-qty');
        const clonedButtons = clonedCard.querySelectorAll('.btn-qty');
        sourceButtons.forEach((srcBtn, i) => {
            if (clonedButtons[i]) clonedButtons[i].disabled = srcBtn.disabled;
        });

        // Synchronizuj data attributes
        clonedCard.dataset.quantityDone = sourceCard.dataset.quantityDone;
    }

    // Synchronizuj header counter (order-grouped)
    const sourceCounter = sourceCard.querySelector('.products-checked');
    const clonedCounter = clonedCard.querySelector('.products-checked');
    if (sourceCounter && clonedCounter) {
        clonedCounter.textContent = sourceCounter.textContent;
    }

    // Synchronizuj header stats (flat stations)
    const sourceStats = sourceCard.querySelector('.order-stats');
    const clonedStats = clonedCard.querySelector('.order-stats');
    if (sourceStats && clonedStats) {
        clonedStats.innerHTML = sourceStats.innerHTML;
    }

    // Synchronizuj przycisk complete
    const sourceCompleteBtn = sourceCard.querySelector('.btn-complete');
    const clonedCompleteBtn = clonedCard.querySelector('.btn-complete');
    if (sourceCompleteBtn && clonedCompleteBtn) {
        clonedCompleteBtn.disabled = sourceCompleteBtn.disabled;
        clonedCompleteBtn.textContent = sourceCompleteBtn.textContent;
        clonedCompleteBtn.className = sourceCompleteBtn.className;
    }
}

/**
 * Inicjalizuje ikony expand dla wszystkich kart zamówień
 */
function initExpandIcons() {
    const expandIcons = document.querySelectorAll('.expand-icon-wrapper');
    expandIcons.forEach(icon => {
        // Usuń stare listenery
        icon.replaceWith(icon.cloneNode(true));
    });

    // Dodaj nowe listenery
    document.querySelectorAll('.expand-icon-wrapper').forEach(icon => {
        icon.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();

            const orderCard = this.closest('.order-card');
            if (orderCard && !orderCard.dataset.fullscreenClone) {
                openFullscreenOrder(orderCard);
            }
        });
    });

    console.log('[Fullscreen] Expand icons initialized');
}

// Eksportuj do globalnego scope
window.openFullscreenOrder = openFullscreenOrder;
window.closeFullscreenOrder = closeFullscreenOrder;
window.closeFullscreenIfActive = closeFullscreenIfActive;
window.syncClonedCardUI = syncClonedCardUI;
window.initExpandIcons = initExpandIcons;
window.EXPAND_ICON_SVG = EXPAND_ICON_SVG;
window.COLLAPSE_ICON_SVG = COLLAPSE_ICON_SVG;
window.FULLSCREEN_STATE = FULLSCREEN_STATE;

/* ============================================================================
   ORDER SEARCH MODAL - Wyszukiwanie zamówień
   ============================================================================ */

/**
 * Stan modalu wyszukiwania
 */
const ORDER_SEARCH_STATE = {
    isOpen: false,
    modal: null
};

/**
 * SVG ikona lupy
 */
const SEARCH_ICON_SVG = `
<svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="11" cy="11" r="8"></circle>
    <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
</svg>`;

/**
 * Otwiera modal wyszukiwania zamówień
 */
function openOrderSearchModal() {
    if (ORDER_SEARCH_STATE.isOpen) {
        return;
    }

    console.log('[OrderSearch] Opening modal');

    // Pobierz wszystkie zamówienia z DOM
    const orderCards = document.querySelectorAll('.order-card:not([data-fullscreen-clone="true"])');
    const orders = [];

    orderCards.forEach(card => {
        const productId = card.dataset.productId || '';
        const orderNumber = card.dataset.orderNumber || '';
        const internalText = card.querySelector('.order-internal')?.textContent || '';
        const baselinkerText = card.querySelector('.order-baselinker')?.textContent || '';
        // Numer systemowy: product ID (flat) lub order number (grouped)
        const systemNumber = productId || orderNumber || '';

        // Wyciągnij numer BL do sortowania
        const blMatch = baselinkerText.match(/BL-(\d+)/);
        const blNumber = blMatch ? parseInt(blMatch[1], 10) : 0;

        orders.push({
            systemNumber,
            internalText,
            baselinkerText,
            blNumber,
            card
        });
    });

    // Sortuj po numerze BL (malejąco)
    orders.sort((a, b) => b.blNumber - a.blNumber);

    // Stwórz modal
    const modal = document.createElement('div');
    modal.className = 'order-search-modal active';
    modal.id = 'orderSearchModal';

    let ordersHTML = '';
    if (orders.length === 0) {
        ordersHTML = `
            <div class="order-search-empty">
                <div class="order-search-empty-icon">🔍</div>
                <h4>Brak zamówień</h4>
                <p>Nie ma żadnych zamówień do wyświetlenia.</p>
            </div>
        `;
    } else {
        orders.forEach((order, index) => {
            ordersHTML += `
                <button class="order-search-btn" data-order-index="${index}">
                    <span class="order-number">${order.systemNumber}</span>
                    ${order.internalText ? `<span class="order-internal">${order.internalText}</span>` : ''}
                    ${order.baselinkerText ? `<span class="order-baselinker">${order.baselinkerText}</span>` : ''}
                </button>
            `;
        });
    }

    modal.innerHTML = `
        <div class="order-search-modal-content">
            <div class="order-search-modal-header">
                <h3>Wyszukaj zamówienie</h3>
                <button class="order-search-modal-close">&times;</button>
            </div>
            <div class="order-search-input-wrapper">
                <input type="text" class="order-search-input" placeholder="Wpisz numer zamówienia lub BL..." autofocus>
            </div>
            <div class="order-search-modal-body">
                ${ordersHTML}
            </div>
        </div>
    `;

    document.body.appendChild(modal);
    ORDER_SEARCH_STATE.modal = modal;
    ORDER_SEARCH_STATE.isOpen = true;

    // Event listener dla zamknięcia
    modal.querySelector('.order-search-modal-close').addEventListener('click', closeOrderSearchModal);

    // Filtrowanie po wpisaniu
    const searchInput = modal.querySelector('.order-search-input');
    const allButtons = modal.querySelectorAll('.order-search-btn');
    searchInput.addEventListener('input', function() {
        const query = this.value.toLowerCase().trim();
        allButtons.forEach(btn => {
            const text = btn.textContent.toLowerCase();
            btn.style.display = (!query || text.includes(query)) ? '' : 'none';
        });
    });
    searchInput.focus();

    // Event listenery dla przycisków zamówień
    allButtons.forEach((btn, index) => {
        btn.addEventListener('click', function() {
            const order = orders[index];
            if (order && order.card) {
                closeOrderSearchModal();
                openFullscreenOrder(order.card);
            }
        });
    });

    console.log(`[OrderSearch] Modal opened with ${orders.length} orders`);
}

/**
 * Zamyka modal wyszukiwania zamówień
 */
function closeOrderSearchModal() {
    if (!ORDER_SEARCH_STATE.isOpen) {
        return;
    }

    console.log('[OrderSearch] Closing modal');

    if (ORDER_SEARCH_STATE.modal) {
        ORDER_SEARCH_STATE.modal.remove();
    }

    ORDER_SEARCH_STATE.modal = null;
    ORDER_SEARCH_STATE.isOpen = false;
}

/**
 * Inicjalizuje przycisk wyszukiwania
 */
function initOrderSearchButton() {
    const searchBtn = document.getElementById('search-orders-btn');
    if (searchBtn) {
        searchBtn.addEventListener('click', function(e) {
            e.preventDefault();
            openOrderSearchModal();
        });
        console.log('[OrderSearch] Search button initialized');
    }
}

// Eksportuj do globalnego scope
window.openOrderSearchModal = openOrderSearchModal;
window.closeOrderSearchModal = closeOrderSearchModal;
window.initOrderSearchButton = initOrderSearchButton;
window.SEARCH_ICON_SVG = SEARCH_ICON_SVG;

/* ============================================================================
   STATION TOAST NOTIFICATIONS - Powiadomienia nad headerem
   ============================================================================ */

/**
 * Stan systemu toastów
 */
const TOAST_STATE = {
    container: null,
    activeToasts: [],
    defaultDuration: 5000 // 5 sekund domyślnie
};

/**
 * Typy toastów z ikonami
 */
const TOAST_TYPES = {
    info: { icon: 'ℹ️', className: 'toast-info' },
    success: { icon: '✅', className: 'toast-success' },
    warning: { icon: '⚠️', className: 'toast-warning' },
    error: { icon: '❌', className: 'toast-error' },
    'new-orders': { icon: '📦', className: 'toast-new-orders' },
    priority: { icon: '🔥', className: 'toast-priority' }
};

/**
 * Inicjalizuje kontener na toasty
 */
function initToastContainer() {
    if (TOAST_STATE.container) return TOAST_STATE.container;

    const container = document.createElement('div');
    container.className = 'station-toast-container';
    container.id = 'stationToastContainer';
    document.body.appendChild(container);

    TOAST_STATE.container = container;
    console.log('[Toast] Container initialized');

    return container;
}

/**
 * Wyświetla toast notification
 * @param {string} message - Treść powiadomienia
 * @param {string} type - Typ toasta: 'info', 'success', 'warning', 'error', 'new-orders', 'priority'
 * @param {Object} options - Opcje dodatkowe
 * @param {number} options.duration - Czas wyświetlania w ms (0 = bez auto-hide)
 * @param {boolean} options.closable - Czy pokazać przycisk zamknięcia
 * @param {string} options.icon - Własna ikona (nadpisuje domyślną)
 * @returns {HTMLElement} Element toasta
 */
function showStationToast(message, type = 'info', options = {}) {
    const container = initToastContainer();

    const {
        duration = TOAST_STATE.defaultDuration,
        closable = true,
        icon = null
    } = options;

    const toastConfig = TOAST_TYPES[type] || TOAST_TYPES.info;
    const toastIcon = icon || toastConfig.icon;

    // Stwórz element toasta
    const toast = document.createElement('div');
    toast.className = `station-toast ${toastConfig.className}`;

    toast.innerHTML = `
        <span class="station-toast-icon">${toastIcon}</span>
        <span class="station-toast-message">${message}</span>
        ${closable ? '<button class="station-toast-close">&times;</button>' : ''}
    `;

    // Dodaj do kontenera
    container.appendChild(toast);
    TOAST_STATE.activeToasts.push(toast);

    // Animacja wejścia
    requestAnimationFrame(() => {
        toast.classList.add('show');
    });

    // Event listener dla zamknięcia
    if (closable) {
        const closeBtn = toast.querySelector('.station-toast-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => hideStationToast(toast));
        }
    }

    // Auto-hide po określonym czasie
    if (duration > 0) {
        setTimeout(() => {
            hideStationToast(toast);
        }, duration);
    }

    console.log(`[Toast] Shown: "${message}" (type: ${type})`);

    return toast;
}

/**
 * Ukrywa i usuwa toast
 * @param {HTMLElement} toast - Element toasta do usunięcia
 */
function hideStationToast(toast) {
    if (!toast || toast.classList.contains('hiding')) return;

    toast.classList.add('hiding');
    toast.classList.remove('show');

    // Usuń po zakończeniu animacji
    setTimeout(() => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }

        // Usuń z listy aktywnych
        const index = TOAST_STATE.activeToasts.indexOf(toast);
        if (index > -1) {
            TOAST_STATE.activeToasts.splice(index, 1);
        }
    }, 300);
}

/**
 * Ukrywa wszystkie aktywne toasty
 */
function hideAllStationToasts() {
    TOAST_STATE.activeToasts.forEach(toast => {
        hideStationToast(toast);
    });
}

/* ============================================================================
   HELPER FUNCTIONS - Skróty dla częstych typów powiadomień
   ============================================================================ */

/**
 * Wyświetla toast o nowych zamówieniach
 * @param {number} count - Liczba nowych zamówień
 * @param {Object} options - Opcje dodatkowe
 */
function showNewOrdersToast(count, options = {}) {
    const message = count === 1
        ? 'DODANO 1 NOWE ZAMÓWIENIE'
        : `DODANO ${count} NOWYCH ZAMÓWIEŃ`;

    return showStationToast(message, 'new-orders', {
        duration: 6000,
        ...options
    });
}

/**
 * Wyświetla toast o pilnym zamówieniu
 * @param {string} orderNumber - Numer zamówienia
 * @param {Object} options - Opcje dodatkowe
 */
function showPriorityOrderToast(orderNumber, options = {}) {
    const message = `PILNE ZAMÓWIENIE: ${orderNumber}`;

    return showStationToast(message, 'priority', {
        duration: 8000,
        ...options
    });
}

/**
 * Wyświetla toast o pomyślnym zakończeniu
 * @param {string} message - Treść komunikatu
 * @param {Object} options - Opcje dodatkowe
 */
function showSuccessToast(message, options = {}) {
    return showStationToast(message, 'success', {
        duration: 4000,
        ...options
    });
}

/**
 * Wyświetla toast o błędzie
 * @param {string} message - Treść komunikatu
 * @param {Object} options - Opcje dodatkowe
 */
function showErrorToast(message, options = {}) {
    return showStationToast(message, 'error', {
        duration: 6000,
        ...options
    });
}

/**
 * Wyświetla toast ostrzegawczy
 * @param {string} message - Treść komunikatu
 * @param {Object} options - Opcje dodatkowe
 */
function showWarningToast(message, options = {}) {
    return showStationToast(message, 'warning', {
        duration: 5000,
        ...options
    });
}

/**
 * Wyświetla toast informacyjny
 * @param {string} message - Treść komunikatu
 * @param {Object} options - Opcje dodatkowe
 */
function showInfoToast(message, options = {}) {
    return showStationToast(message, 'info', {
        duration: 4000,
        ...options
    });
}

// Eksportuj do globalnego scope
window.initToastContainer = initToastContainer;
window.showStationToast = showStationToast;
window.hideStationToast = hideStationToast;
window.hideAllStationToasts = hideAllStationToasts;
window.showNewOrdersToast = showNewOrdersToast;
window.showPriorityOrderToast = showPriorityOrderToast;
window.showSuccessToast = showSuccessToast;
window.showErrorToast = showErrorToast;
window.showWarningToast = showWarningToast;
window.showInfoToast = showInfoToast;
window.TOAST_TYPES = TOAST_TYPES;