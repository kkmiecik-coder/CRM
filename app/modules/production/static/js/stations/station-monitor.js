<<<<<<< Updated upstream
// station-monitor.js - MONITOR PRODUKCJI
// Wersja 2.4 - Szybsza inicjalizacja auto-scroll (2s zamiast 5s)
=======
// station-monitor.js - Monitor Produkcji
// Wyswietlanie statusow zamowien na telewizorze
// Wersja 1.0
>>>>>>> Stashed changes

/**
 * Global state dla monitora
 */
window.MONITOR_STATE = {
    config: null,
    refreshTimer: null,
    countdownTimer: null,
<<<<<<< Updated upstream
    isRefreshing: false,
    lastRefreshTime: Date.now(),
    lastTickTime: Date.now(),
    isOnline: true,
    secondsLeft: 30,

    // Infinity scroll state
    autoScroll: {
        enabled: false,           // Domyślnie wyłączony, włączany gdy gotowy
        isRunning: false,
        isPaused: false,
        animationId: null,
        pauseTimer: null,
        pauseCountdownTimer: null,
        initTimer: null,

        // Konfiguracja
        scrollSpeed: 30,           // Pikseli na sekundę
        pauseDuration: 10000,      // Jak długo trwa pauza (10 sekund)
        pauseEveryNRows: 2,        // Pauza co N wierszy

        // Stan
        currentOffset: 0,          // Aktualny offset scrollowania
        rowHeight: 0,              // Wysokość wiersza (karta + gap)
        columnsCount: 1,           // Liczba kolumn w gridzie
        rowsMoved: 0,              // Licznik przeniesionych wierszy
        pauseCountdown: 0,         // Odliczanie pauzy
        lastFrameTime: 0,          // Czas ostatniej klatki animacji

        // Cache aktualnych zamówień (dla inkrementalnego update)
        currentOrders: new Map()   // order_number -> order data
    }
=======
    isOnline: true,
    lastRefreshTime: Date.now()
>>>>>>> Stashed changes
};

/* ============================================================================
   INITIALIZATION
   ============================================================================ */

<<<<<<< Updated upstream
document.addEventListener('DOMContentLoaded', function() {
    console.log('[Monitor] Initializing v2.4...');

    // Load config
    if (window.MONITOR_CONFIG) {
        window.MONITOR_STATE.config = {
            refreshInterval: window.MONITOR_CONFIG.refreshInterval || 30,
            debugMode: window.MONITOR_CONFIG.debugMode || false,
            ajaxUrl: '/production/stations/ajax/monitor',
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
=======
/**
 * Initialize monitor on page load
 */
document.addEventListener('DOMContentLoaded', function() {
    console.log('[Monitor] Initializing...');

    // Load config
    loadMonitorConfig();

    // Start datetime updater
    updateCurrentDatetime();
    setInterval(updateCurrentDatetime, 1000);

    // Start auto-refresh
    startAutoRefresh();

    // Start countdown
    startRefreshCountdown();

    console.log('[Monitor] Initialized successfully');
});

/**
 * Load monitor config from window.MONITOR_CONFIG
 */
function loadMonitorConfig() {
    if (!window.MONITOR_CONFIG) {
        console.error('[Monitor] MONITOR_CONFIG not found');
        window.MONITOR_STATE.config = {
            refreshInterval: 30,
            debugMode: false
        };
        return;
    }

    window.MONITOR_STATE.config = {
        refreshInterval: window.MONITOR_CONFIG.refreshInterval || 30,
        debugMode: window.MONITOR_CONFIG.debugMode || false
    };

    console.log('[Monitor] Config loaded:', window.MONITOR_STATE.config);
}

/* ============================================================================
   DATETIME & COUNTDOWN
>>>>>>> Stashed changes
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

<<<<<<< Updated upstream
    // Update day label if exists
    const labelElement = datetimeElement.previousElementSibling;
    if (labelElement && labelElement.classList.contains('stat-label')) {
=======
    // Update day label
    const labelElement = datetimeElement.closest('.stat-content')?.querySelector('.stat-label');
    if (labelElement) {
>>>>>>> Stashed changes
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

<<<<<<< Updated upstream
    window.MONITOR_STATE.secondsLeft = config.refreshInterval;
=======
    let secondsLeft = config.refreshInterval;
>>>>>>> Stashed changes
    const countdownElement = document.getElementById('refresh-countdown');
    const refreshIcon = document.querySelector('.refresh-icon');

    const updateCountdown = () => {
<<<<<<< Updated upstream
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
                <div class="order-ids">
                    <span class="order-number">${order.order_number}</span>
                    ${order.client_order_number ? `<span class="order-client-number">${order.client_order_number}</span>` : ''}
                    ${order.baselinker_order_id ? `<span class="order-baselinker">BL-${order.baselinker_order_id}</span>` : ''}
                </div>
                <div class="order-status">
                    <span class="status-badge ${order.status_class}">${order.status_label}</span>
                </div>
            </div>
            <div class="order-details">
                <div class="order-progress">
                    <span class="progress-text">${order.completed_products} / ${order.total_products}</span>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${progressPercent}%"></div>
                    </div>
                </div>
                <div class="order-volume">
                    <span class="volume-value">${orderVolume.toFixed(3)}</span>
                    <span class="volume-unit">m<sup>3</sup></span>
                </div>
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
        progressText.textContent = `${order.completed_products} / ${order.total_products}`;
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
        volumeValue.textContent = vol.toFixed(3);
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
        const response = await fetch('/production/stations/ajax/monitor', {
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
=======
        if (countdownElement) {
            countdownElement.textContent = `${secondsLeft}s`;
        }

        // Spin icon when refreshing soon
        if (secondsLeft <= 3 && refreshIcon) {
            refreshIcon.classList.add('spinning');
        } else if (refreshIcon) {
            refreshIcon.classList.remove('spinning');
        }
    };

    updateCountdown();

    window.MONITOR_STATE.countdownTimer = setInterval(() => {
        secondsLeft--;

        if (secondsLeft <= 0) {
            secondsLeft = config.refreshInterval;
        }

        updateCountdown();
    }, 1000);
}

/* ============================================================================
   AUTO-REFRESH
   ============================================================================ */

/**
 * Start auto-refresh timer
 */
function startAutoRefresh() {
    const config = window.MONITOR_STATE.config;
    if (!config) return;

    console.log(`[Monitor] Starting auto-refresh (${config.refreshInterval}s)`);

    // Clear existing timer
    if (window.MONITOR_STATE.refreshTimer) {
        clearInterval(window.MONITOR_STATE.refreshTimer);
    }

    // Start refresh timer
    window.MONITOR_STATE.refreshTimer = setInterval(() => {
        refreshMonitorData();
    }, config.refreshInterval * 1000);
}

/**
 * Refresh monitor data from server
 */
async function refreshMonitorData() {
    console.log('[Monitor] Refreshing data...');

    try {
        // Simple page reload for now - most reliable approach
        const response = await fetch(window.location.href, {
            method: 'GET',
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        });

        if (response.ok) {
            // Reload page to get fresh data
            window.location.reload();
        } else {
            throw new Error(`HTTP ${response.status}`);
        }

    } catch (error) {
        console.error('[Monitor] Refresh failed:', error);
        setOfflineStatus();
>>>>>>> Stashed changes
    }
}

/* ============================================================================
<<<<<<< Updated upstream
   INFINITY SCROLL - Smooth row-based scrolling
   ============================================================================ */

/**
 * Schedule auto-scroll initialization after page is fully ready
 */
function scheduleAutoScrollInit() {
    const state = window.MONITOR_STATE.autoScroll;

    // Wyczyść poprzedni timer jeśli istnieje
    if (state.initTimer) {
        clearTimeout(state.initTimer);
    }

    // Czekaj 500ms po DOMContentLoaded, potem sprawdzaj
    state.initTimer = setTimeout(() => {
        tryInitAutoScroll();
    }, 500);
}

/**
 * Try to initialize auto-scroll (sprawdza czy strona jest gotowa)
 */
function tryInitAutoScroll() {
    const grid = document.querySelector('.orders-grid');
    if (!grid) {
        console.log('[Monitor] Grid not found, retrying in 1s...');
        setTimeout(tryInitAutoScroll, 1000);
        return;
    }

    const cards = grid.querySelectorAll('.order-card');
    if (cards.length === 0) {
        console.log('[Monitor] No cards found, retrying in 1s...');
        setTimeout(tryInitAutoScroll, 1000);
        return;
    }

    // Sprawdź czy karty mają wymiary (są wyrenderowane)
    const firstCard = cards[0];
    const cardRect = firstCard.getBoundingClientRect();

    if (cardRect.height === 0 || cardRect.width === 0) {
        console.log('[Monitor] Cards not rendered yet, retrying in 500ms...');
        setTimeout(tryInitAutoScroll, 500);
        return;
    }

    // Strona gotowa - oblicz wymiary i sprawdź czy potrzebny scroll
    console.log('[Monitor] Page ready, initializing auto-scroll...');
    calculateGridDimensions();

    // Krótkie opóźnienie 1.5s żeby użytkownik zobaczył pierwszą stronę
    setTimeout(() => {
        checkAutoScrollNeeded();
    }, 1500);
}

/**
 * Check if auto-scroll is needed and start/stop accordingly
 */
function checkAutoScrollNeeded() {
    const grid = document.querySelector('.orders-grid');
    if (!grid) return;

    const state = window.MONITOR_STATE.autoScroll;
    const cards = grid.querySelectorAll('.order-card');

    if (cards.length === 0 || state.columnsCount === 0 || state.rowHeight === 0) {
        console.log(`[Monitor] Check scroll skipped: cards=${cards.length}, cols=${state.columnsCount}, rowH=${state.rowHeight}`);
        return;
    }

    const totalRows = Math.ceil(cards.length / state.columnsCount);
    const visibleRows = getVisibleRowCount();

    // Sprawdź też czy grid jest wyższy niż viewport (fallback)
    const gridHeight = grid.scrollHeight;
    const header = document.querySelector('.monitor-header');
    const headerHeight = header ? header.getBoundingClientRect().height : 140;
    const viewportHeight = window.innerHeight - headerHeight;
    const needsScrollByHeight = gridHeight > viewportHeight;

    console.log(`[Monitor] Check scroll: ${cards.length} cards, ${state.columnsCount} cols, ${totalRows} total rows, ${visibleRows} visible, gridH=${gridHeight}px, viewH=${viewportHeight}px, needsByHeight=${needsScrollByHeight}`);

    if (totalRows > visibleRows || needsScrollByHeight) {
        // Potrzebny scroll
        if (!state.isRunning) {
            startAutoScroll();
        }
    } else {
        // Nie potrzebny scroll
        if (state.isRunning) {
            stopAutoScroll();
        }
    }
}

/**
 * Calculate grid dimensions (columns, row height)
 */
function calculateGridDimensions() {
    const grid = document.querySelector('.orders-grid');
    if (!grid) return;

    const cards = grid.querySelectorAll('.order-card');
    if (cards.length === 0) return;

    const state = window.MONITOR_STATE.autoScroll;
    const gridStyle = window.getComputedStyle(grid);
    const gap = parseInt(gridStyle.gap) || 12;

    // Pobierz wymiary pierwszej karty
    const firstCard = cards[0];
    const cardRect = firstCard.getBoundingClientRect();

    if (cardRect.height > 0) {
        state.rowHeight = cardRect.height + gap;
    }

    // Oblicz liczbę kolumn
    const gridRect = grid.getBoundingClientRect();
    if (cardRect.width > 0) {
        state.columnsCount = Math.max(1, Math.round(gridRect.width / (cardRect.width + gap)));
    }

    console.log(`[Monitor] Grid dimensions: rowHeight=${state.rowHeight}px, columns=${state.columnsCount}`);
}

/**
 * Get visible row count (based on viewport, not content height)
 */
function getVisibleRowCount() {
    const content = document.querySelector('.monitor-content');
    if (!content) return 3;

    const state = window.MONITOR_STATE.autoScroll;
    if (!state.rowHeight || state.rowHeight === 0) return 3;

    // Użyj wysokości widocznego obszaru (viewport minus header)
    const header = document.querySelector('.monitor-header');
    const headerHeight = header ? header.getBoundingClientRect().height : 140;
    const viewportHeight = window.innerHeight - headerHeight;

    // Padding kontenera
    const contentStyle = window.getComputedStyle(content);
    const paddingTop = parseInt(contentStyle.paddingTop) || 16;

    const availableHeight = viewportHeight - paddingTop;
    const visibleRows = Math.floor(availableHeight / state.rowHeight);

    console.log(`[Monitor] Viewport calc: viewportH=${viewportHeight}px, availableH=${availableHeight}px, rowH=${state.rowHeight}px, visibleRows=${visibleRows}`);

    return visibleRows;
}

/**
 * Create scroll indicator element
 */
function createScrollIndicator() {
    // Usuń jeśli istnieje
    const existing = document.querySelector('.auto-scroll-indicator');
    if (existing) existing.remove();

    const indicator = document.createElement('div');
    indicator.className = 'auto-scroll-indicator';
    indicator.style.display = 'none'; // Domyślnie ukryty
    indicator.innerHTML = `
        <svg class="scroll-icon animated" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 5v14M5 12l7 7 7-7"/>
        </svg>
        <span class="scroll-status">Auto-scroll</span>
        <span class="pause-countdown" style="display: none;"></span>
    `;

    document.body.appendChild(indicator);
}

/**
 * Start auto-scroll animation
 */
function startAutoScroll() {
    const state = window.MONITOR_STATE.autoScroll;

    if (state.isRunning) {
        console.log('[Monitor] Auto-scroll already running');
        return;
    }

    if (state.animationId) {
        cancelAnimationFrame(state.animationId);
    }

    state.enabled = true;
    state.isRunning = true;
    state.isPaused = false;
    state.lastFrameTime = performance.now();

    console.log(`[Monitor] Starting smooth auto-scroll (${state.scrollSpeed}px/s, pause every ${state.pauseEveryNRows} rows)`);

    updateScrollIndicator(false);

    // Start animation loop
    animateScroll();
}

/**
 * Animation loop for smooth scrolling
 */
function animateScroll() {
    const state = window.MONITOR_STATE.autoScroll;

    if (!state.enabled || !state.isRunning) return;

    const now = performance.now();
    const deltaTime = (now - state.lastFrameTime) / 1000; // w sekundach
    state.lastFrameTime = now;

    if (!state.isPaused && state.rowHeight > 0) {
        // Oblicz przesunięcie
        const pixelsToMove = state.scrollSpeed * deltaTime;
        state.currentOffset += pixelsToMove;

        // Zastosuj transform do grida
        applyScrollTransform();

        // Sprawdź czy trzeba przenieść wiersz
        if (state.currentOffset >= state.rowHeight) {
            moveTopRowToBottom();
        }
    }

    // Kontynuuj animację
    state.animationId = requestAnimationFrame(animateScroll);
}

/**
 * Apply CSS transform to grid for smooth scrolling
 */
function applyScrollTransform() {
    const grid = document.querySelector('.orders-grid');
    if (!grid) return;

    const state = window.MONITOR_STATE.autoScroll;
    grid.style.transform = `translateY(-${state.currentOffset}px)`;
}

/**
 * Move top row of cards to bottom
 */
function moveTopRowToBottom() {
    const grid = document.querySelector('.orders-grid');
    if (!grid) return;

    const state = window.MONITOR_STATE.autoScroll;
    const cards = grid.querySelectorAll('.order-card');

    if (cards.length < state.columnsCount) return;

    // Przenieś tyle kart ile jest kolumn (cały wiersz)
    for (let i = 0; i < state.columnsCount && i < cards.length; i++) {
        grid.appendChild(cards[i]);
    }

    // Reset offset (odejmij wysokość wiersza)
    state.currentOffset -= state.rowHeight;

    // Natychmiast zastosuj nową pozycję żeby nie było skoku
    grid.style.transform = `translateY(-${state.currentOffset}px)`;

    // Zwiększ licznik wierszy
    state.rowsMoved++;

    // Sprawdź czy czas na pauzę
    if (state.rowsMoved >= state.pauseEveryNRows) {
        pauseAutoScroll();
    }
}

/**
 * Stop auto-scroll completely
 */
function stopAutoScroll() {
    const state = window.MONITOR_STATE.autoScroll;

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
    state.currentOffset = 0;
    state.rowsMoved = 0;

    // Reset transform
    const grid = document.querySelector('.orders-grid');
    if (grid) {
        grid.style.transform = '';
    }

    // Ukryj indicator
    const indicator = document.querySelector('.auto-scroll-indicator');
    if (indicator) {
        indicator.style.display = 'none';
    }

    console.log('[Monitor] Auto-scroll stopped');
}

/**
 * Pause auto-scroll with countdown
 */
function pauseAutoScroll() {
    const state = window.MONITOR_STATE.autoScroll;

    state.isPaused = true;
    state.pauseCountdown = Math.ceil(state.pauseDuration / 1000);

    console.log(`[Monitor] Auto-scroll paused for ${state.pauseCountdown}s`);

    updateScrollIndicator(true);

    // Odliczanie pauzy
    state.pauseCountdownTimer = setInterval(() => {
        state.pauseCountdown--;
        updatePauseCountdown();

        if (state.pauseCountdown <= 0) {
            clearInterval(state.pauseCountdownTimer);
            state.pauseCountdownTimer = null;
        }
    }, 1000);

    // Timer do wznowienia
    state.pauseTimer = setTimeout(() => {
        state.isPaused = false;
        state.rowsMoved = 0;
        state.lastFrameTime = performance.now(); // Reset time to avoid jump
        updateScrollIndicator(false);
        console.log('[Monitor] Auto-scroll resumed');
    }, state.pauseDuration);
}

/**
 * Update scroll indicator UI
 */
function updateScrollIndicator(isPaused) {
    const indicator = document.querySelector('.auto-scroll-indicator');
    if (!indicator) return;

    indicator.style.display = 'flex';

    const statusText = indicator.querySelector('.scroll-status');
    const countdown = indicator.querySelector('.pause-countdown');
    const icon = indicator.querySelector('.scroll-icon');

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
    const indicator = document.querySelector('.auto-scroll-indicator');
    if (!indicator) return;

    const countdown = indicator.querySelector('.pause-countdown');
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
=======
   CONNECTION STATUS
   ============================================================================ */

/**
 * Set online status
 */
function setOnlineStatus() {
    if (window.MONITOR_STATE.isOnline) return;

    window.MONITOR_STATE.isOnline = true;

    const statusElement = document.getElementById('connection-status');
    const offlineBanner = document.getElementById('offline-banner');

    if (statusElement) {
        statusElement.classList.remove('offline');
        statusElement.classList.add('online');
        statusElement.querySelector('.status-text').textContent = 'ONLINE';
    }

    if (offlineBanner) {
        offlineBanner.style.display = 'none';
    }

    console.log('[Monitor] Status: ONLINE');
}

/**
 * Set offline status
 */
function setOfflineStatus() {
    if (!window.MONITOR_STATE.isOnline) return;

    window.MONITOR_STATE.isOnline = false;

    const statusElement = document.getElementById('connection-status');
    const offlineBanner = document.getElementById('offline-banner');

    if (statusElement) {
        statusElement.classList.remove('online');
        statusElement.classList.add('offline');
        statusElement.querySelector('.status-text').textContent = 'OFFLINE';
    }

    if (offlineBanner) {
        offlineBanner.style.display = 'block';
    }

    console.log('[Monitor] Status: OFFLINE');

    // Try to reconnect after 10 seconds
    setTimeout(() => {
        checkConnection();
    }, 10000);
}

/**
 * Check connection to server
 */
async function checkConnection() {
    try {
        const response = await fetch('/production/api/health', {
            method: 'GET',
            cache: 'no-cache'
        });

        if (response.ok) {
            setOnlineStatus();
            // Reload to get fresh data
            window.location.reload();
        } else {
            setOfflineStatus();
        }
    } catch (error) {
        setOfflineStatus();
>>>>>>> Stashed changes
    }
}

/* ============================================================================
<<<<<<< Updated upstream
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
=======
   VISIBILITY API - Pause refresh when tab not visible
   ============================================================================ */

document.addEventListener('visibilitychange', function() {
    if (document.hidden) {
        console.log('[Monitor] Tab hidden - pausing refresh');
        if (window.MONITOR_STATE.refreshTimer) {
            clearInterval(window.MONITOR_STATE.refreshTimer);
        }
        if (window.MONITOR_STATE.countdownTimer) {
            clearInterval(window.MONITOR_STATE.countdownTimer);
        }
    } else {
        console.log('[Monitor] Tab visible - resuming refresh');
        // Refresh immediately when tab becomes visible
        refreshMonitorData();
        startRefreshCountdown();
        startAutoRefresh();
    }
});

/* ============================================================================
   DEBUG
   ============================================================================ */

if (window.MONITOR_CONFIG?.debugMode) {
    window.monitorDebug = {
        getState: () => window.MONITOR_STATE,
        refresh: () => refreshMonitorData(),
        setOffline: () => setOfflineStatus(),
        setOnline: () => setOnlineStatus()
    };
    console.log('[Monitor] Debug mode enabled - use window.monitorDebug');
}
>>>>>>> Stashed changes
