/**
 * ============================================================================
 * STATION ASSEMBLY - QUANTITY-BASED VERSION
 * ============================================================================
 *
 * Wersja z quantity buttons (+/-) zamiast checkboxów
 *
 * Funkcjonalność:
 * - Przyciski +/- do zmiany quantity_done
 * - Przyciski +10/-10 dla ilości >= 10
 * - Natychmiastowy zapis do API (rate limiting 200ms)
 * - Bulk completion całych zamówień z countdown 10s
 * - Optimistic UI z error recovery
 * - Smart merge podczas auto-refresh
 * - Zegar odświeżany co sekundę
 * - Auto-refresh co 60s (z konfiguracji)
 *
 * @author: Konrad Kmiecik
 * @date: 2025-11
 * @version: 3.0
 */

(function() {
    'use strict';

    // ========================================================================
    // STATE
    // ========================================================================

    const state = {
        config: null,
        refreshTimer: null,
        countdownTimer: null,
        activeCountdowns: new Map(), // orderNumber -> { timerId, secondsLeft }
        pendingRequests: new Map(),  // productId -> timeoutId (rate limiting)
        lastRequestTime: new Map()   // productId -> timestamp
    };

    const RATE_LIMIT_MS = 200; // Minimalny odstęp między requestami dla tego samego produktu

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    document.addEventListener('DOMContentLoaded', function() {
        console.log('[Assembly] Initializing QUANTITY-BASED station v3.0...');
        initializeAssemblyStation();
    });

    function initializeAssemblyStation() {
        const config = window.STATION_CONFIG;

        if (!config || config.stationCode !== 'assembly') {
            console.error('[Assembly] Invalid station config');
            return;
        }

        state.config = config;
        console.log('[Assembly] Station config loaded:', config);

        // Attach event listeners to existing order cards
        const existingCards = document.querySelectorAll('.order-card');
        console.log(`[Assembly] Found ${existingCards.length} order cards`);

        existingCards.forEach(card => {
            initializeOrderCard(card);
        });

        // Fetch today's m³
        fetchTodayM3();

        // Start datetime clock (updates every second)
        setInterval(updateCurrentDatetime, 1000);
        updateCurrentDatetime();

        // Start auto-refresh with countdown
        if (config.refreshInterval && config.refreshInterval > 0) {
            startAutoRefresh(config.refreshInterval);
            startRefreshCountdown(config.refreshInterval);
        }

        // Theme toggle
        setupThemeToggle();

        // Initialize connection monitor
        if (window.StationCommon && window.StationCommon.initConnectionMonitor) {
            window.StationCommon.initConnectionMonitor();
            console.log('[Assembly] Connection monitor initialized');

            // Register listener for connection changes
            if (window.StationCommon.onConnectionChange) {
                window.StationCommon.onConnectionChange(handleConnectionChange);
                console.log('[Assembly] Connection change listener registered');
            }
        }

        // Initialize expand icons for fullscreen mode
        if (typeof window.initExpandIcons === 'function') {
            window.initExpandIcons();
            console.log('[Assembly] Expand icons initialized');
        }

        // Initialize order search button
        if (typeof window.initOrderSearchButton === 'function') {
            window.initOrderSearchButton();
            console.log('[Assembly] Order search button initialized');
        }

        console.log('[Assembly] Station initialized successfully');
    }

    // ========================================================================
    // DATETIME UPDATES
    // ========================================================================

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

        // Update day label
        const labelElement = datetimeElement.previousElementSibling;
        if (labelElement && labelElement.classList.contains('stat-label')) {
            labelElement.textContent = dayName;
        }
    }

    // ========================================================================
    // REFRESH COUNTDOWN
    // ========================================================================

    function startRefreshCountdown(intervalSeconds) {
        if (state.countdownTimer) {
            clearInterval(state.countdownTimer);
        }

        let secondsLeft = intervalSeconds;
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

                // Spin icon when <= 5s
                if (secondsLeft <= 5) {
                    if (refreshIcon) refreshIcon.classList.add('spinning');
                } else {
                    if (refreshIcon) refreshIcon.classList.remove('spinning');
                }
            }
        };

        updateCountdown();

        state.countdownTimer = setInterval(() => {
            secondsLeft--;

            if (secondsLeft <= 0) {
                secondsLeft = intervalSeconds;
            }

            updateCountdown();
        }, 1000);

        console.log(`[Assembly] Refresh countdown started: ${intervalSeconds}s`);
    }

    // ========================================================================
    // ORDER CARD INITIALIZATION
    // ========================================================================

    function initializeOrderCard(card) {
        const orderNumber = card.dataset.orderNumber;

        if (!orderNumber) {
            console.warn('[Assembly] Order card missing order number');
            return;
        }

        console.log(`[Assembly] Initializing order card: ${orderNumber}`);

        // Hide empty product-params containers
        hideEmptyProductParams(card);

        // Attach quantity button listeners
        const quantityButtons = card.querySelectorAll('.btn-qty');
        quantityButtons.forEach(button => {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                handleQuantityButtonClick(card, orderNumber, this);
            });
        });

        // Attach complete button listener
        const completeBtn = card.querySelector('.btn-complete');
        if (completeBtn) {
            completeBtn.addEventListener('click', function() {
                handleCompleteClick(card, orderNumber);
            });
        }

        // Initial button state update
        updateCompleteButtonState(card);
        updateOrderCounter(card);
    }

    // ========================================================================
    // HIDE EMPTY PRODUCT PARAMS
    // ========================================================================

    function hideEmptyProductParams(card) {
        const productRows = card.querySelectorAll('.product-row');

        productRows.forEach(row => {
            const paramsContainer = row.querySelector('.product-params');
            if (!paramsContainer) return;

            // Check if there are any badges inside
            const badges = paramsContainer.querySelectorAll('.badge');

            // If no badges exist, hide the container
            if (badges.length === 0) {
                paramsContainer.style.display = 'none';
            }
        });
    }

    // ========================================================================
    // QUANTITY BUTTON HANDLING
    // ========================================================================

    async function handleQuantityButtonClick(card, orderNumber, button) {
        const productId = button.dataset.productId;
        const action = button.dataset.action;
        const productRow = button.closest('.product-row');

        if (!productId || !action || !productRow) {
            console.warn('[Assembly] Invalid button data');
            return;
        }

        // Check online status
        const isOnline = window.StationCommon && window.StationCommon.isOnline ? window.StationCommon.isOnline() : true;
        if (!isOnline) {
            showToast('warning', 'Brak połączenia - nie można zapisać zmiany');
            return;
        }

        // Get current values
        const qtyDoneEl = productRow.querySelector('.qty-done');
        const qtyTotalEl = productRow.querySelector('.qty-total');

        if (!qtyDoneEl || !qtyTotalEl) return;

        let qtyDone = parseInt(qtyDoneEl.textContent) || 0;
        const qtyTotal = parseInt(qtyTotalEl.textContent) || 0;

        // Calculate new value based on action
        let newQtyDone = qtyDone;
        switch (action) {
            case 'increment':
                newQtyDone = Math.min(qtyDone + 1, qtyTotal);
                break;
            case 'decrement':
                newQtyDone = Math.max(qtyDone - 1, 0);
                break;
            case 'increment10':
                newQtyDone = Math.min(qtyDone + 10, qtyTotal);
                break;
            case 'decrement10':
                newQtyDone = Math.max(qtyDone - 10, 0);
                break;
        }

        // Skip if no change
        if (newQtyDone === qtyDone) {
            return;
        }

        // Optimistic UI update
        qtyDoneEl.textContent = newQtyDone;
        productRow.dataset.quantityDone = newQtyDone;

        // Update button states
        updateProductButtonStates(productRow, newQtyDone, qtyTotal);

        // Update order counter and complete button
        updateOrderCounter(card);
        updateCompleteButtonState(card);

        // Send to API with rate limiting
        await sendQuantityUpdate(productId, action, productRow, qtyDone, card);
    }

    async function sendQuantityUpdate(productId, action, productRow, previousValue, card) {
        // Rate limiting - cancel pending request for this product
        if (state.pendingRequests.has(productId)) {
            clearTimeout(state.pendingRequests.get(productId));
        }

        // Check if we need to wait
        const lastRequest = state.lastRequestTime.get(productId) || 0;
        const timeSinceLastRequest = Date.now() - lastRequest;
        const delay = Math.max(0, RATE_LIMIT_MS - timeSinceLastRequest);

        const timeoutId = setTimeout(async () => {
            state.pendingRequests.delete(productId);
            state.lastRequestTime.set(productId, Date.now());

            try {
                const response = await fetch('/production/api/update-quantity-done', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        product_id: productId,
                        station: 'assembly',
                        action: action
                    })
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || `HTTP ${response.status}`);
                }

                const result = await response.json();
                console.log(`[Assembly] Product ${productId} quantity updated:`, result);

                // Update UI with server response
                const qtyDoneEl = productRow.querySelector('.qty-done');
                if (qtyDoneEl && result.quantity_done !== undefined) {
                    qtyDoneEl.textContent = result.quantity_done;
                    productRow.dataset.quantityDone = result.quantity_done;
                    updateProductButtonStates(productRow, result.quantity_done, result.quantity);
                    updateOrderCounter(card);
                    updateCompleteButtonState(card);
                }

            } catch (error) {
                console.error('[Assembly] Failed to update quantity:', error);

                // Revert UI on error
                const qtyDoneEl = productRow.querySelector('.qty-done');
                if (qtyDoneEl) {
                    qtyDoneEl.textContent = previousValue;
                    productRow.dataset.quantityDone = previousValue;
                    const qtyTotal = parseInt(productRow.querySelector('.qty-total').textContent) || 0;
                    updateProductButtonStates(productRow, previousValue, qtyTotal);
                    updateOrderCounter(card);
                    updateCompleteButtonState(card);
                }

                showToast('error', `Błąd zapisu: ${error.message}`);
            }
        }, delay);

        state.pendingRequests.set(productId, timeoutId);
    }

    function updateProductButtonStates(productRow, qtyDone, qtyTotal) {
        const btnMinus = productRow.querySelector('.btn-minus');
        const btnPlus = productRow.querySelector('.btn-plus');
        const btnMinus10 = productRow.querySelector('.btn-minus-10');
        const btnPlus10 = productRow.querySelector('.btn-plus-10');

        if (btnMinus) {
            btnMinus.disabled = qtyDone <= 0;
        }
        if (btnPlus) {
            btnPlus.disabled = qtyDone >= qtyTotal;
        }
        if (btnMinus10) {
            btnMinus10.disabled = qtyDone < 10;
        }
        if (btnPlus10) {
            btnPlus10.disabled = (qtyTotal - qtyDone) < 10;
        }

        // Update row styling if complete
        if (qtyDone === qtyTotal) {
            productRow.classList.add('product-complete');
        } else {
            productRow.classList.remove('product-complete');
        }
    }

    // ========================================================================
    // ORDER COUNTER UPDATE
    // ========================================================================

    function updateOrderCounter(card) {
        const orderNumber = card.dataset.orderNumber;
        const productRows = card.querySelectorAll('.product-row');

        let totalDone = 0;
        let totalQuantity = 0;

        productRows.forEach(row => {
            const qtyDone = parseInt(row.dataset.quantityDone) || 0;
            const qtyTotal = parseInt(row.dataset.quantity) || 0;
            totalDone += qtyDone;
            totalQuantity += qtyTotal;
        });

        // Update counter in header
        const counterElement = document.querySelector(`.products-checked[data-order="${orderNumber}"]`);
        if (counterElement) {
            counterElement.textContent = totalDone;
        }

        console.log(`[Assembly] Updated counter for ${orderNumber}: ${totalDone}/${totalQuantity}`);
    }

    // ========================================================================
    // CONNECTION STATUS HANDLING
    // ========================================================================

    function handleConnectionChange(isOnline) {
        console.log(`[Assembly] Connection status changed: ${isOnline ? 'ONLINE' : 'OFFLINE'}`);

        // Update all complete buttons
        const allCards = document.querySelectorAll('.order-card');
        allCards.forEach(card => {
            updateCompleteButtonState(card);

            // Disable/enable quantity buttons
            const qtyButtons = card.querySelectorAll('.btn-qty');
            qtyButtons.forEach(btn => {
                if (!isOnline) {
                    btn.classList.add('offline-disabled');
                } else {
                    btn.classList.remove('offline-disabled');
                }
            });
        });
    }

    // ========================================================================
    // COMPLETE BUTTON STATE
    // ========================================================================

    function updateCompleteButtonState(card) {
        const completeBtn = card.querySelector('.btn-complete');
        if (!completeBtn) {
            return;
        }

        // Check if offline first
        const isOnline = window.StationCommon && window.StationCommon.isOnline ? window.StationCommon.isOnline() : true;

        if (!isOnline) {
            completeBtn.disabled = true;
            completeBtn.textContent = 'Jesteś offline';
            completeBtn.classList.add('offline');
            return;
        }

        // Remove offline styling if previously set
        completeBtn.classList.remove('offline');
        completeBtn.textContent = 'ZAKOŃCZ SKŁADANIE';

        // Check if all products are complete (quantity_done == quantity)
        const productRows = card.querySelectorAll('.product-row');
        let allComplete = true;
        let hasProducts = false;

        productRows.forEach(row => {
            hasProducts = true;
            const qtyDone = parseInt(row.dataset.quantityDone) || 0;
            const qtyTotal = parseInt(row.dataset.quantity) || 0;
            if (qtyDone < qtyTotal) {
                allComplete = false;
            }
        });

        // Enable button only if ALL products are complete
        if (allComplete && hasProducts) {
            completeBtn.disabled = false;
        } else {
            completeBtn.disabled = true;
        }
    }

    // ========================================================================
    // COUNTDOWN 10 SEKUND PRZED ZAKOŃCZENIEM
    // ========================================================================

    function handleCompleteClick(card, orderNumber) {
        console.log(`[Assembly] Complete button clicked for order: ${orderNumber}`);

        // Check online status first
        if (!window.StationCommon.isOnline()) {
            console.warn('[Assembly] Offline - cannot complete orders');
            showToast('warning', 'Brak połączenia - nie możesz zakończyć zamówienia');
            return;
        }

        // Get all product IDs
        const productIds = [];
        const productRows = card.querySelectorAll('.product-row');
        productRows.forEach(row => {
            productIds.push(row.dataset.productId);
        });

        if (productIds.length === 0) {
            console.warn('[Assembly] No products found');
            showToast('warning', 'Brak produktów w zamówieniu');
            return;
        }

        // Mark card as in-progress
        card.dataset.inProgress = 'true';
        card.classList.add('processing');

        // Start 10-second countdown
        startCountdown(card, orderNumber, productIds);
    }

    function startCountdown(card, orderNumber, productIds) {
        console.log(`[Assembly] Starting 10-second countdown for ${orderNumber}`);

        const actionContainer = card.querySelector('.order-action');
        if (!actionContainer) {
            console.error('[Assembly] No action container found');
            return;
        }

        // Replace button with countdown UI
        actionContainer.innerHTML = `
            <div class="action-countdown">
                <button class="btn-complete processing">
                    <span class="spinner"></span>
                    <span class="countdown-text">Zapisuje... 10s</span>
                </button>
                <button class="btn-cancel">ANULUJ</button>
            </div>
        `;

        const processingBtn = actionContainer.querySelector('.btn-complete');
        const cancelBtn = actionContainer.querySelector('.btn-cancel');
        const countdownText = processingBtn.querySelector('.countdown-text');

        let secondsLeft = 10;

        const updateCountdownText = () => {
            if (countdownText) {
                countdownText.textContent = `Zapisuje... ${secondsLeft}s`;
            }
        };

        const timerId = setInterval(() => {
            secondsLeft--;

            if (secondsLeft > 0) {
                updateCountdownText();
            } else {
                // Countdown complete - execute bulk completion
                clearInterval(timerId);
                state.activeCountdowns.delete(orderNumber);
                completeOrder(card, orderNumber, productIds);
            }
        }, 1000);

        // Store timer ID
        state.activeCountdowns.set(orderNumber, { timerId, secondsLeft });

        // Cancel button listener
        cancelBtn.addEventListener('click', function(event) {
            event.preventDefault();
            event.stopPropagation();
            cancelCountdown(card, orderNumber, timerId);
        });

        console.log(`[Assembly] Countdown started for ${orderNumber}`);
    }

    function cancelCountdown(card, orderNumber, timerId) {
        console.log(`[Assembly] Countdown cancelled for ${orderNumber}`);

        // Clear timer
        if (timerId) {
            clearInterval(timerId);
            state.activeCountdowns.delete(orderNumber);
        }

        // Reset card state
        card.dataset.inProgress = 'false';
        card.classList.remove('processing');

        // Restore original button
        const actionContainer = card.querySelector('.order-action');
        if (actionContainer) {
            actionContainer.innerHTML = '<button class="btn-complete" data-action="complete" disabled>ZAKOŃCZ SKŁADANIE</button>';

            // Re-attach listener
            const completeBtn = actionContainer.querySelector('.btn-complete');
            if (completeBtn) {
                completeBtn.addEventListener('click', function() {
                    handleCompleteClick(card, orderNumber);
                });

                // Update button state
                updateCompleteButtonState(card);
            }
        }

        showToast('info', 'Anulowano składanie zamówienia');
    }

    // ========================================================================
    // BULK COMPLETION - Optimistic UI
    // ========================================================================

    async function completeOrder(card, orderNumber, productIds) {
        console.log(`[Assembly] Starting bulk completion for ${orderNumber}`, productIds);

        // BACKUP before removal
        const cardBackup = card.cloneNode(true);

        // Show processing state
        const actionContainer = card.querySelector('.order-action');
        if (actionContainer) {
            actionContainer.innerHTML = `
                <button class="btn-complete saving">
                    <span class="spinner"></span>
                    <span>Zapisuje</span>
                </button>
            `;
        }

        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 10000); // 10s timeout

            const response = await fetch('/production/stations/complete-order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    order_number: orderNumber,
                    product_ids: productIds,
                    station: 'assembly',
                    action: 'complete'
                }),
                signal: controller.signal
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(errorText || `HTTP ${response.status}`);
            }

            const result = await response.json();

            console.log('[Assembly] Order completed successfully:', result);

            // SUCCESS - show success state
            if (actionContainer) {
                actionContainer.innerHTML = '<button class="btn-complete success">Zapisano</button>';
            }

            showToast('success', `Zamówienie ${orderNumber} ukończone`);

            // Update today's m³ statistics
            fetchTodayM3();

            // Close fullscreen if active
            if (typeof window.closeFullscreenIfActive === 'function') {
                window.closeFullscreenIfActive(orderNumber);
            }

            // Wait 1 second, then remove card with animation
            setTimeout(() => {
                card.classList.add('removing');
                setTimeout(() => {
                    card.remove();
                    updateStatsAfterRemoval();
                }, 300);
            }, 1000);

        } catch (error) {
            // ERROR - restore card
            console.error('[Assembly] Failed to complete order:', error);

            const ordersList = document.getElementById('orders-list');

            if (ordersList) {
                // Re-insert card
                ordersList.insertBefore(cardBackup, ordersList.firstChild);

                // Re-initialize the restored card
                initializeOrderCard(cardBackup);
            }

            let errorMessage = error.message;
            if (error.name === 'AbortError') {
                errorMessage = 'Timeout - przekroczono 10 sekund';
            }

            showToast('error', `Błąd ukończenia: ${errorMessage}`);
        }
    }

    // ========================================================================
    // STATS UPDATE
    // ========================================================================

    function updateStatsAfterRemoval() {
        // Check if empty state should be shown
        const remainingCards = document.querySelectorAll('.order-card').length;

        if (remainingCards === 0) {
            showEmptyState();
        }

        // Update header statistics
        updateHeaderStats();

        console.log(`[Assembly] Remaining cards: ${remainingCards}`);
    }

    function updateHeaderStats() {
        const allCards = document.querySelectorAll('.order-card');

        let totalProducts = 0;
        let totalVolume = 0;

        allCards.forEach(card => {
            const cardTotalProducts = parseInt(card.dataset.totalProducts) || 0;
            const cardTotalVolume = parseFloat(card.dataset.totalVolume) || 0;

            totalProducts += cardTotalProducts;
            totalVolume += cardTotalVolume;
        });

        // Update DOM
        const totalProductsElement = document.getElementById('total-products');
        const totalVolumeElement = document.getElementById('total-volume');

        if (totalProductsElement) {
            totalProductsElement.textContent = totalProducts;
        }

        if (totalVolumeElement) {
            totalVolumeElement.textContent = totalVolume.toFixed(4);
        }

        console.log(`[Assembly] Updated header stats: ${totalProducts} products, ${totalVolume.toFixed(4)} m³`);
    }

    function showEmptyState() {
        const ordersList = document.getElementById('orders-list');

        if (!ordersList) {
            return;
        }

        ordersList.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">✅</div>
                <h2>Brak zamówień do składania</h2>
                <p>Świetna robota! Wszystkie zamówienia zostały złożone.</p>
            </div>
        `;

        console.log('[Assembly] Showing empty state');
    }

    // ========================================================================
    // TOAST NOTIFICATIONS
    // ========================================================================

    function showToast(type, message) {
        const prefix = type === 'success' ? '✅' : type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️';
        console.log(`[Assembly] ${prefix} ${message}`);

        // TODO: Implement visual toast notifications if needed
    }

    // ========================================================================
    // AUTO-REFRESH WITH SMART MERGE
    // ========================================================================

    function startAutoRefresh(intervalSeconds) {
        if (state.refreshTimer) {
            clearInterval(state.refreshTimer);
        }

        console.log(`[Assembly] Starting auto-refresh every ${intervalSeconds}s`);

        state.refreshTimer = setInterval(async () => {
            await performAutoRefresh();
        }, intervalSeconds * 1000);
    }

    async function performAutoRefresh() {
        console.log('[Assembly] Performing auto-refresh...');

        try {
            const response = await fetch('/production/stations/ajax/orders/assembly?sort=priority');

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const result = await response.json();

            if (!result.success || !result.data || !result.data.orders) {
                throw new Error('Invalid response format');
            }

            console.log(`[Assembly] Fetched ${result.data.orders.length} orders`);

            smartMergeOrders(result.data.orders);

            // Update header statistics from API data (more reliable than DOM)
            updateHeaderStatsFromAPI(result.data.orders);

            // Update today's m³ statistics
            fetchTodayM3();

        } catch (error) {
            console.error('[Assembly] Auto-refresh failed:', error);
        }
    }

    function updateHeaderStatsFromAPI(orders) {
        let totalOrders = orders.length;
        let totalVolume = 0;

        orders.forEach(order => {
            totalVolume += order.total_volume || 0;
        });

        const totalOrdersElement = document.getElementById('total-orders');
        const totalVolumeElement = document.getElementById('total-volume');

        if (totalOrdersElement) {
            totalOrdersElement.textContent = totalOrders;
        }

        if (totalVolumeElement) {
            totalVolumeElement.textContent = totalVolume.toFixed(4);
        }

        console.log(`[Assembly] Updated header stats from API: ${totalOrders} orders, ${totalVolume.toFixed(4)} m³`);
    }

    function smartMergeOrders(newOrders) {
        const ordersList = document.getElementById('orders-list');

        if (!ordersList) {
            return;
        }

        const existingCards = ordersList.querySelectorAll('.order-card');
        const existingOrderNumbers = new Set();

        existingCards.forEach(card => {
            existingOrderNumbers.add(card.dataset.orderNumber);
        });

        // Stwórz zbiór numerów zamówień z API
        const apiOrderNumbers = new Set(newOrders.map(order => order.order_number));

        // Add only NEW orders (that don't exist yet)
        newOrders.forEach(order => {
            if (!existingOrderNumbers.has(order.order_number)) {
                console.log(`[Assembly] Adding new order: ${order.order_number}`);
                addOrderCard(order);
            } else {
                // Update existing order's quantity data
                updateExistingOrderCard(order);
            }
        });

        // Remove cards that are no longer in API response (but not if user is working on them)
        existingCards.forEach(card => {
            const orderNumber = card.dataset.orderNumber;
            if (!apiOrderNumbers.has(orderNumber)) {
                // Sprawdź czy karta nie jest w trakcie przetwarzania (countdown aktywny)
                const hasActiveCountdown = state.activeCountdowns.has(orderNumber);
                const isProcessing = card.classList.contains('processing');

                if (!hasActiveCountdown && !isProcessing) {
                    console.log(`[Assembly] Removing order no longer on station: ${orderNumber}`);
                    card.classList.add('removing');
                    setTimeout(() => {
                        card.remove();
                        // Jeśli nie ma już żadnych kart, pokaż empty state
                        checkAndShowEmptyState();
                    }, 300);
                } else {
                    console.log(`[Assembly] Keeping order ${orderNumber} - user is working on it`);
                }
            }
        });

        console.log('[Assembly] Smart merge completed');
    }

    function updateExistingOrderCard(orderData) {
        const card = document.querySelector(`[data-order-number="${orderData.order_number}"]`);
        if (!card) return;

        // Skip if card is being processed
        if (card.dataset.inProgress === 'true') return;

        // Update each product's quantity data and priority
        orderData.products.forEach(product => {
            const productRow = card.querySelector(`[data-product-id="${product.id}"]`);
            if (productRow) {
                const currentQtyDone = parseInt(productRow.dataset.quantityDone) || 0;
                const serverQtyDone = product.quantity_done || 0;

                // Only update if server value is different and no pending request
                if (currentQtyDone !== serverQtyDone && !state.pendingRequests.has(product.id)) {
                    productRow.dataset.quantityDone = serverQtyDone;
                    const qtyDoneEl = productRow.querySelector('.qty-done');
                    if (qtyDoneEl) {
                        qtyDoneEl.textContent = serverQtyDone;
                    }
                    updateProductButtonStates(productRow, serverQtyDone, product.quantity);
                }

                // Update priority status
                const currentPriority = productRow.dataset.isPriority === 'true';
                const serverPriority = product.is_priority || false;
                if (currentPriority !== serverPriority) {
                    productRow.dataset.isPriority = serverPriority ? 'true' : 'false';
                    if (serverPriority) {
                        productRow.classList.add('priority-product');
                    } else {
                        productRow.classList.remove('priority-product');
                    }
                }
            }
        });

        // Update order-level priority classes
        const allProductsPriority = orderData.products.length > 0 && orderData.products.every(p => p.is_priority);
        const anyProductPriority = orderData.products.some(p => p.is_priority);

        card.dataset.allPriority = allProductsPriority ? 'true' : 'false';
        card.dataset.anyPriority = anyProductPriority ? 'true' : 'false';

        if (allProductsPriority) {
            card.classList.add('priority-order');
        } else {
            card.classList.remove('priority-order');
        }

        updateOrderCounter(card);
        updateCompleteButtonState(card);
    }

    function checkAndShowEmptyState() {
        const ordersList = document.getElementById('orders-list');
        if (!ordersList) return;

        const remainingCards = ordersList.querySelectorAll('.order-card:not(.removing)');
        if (remainingCards.length === 0) {
            const emptyState = ordersList.querySelector('.empty-state');
            if (!emptyState) {
                ordersList.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">✅</div>
                        <h2>Brak zamówień do składania</h2>
                        <p>Świetna robota! Wszystkie zamówienia zostały złożone.</p>
                    </div>
                `;
            }
        }
    }

    function addOrderCard(orderData) {
        const ordersList = document.getElementById('orders-list');

        if (!ordersList) {
            return;
        }

        // Remove empty state if present
        const emptyState = ordersList.querySelector('.empty-state');
        if (emptyState) {
            emptyState.remove();
        }

        // Create card HTML
        const cardHTML = createOrderCardHTML(orderData);

        // Insert at the beginning (highest priority)
        ordersList.insertAdjacentHTML('afterbegin', cardHTML);

        // Initialize the new card
        const newCard = ordersList.querySelector(`[data-order-number="${orderData.order_number}"]`);
        if (newCard) {
            initializeOrderCard(newCard);

            // Re-initialize attachment handlers for the new card
            if (typeof window.reinitializeAttachmentHandlers === 'function') {
                window.reinitializeAttachmentHandlers();
            }

            // Re-initialize expand icons for the new card
            if (typeof window.initExpandIcons === 'function') {
                window.initExpandIcons();
            }
        }
    }

    function createOrderCardHTML(order) {
        const productsHTML = order.products.map(product => {
            const quantity = product.quantity || 1;
            const quantityDone = product.quantity_done || 0;
            const hasLargeQty = quantity >= 10;

            // Małe badges z parametrami
            const paramsHTML = `
                ${product.wood_species ? `<span class="badge badge-species">${product.wood_species}</span>` : ''}
                ${product.technology ? `<span class="badge badge-technology">${product.technology}</span>` : ''}
                ${product.wood_class ? `<span class="badge badge-class">${product.wood_class}</span>` : ''}
            `;

            // Dimensions row - badge format matching HTML template
            let dimensionsBadge = '';
            if (product.dimensions) {
                const formattedDimensions = product.dimensions.replace(/x/g, ' x ').replace(/×/g, ' × ');
                dimensionsBadge = `<span class="badge badge-dimensions">${formattedDimensions}</span>`;
            } else if (product.original_name) {
                dimensionsBadge = `<span class="badge badge-dimensions">${product.original_name}</span>`;
            } else if (product.attachment_file_url) {
                dimensionsBadge = `<span class="badge badge-dimensions">Zgodnie z załącznikiem</span>`;
            }

            // Quantity buttons
            const minusDisabled = quantityDone <= 0 ? 'disabled' : '';
            const plusDisabled = quantityDone >= quantity ? 'disabled' : '';
            const minus10Disabled = quantityDone < 10 ? 'disabled' : '';
            const plus10Disabled = (quantity - quantityDone) < 10 ? 'disabled' : '';

            // Grid layout class for >=10 items
            const gridClass = hasLargeQty ? ' grid-layout' : '';

            const quantityButtonsHTML = hasLargeQty ? `
                <button class="btn-qty btn-minus" data-product-id="${product.id}" data-action="decrement" ${minusDisabled}>−</button>
                <button class="btn-qty btn-minus-10" data-product-id="${product.id}" data-action="decrement10" ${minus10Disabled}>−10</button>
                <button class="btn-qty btn-plus-10" data-product-id="${product.id}" data-action="increment10" ${plus10Disabled}>+10</button>
                <button class="btn-qty btn-plus" data-product-id="${product.id}" data-action="increment" ${plusDisabled}>+</button>
            ` : `
                <button class="btn-qty btn-minus" data-product-id="${product.id}" data-action="decrement" ${minusDisabled}>−</button>
                <button class="btn-qty btn-plus" data-product-id="${product.id}" data-action="increment" ${plusDisabled}>+</button>
            `;

            const completeClass = quantityDone === quantity ? 'product-complete' : '';
            const priorityClass = product.is_priority ? ' priority-product' : '';

            return `
                <div class="product-row ${completeClass}${priorityClass}"
                     data-product-id="${product.id}"
                     data-quantity="${quantity}"
                     data-quantity-done="${quantityDone}"
                     data-status="${product.current_status}"
                     data-species="${product.wood_species || ''}"
                     data-technology="${product.technology || ''}"
                     data-wood-class="${product.wood_class || ''}"
                     data-is-priority="${product.is_priority ? 'true' : 'false'}">
                    <div class="product-left-col">
                        <div class="product-params">${paramsHTML}</div>
                        <div class="product-dimensions-row">${dimensionsBadge}</div>
                    </div>
                    <div class="quantity-controls">
                        <div class="quantity-counter">
                            <span class="qty-done">${quantityDone}</span>
                            <span class="qty-separator">/</span>
                            <span class="qty-total">${quantity}</span>
                        </div>
                        <div class="quantity-buttons${gridClass}">
                            ${quantityButtonsHTML}
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        // Build header icons HTML
        const firstProduct = order.products[0];
        let iconsHTML = '';

        if (firstProduct) {
            if (firstProduct.attachment_file_url) {
                const attachmentType = firstProduct.attachment_file_name && firstProduct.attachment_file_name.toLowerCase().endsWith('.pdf') ? 'pdf' : 'image';
                iconsHTML += `
                    <div class="header-icon-wrapper attachment-icon-wrapper"
                         data-attachment-url="${firstProduct.attachment_file_url}"
                         data-attachment-name="${firstProduct.attachment_file_name || ''}"
                         data-attachment-type="${attachmentType}">
                        <svg class="header-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
                        </svg>
                    </div>
                `;
            }
            if (firstProduct.order_notes) {
                const truncatedNotes = firstProduct.order_notes.length > 100
                    ? firstProduct.order_notes.substring(0, 100) + '...'
                    : firstProduct.order_notes;
                iconsHTML += `
                    <div class="header-icon-wrapper notes-icon-wrapper"
                         data-notes="${firstProduct.order_notes.replace(/"/g, '&quot;')}"
                         title="${truncatedNotes.replace(/"/g, '&quot;')}">
                        <svg class="header-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                        </svg>
                    </div>
                `;
            }
        }

        // Ikona powiększenia (zawsze)
        iconsHTML += `
            <div class="header-icon-wrapper expand-icon-wrapper" title="Powiększ zamówienie">
                <svg class="header-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="15 3 21 3 21 9"></polyline>
                    <polyline points="9 21 3 21 3 15"></polyline>
                    <line x1="21" y1="3" x2="14" y2="10"></line>
                    <line x1="3" y1="21" x2="10" y2="14"></line>
                </svg>
            </div>
        `;

        const clientOrderBadge = order.client_order_number ? `<span class="order-client-number">${order.client_order_number}</span>` : '';
        const blBadge = order.baselinker_order_id ? `<span class="order-baselinker">BL-${order.baselinker_order_id}</span>` : '';

        // Calculate total done
        let totalDone = 0;
        let totalQty = 0;
        order.products.forEach(p => {
            totalDone += (p.quantity_done || 0);
            totalQty += (p.quantity || 1);
        });

        // Calculate priority flags for order card
        const allProductsPriority = order.products.length > 0 && order.products.every(p => p.is_priority);
        const anyProductPriority = order.products.some(p => p.is_priority);
        const orderPriorityClass = allProductsPriority ? ' priority-order' : '';

        return `
            <div class="order-card${orderPriorityClass}"
                 data-order-number="${order.order_number}"
                 data-priority-rank="${order.best_priority_rank}"
                 data-total-products="${order.total_products}"
                 data-total-quantity="${totalQty}"
                 data-total-volume="${order.total_volume}"
                 data-in-progress="false"
                 data-all-priority="${allProductsPriority ? 'true' : 'false'}"
                 data-any-priority="${anyProductPriority ? 'true' : 'false'}">
                <div class="order-header">
                    <div class="order-header-row order-ids-row">
                        <span class="order-number">${order.order_number}</span>
                        ${clientOrderBadge}
                        ${blBadge}
                    </div>
                    <div class="order-header-row order-stats-row">
                        <div class="order-stats">
                            <span class="products-checked" data-order="${order.order_number}">${totalDone}</span>/<span class="products-total" data-order="${order.order_number}">${totalQty}</span> szt. • ${order.total_volume.toFixed(4)} m³
                        </div>
                        <div class="order-icons">${iconsHTML}</div>
                    </div>
                </div>
                <div class="products-list">
                    ${productsHTML}
                </div>
                <div class="order-action">
                    <button class="btn-complete" data-action="complete" disabled>ZAKOŃCZ SKŁADANIE</button>
                </div>
            </div>
        `;
    }

    // ========================================================================
    // FETCH TODAY'S M³
    // ========================================================================

    async function fetchTodayM3() {
        try {
            const response = await fetch('/production/stations/ajax/station-today-m3/assembly');

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const result = await response.json();

            if (result.success && result.data) {
                const todayM3Element = document.getElementById('today-m3');
                if (todayM3Element) {
                    todayM3Element.textContent = result.data.today_m3.toFixed(4);
                }

                console.log(`[Assembly] Today's m³: ${result.data.today_m3}`);
            }

        } catch (error) {
            console.error('[Assembly] Failed to fetch today m³:', error);
        }
    }

    // ========================================================================
    // THEME TOGGLE
    // ========================================================================

    function setupThemeToggle() {
        const themeToggle = document.getElementById('theme-toggle');

        if (!themeToggle) {
            return;
        }

        themeToggle.addEventListener('click', function() {
            document.body.classList.toggle('light-mode');
            const isLight = document.body.classList.contains('light-mode');

            const sunIcon = themeToggle.querySelector('.sun-icon');
            const moonIcon = themeToggle.querySelector('.moon-icon');
            const themeText = themeToggle.querySelector('.theme-text');

            if (isLight) {
                sunIcon.style.display = 'none';
                moonIcon.style.display = 'block';
                themeText.textContent = 'Tryb ciemny';
            } else {
                sunIcon.style.display = 'block';
                moonIcon.style.display = 'none';
                themeText.textContent = 'Tryb jasny';
            }

            localStorage.setItem('theme', isLight ? 'light' : 'dark');
        });

        // Load saved theme
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme === 'light') {
            themeToggle.click();
        }
    }

    // ========================================================================
    // CLEANUP
    // ========================================================================

    window.addEventListener('beforeunload', function() {
        if (state.refreshTimer) {
            clearInterval(state.refreshTimer);
            console.log('[Assembly] Cleared auto-refresh interval');
        }

        if (state.countdownTimer) {
            clearInterval(state.countdownTimer);
            console.log('[Assembly] Cleared countdown timer');
        }

        // Clear all active order countdowns
        state.activeCountdowns.forEach((countdown, orderNumber) => {
            if (countdown.timerId) {
                clearInterval(countdown.timerId);
                console.log(`[Assembly] Cleared countdown for ${orderNumber}`);
            }
        });

        // Clear pending requests
        state.pendingRequests.forEach((timeoutId) => {
            clearTimeout(timeoutId);
        });
    });

    console.log('[Assembly] Module loaded v3.0 (quantity-based with +/- buttons)');

})();
