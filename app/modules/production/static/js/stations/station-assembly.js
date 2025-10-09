// station-cutting.js - Dedykowana logika dla stanowiska wycinania
// Wersja 2.0 - Nowy interfejs

/**
 * Initialize Cutting Station
 */
function initAssemblyStation() {
    console.log('[Assembly] Initializing station v2.0...');

    // Load config
    const config = window.StationCommon.loadStationConfig();

    if (!config) {
        console.error('[Assembly] Failed to load config');
        window.StationCommon.showError('Błąd konfiguracji stanowiska');
        return;
    }

    // Attach event listeners to existing cards
    const existingCards = document.querySelectorAll('.product-card');
    console.log(`[Assembly] Found ${existingCards.length} existing cards`);

    existingCards.forEach(card => {
        attachCardEventListeners(card);
    });

    // Start auto-refresh
    if (config.autoRefreshEnabled) {
        window.StationCommon.startAutoRefresh(autoRefreshCallback);
        console.log(`[Assembly] Auto-refresh started (${config.refreshInterval}s)`);
    }

    // Initialize Connection Monitor (Offline Mode)
    window.StationCommon.initConnectionMonitor();

    // Register connection change handler
    window.StationCommon.onConnectionChange((isOnline) => {
        handleConnectionChange(isOnline);
    });

    // ✅ POPRAWIONE
    window.StationCommon.fetchTodayM3('assembly').catch(err => {
        console.error('[Assembly] Failed to load today m3:', err);
    });

    // Setup keyboard shortcuts
    setupKeyboardShortcuts();

    // Theme toggle
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            document.body.classList.toggle('light-mode');
            const isLight = document.body.classList.contains('light-mode');

            // Zmień ikonę
            const sunIcon = themeToggle.querySelector('.sun-icon');
            const moonIcon = themeToggle.querySelector('.moon-icon');
            const themeText = themeToggle.querySelector('.theme-text');

            // DODANE: Zmień logo
            const logo = document.getElementById('station-logo');
            if (logo) {
                logo.src = isLight
                    ? "{{ url_for('static', filename='images/logo.svg') }}"
                    : "{{ url_for('static', filename='images/logo-light.svg') }}";
            }

            if (isLight) {
                sunIcon.style.display = 'none';
                moonIcon.style.display = 'block';
                themeText.textContent = 'Tryb ciemny';
            } else {
                sunIcon.style.display = 'block';
                moonIcon.style.display = 'none';
                themeText.textContent = 'Tryb jasny';
            }

            // Zapisz preferencję
            localStorage.setItem('theme', isLight ? 'light' : 'dark');
        });

        // Wczytaj zapisaną preferencję
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme === 'light') {
            themeToggle.click();
        }
    }
    console.log('[Assembly] Station initialized successfully');
}

/**
 * Auto-refresh callback
 */
async function autoRefreshCallback() {
    // Check if already refreshing
    if (window.STATION_STATE.isRefreshing) {
        console.log('[Assembly] Refresh already in progress, skipping');
        return;
    }
    // Check network
    if (!window.StationCommon.isOnline()) {
        console.warn('[Assembly] Offline - skipping refresh');
        window.StationCommon.showWarning('Brak połączenia - pominięto odświeżanie');
        return;
    }
    window.STATION_STATE.isRefreshing = true;
    try {
        const stationCode = window.STATION_STATE.config.stationCode;
        console.log(`[Assembly] Fetching products for station: ${stationCode}`);
        // Fetch new data
        const data = await window.StationCommon.fetchProducts(stationCode, 'priority');
        // Validate data
        if (!data || !data.products) {
            throw new Error('Invalid response data');
        }
        console.log(`[Assembly] Received ${data.products.length} products`);
        // Smart merge - only add new, don't touch processing
        window.StationCommon.smartMergeProducts(data.products);
        // Update stats bar
        if (data.stats) {
            window.StationCommon.updateStatsBar(data.stats);
        }

        // ✅ POPRAWIONE
        window.StationCommon.fetchTodayM3('assembly').catch(err => {
            console.error('[Assembly] Failed to refresh today m3:', err);
        });

        console.log('[Assembly] Auto-refresh completed successfully');
    } catch (error) {
        console.error('[Assembly] Auto-refresh failed:', error);
        window.StationCommon.showError(`Błąd odświeżania: ${error.message}`);
    } finally {
        window.STATION_STATE.isRefreshing = false;

        // Restart countdown po zakończeniu odświeżania
        if (typeof window.StationCommon.startRefreshCountdown === 'function') {
            window.StationCommon.startRefreshCountdown();
        }
    }
}

/**
 * Attach event listeners to a card
 * @param {HTMLElement} card - Product card element
 */
function attachCardEventListeners(card) {
    if (!card) {
        console.warn('[Assembly] Cannot attach listeners to null card');
        return;
    }

    const productId = card.dataset.productId;
    const completeBtn = card.querySelector('[data-action="complete"]');

    if (!completeBtn) {
        console.warn(`[Assembly] Complete button not found in card: ${productId}`);
        return;
    }

    // Remove existing listeners (prevent duplicates)
    const newBtn = completeBtn.cloneNode(true);
    completeBtn.parentNode.replaceChild(newBtn, completeBtn);

    // Add click listener
    newBtn.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        handleCompleteClick(card, productId);
    });

    // Add keyboard support (Enter or Space when focused)
    newBtn.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleCompleteClick(card, productId);
        }
    });

    console.log(`[Assembly] Event listeners attached to card: ${productId}`);
}

/**
 * Handle complete button click
 * @param {HTMLElement} card - Card element
 * @param {string} productId - Product ID
 */
function handleCompleteClick(card, productId) {
    console.log(`[Assembly] Complete clicked: ${productId}`);

    // Check if online - FIRST PRIORITY
    if (!window.StationCommon.isOnline()) {
        console.warn('[Assembly] Cannot complete - offline');
        window.StationCommon.showWarning('Brak połączenia - poczekaj na powrót internetu');
        return;
    }

    // Check if already in progress
    if (card.dataset.inProgress === 'true') {
        console.warn(`[Assembly] Card already in progress: ${productId}`);
        return;
    }

    // Validate card state
    if (!card || !card.parentElement) {
        console.error(`[Assembly] Invalid card state: ${productId}`);
        return;
    }

    // Mark card as in progress
    card.dataset.inProgress = 'true';
    card.classList.add('processing');

    // Start countdown
    startCompleteCountdown(card, productId);
}
/**
 * Start 10-second countdown before completion
 * @param {HTMLElement} card - Card element
 * @param {string} productId - Product ID
 */
function startCompleteCountdown(card, productId) {
    const completeBtn = card.querySelector('.btn-complete');
    const actionContainer = card.querySelector('.card-action');

    if (!completeBtn || !actionContainer) {
        console.error(`[Assembly] Missing button/container for ${productId}`);
        return;
    }

    // Change button to processing state
    setButtonProcessing(completeBtn);

    // Create countdown container
    const countdownHTML = document.createElement('div');
    countdownHTML.className = 'action-countdown';
    countdownHTML.innerHTML = `
        <button class="btn-complete processing">
            <span class="spinner"></span>
            <span>KOŃCZENIE... 10s</span>
        </button>
        <button class="btn-cancel" data-action="cancel">ANULUJ</button>
    `;

    // Replace button with countdown
    actionContainer.innerHTML = '';
    actionContainer.appendChild(countdownHTML);

    const processingBtn = countdownHTML.querySelector('.btn-complete');
    const cancelBtn = countdownHTML.querySelector('.btn-cancel');

    // Countdown state
    let secondsLeft = 10;
    let timerId = null;

    // Update countdown text
    const updateCountdown = () => {
        if (!processingBtn || !processingBtn.parentElement) {
            console.warn(`[Assembly] Button removed during countdown: ${productId}`);
            if (timerId) clearInterval(timerId);
            return;
        }

        const textSpan = processingBtn.querySelector('span:last-child');
        if (textSpan) {
            textSpan.textContent = `KOŃCZENIE... ${secondsLeft}s`;
        }
    };

    // Start countdown timer
    timerId = setInterval(() => {
        secondsLeft--;

        if (secondsLeft > 0) {
            updateCountdown();
        } else {
            // Countdown finished
            clearInterval(timerId);
            window.STATION_STATE.countdownTimers.delete(productId);

            // Execute completion
            onCountdownComplete(card, productId);
        }
    }, 1000);

    // Store timer ID
    window.STATION_STATE.countdownTimers.set(productId, timerId);

    // Cancel button listener
    const cancelHandler = (event) => {
        event.preventDefault();
        event.stopPropagation();
        console.log(`[Assembly] Cancel button clicked for ${productId}`);
        cancelCountdown(card, productId, timerId);
    };

    cancelBtn.addEventListener('click', cancelHandler);
    cancelBtn.addEventListener('touchstart', cancelHandler, { passive: false });

    // Keyboard support for cancel
    cancelBtn.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            cancelCountdown(card, productId, timerId);
        }
    });

    console.log(`[Assembly] Countdown started for ${productId} (10s)`);
}

/**
 * Cancel countdown for a card
 * @param {HTMLElement} card - Card element
 * @param {string} productId - Product ID
 * @param {number} timerId - Timer ID
 */
function cancelCountdown(card, productId, timerId) {
    console.log(`[Assembly] Countdown cancelled: ${productId}`);

    // Clear timer
    if (timerId) {
        clearInterval(timerId);
        window.STATION_STATE.countdownTimers.delete(productId);
    }

    // Validate card still exists
    if (!card || !card.parentElement) {
        console.warn(`[Assembly] Card no longer exists: ${productId}`);
        return;
    }

    // Reset card state
    card.dataset.inProgress = 'false';
    card.classList.remove('processing');

    // Reset button
    const actionContainer = card.querySelector('.card-action');
    if (actionContainer) {
        actionContainer.innerHTML = '<button class="btn-complete" data-action="complete">ZAKOŃCZ</button>';

        // Re-attach listener
        const newCompleteBtn = actionContainer.querySelector('.btn-complete');
        if (newCompleteBtn) {
            // Check if we're offline and disable button if needed
            if (!window.StationCommon.isOnline()) {
                newCompleteBtn.classList.add('disabled-offline');
                newCompleteBtn.disabled = true;
                console.log(`[Assembly] Button disabled after cancel (offline): ${productId}`);
            }

            newCompleteBtn.addEventListener('click', function (event) {
                event.preventDefault();
                event.stopPropagation();
                handleCompleteClick(card, productId);
            });
        }
    }

    window.StationCommon.showInfo('Anulowano ukończenie zadania');
}

/**
 * Execute task completion after countdown
 * @param {HTMLElement} card - Card element
 * @param {string} productId - Product ID
 */
async function onCountdownComplete(card, productId) {
    console.log(`[Assembly] Completing task: ${productId}`);

    const actionContainer = card.querySelector('.card-action');
    const stationCode = window.STATION_STATE.config.stationCode;

    // Validate card still exists
    if (!card || !card.parentElement) {
        console.error(`[Assembly] Card removed during countdown: ${productId}`);
        return;
    }

    // ✅ DODANE - Pobierz volume_m3 PRZED usunięciem karty
    const volumeElement = card.querySelector('.header-volume');
    let productVolume = 0.0;
    if (volumeElement) {
        const match = volumeElement.textContent.match(/[\d.]+/);
        if (match) {
            productVolume = parseFloat(match[0]);
            console.log(`[Assembly] Product volume: ${productVolume} m³`);
        }
    }

    try {
        // Show processing state
        if (actionContainer) {
            actionContainer.innerHTML = `
                <button class="btn-complete processing">
                    <span class="spinner"></span>
                    <span>ZAPISYWANIE...</span>
                </button>
            `;
        }

        // Call API
        const response = await window.StationCommon.completeTask(productId, stationCode);

        console.log(`[Assembly] Task completed successfully: ${productId}`, response);

        // ✅ DODANE - Inkrementuj today-m3 natychmiast po sukcesie
        if (productVolume > 0) {
            window.StationCommon.incrementTodayM3(productVolume);
        }

        // Show success state (1 second)
        if (actionContainer) {
            actionContainer.innerHTML = `
                <button class="btn-complete success">ZAKOŃCZONO ✓</button>
            `;
        }

        // Success notification
        window.StationCommon.showSuccess(`Produkt ${productId} ukończony`);

        // Wait 1 second, then remove card
        setTimeout(() => {
            if (card && card.parentElement) {
                window.StationCommon.removeProductCard(productId);
                updateStatsAfterCompletion();
            }
        }, 1000);

    } catch (error) {
        console.error(`[Assembly] Failed to complete task: ${productId}`, error);

        // Show detailed error
        const errorMessage = error.message || 'Nieznany błąd';
        window.StationCommon.showError(`Nie udało się ukończyć: ${errorMessage}`);

        // Reset card on error
        if (card && card.parentElement) {
            card.dataset.inProgress = 'false';
            card.classList.remove('processing');

            if (actionContainer) {
                actionContainer.innerHTML = '<button class="btn-complete" data-action="complete">ZAKOŃCZ</button>';

                // Re-attach listener
                const newCompleteBtn = actionContainer.querySelector('.btn-complete');
                if (newCompleteBtn) {
                    newCompleteBtn.addEventListener('click', function (event) {
                        event.preventDefault();
                        event.stopPropagation();
                        handleCompleteClick(card, productId);
                    });
                }
            }
        }
    }
}

/**
 * Update stats after completion (approximate)
 */
function updateStatsAfterCompletion() {
    const totalElement = document.getElementById('total-products');
    if (totalElement) {
        const current = parseInt(totalElement.textContent) || 0;
        if (current > 0) {
            totalElement.textContent = current - 1;
        }
    }

    // Update volume
    const volumeElement = document.getElementById('total-volume');
    if (volumeElement) {
        const cards = document.querySelectorAll('.product-card');
        let totalVolume = 0;

        cards.forEach(card => {
            const volumeText = card.querySelector('.header-volume');
            if (volumeText) {
                const match = volumeText.textContent.match(/[\d.]+/);
                if (match) {
                    totalVolume += parseFloat(match[0]);
                }
            }
        });

        volumeElement.textContent = totalVolume.toFixed(4);
    }

    // Check if empty
    const remainingCards = window.StationCommon.getAllCards();
    if (remainingCards.length === 0) {
        console.log('[Assembly] No more products - showing empty state');
        window.StationCommon.showEmptyState();
    }
}

/**
 * Set button to processing state
 * @param {HTMLElement} button - Button element
 */
function setButtonProcessing(button) {
    if (!button) return;
    button.classList.add('processing');
    button.classList.remove('success');
    button.disabled = true;
}

/**
 * Handle connection state changes
 * @param {boolean} isOnline - Connection state
 */
function handleConnectionChange(isOnline) {
    console.log(`[Assembly] Connection changed: ${isOnline ? 'ONLINE' : 'OFFLINE'}`);

    const completeButtons = document.querySelectorAll('.btn-complete');
    const refreshCountdownElement = document.getElementById('refresh-countdown');

    if (isOnline) {
        // ========== ONLINE MODE ==========

        // Enable all complete buttons
        completeButtons.forEach(btn => {
            btn.classList.remove('disabled-offline');
            btn.disabled = false;
        });
        console.log('[Assembly] All complete buttons enabled');

        // Resume refresh countdown
        if (window.STATION_STATE.countdownTimer) {
            console.log('[Assembly] Refresh countdown already running');
        } else {
            console.log('[Assembly] Restarting refresh countdown');
            window.StationCommon.startRefreshCountdown();
        }

        // Remove warning class from countdown display
        if (refreshCountdownElement) {
            refreshCountdownElement.classList.remove('warning');
        }

    } else {
        // ========== OFFLINE MODE ==========

        // Disable all complete buttons
        completeButtons.forEach(btn => {
            btn.classList.add('disabled-offline');
            btn.disabled = true;
        });

        // Cancel all active countdowns
        const activeTimers = window.STATION_STATE.countdownTimers;
        if (activeTimers.size > 0) {
            console.log(`[Assembly] Cancelling ${activeTimers.size} active countdowns due to offline`);
            activeTimers.forEach((timerId, productId) => {
                const card = window.StationCommon.getCardById(productId);
                if (card) {
                    cancelCountdown(card, productId, timerId);
                }
            });
            window.StationCommon.showWarning('Aktywne zadania anulowane - brak połączenia');
        }

        // Stop refresh countdown
        if (window.STATION_STATE.countdownTimer) {
            clearInterval(window.STATION_STATE.countdownTimer);
            window.STATION_STATE.countdownTimer = null;
            console.log('[Assembly] Refresh countdown stopped');
        }

        // Update countdown display to show offline
        if (refreshCountdownElement) {
            refreshCountdownElement.textContent = 'OFFLINE';
            refreshCountdownElement.classList.add('warning');
        }

        console.log('[Assembly] All complete buttons disabled');
    }
}

/**
 * Setup keyboard shortcuts
 */
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (event) => {
        // Escape - cancel all countdowns
        if (event.key === 'Escape') {
            const activeTimers = window.STATION_STATE.countdownTimers;
            if (activeTimers.size > 0) {
                console.log(`[Assembly] Escape pressed - cancelling ${activeTimers.size} countdowns`);
                activeTimers.forEach((timerId, productId) => {
                    const card = window.StationCommon.getCardById(productId);
                    if (card) {
                        cancelCountdown(card, productId, timerId);
                    }
                });
            }
        }

        // F5 or Ctrl+R - manual refresh (log it)
        if (event.key === 'F5' || (event.ctrlKey && event.key === 'r')) {
            console.log('[Assembly] Manual refresh triggered');
        }
    });
}

/**
 * Toggle debug mode
 */
function toggleDebugMode() {
    document.body.classList.toggle('debug-mode');
    console.log('[Assembly] Debug mode toggled');
    console.log('State:', window.STATION_STATE);
    window.StationCommon.showInfo('Debug mode toggled (check console)');
}

/**
 * Initialize on DOM ready
 */
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAssemblyStation);
} else {
    initAssemblyStation();
}

/**
 * Cleanup on page unload
 */
window.addEventListener('beforeunload', () => {
    console.log('[Assembly] Cleaning up...');
    window.StationCommon.stopAutoRefresh();

    // Clear all countdown timers
    window.STATION_STATE.countdownTimers.forEach((timerId, productId) => {
        clearInterval(timerId);
        console.log(`[Assembly] Cleared timer for ${productId}`);
    });
    window.STATION_STATE.countdownTimers.clear();
});

/**
 * Debug helpers (available in console)
 */
window.CuttingDebug = {
    getState: () => window.STATION_STATE,
    getConfig: () => window.STATION_STATE.config,
    triggerRefresh: autoRefreshCallback,
    cancelAll: () => {
        window.STATION_STATE.countdownTimers.forEach((timerId, productId) => {
            const card = window.StationCommon.getCardById(productId);
            if (card) cancelCountdown(card, productId, timerId);
        });
    },
    listCards: () => {
        const cards = window.StationCommon.getAllCards();
        console.table(cards.map(c => ({
            id: c.dataset.productId,
            priority: c.dataset.priorityRank,
            inProgress: c.dataset.inProgress
        })));
    },
    forceComplete: async (productId) => {
        try {
            const result = await window.StationCommon.completeTask(
                productId,
                window.STATION_STATE.config.stationCode
            );
            console.log('Force complete result:', result);
            window.StationCommon.removeProductCard(productId);
        } catch (error) {
            console.error('Force complete failed:', error);
        }
    }
};

// Attach debug toggle to button
const debugBtn = document.getElementById('debug-toggle');
if (debugBtn) {
    debugBtn.addEventListener('click', toggleDebugMode);
}

console.log('[Assembly] Station module loaded v2.0');
console.log('[Assembly] Debug commands available via window.CuttingDebug');