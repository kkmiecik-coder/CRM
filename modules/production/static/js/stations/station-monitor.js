// station-monitor.js - MONITOR PRODUKCJI
// Wersja 2.4 - Szybsza inicjalizacja auto-scroll (2s zamiast 5s)

/**
 * Global state dla monitora
 */
window.MONITOR_STATE = {
    config: null,
    refreshTimer: null,
    countdownTimer: null,
    isRefreshing: false,
    lastRefreshTime: Date.now(),
    lastTickTime: Date.now(),
    isOnline: true,
    secondsLeft: 30,

    // Auto-scroll state
    autoScroll: {
        enabled: false,
        isRunning: false,
        isPaused: false,
        animationId: null,
        pauseTimer: null,
        pauseCountdownTimer: null,
        initTimer: null,

        // Konfiguracja
        scrollSpeed: 30,           // Pikseli na sekundę
        pauseDuration: 10000,      // Pauza 10 sekund
        pauseEveryPx: 0,           // Co ile px pauzować (obliczane dynamicznie)

        // Stan
        rowHeight: 0,
        columnsCount: 1,
        rowsMoved: 0,
        pauseCountdown: 0,
        lastFrameTime: 0,
        subPixelAccum: 0,          // Akumulator sub-pixelowy

        // Cache aktualnych zamówień (dla inkrementalnego update)
        currentOrders: new Map()
    }
};

/* ============================================================================
   INITIALIZATION
   ============================================================================ */

document.addEventListener('DOMContentLoaded', function() {
    console.log('[Monitor] Initializing v2.4...');

    // Load config
    if (window.MONITOR_CONFIG) {
        window.MONITOR_STATE.config = {
            refreshInterval: window.MONITOR_CONFIG.refreshInterval || 30,
            debugMode: window.MONITOR_CONFIG.debugMode || false,
            ajaxUrl: (window.MONITOR_CONFIG && window.MONITOR_CONFIG.ajaxUrl) || '/production/stations/ajax/monitor',
            // Auto-scroll config
            autoScrollSpeed: window.MONITOR_CONFIG.autoScrollSpeed || 30,
            autoScrollPauseDuration: window.MONITOR_CONFIG.autoScrollPauseDuration || 10000,
            autoScrollPauseEveryRows: window.MONITOR_CONFIG.autoScrollPauseEveryRows || 2
        };

        // Zastosuj konfigurację auto-scroll
        window.MONITOR_STATE.autoScroll.scrollSpeed = window.MONITOR_STATE.config.autoScrollSpeed;
        window.MONITOR_STATE.autoScroll.pauseDuration = window.MONITOR_STATE.config.autoScrollPauseDuration;
        window.MONITOR_STATE.autoScroll.pauseEveryNRows = window.MONITOR_STATE.config.autoScrollPauseEveryRows;

        console.log('[Monitor] Config loaded:', window.MONITOR_STATE.config);
    }

    // Start datetime update
    updateCurrentDatetime();
    setInterval(updateCurrentDatetime, 1000);

    // Start refresh countdown
    startRefreshCountdown();

    // Setup connection monitoring
    setupConnectionMonitoring();

    // Setup visibility change handler (kluczowe dla TV Box)
    setupVisibilityHandler();

    // Setup frozen timer detection
    setupFrozenTimerDetection();

    // Utwórz indicator (ale jeszcze nie startuj scrollu)
    createScrollIndicator();

    // Załaduj początkowe zamówienia do cache
    initializeOrdersCache();

    // Opóźniony start auto-scroll - czekaj aż strona będzie w pełni gotowa
    scheduleAutoScrollInit();

    console.log('[Monitor] Initialization complete');
});

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
    const days = ['Niedziela', 'Poniedzialek', 'Wtorek', 'Sroda', 'Czwartek', 'Piatek', 'Sobota'];
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

    datetimeElement.textContent = `${date} ${time}`;

    // Update day label if exists
    const labelElement = datetimeElement.previousElementSibling;
    if (labelElement && labelElement.classList.contains('stat-label')) {
        labelElement.textContent = dayName;
    }
}

/**
 * Start refresh countdown
 */
function startRefreshCountdown() {
    const config = window.MONITOR_STATE.config;
    if (!config) return;

    // Clear existing countdown
    if (window.MONITOR_STATE.countdownTimer) {
        clearInterval(window.MONITOR_STATE.countdownTimer);
    }

    window.MONITOR_STATE.secondsLeft = config.refreshInterval;
    const countdownElement = document.getElementById('refresh-countdown');
    const refreshIcon = document.querySelector('.refresh-icon');

    const updateCountdown = () => {
        // Zapisz czas ostatniego ticka
        window.MONITOR_STATE.lastTickTime = Date.now();

        if (countdownElement) {
            countdownElement.textContent = `${window.MONITOR_STATE.secondsLeft}s`;
        }

        if (window.MONITOR_STATE.secondsLeft <= 0) {
            // Trigger refresh
            refreshMonitorData();
            window.MONITOR_STATE.secondsLeft = config.refreshInterval;
        } else {
            window.MONITOR_STATE.secondsLeft--;
        }

        // Visual feedback when close to refresh
        if (refreshIcon) {
            if (window.MONITOR_STATE.secondsLeft <= 3) {
                refreshIcon.classList.add('spinning');
            } else {
                refreshIcon.classList.remove('spinning');
            }
        }
    };

    // Initial update
    updateCountdown();

    // Start interval
    window.MONITOR_STATE.countdownTimer = setInterval(updateCountdown, 1000);
}

/* ============================================================================
   ORDERS CACHE & INCREMENTAL UPDATE
   ============================================================================ */

/**
 * Initialize orders cache from existing DOM
 */
function initializeOrdersCache() {
    const grid = document.querySelector('.orders-grid');
    if (!grid) return;

    const cards = grid.querySelectorAll('.order-card');
    const cache = window.MONITOR_STATE.autoScroll.currentOrders;

    cards.forEach(card => {
        const orderNumber = card.dataset.order;
        if (orderNumber) {
            cache.set(orderNumber, {
                element: card,
                orderNumber: orderNumber
            });
        }
    });

    console.log(`[Monitor] Initialized cache with ${cache.size} orders`);
}

/**
 * Generate HTML for single order card
 */
function generateOrderCardHTML(order) {
    const progressPercent = order.total_products > 0
        ? (order.completed_products / order.total_products * 100)
        : 0;
    const orderVolume = parseFloat(order.total_volume) || 0;

    return `
        <div class="order-card ${order.status_class}" data-order="${order.order_number}">
            <div class="order-main">
                <span class="order-number">${order.order_number}</span>
                ${order.client_order_number ? `<span class="order-client-number">${order.client_order_number}</span>` : ''}
                ${order.baselinker_order_id ? `<span class="order-baselinker">BL-${order.baselinker_order_id}</span>` : ''}
            </div>
            <div class="order-meta">
                <span class="status-badge ${order.status_class}">${order.status_label}</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: ${progressPercent}%"></div>
            </div>
            <div class="order-details">
                <span class="progress-text">${order.completed_products}/${order.total_products} szt</span>
                <span class="order-volume">
                    <span class="volume-value">${orderVolume.toFixed(4)}</span>
                    <span class="volume-unit">m<sup>3</sup></span>
                </span>
            </div>
        </div>
    `;
}

/**
 * Update single order card in place (bez przebudowywania całego DOM)
 */
function updateOrderCard(card, order) {
    // Update status class
    const currentClasses = Array.from(card.classList).filter(c => c.startsWith('status-'));
    currentClasses.forEach(c => card.classList.remove(c));
    if (order.status_class) {
        card.classList.add(order.status_class);
    }

    // Update status badge
    const badge = card.querySelector('.status-badge');
    if (badge) {
        currentClasses.forEach(c => badge.classList.remove(c));
        if (order.status_class) badge.classList.add(order.status_class);
        badge.textContent = order.status_label;
    }

    // Update progress
    const progressText = card.querySelector('.progress-text');
    if (progressText) {
        progressText.textContent = `${order.completed_products}/${order.total_products} szt`;
    }

    const progressFill = card.querySelector('.progress-fill');
    if (progressFill) {
        const percent = order.total_products > 0
            ? (order.completed_products / order.total_products * 100)
            : 0;
        progressFill.style.width = `${percent}%`;
    }

    // Update volume
    const volumeValue = card.querySelector('.volume-value');
    if (volumeValue) {
        const vol = parseFloat(order.total_volume) || 0;
        volumeValue.textContent = vol.toFixed(4);
    }
}

/* ============================================================================
   AJAX REFRESH - Incremental Update
   ============================================================================ */

/**
 * Refresh monitor data via AJAX (inkrementalne odświeżanie)
 */
async function refreshMonitorData() {
    if (window.MONITOR_STATE.isRefreshing) {
        console.log('[Monitor] Already refreshing, skipping...');
        return;
    }

    window.MONITOR_STATE.isRefreshing = true;
    console.log('[Monitor] Refreshing data (incremental)...');

    try {
        const response = await fetch(MONITOR_STATE.config.ajaxUrl, {
            method: 'GET',
            headers: {
                'Accept': 'application/json'
            }
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        if (data.success) {
            // Update stats
            updateStats(data.stats);

        // Update species stats
        if (data.species_stats) {
            data.species_stats.forEach(function(sp, idx) {
                var el = document.getElementById('species-' + (idx + 1));
                if (el) {
                    var valueEl = el.querySelector('.stat-value');
                    if (valueEl) {
                        valueEl.innerHTML = sp.count + ' szt &middot; ' + sp.volume.toFixed(3) + ' m<sup>3</sup>';
                    }
                }
            });
        }

            // Inkrementalne odświeżenie zamówień (BEZ resetowania scrollu)
            incrementalUpdateOrders(data.orders);

            setConnectionStatus(true);
            window.MONITOR_STATE.lastRefreshTime = Date.now();
        } else {
            console.error('[Monitor] Refresh failed:', data.error);
            setConnectionStatus(false);
        }

    } catch (error) {
        console.error('[Monitor] Refresh error:', error);
        setConnectionStatus(false);
    } finally {
        window.MONITOR_STATE.isRefreshing = false;
    }
}

/**
 * Update stats display
 */
function updateStats(stats) {
    if (!stats) return;

    updateElement('total-orders', stats.total_orders || 0);
    updateElement('total-products', stats.total_products || 0);
    const totalVolume = parseFloat(stats.total_volume) || 0;
    updateElement('total-volume', totalVolume.toFixed(3) + ' m<sup>3</sup>');
}

/**
 * Inkrementalne odświeżenie zamówień - bez resetowania scrollu
 */
function incrementalUpdateOrders(orders) {
    const grid = document.querySelector('.orders-grid');
    if (!grid) return;

    const cache = window.MONITOR_STATE.autoScroll.currentOrders;

    // Handle empty state
    if (!orders || orders.length === 0) {
        if (cache.size > 0) {
            // Były zamówienia, teraz nie ma - pokaż empty state
            stopAutoScroll();
            cache.clear();
            const main = document.querySelector('.monitor-content');
            if (main) {
                main.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">
                            <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                                <polyline points="22 4 12 14.01 9 11.01"></polyline>
                            </svg>
                        </div>
                        <h2>Brak zamowien w systemie</h2>
                        <p>Wszystkie zamowienia zostaly zrealizowane lub nie ma nowych zamowien.</p>
                    </div>
                `;
            }
        }
        return;
    }

    // Utwórz mapę nowych zamówień
    const newOrdersMap = new Map();
    orders.forEach(order => {
        newOrdersMap.set(order.order_number, order);
    });

    // 1. Usuń zamówienia które już nie istnieją
    const toRemove = [];
    cache.forEach((cached, orderNumber) => {
        if (!newOrdersMap.has(orderNumber)) {
            toRemove.push(orderNumber);
        }
    });

    toRemove.forEach(orderNumber => {
        const cached = cache.get(orderNumber);
        if (cached && cached.element && cached.element.parentNode) {
            cached.element.remove();
            console.log(`[Monitor] Removed order: ${orderNumber}`);
        }
        cache.delete(orderNumber);
    });

    // 2. Zaktualizuj istniejące i dodaj nowe
    orders.forEach(order => {
        const orderNumber = order.order_number;
        const cached = cache.get(orderNumber);

        if (cached && cached.element && cached.element.parentNode) {
            // Zamówienie istnieje - zaktualizuj w miejscu
            updateOrderCard(cached.element, order);
        } else {
            // Nowe zamówienie - dodaj na koniec
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = generateOrderCardHTML(order);
            const newCard = tempDiv.firstElementChild;
            grid.appendChild(newCard);

            cache.set(orderNumber, {
                element: newCard,
                orderNumber: orderNumber
            });

            console.log(`[Monitor] Added new order: ${orderNumber}`);
        }
    });

    // 3. Przelicz wymiary jeśli trzeba (ale NIE resetuj scrollu)
    calculateGridDimensions();

    // 4. Sprawdź czy auto-scroll powinien być aktywny
    checkAutoScrollNeeded();

    console.log(`[Monitor] Incremental update complete. Orders in cache: ${cache.size}`);
}

/**
 * Helper to update element content
 */
function updateElement(id, value) {
    const element = document.getElementById(id);
    if (element) {
        element.innerHTML = value;
    }
}

/* ============================================================================
   AUTO-SCROLL — scrollTop-based, no DOM manipulation
   Scrolluje monitor-content w dół. Po dojechaniu do końca wraca na początek.
   Pauza co 2 wiersze (obliczane dynamicznie z rowHeight).
   ============================================================================ */

/**
 * Schedule auto-scroll initialization after page is fully ready
 */
function scheduleAutoScrollInit() {
    var state = window.MONITOR_STATE.autoScroll;
    if (state.initTimer) clearTimeout(state.initTimer);
    state.initTimer = setTimeout(tryInitAutoScroll, 500);
}

/**
 * Try to initialize auto-scroll
 */
function tryInitAutoScroll() {
    var grid = document.querySelector('.orders-grid');
    if (!grid || grid.querySelectorAll('.order-card').length === 0) {
        setTimeout(tryInitAutoScroll, 1000);
        return;
    }

    var firstCard = grid.querySelector('.order-card');
    if (!firstCard || firstCard.getBoundingClientRect().height === 0) {
        setTimeout(tryInitAutoScroll, 500);
        return;
    }

    calculateGridDimensions();
    setTimeout(checkAutoScrollNeeded, 1500);
}

/**
 * Calculate grid dimensions
 */
function calculateGridDimensions() {
    var grid = document.querySelector('.orders-grid');
    if (!grid) return;

    var cards = grid.querySelectorAll('.order-card');
    if (cards.length === 0) return;

    var state = window.MONITOR_STATE.autoScroll;
    var gridStyle = window.getComputedStyle(grid);
    var gap = parseInt(gridStyle.gap) || 6;
    var firstCard = cards[0];
    var cardRect = firstCard.getBoundingClientRect();
    var gridRect = grid.getBoundingClientRect();

    if (cardRect.height > 0) {
        state.rowHeight = cardRect.height + gap;
    }
    if (cardRect.width > 0) {
        state.columnsCount = Math.max(1, Math.round(gridRect.width / (cardRect.width + gap)));
    }

    // Oblicz co ile px pauzować (2 wiersze)
    state.pauseEveryPx = state.rowHeight * 2;
}

/**
 * Check if auto-scroll is needed
 */
function checkAutoScrollNeeded() {
    var content = document.querySelector('.monitor-content');
    if (!content) return;

    var state = window.MONITOR_STATE.autoScroll;
    var scrollable = content.scrollHeight > content.clientHeight;

    if (scrollable && !state.isRunning) {
        startAutoScroll();
    } else if (!scrollable && state.isRunning) {
        stopAutoScroll();
    }
}

/**
 * Create scroll indicator element
 */
function createScrollIndicator() {
    var existing = document.querySelector('.auto-scroll-indicator');
    if (existing) existing.remove();

    var indicator = document.createElement('div');
    indicator.className = 'auto-scroll-indicator';
    indicator.style.display = 'none';
    indicator.innerHTML =
        '<svg class="scroll-icon animated" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
        '<path d="M12 5v14M5 12l7 7 7-7"/>' +
        '</svg>' +
        '<span class="scroll-status">Auto-scroll</span>' +
        '<span class="pause-countdown" style="display:none;"></span>';
    document.body.appendChild(indicator);
}

/**
 * Start auto-scroll
 */
function startAutoScroll() {
    var state = window.MONITOR_STATE.autoScroll;
    if (state.isRunning) return;

    if (state.animationId) cancelAnimationFrame(state.animationId);

    state.enabled = true;
    state.isRunning = true;
    state.isPaused = false;
    state.rowsMoved = 0;
    state.subPixelAccum = 0;
    state.lastFrameTime = performance.now();

    updateScrollIndicator(false);
    animateScroll();
}

/**
 * Animation loop — uses scrollTop on .monitor-content
 */
function animateScroll() {
    var state = window.MONITOR_STATE.autoScroll;
    if (!state.enabled || !state.isRunning) return;

    var now = performance.now();
    var deltaTime = (now - state.lastFrameTime) / 1000;
    state.lastFrameTime = now;

    if (!state.isPaused) {
        var content = document.querySelector('.monitor-content');
        if (content) {
            var maxScroll = content.scrollHeight - content.clientHeight;
            state.subPixelAccum += state.scrollSpeed * deltaTime;
            var wholePixels = Math.floor(state.subPixelAccum);
            if (wholePixels < 1) {
                state.animationId = requestAnimationFrame(animateScroll);
                return;
            }
            state.subPixelAccum -= wholePixels;
            var prevScroll = content.scrollTop;
            content.scrollTop += wholePixels;

            // Sprawdź czy przekroczyliśmy próg pauzy (co 2 wiersze)
            if (state.pauseEveryPx > 0 && state.rowHeight > 0) {
                var prevRow = Math.floor(prevScroll / state.pauseEveryPx);
                var currRow = Math.floor(content.scrollTop / state.pauseEveryPx);
                if (currRow > prevRow && content.scrollTop < maxScroll) {
                    pauseAutoScroll();
                }
            }

            // Dojechaliśmy do końca — pauza na dole, reset, pauza na górze, restart
            if (content.scrollTop >= maxScroll) {
                // Pierwsza pauza (na dole)
                pauseAutoScroll(function() {
                    content.scrollTop = 0;
                    state.subPixelAccum = 0;
                    // Druga pauza (na górze)
                    pauseAutoScroll(function() {
                        state.lastFrameTime = performance.now();
                        animateScroll();
                    });
                });
                return;
            }
        }
    }

    state.animationId = requestAnimationFrame(animateScroll);
}

/**
 * Stop auto-scroll
 */
function stopAutoScroll() {
    var state = window.MONITOR_STATE.autoScroll;

    if (state.animationId) {
        cancelAnimationFrame(state.animationId);
        state.animationId = null;
    }
    if (state.pauseTimer) {
        clearTimeout(state.pauseTimer);
        state.pauseTimer = null;
    }
    if (state.pauseCountdownTimer) {
        clearInterval(state.pauseCountdownTimer);
        state.pauseCountdownTimer = null;
    }

    state.enabled = false;
    state.isRunning = false;
    state.isPaused = false;
    state.rowsMoved = 0;

    var content = document.querySelector('.monitor-content');
    if (content) content.scrollTop = 0;

    var indicator = document.querySelector('.auto-scroll-indicator');
    if (indicator) indicator.style.display = 'none';
}

/**
 * Pause auto-scroll with countdown, then resume
 * @param {Function} onResumeCallback — optional, called right before resuming
 */
function pauseAutoScroll(onResumeCallback) {
    var state = window.MONITOR_STATE.autoScroll;
    state.isPaused = true;
    state.pauseCountdown = Math.ceil(state.pauseDuration / 1000);

    updateScrollIndicator(true);

    state.pauseCountdownTimer = setInterval(function() {
        state.pauseCountdown--;
        updatePauseCountdown();
        if (state.pauseCountdown <= 0) {
            clearInterval(state.pauseCountdownTimer);
            state.pauseCountdownTimer = null;
        }
    }, 1000);

    state.pauseTimer = setTimeout(function() {
        state.isPaused = false;
        state.lastFrameTime = performance.now();
        if (onResumeCallback) {
            onResumeCallback();
        } else {
            updateScrollIndicator(false);
        }
    }, state.pauseDuration);
}

/**
 * Update scroll indicator UI
 */
function updateScrollIndicator(isPaused) {
    var indicator = document.querySelector('.auto-scroll-indicator');
    if (!indicator) return;

    indicator.style.display = 'flex';

    var statusText = indicator.querySelector('.scroll-status');
    var countdown = indicator.querySelector('.pause-countdown');
    var icon = indicator.querySelector('.scroll-icon');

    if (isPaused) {
        indicator.classList.add('paused');
        if (statusText) statusText.textContent = 'Pauza';
        if (countdown) {
            countdown.style.display = 'inline';
            countdown.textContent = window.MONITOR_STATE.autoScroll.pauseCountdown + 's';
        }
        if (icon) icon.classList.remove('animated');
    } else {
        indicator.classList.remove('paused');
        if (statusText) statusText.textContent = 'Auto-scroll';
        if (countdown) countdown.style.display = 'none';
        if (icon) icon.classList.add('animated');
    }
}

/**
 * Update pause countdown display
 */
function updatePauseCountdown() {
    var indicator = document.querySelector('.auto-scroll-indicator');
    if (!indicator) return;

    var countdown = indicator.querySelector('.pause-countdown');
    if (countdown) {
        countdown.textContent = window.MONITOR_STATE.autoScroll.pauseCountdown + 's';
    }
}

/* ============================================================================
   CONNECTION MONITORING
   ============================================================================ */

/**
 * Setup connection monitoring
 */
function setupConnectionMonitoring() {
    // Monitor online/offline events
    window.addEventListener('online', () => setConnectionStatus(true));
    window.addEventListener('offline', () => setConnectionStatus(false));

    // Initial check
    setConnectionStatus(navigator.onLine);
}

/**
 * Set connection status
 */
function setConnectionStatus(isOnline) {
    window.MONITOR_STATE.isOnline = isOnline;

    const statusBadge = document.getElementById('connection-status');
    const offlineBanner = document.getElementById('offline-banner');

    if (statusBadge) {
        const statusText = statusBadge.querySelector('.status-text');
        if (isOnline) {
            statusBadge.classList.remove('offline');
            statusBadge.classList.add('online');
            if (statusText) statusText.textContent = 'ONLINE';
        } else {
            statusBadge.classList.remove('online');
            statusBadge.classList.add('offline');
            if (statusText) statusText.textContent = 'OFFLINE';
        }
    }

    if (offlineBanner) {
        offlineBanner.style.display = isOnline ? 'none' : 'block';
    }
}

/* ============================================================================
   TV BOX / EMBEDDED BROWSER SUPPORT
   ============================================================================ */

/**
 * Setup visibility change handler
 * Kluczowe dla urządzeń TV Box - wykrywa gdy przeglądarka "budzi się"
 */
function setupVisibilityHandler() {
    document.addEventListener('visibilitychange', function() {
        if (document.visibilityState === 'visible') {
            console.log('[Monitor] Page became visible - checking if refresh needed');

            const timeSinceLastRefresh = Date.now() - window.MONITOR_STATE.lastRefreshTime;
            const refreshInterval = (window.MONITOR_STATE.config?.refreshInterval || 30) * 1000;

            // Jeśli minęło więcej niż interwał odświeżania - odśwież natychmiast
            if (timeSinceLastRefresh > refreshInterval) {
                console.log('[Monitor] Stale data detected, refreshing immediately');
                refreshMonitorData();
                // Restart countdown
                startRefreshCountdown();
            }

            // Restart auto-scroll if it should be running
            const state = window.MONITOR_STATE.autoScroll;
            if (state.enabled && !state.animationId) {
                state.lastFrameTime = performance.now();
                animateScroll();
            }
        }
    });

    // Także obsłuż focus (niektóre przeglądarki embedded nie wspierają visibilitychange)
    window.addEventListener('focus', function() {
        console.log('[Monitor] Window focused - checking timers');
        checkAndRestartTimers();
    });
}

/**
 * Setup frozen timer detection
 * Wykrywa gdy setInterval został wstrzymany przez przeglądarkę
 */
function setupFrozenTimerDetection() {
    // Co 5 sekund sprawdzaj czy timer działa poprawnie
    setInterval(function() {
        const now = Date.now();
        const timeSinceLastTick = now - window.MONITOR_STATE.lastTickTime;

        // Jeśli ostatni tick był więcej niż 3 sekundy temu, timer prawdopodobnie zamarzł
        if (timeSinceLastTick > 3000) {
            console.log(`[Monitor] Timer freeze detected (${Math.round(timeSinceLastTick/1000)}s since last tick)`);
            checkAndRestartTimers();
        }
    }, 5000);
}

/**
 * Check and restart timers if needed
 */
function checkAndRestartTimers() {
    const now = Date.now();
    const timeSinceLastRefresh = now - window.MONITOR_STATE.lastRefreshTime;
    const refreshInterval = (window.MONITOR_STATE.config?.refreshInterval || 30) * 1000;

    // Jeśli minęło więcej niż interwał - odśwież dane
    if (timeSinceLastRefresh > refreshInterval) {
        console.log('[Monitor] Data is stale, triggering refresh');
        refreshMonitorData();
    }

    // Restart countdown timer
    console.log('[Monitor] Restarting countdown timer');
    startRefreshCountdown();

    // Restart auto-scroll if needed
    const state = window.MONITOR_STATE.autoScroll;
    if (state.enabled && !state.animationId) {
        state.lastFrameTime = performance.now();
        animateScroll();
    }
}

/* ============================================================================
   CLEANUP
   ============================================================================ */

window.addEventListener('beforeunload', function() {
    stopAutoScroll();
    if (window.MONITOR_STATE.countdownTimer) {
        clearInterval(window.MONITOR_STATE.countdownTimer);
    }
});

// Obsłuż resize - przelicz wymiary
window.addEventListener('resize', function() {
    calculateGridDimensions();
    checkAutoScrollNeeded();
});

console.log('[Monitor] Module loaded v2.4');
