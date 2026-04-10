/**
 * ============================================================================
 * STATION PACKAGING - QUANTITY-BASED VERSION
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
        console.log('[Packaging] Initializing QUANTITY-BASED station v3.0...');
        initializePackagingStation();
    });

    function initializePackagingStation() {
        const config = window.STATION_CONFIG;

        if (!config || config.stationCode !== 'packaging') {
            console.error('[Packaging] Invalid station config');
            return;
        }

        state.config = config;
        console.log('[Packaging] Station config loaded:', config);

        // Attach event listeners to existing order cards
        const existingCards = document.querySelectorAll('.order-card');
        console.log(`[Packaging] Found ${existingCards.length} order cards`);

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

        // Initialize connection monitor
        if (window.StationCommon && window.StationCommon.initConnectionMonitor) {
            window.StationCommon.initConnectionMonitor();
            console.log('[Packaging] Connection monitor initialized');

            // Register listener for connection changes
            if (window.StationCommon.onConnectionChange) {
                window.StationCommon.onConnectionChange(handleConnectionChange);
                console.log('[Packaging] Connection change listener registered');
            }
        }

        // Initialize expand icons for fullscreen mode
        if (typeof window.initExpandIcons === 'function') {
            window.initExpandIcons();
            console.log('[Packaging] Expand icons initialized');
        }

        // Initialize order search button
        if (typeof window.initOrderSearchButton === 'function') {
            window.initOrderSearchButton();
            console.log('[Packaging] Order search button initialized');
        }

        console.log('[Packaging] Station initialized successfully');
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

        console.log(`[Packaging] Refresh countdown started: ${intervalSeconds}s`);
    }

    // ========================================================================
    // ORDER CARD INITIALIZATION
    // ========================================================================

    function initializeOrderCard(card) {
        const orderNumber = card.dataset.orderNumber;

        if (!orderNumber) {
            console.warn('[Packaging] Order card missing order number');
            return;
        }

        console.log(`[Packaging] Initializing order card: ${orderNumber}`);

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

        // Initialize delivery icon click handler (2025-12)
        initDeliveryIconHandler(card);
    }

    // ========================================================================
    // DELIVERY MODAL HANDLING (2025-12)
    // ========================================================================

    function initDeliveryIconHandler(card) {
        const deliveryIcon = card.querySelector('.delivery-icon-wrapper');
        if (!deliveryIcon) return;

        deliveryIcon.addEventListener('click', function(e) {
            e.stopPropagation();
            openDeliveryModal(this);
        });
    }

    function openDeliveryModal(iconElement) {
        const modal = document.getElementById('deliveryModal');
        if (!modal) return;

        // Get delivery data from data attributes
        const fullname = iconElement.dataset.deliveryFullname || '';
        const company = iconElement.dataset.deliveryCompany || '';
        const address = iconElement.dataset.deliveryAddress || '';
        const postcode = iconElement.dataset.deliveryPostcode || '';
        const city = iconElement.dataset.deliveryCity || '';
        const country = iconElement.dataset.deliveryCountry || 'PL';

        // Map country codes to names
        const countryNames = {
            'PL': 'Polska',
            'DE': 'Niemcy',
            'CZ': 'Czechy',
            'SK': 'Słowacja',
            'AT': 'Austria',
            'NL': 'Holandia',
            'BE': 'Belgia',
            'FR': 'Francja',
            'GB': 'Wielka Brytania',
            'IT': 'Włochy',
            'ES': 'Hiszpania'
        };
        const countryName = countryNames[country] || country;

        // Populate modal fields
        document.getElementById('delivery-fullname').textContent = fullname;
        document.getElementById('delivery-company').textContent = company;
        document.getElementById('delivery-address').textContent = address;
        document.getElementById('delivery-postcode').textContent = postcode;
        document.getElementById('delivery-city').textContent = city;
        document.getElementById('delivery-country').textContent = countryName;

        // Hide empty rows
        document.getElementById('delivery-fullname-row').style.display = fullname ? 'flex' : 'none';
        document.getElementById('delivery-company-row').style.display = company ? 'flex' : 'none';
        document.getElementById('delivery-address-row').style.display = address ? 'flex' : 'none';
        document.getElementById('delivery-postcode-row').style.display = postcode ? 'flex' : 'none';
        document.getElementById('delivery-city-row').style.display = city ? 'flex' : 'none';
        document.getElementById('delivery-country-row').style.display = country ? 'flex' : 'none';

        // Show modal
        modal.classList.add('active');

        console.log('[Packaging] Delivery modal opened');

        // === INICJALIZACJA SEKCJI WYSYŁKI ===
        // Znajdź kartę zamówienia (parent)
        const orderCard = iconElement.closest('.order-card');
        if (orderCard && typeof initShippingSection === 'function') {
            const orderId = orderCard.dataset.baselinkerId || orderCard.dataset.orderNumber;

            // Pobierz produkty z karty zamówienia
            const productRows = orderCard.querySelectorAll('.product-row');
            const products = [];

            productRows.forEach(row => {
                products.push({
                    parsed_length_cm: parseFloat(row.dataset.length) || 0,
                    parsed_width_cm: parseFloat(row.dataset.width) || 0,
                    parsed_thickness_cm: parseFloat(row.dataset.thickness) || 0,
                    volume_m3: parseFloat(row.dataset.volume) || 0,
                    quantity: parseInt(row.dataset.quantity) || 1
                });
            });

            // Dane zamówienia do przekazania
            const orderData = {
                order_id: orderId,
                products: products,
                is_personal_pickup: false, // Jeśli modal dostawy jest otwarty, to nie jest odbiór osobisty
                delivery_postcode: postcode,
                // Dane wysyłki (jeśli już zgłoszona)
                shipping_package_id: iconElement.dataset.shippingPackageId || '',
                shipping_tracking_number: iconElement.dataset.shippingTracking || '',
                shipping_courier_name: iconElement.dataset.shippingCourier || '',
                shipping_price: iconElement.dataset.shippingPrice || '',
                shipping_created_at: iconElement.dataset.shippingDate || '',
                shipping_label_base64: iconElement.dataset.shippingLabel || ''
            };

            console.log('[Packaging] Inicjalizacja sekcji wysyłki dla zamówienia:', orderId);
            initShippingSection(orderData);
        }
    }

    // Global function for close button
    window.closeDeliveryModal = function() {
        const modal = document.getElementById('deliveryModal');
        if (modal) {
            modal.classList.remove('active');
        }
    };

    // Close modal on overlay click and Escape key
    document.addEventListener('DOMContentLoaded', function() {
        const modal = document.getElementById('deliveryModal');
        if (modal) {
            modal.addEventListener('click', function(e) {
                if (e.target === this) {
                    closeDeliveryModal();
                }
            });
        }

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                closeDeliveryModal();
            }
        });
    });

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
            console.warn('[Packaging] Invalid button data');
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
                        station: 'packaging',
                        action: action
                    })
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || `HTTP ${response.status}`);
                }

                const result = await response.json();
                console.log(`[Packaging] Product ${productId} quantity updated:`, result);

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
                console.error('[Packaging] Failed to update quantity:', error);

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
        // Liczymy tylko aktywne produkty (nie-disabled)
        const productRows = card.querySelectorAll('.product-row:not(.product-disabled)');

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

        console.log(`[Packaging] Updated counter for ${orderNumber}: ${totalDone}/${totalQuantity}`);
    }

    // ========================================================================
    // CONNECTION STATUS HANDLING
    // ========================================================================

    function handleConnectionChange(isOnline) {
        console.log(`[Packaging] Connection status changed: ${isOnline ? 'ONLINE' : 'OFFLINE'}`);

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
        completeBtn.textContent = 'ZAKOŃCZ PAKOWANIE';

        // Sprawdzamy WSZYSTKIE produkty zamówienia
        const activeProductRows = card.querySelectorAll('.product-row:not(.product-disabled)');
        const disabledProductRows = card.querySelectorAll('.product-row.product-disabled');
        let allComplete = true;
        let hasProducts = false;
        // Zamówienie niekompletne jeśli ma produkty na wcześniejszych stanowiskach
        let hasDisabledProducts = disabledProductRows.length > 0;

        activeProductRows.forEach(row => {
            hasProducts = true;
            const qtyDone = parseInt(row.dataset.quantityDone) || 0;
            const qtyTotal = parseInt(row.dataset.quantity) || 0;
            if (qtyDone < qtyTotal) {
                allComplete = false;
            }
        });

        // Przycisk aktywny tylko gdy WSZYSTKIE aktywne produkty ukończone i brak wyszarzonych
        if (allComplete && hasProducts && !hasDisabledProducts) {
            completeBtn.disabled = false;
        } else {
            completeBtn.disabled = true;
        }
    }

    // ========================================================================
    // COUNTDOWN 10 SEKUND PRZED ZAKOŃCZENIEM
    // ========================================================================

    function handleCompleteClick(card, orderNumber) {
        console.log(`[Packaging] Complete button clicked for order: ${orderNumber}`);

        // Check online status first
        if (!window.StationCommon.isOnline()) {
            console.warn('[Packaging] Offline - cannot complete orders');
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
            console.warn('[Packaging] No products found');
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
        console.log(`[Packaging] Starting 10-second countdown for ${orderNumber}`);

        const actionContainer = card.querySelector('.order-action');
        if (!actionContainer) {
            console.error('[Packaging] No action container found');
            return;
        }

        // Replace button with countdown UI
        actionContainer.innerHTML = `
            <div class="action-countdown">
                <button class="btn-complete processing">
                    <span class="spinner"></span>
                    <span class="countdown-text">Zapisuje... 5s</span>
                </button>
                <button class="btn-cancel">ANULUJ</button>
            </div>
        `;

        const processingBtn = actionContainer.querySelector('.btn-complete');
        const cancelBtn = actionContainer.querySelector('.btn-cancel');
        const countdownText = processingBtn.querySelector('.countdown-text');

        let secondsLeft = 5;

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

        console.log(`[Packaging] Countdown started for ${orderNumber}`);
    }

    function cancelCountdown(card, orderNumber, timerId) {
        console.log(`[Packaging] Countdown cancelled for ${orderNumber}`);

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
            actionContainer.innerHTML = '<button class="btn-complete" data-action="complete" disabled>ZAKOŃCZ PAKOWANIE</button>';

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

        showToast('info', 'Anulowano pakowanie zamówienia');
    }

    // ========================================================================
    // BULK COMPLETION - Optimistic UI
    // ========================================================================

    async function completeOrder(card, orderNumber, productIds) {
        console.log(`[Packaging] Starting bulk completion for ${orderNumber}`, productIds);

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
                    station: 'packaging',
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

            console.log('[Packaging] Order completed successfully:', result);

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
            console.error('[Packaging] Failed to complete order:', error);

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

        console.log(`[Packaging] Remaining cards: ${remainingCards}`);
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

        console.log(`[Packaging] Updated header stats: ${totalProducts} products, ${totalVolume.toFixed(4)} m³`);
    }

    function showEmptyState() {
        const ordersList = document.getElementById('orders-list');

        if (!ordersList) {
            return;
        }

        ordersList.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">✅</div>
                <h2>Brak zamówień do pakowania</h2>
                <p>Świetna robota! Wszystkie zamówienia zostały spakowane.</p>
            </div>
        `;

        console.log('[Packaging] Showing empty state');
    }

    // ========================================================================
    // TOAST NOTIFICATIONS
    // ========================================================================

    function showToast(type, message) {
        const prefix = type === 'success' ? '✅' : type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️';
        console.log(`[Packaging] ${prefix} ${message}`);

        // TODO: Implement visual toast notifications if needed
    }

    // ========================================================================
    // AUTO-REFRESH WITH SMART MERGE
    // ========================================================================

    function startAutoRefresh(intervalSeconds) {
        if (state.refreshTimer) {
            clearInterval(state.refreshTimer);
        }

        console.log(`[Packaging] Starting auto-refresh every ${intervalSeconds}s`);

        state.refreshTimer = setInterval(async () => {
            await performAutoRefresh();
        }, intervalSeconds * 1000);
    }

    async function performAutoRefresh() {
        console.log('[Packaging] Performing auto-refresh...');

        try {
            const response = await fetch('/production/stations/ajax/orders/packaging?sort=priority');

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const result = await response.json();

            if (!result.success || !result.data || !result.data.orders) {
                throw new Error('Invalid response format');
            }

            console.log(`[Packaging] Fetched ${result.data.orders.length} orders`);

            smartMergeOrders(result.data.orders);

            // Update header statistics from API data (more reliable than DOM)
            updateHeaderStatsFromAPI(result.data.orders);

            // Update today's m³ statistics
            fetchTodayM3();

        } catch (error) {
            console.error('[Packaging] Auto-refresh failed:', error);
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

        console.log(`[Packaging] Updated header stats from API: ${totalOrders} orders, ${totalVolume.toFixed(4)} m³`);
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
                console.log(`[Packaging] Adding new order: ${order.order_number}`);
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
                    console.log(`[Packaging] Removing order no longer on station: ${orderNumber}`);
                    card.classList.add('removing');
                    setTimeout(() => {
                        card.remove();
                        // Jeśli nie ma już żadnych kart, pokaż empty state
                        checkAndShowEmptyState();
                    }, 300);
                } else {
                    console.log(`[Packaging] Keeping order ${orderNumber} - user is working on it`);
                }
            }
        });

        console.log('[Packaging] Smart merge completed');
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

                // Aktualizacja statusu — wlaczenie/wylaczenie wyszarzenia
                const currentStatus = productRow.dataset.status;
                const serverStatus = product.current_status;
                if (currentStatus !== serverStatus) {
                    productRow.dataset.status = serverStatus;
                    const isDisabled = serverStatus !== 'czeka_na_pakowanie';
                    productRow.dataset.disabled = isDisabled ? 'true' : 'false';

                    if (isDisabled) {
                        productRow.classList.add('product-disabled');
                        if (!productRow.querySelector('.badge-station')) {
                            const paramsDiv = productRow.querySelector('.product-params');
                            if (paramsDiv) {
                                paramsDiv.insertAdjacentHTML('afterbegin', getStationBadgeHTML(serverStatus));
                            }
                        }
                    } else {
                        productRow.classList.remove('product-disabled');
                        const stationBadge = productRow.querySelector('.badge-station');
                        if (stationBadge) stationBadge.remove();
                    }
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
                        <h2>Brak zamówień do pakowania</h2>
                        <p>Świetna robota! Wszystkie zamówienia zostały spakowane.</p>
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

    // Helper: badge HTML informujący, na której stacji aktualnie jest produkt
    function getStationBadgeHTML(status) {
        const stationMap = {
            'czeka_na_wyciecie':     { code: 'cutting',    label: 'WYCIN' },
            'czeka_na_skladanie':    { code: 'assembly',   label: 'SKŁAD' },
            'czeka_na_sklejanie':    { code: 'gluing',     label: 'SKLEJ' },
            'czeka_na_formatowanie': { code: 'formatting', label: 'FORMA' },
            'czeka_na_wykanczanie':  { code: 'finishing',  label: 'WYKAŃ' },
            'czeka_na_logistyke':    { code: 'logistics',  label: 'LOGIS' },
        };
        const station = stationMap[status];
        if (!station) return '';
        const icons = {
            cutting:    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/></svg>',
            assembly:   '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/></svg>',
            gluing:     '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2C12 2 5 10 5 15a7 7 0 0 0 14 0C19 10 12 2 12 2z"/></svg>',
            formatting: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21L21 3"/><path d="M6 3h15v3H9z" fill="none"/><path d="M9 3v3"/><path d="M12 3v3"/><path d="M15 3v3"/><path d="M18 3v3"/></svg>',
            finishing:  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18.37 2.63L14 7l-1.59-1.59a2 2 0 00-2.82 0L8 7l9 9 1.59-1.59a2 2 0 000-2.82L17 10l4.37-4.37a2.12 2.12 0 10-3-3z"/><path d="M9 8C5.49 12 1 21 1 21s9-4.49 13-8"/></svg>',
            logistics:  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg>',
        };
        const icon = icons[station.code] || '';
        return `<span class="badge badge-station badge-station-${station.code}">${icon} ${station.label}</span>`;
    }

    function createOrderCardHTML(order) {
        // Sortowanie: aktywne (czeka_na_pakowanie) najpierw, potem nieaktywne, w ramach grup po ID
        const sortedProducts = [...order.products].sort((a, b) => {
            const aActive = a.current_status === 'czeka_na_pakowanie' ? 0 : 1;
            const bActive = b.current_status === 'czeka_na_pakowanie' ? 0 : 1;
            if (aActive !== bActive) return aActive - bActive;
            return (a.id || '').localeCompare(b.id || '');
        });
        const productsHTML = sortedProducts.map(product => {
            const quantity = product.quantity || 1;
            const quantityDone = product.quantity_done || 0;
            const hasLargeQty = quantity >= 10;
            const isNotReady = product.current_status !== 'czeka_na_pakowanie';

            // Produkt disabled = nie jest na tej stacji (wyszarzenie)
            const isDisabled = product.current_status !== 'czeka_na_pakowanie';
            const disabledClass = isDisabled ? ' product-disabled' : '';
            const stationBadgeHTML = isDisabled ? getStationBadgeHTML(product.current_status) : '';

            // Małe badges z parametrami
            const paramsHTML = `
                ${product.wood_species ? `<span class="badge badge-species">${product.wood_species}</span>` : ''}
                ${product.technology ? `<span class="badge badge-technology">${product.technology}</span>` : ''}
                ${product.wood_class ? `<span class="badge badge-class">${product.wood_class}</span>` : ''}
                ${product.finish_state ? `<span class="badge badge-finish">${product.finish_state}</span>` : ''}
            `;

            // Dimensions row - badge format matching HTML template
            let dimensionsBadge = '';
            if (product.dimensions) {
                dimensionsBadge = `<span class="badge badge-dimensions">${product.dimensions}</span>`;
            } else if (product.original_name) {
                dimensionsBadge = `<span class="badge badge-dimensions">${product.original_name}</span>`;
            }

            // Quantity buttons - disabled if not ready for packaging
            const notReadyDisabled = isNotReady ? 'disabled' : '';
            const minusDisabled = (quantityDone <= 0 || isNotReady) ? 'disabled' : '';
            const plusDisabled = (quantityDone >= quantity || isNotReady) ? 'disabled' : '';
            const minus10Disabled = (quantityDone < 10 || isNotReady) ? 'disabled' : '';
            const plus10Disabled = ((quantity - quantityDone) < 10 || isNotReady) ? 'disabled' : '';

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
            const notReadyClass = isNotReady ? 'product-not-ready' : '';
            const priorityClass = product.is_priority ? ' priority-product' : '';

            return `
                <div class="product-row ${completeClass} ${notReadyClass}${disabledClass}${priorityClass}"
                     data-product-id="${product.id}"
                     data-quantity="${quantity}"
                     data-quantity-done="${quantityDone}"
                     data-status="${product.current_status}"
                     data-disabled="${isDisabled}"
                     data-species="${product.wood_species || ''}"
                     data-technology="${product.technology || ''}"
                     data-wood-class="${product.wood_class || ''}"
                     data-is-priority="${product.is_priority ? 'true' : 'false'}"
                     data-length="${product.parsed_length_cm || 0}"
                     data-width="${product.parsed_width_cm || 0}"
                     data-thickness="${product.parsed_thickness_cm || 0}"
                     data-volume="${product.volume_m3 || 0}">
                    <div class="product-left-col">
                        <div class="product-params">${stationBadgeHTML}${paramsHTML}</div>
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

        // Build delivery badge HTML (2025-12)
        const isPersonalPickup = order.is_personal_pickup || false;
        let deliveryBadgeHTML = '';

        if (isPersonalPickup) {
            deliveryBadgeHTML = `
                <div class="delivery-badge-container">
                    <span class="delivery-badge delivery-pickup" title="Odbiór osobisty">
                        <svg class="delivery-badge-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                            <circle cx="12" cy="7" r="4"></circle>
                        </svg>
                        Odbiór osobisty
                    </span>
                </div>
            `;
        } else {
            deliveryBadgeHTML = `
                <div class="delivery-badge-container">
                    <span class="delivery-badge delivery-courier" title="Kurier">
                        <svg class="delivery-badge-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="1" y="3" width="15" height="13"></rect>
                            <polygon points="16 8 20 8 23 11 23 16 16 16 16 8"></polygon>
                            <circle cx="5.5" cy="18.5" r="2.5"></circle>
                            <circle cx="18.5" cy="18.5" r="2.5"></circle>
                        </svg>
                        Kurier
                    </span>
                </div>
            `;
        }

        // Build header icons HTML
        const firstProduct = order.products[0];
        let iconsHTML = '';

        // Delivery icon (only for courier) (2025-12)
        if (!isPersonalPickup) {
            iconsHTML += `
                <div class="header-icon-wrapper delivery-icon-wrapper"
                     data-delivery-fullname="${(order.delivery_fullname || '').replace(/"/g, '&quot;')}"
                     data-delivery-company="${(order.delivery_company || '').replace(/"/g, '&quot;')}"
                     data-delivery-address="${(order.delivery_address || '').replace(/"/g, '&quot;')}"
                     data-delivery-postcode="${(order.delivery_postcode || '').replace(/"/g, '&quot;')}"
                     data-delivery-city="${(order.delivery_city || '').replace(/"/g, '&quot;')}"
                     data-delivery-country="${(order.delivery_country_code || 'PL').replace(/"/g, '&quot;')}"
                     title="Pokaż adres dostawy">
                    <svg class="header-icon" width="18" height="18"><use href="${window.STATION_CONFIG.iconsUrl}#icon-delivery"/></svg>
                </div>
            `;
        }

        if (firstProduct) {
            if (firstProduct.attachment_file_url) {
                const attachmentType = firstProduct.attachment_file_name && firstProduct.attachment_file_name.toLowerCase().endsWith('.pdf') ? 'pdf' : 'image';
                iconsHTML += `
                    <div class="header-icon-wrapper attachment-icon-wrapper"
                         data-attachment-url="${firstProduct.attachment_file_url}"
                         data-attachment-name="${firstProduct.attachment_file_name || ''}"
                         data-attachment-type="${attachmentType}">
                        <svg class="header-icon" width="18" height="18"><use href="${window.STATION_CONFIG.iconsUrl}#icon-attachment"/></svg>
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
                        <svg class="header-icon" width="18" height="18"><use href="${window.STATION_CONFIG.iconsUrl}#icon-notes"/></svg>
                    </div>
                `;
            }
        }

        // Ikona powiększenia (zawsze)
        iconsHTML += `
            <div class="header-icon-wrapper expand-icon-wrapper" title="Powiększ zamówienie">
                <svg class="header-icon" width="18" height="18"><use href="${window.STATION_CONFIG.iconsUrl}#icon-expand"/></svg>
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
                        <div class="order-ids">
                            <span class="order-number">${order.order_number}</span>
                            ${clientOrderBadge}
                            ${blBadge}
                        </div>
                        ${deliveryBadgeHTML}
                        <div class="order-icons">${iconsHTML}</div>
                    </div>
                </div>
                <div class="products-list">
                    ${productsHTML}
                </div>
                <div class="order-action">
                    <button class="btn-complete" data-action="complete" disabled>ZAKOŃCZ PAKOWANIE</button>
                </div>
            </div>
        `;
    }

    // ========================================================================
    // FETCH TODAY'S M³
    // ========================================================================

    async function fetchTodayM3() {
        try {
            const response = await fetch('/production/stations/ajax/station-today-m3/packaging');

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const result = await response.json();

            if (result.success && result.data) {
                const todayM3Element = document.getElementById('today-m3');
                if (todayM3Element) {
                    todayM3Element.textContent = result.data.today_m3.toFixed(4);
                }

                console.log(`[Packaging] Today's m³: ${result.data.today_m3}`);
            }

        } catch (error) {
            console.error('[Packaging] Failed to fetch today m³:', error);
        }
    }

    // ========================================================================
    // SHIPPING MODULE (2025-12)
    // ========================================================================

    const ShippingModule = {
        currentOrderId: null,
        currentOrderData: null,
        currentLabel: null,
        lastDimensions: null,

        // Nazwy kroków dla wyświetlania
        STEP_NAMES: {
            'dimensions': 'Obliczanie wymiarów paczki',
            'variants': 'Generowanie wariantów pakowania',
            'prices': 'Sprawdzanie cen kurierów',
            'compare': 'Porównywanie ofert',
            'create': 'Zgłaszanie paczki do kuriera',
            'label': 'Pobieranie etykiety'
        },

        // Kolejność kroków
        STEPS: ['dimensions', 'variants', 'prices', 'compare', 'create', 'label'],

        // Limity kuriera
        LIMITS: {
            maxWeight: 31.5,
            maxDimension: 200
        }
    };

    /**
     * Inicjalizuje sekcję wysyłki w modalu dostawy (tylko przycisk)
     */
    function initShippingSection(orderData) {
        const orderId = orderData.order_id || orderData.baselinker_order_id || orderData.order_number;
        console.log('[Shipping] Inicjalizacja sekcji wysyłki dla zamówienia:', orderId);

        ShippingModule.currentOrderId = orderId;
        ShippingModule.currentOrderData = orderData;

        const shippingSection = document.getElementById('shippingSection');
        const shippingInfoSection = document.getElementById('shippingInfoSection');
        const overlimitMessage = document.getElementById('overlimitMessage');

        if (!shippingSection || !overlimitMessage) {
            console.warn('[Shipping] Nie znaleziono elementów sekcji wysyłki');
            return;
        }

        // Sprawdź czy to kurier (nie odbiór osobisty)
        if (orderData.is_personal_pickup) {
            console.log('[Shipping] Odbiór osobisty - ukrywam sekcję wysyłki');
            shippingSection.style.display = 'none';
            if (shippingInfoSection) shippingInfoSection.style.display = 'none';
            overlimitMessage.style.display = 'none';
            return;
        }

        // === SPRAWDŹ CZY PRZESYŁKA JUŻ ZOSTAŁA ZGŁOSZONA ===
        if (orderData.shipping_package_id && orderData.shipping_package_id !== '') {
            console.log('[Shipping] Przesyłka już zgłoszona - pokazuję dane wysyłki');

            // Ukryj przycisk zgłoszenia i komunikat limitu
            shippingSection.style.display = 'none';
            overlimitMessage.style.display = 'none';

            // Wypełnij dane zgłoszonej przesyłki
            if (shippingInfoSection) {
                document.getElementById('shippingInfoCourier').textContent = orderData.shipping_courier_name || '-';
                document.getElementById('shippingInfoTracking').textContent = orderData.shipping_tracking_number || '-';
                document.getElementById('shippingInfoPrice').textContent = orderData.shipping_price ? orderData.shipping_price + ' zł' : '-';

                // Formatuj datę
                let dateText = '-';
                if (orderData.shipping_created_at) {
                    try {
                        const date = new Date(orderData.shipping_created_at);
                        dateText = date.toLocaleString('pl-PL', {
                            day: '2-digit',
                            month: '2-digit',
                            year: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit'
                        });
                    } catch (e) {
                        dateText = orderData.shipping_created_at;
                    }
                }
                document.getElementById('shippingInfoDate').textContent = dateText;

                // Zapisz etykietę do późniejszego pobrania
                ShippingModule.lastLabelBase64 = orderData.shipping_label_base64 || '';

                // Pokaż sekcję
                shippingInfoSection.style.display = 'block';

                // Ustaw handler dla przycisku pobierania etykiety
                const downloadBtn = document.getElementById('downloadLabelFromInfoBtn');
                if (downloadBtn) {
                    downloadBtn.onclick = function() {
                        if (ShippingModule.lastLabelBase64) {
                            downloadLabelPdf(ShippingModule.lastLabelBase64, orderId);
                        } else {
                            alert('Etykieta niedostępna');
                        }
                    };
                }
            }
            return;
        }

        // Przesyłka nie jest zgłoszona - ukryj sekcję info
        if (shippingInfoSection) shippingInfoSection.style.display = 'none';

        // Oblicz wymiary
        const dimensions = calculateOrderDimensions(orderData.products || []);
        ShippingModule.lastDimensions = dimensions;

        console.log('[Shipping] Obliczone wymiary:', dimensions);

        // Sprawdź limity
        if (dimensions.weight > ShippingModule.LIMITS.maxWeight ||
            dimensions.maxDimension > ShippingModule.LIMITS.maxDimension) {
            console.log('[Shipping] Przekroczono limity kuriera - pokazuję komunikat');
            shippingSection.style.display = 'none';
            overlimitMessage.style.display = 'flex';
            return;
        }

        // Pokaż przycisk "Zgłoś wysyłkę"
        console.log('[Shipping] Zamówienie w limitach - pokazuję przycisk');
        shippingSection.style.display = 'block';
        overlimitMessage.style.display = 'none';
    }

    /**
     * Otwiera modal z wymiarami wysyłki
     */
    function openShippingDimensionsModal() {
        console.log('[Shipping] Otwieranie modalu wymiarów');

        // Zamknij modal dostawy
        closeDeliveryModal();

        // Wypełnij wymiary w formularzu
        const dimensions = ShippingModule.lastDimensions;
        if (dimensions) {
            document.getElementById('shipLength').value = dimensions.length;
            document.getElementById('shipWidth').value = dimensions.width;
            document.getElementById('shipHeight').value = dimensions.height;
            document.getElementById('shipWeight').value = dimensions.weight.toFixed(1);
        }

        // Otwórz modal wymiarów
        const modal = document.getElementById('shippingDimensionsModal');
        if (modal) modal.classList.add('active');
    }

    /**
     * Oblicza wymiary paczki dla produktów zamówienia
     */
    function calculateOrderDimensions(products) {
        console.log('[Shipping] Obliczanie wymiarów dla produktów:', products.length);

        let maxLength = 0, maxWidth = 0, totalThickness = 0, totalVolume = 0;

        products.forEach((p, idx) => {
            const length = parseFloat(p.parsed_length_cm) || 0;
            const width = parseFloat(p.parsed_width_cm) || 0;
            const thickness = parseFloat(p.parsed_thickness_cm) || 0;
            const volume = parseFloat(p.volume_m3) || 0;
            const qty = parseInt(p.quantity) || 1;

            console.log(`[Shipping] Produkt ${idx + 1}: ${length}x${width}x${thickness}cm, vol=${volume}m³, qty=${qty}`);

            maxLength = Math.max(maxLength, length);
            maxWidth = Math.max(maxWidth, width);
            totalThickness += thickness * qty;
            totalVolume += volume * qty;
        });

        const MARGIN = 5;
        const WEIGHT_FACTOR = 800;

        const result = {
            length: Math.ceil(maxLength + MARGIN),
            width: Math.ceil(maxWidth + MARGIN),
            height: Math.ceil(totalThickness + MARGIN),
            weight: totalVolume * WEIGHT_FACTOR,
            maxDimension: Math.max(maxLength + MARGIN, maxWidth + MARGIN, totalThickness + MARGIN)
        };

        console.log('[Shipping] Wynik obliczeń:', result);
        return result;
    }

    /**
     * Otwiera modal postępu wysyłki
     */
    function openProgressModal() {
        console.log('[Shipping] Otwieram modal postępu');

        // Resetuj wszystkie kroki
        ShippingModule.STEPS.forEach(step => {
            const stepEl = document.getElementById(`step-${step}`);
            if (stepEl) {
                stepEl.classList.remove('active', 'completed', 'error');
            }
        });

        const stepDetails = document.getElementById('stepDetails');
        if (stepDetails) stepDetails.textContent = '';

        const modal = document.getElementById('shippingProgressModal');
        if (modal) modal.classList.add('active');
    }

    /**
     * Aktualizuje status kroku
     */
    function updateStep(stepId, status, details = null) {
        console.log(`[Shipping] Aktualizacja kroku: ${stepId} -> ${status}`, details || '');

        const stepEl = document.getElementById(`step-${stepId}`);
        if (!stepEl) {
            console.warn(`[Shipping] Nie znaleziono elementu kroku: step-${stepId}`);
            return;
        }

        // Usuń poprzednie klasy statusu
        stepEl.classList.remove('active', 'completed', 'error');

        // Dodaj nową klasę
        if (status === 'active' || status === 'completed' || status === 'error') {
            stepEl.classList.add(status);
        }

        // Aktualizuj szczegóły
        if (details) {
            const stepDetails = document.getElementById('stepDetails');
            if (stepDetails) stepDetails.textContent = details;
        }
    }

    /**
     * Pokazuje modal sukcesu
     */
    function showSuccessModal(data) {
        console.log('[Shipping] Pokazuję modal sukcesu:', data);

        const progressModal = document.getElementById('shippingProgressModal');
        if (progressModal) progressModal.classList.remove('active');

        document.getElementById('successCourierName').textContent = data.courier_name || 'Nieznany';
        document.getElementById('successPrice').textContent = (data.price || 0).toFixed(2) + ' zł';
        document.getElementById('successTrackingNumber').textContent = data.tracking_number || 'Oczekiwanie...';

        ShippingModule.currentLabel = data.label_base64;

        const successModal = document.getElementById('shippingSuccessModal');
        if (successModal) successModal.classList.add('active');

        // Jeśli brak numeru śledzenia, odpytaj po kilku sekundach
        if (!data.tracking_number) {
            console.log('[Shipping] Brak numeru śledzenia - odpytuję za 5 sekund...');
            setTimeout(() => {
                refreshTrackingNumber(ShippingModule.currentOrderId);
            }, 5000);
        }
    }

    /**
     * Odpytuje o numer śledzenia z Baselinker
     */
    function refreshTrackingNumber(orderId, retryCount = 0) {
        const maxRetries = 3;
        const retryDelay = 5000; // 5 sekund między próbami

        console.log(`[Shipping] Odpytywanie o numer śledzenia (próba ${retryCount + 1}/${maxRetries + 1})...`);

        fetch(`/production/stations/api/packaging/refresh-tracking/${orderId}`)
            .then(response => response.json())
            .then(result => {
                console.log('[Shipping] Odpowiedź refresh-tracking:', result);

                if (result.success && result.tracking_number) {
                    // Mamy numer - aktualizuj UI
                    console.log('[Shipping] Otrzymano numer śledzenia:', result.tracking_number);

                    const trackingEl = document.getElementById('successTrackingNumber');
                    if (trackingEl) {
                        trackingEl.textContent = result.tracking_number;
                    }

                    // Aktualizuj też w sekcji info jeśli jest widoczna
                    const infoTrackingEl = document.getElementById('shippingInfoTracking');
                    if (infoTrackingEl) {
                        infoTrackingEl.textContent = result.tracking_number;
                    }
                } else if (retryCount < maxRetries) {
                    // Brak numeru - spróbuj ponownie za chwilę
                    console.log(`[Shipping] Brak numeru śledzenia, ponawiam za ${retryDelay/1000}s...`);
                    setTimeout(() => {
                        refreshTrackingNumber(orderId, retryCount + 1);
                    }, retryDelay);
                } else {
                    console.log('[Shipping] Nie udało się pobrać numeru śledzenia po wszystkich próbach');
                    const trackingEl = document.getElementById('successTrackingNumber');
                    if (trackingEl && trackingEl.textContent === 'Oczekiwanie...') {
                        trackingEl.textContent = 'Niedostępny (sprawdź później)';
                    }
                }
            })
            .catch(error => {
                console.error('[Shipping] Błąd podczas odpytywania o numer śledzenia:', error);
                if (retryCount < maxRetries) {
                    setTimeout(() => {
                        refreshTrackingNumber(orderId, retryCount + 1);
                    }, retryDelay);
                }
            });
    }

    /**
     * Pokazuje modal błędu
     */
    function showErrorModal(step, errorMessage) {
        console.error(`[Shipping] Błąd w kroku "${step}":`, errorMessage);

        const progressModal = document.getElementById('shippingProgressModal');
        if (progressModal) progressModal.classList.remove('active');

        const stepName = ShippingModule.STEP_NAMES[step] || step;
        document.getElementById('errorStep').textContent = stepName;
        document.getElementById('errorMessage').textContent = errorMessage;

        const errorModal = document.getElementById('shippingErrorModal');
        if (errorModal) errorModal.classList.add('active');
    }

    /**
     * Zamyka wszystkie modale wysyłki
     */
    window.closeShippingModals = function() {
        console.log('[Shipping] Zamykam wszystkie modale wysyłki');

        const modals = ['shippingDimensionsModal', 'shippingConfirmModal', 'shippingProgressModal', 'shippingSuccessModal', 'shippingErrorModal'];
        modals.forEach(id => {
            const modal = document.getElementById(id);
            if (modal) modal.classList.remove('active');
        });
    };

    /**
     * Ponawia próbę wysyłki - otwiera modal wymiarów
     */
    window.retryShipment = function() {
        console.log('[Shipping] Ponawiam wysyłkę - otwieranie modalu wymiarów');
        closeShippingModals();
        // Otwórz modal wymiarów ponownie
        const dimensionsModal = document.getElementById('shippingDimensionsModal');
        if (dimensionsModal) dimensionsModal.classList.add('active');
    };

    /**
     * Helper - pauza
     */
    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * KROK 1: Pobiera wycenę i pokazuje modal potwierdzenia
     */
    async function getQuoteAndShowConfirm() {
        console.log('[Shipping] ========== POBIERAM WYCENĘ ==========');
        console.log('[Shipping] Order ID:', ShippingModule.currentOrderId);

        const btn = document.getElementById('submitShipmentBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<svg class="spinner-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line></svg> Pobieranie wyceny...';
        }

        // Pobierz wymiary z formularza
        const dimensions = {
            length: parseInt(document.getElementById('shipLength').value) || 0,
            width: parseInt(document.getElementById('shipWidth').value) || 0,
            height: parseInt(document.getElementById('shipHeight').value) || 0,
            weight: parseFloat(document.getElementById('shipWeight').value) || 0
        };

        console.log('[Shipping] Wymiary do wyceny:', dimensions);

        // Walidacja
        if (dimensions.length <= 0 || dimensions.width <= 0 ||
            dimensions.height <= 0 || dimensions.weight <= 0) {
            alert('Wprowadź prawidłowe wymiary i wagę przesyłki');
            resetSubmitButton();
            return;
        }

        // Zapisz wymiary w module
        ShippingModule.currentDimensions = dimensions;

        try {
            // Pobierz wycenę z backendu
            console.log('[Shipping] Wysyłam żądanie do /api/packaging/quote/...');

            const response = await fetch(`/production/stations/api/packaging/quote/${ShippingModule.currentOrderId}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(dimensions)
            });

            console.log('[Shipping] Odpowiedź quote status:', response.status);

            const result = await response.json();
            console.log('[Shipping] Odpowiedź quote JSON:', result);

            if (result.success && result.quote) {
                // Zapisz wycenę w module
                ShippingModule.currentQuote = result.quote;

                // Pokaż modal potwierdzenia
                showConfirmModal(result.quote, dimensions);
            } else {
                alert('Błąd pobierania wyceny: ' + (result.error || 'Nieznany błąd'));
                resetSubmitButton();
            }

        } catch (error) {
            console.error('[Shipping] Wyjątek podczas pobierania wyceny:', error);
            alert('Błąd połączenia: ' + error.message);
            resetSubmitButton();
        }
    }

    /**
     * Resetuje przycisk "Zgłaszam wysyłkę" do stanu początkowego
     */
    function resetSubmitButton() {
        const btn = document.getElementById('submitShipmentBtn');
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="1" y="3" width="15" height="13"></rect><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"></polygon><circle cx="5.5" cy="18.5" r="2.5"></circle><circle cx="18.5" cy="18.5" r="2.5"></circle></svg> Zgłaszam wysyłkę';
        }
    }

    /**
     * Pokazuje modal potwierdzenia z wybraną ofertą
     */
    function showConfirmModal(quote, dimensions) {
        console.log('[Shipping] Pokazuję modal potwierdzenia:', quote);

        // Zamknij modal wymiarów
        const dimensionsModal = document.getElementById('shippingDimensionsModal');
        if (dimensionsModal) dimensionsModal.classList.remove('active');

        // Wypełnij dane w modalu potwierdzenia
        document.getElementById('confirmCourierName').textContent = quote.courier_name || 'Nieznany';
        document.getElementById('confirmServiceName').textContent = quote.service_name || '-';
        document.getElementById('confirmPrice').textContent = (quote.price || 0).toFixed(2) + ' zł';
        document.getElementById('confirmDimensions').textContent =
            `${dimensions.length} x ${dimensions.width} x ${dimensions.height} cm, ${dimensions.weight} kg`;

        // Ustaw badge trybu pakowania
        const badge = document.getElementById('packagingModeBadge');
        const modeText = document.getElementById('packagingModeText');
        const multiDetails = document.getElementById('multiPackageDetails');

        if (quote.is_multi_package && quote.total_packages > 1) {
            // Tryb wielu paczek
            badge.className = 'packaging-mode-badge multi-package';
            modeText.textContent = `${quote.total_packages} paczki`;

            // Pokaż szczegóły paczek
            if (multiDetails) {
                multiDetails.style.display = 'block';
                const container = document.getElementById('packagesListContainer');
                if (container && quote.packages) {
                    container.innerHTML = quote.packages.map((pkg, idx) => `
                        <div class="package-item">
                            <span class="package-num">Paczka ${idx + 1}</span>
                            <span class="package-dims">${pkg.length}x${pkg.width}x${pkg.height} cm, ${pkg.weight} kg</span>
                            <span class="package-price">${(pkg.price || 0).toFixed(2)} zł</span>
                        </div>
                    `).join('');
                }
            }
        } else {
            // Tryb pojedynczej paczki
            badge.className = 'packaging-mode-badge single-package';
            modeText.textContent = '1 paczka';
            if (multiDetails) multiDetails.style.display = 'none';
        }

        // Otwórz modal potwierdzenia
        const confirmModal = document.getElementById('shippingConfirmModal');
        if (confirmModal) confirmModal.classList.add('active');

        // Zresetuj przycisk wymiarów
        resetSubmitButton();
    }

    /**
     * Powrót do modalu wymiarów
     */
    window.backToDimensions = function() {
        console.log('[Shipping] Powrót do wymiarów');

        // Zamknij modal potwierdzenia
        const confirmModal = document.getElementById('shippingConfirmModal');
        if (confirmModal) confirmModal.classList.remove('active');

        // Otwórz modal wymiarów
        const dimensionsModal = document.getElementById('shippingDimensionsModal');
        if (dimensionsModal) dimensionsModal.classList.add('active');
    };

    /**
     * KROK 2: Potwierdza i wysyła żądanie utworzenia przesyłki
     */
    async function confirmAndSubmitShipment() {
        console.log('[Shipping] ========== POTWIERDZAM I WYSYŁAM ==========');
        console.log('[Shipping] Order ID:', ShippingModule.currentOrderId);
        console.log('[Shipping] Wymiary:', ShippingModule.currentDimensions);
        console.log('[Shipping] Wycena:', ShippingModule.currentQuote);

        const btn = document.getElementById('confirmShipmentBtn');
        if (btn) btn.disabled = true;

        // Zamknij modal potwierdzenia i otwórz modal postępu
        const confirmModal = document.getElementById('shippingConfirmModal');
        if (confirmModal) confirmModal.classList.remove('active');

        openProgressModal();

        const dimensions = ShippingModule.currentDimensions;

        try {
            // Krok 1: Obliczanie wymiarów (już mamy - tylko oznaczamy)
            updateStep('dimensions', 'active', 'Weryfikacja wymiarów paczki...');
            await sleep(300);
            updateStep('dimensions', 'completed', `Wymiary: ${dimensions.length}x${dimensions.width}x${dimensions.height} cm, ${dimensions.weight} kg`);

            // Krok 2: Warianty (oznaczamy jako aktywny)
            updateStep('variants', 'active', 'Analizowanie możliwości pakowania...');
            await sleep(200);
            updateStep('variants', 'completed');

            // Krok 3: Ceny
            updateStep('prices', 'active', 'Wybrana oferta kuriera...');
            await sleep(200);
            updateStep('prices', 'completed', `${ShippingModule.currentQuote.courier_name} - ${ShippingModule.currentQuote.price.toFixed(2)} zł`);

            // Krok 4: Porównanie
            updateStep('compare', 'active', 'Przygotowywanie przesyłki...');

            // Wysyłamy żądanie do backendu
            console.log('[Shipping] Wysyłam żądanie do /api/packaging/ship/...');

            const response = await fetch(`/production/stations/api/packaging/ship/${ShippingModule.currentOrderId}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(dimensions)
            });

            console.log('[Shipping] Odpowiedź status:', response.status);

            const result = await response.json();
            console.log('[Shipping] Odpowiedź JSON:', result);

            if (result.success) {
                // Oznacz wszystkie kroki jako ukończone
                ShippingModule.STEPS.forEach(step => {
                    updateStep(step, 'completed');
                });
                await sleep(500);
                showSuccessModal(result);
            } else {
                // Oznacz krok błędu
                const failedStep = result.failed_step || 'unknown';

                // Znajdź indeks kroku który się nie powiódł
                const failedIndex = ShippingModule.STEPS.indexOf(failedStep);

                // Oznacz poprzednie kroki jako ukończone
                ShippingModule.STEPS.forEach((step, idx) => {
                    if (idx < failedIndex) {
                        updateStep(step, 'completed');
                    } else if (idx === failedIndex) {
                        updateStep(step, 'error');
                    }
                });

                await sleep(300);
                showErrorModal(failedStep, result.error || 'Nieznany błąd');
            }

        } catch (error) {
            console.error('[Shipping] Wyjątek podczas wysyłki:', error);
            showErrorModal('connection', `Błąd połączenia: ${error.message}`);
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    /**
     * Pobiera etykietę PDF z podanego base64 i nazwy
     */
    function downloadLabelPdf(base64Data, orderId) {
        console.log('[Shipping] Pobieranie etykiety PDF dla zamówienia:', orderId);
        console.log('[Shipping] Rozmiar danych base64:', base64Data ? base64Data.length : 0);

        if (base64Data) {
            // Wyczyść dane base64 z ewentualnych prefiksów i białych znaków
            let cleanBase64 = base64Data.trim();

            // Usuń prefiks data:application/pdf;base64, jeśli jest
            if (cleanBase64.startsWith('data:')) {
                const commaIndex = cleanBase64.indexOf(',');
                if (commaIndex > -1) {
                    cleanBase64 = cleanBase64.substring(commaIndex + 1);
                }
            }

            // Usuń ewentualne białe znaki i nowe linie z base64
            cleanBase64 = cleanBase64.replace(/\s/g, '');

            console.log('[Shipping] Rozmiar po czyszczeniu:', cleanBase64.length);
            console.log('[Shipping] Pierwsze 50 znaków:', cleanBase64.substring(0, 50));

            // Sprawdź czy base64 wygląda poprawnie (zaczyna się od %PDF w base64 = JVBERi)
            if (!cleanBase64.startsWith('JVBERi')) {
                console.warn('[Shipping] UWAGA: Base64 nie wygląda jak PDF (powinien zaczynać się od JVBERi)');
                console.log('[Shipping] Początek danych:', cleanBase64.substring(0, 100));
            }

            try {
                const link = document.createElement('a');
                link.href = 'data:application/pdf;base64,' + cleanBase64;
                link.download = `etykieta_${orderId}.pdf`;
                console.log('[Shipping] Pobieranie pliku:', link.download);
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
            } catch (error) {
                console.error('[Shipping] Błąd podczas tworzenia linku do pobrania:', error);
                alert('Błąd podczas pobierania etykiety: ' + error.message);
            }
        } else {
            console.error('[Shipping] Brak etykiety do pobrania!');
            alert('Brak etykiety do pobrania');
        }
    }

    /**
     * Pobiera etykietę PDF (z modalu sukcesu)
     */
    function downloadLabel() {
        console.log('[Shipping] Pobieranie etykiety PDF');

        if (ShippingModule.currentLabel) {
            const trackingNum = document.getElementById('successTrackingNumber').textContent || 'unknown';
            downloadLabelPdf(ShippingModule.currentLabel, trackingNum);
        } else {
            console.error('[Shipping] Brak etykiety do pobrania!');
            alert('Brak etykiety do pobrania');
        }
    }

    // Inicjalizacja event listenerów dla shipping
    document.addEventListener('DOMContentLoaded', function() {
        console.log('[Shipping] Inicjalizacja event listenerów');

        // Przycisk "Zgłoś wysyłkę" w modalu dostawy - otwiera modal wymiarów
        const openModalBtn = document.getElementById('openShippingModalBtn');
        if (openModalBtn) {
            openModalBtn.addEventListener('click', openShippingDimensionsModal);
        }

        // Przycisk "Zgłaszam wysyłkę" w modalu wymiarów - pobiera wycenę i pokazuje potwierdzenie
        const submitBtn = document.getElementById('submitShipmentBtn');
        if (submitBtn) {
            submitBtn.addEventListener('click', getQuoteAndShowConfirm);
        }

        // Przycisk "Potwierdzam - Zgłoś przesyłkę" w modalu potwierdzenia - tworzy przesyłkę
        const confirmBtn = document.getElementById('confirmShipmentBtn');
        if (confirmBtn) {
            confirmBtn.addEventListener('click', confirmAndSubmitShipment);
        }

        // Przycisk "Pobierz etykietę"
        const downloadBtn = document.getElementById('downloadLabelBtn');
        if (downloadBtn) {
            downloadBtn.addEventListener('click', downloadLabel);
        }

        // Zamykanie modalu wymiarów przez kliknięcie w overlay
        const dimensionsModal = document.getElementById('shippingDimensionsModal');
        if (dimensionsModal) {
            dimensionsModal.addEventListener('click', function(e) {
                if (e.target === this) {
                    closeShippingModals();
                }
            });
        }

        // Zamykanie modalu potwierdzenia przez kliknięcie w overlay
        const confirmModal = document.getElementById('shippingConfirmModal');
        if (confirmModal) {
            confirmModal.addEventListener('click', function(e) {
                if (e.target === this) {
                    closeShippingModals();
                }
            });
        }
    });

    console.log('[Shipping] Module loaded v1.0');

    // ========================================================================
    // CLEANUP
    // ========================================================================

    window.addEventListener('beforeunload', function() {
        if (state.refreshTimer) {
            clearInterval(state.refreshTimer);
            console.log('[Packaging] Cleared auto-refresh interval');
        }

        if (state.countdownTimer) {
            clearInterval(state.countdownTimer);
            console.log('[Packaging] Cleared countdown timer');
        }

        // Clear all active order countdowns
        state.activeCountdowns.forEach((countdown, orderNumber) => {
            if (countdown.timerId) {
                clearInterval(countdown.timerId);
                console.log(`[Packaging] Cleared countdown for ${orderNumber}`);
            }
        });

        // Clear pending requests
        state.pendingRequests.forEach((timeoutId) => {
            clearTimeout(timeoutId);
        });
    });

    console.log('[Packaging] Module loaded v3.0 (quantity-based with +/- buttons)');

})();
