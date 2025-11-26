/**
 * ============================================================================
 * STATION ASSEMBLY - ORDER-BASED VERSION
 * ============================================================================
 *
 * Nowa wersja z order-based cards zamiast product-based
 *
 * Funkcjonalność:
 * - Checkbox tracking w localStorage per zamówienie
 * - Bulk completion całych zamówień z countdown 10s
 * - Optimistic UI z error recovery
 * - Smart merge podczas auto-refresh
 * - Zegar odświeżany co sekundę
 * - Auto-refresh co 60s (z konfiguracji)
 *
 * @author: Konrad Kmiecik
 * @date: 2025-01-24
 * @version: 2.0
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
        activeCountdowns: new Map() // orderNumber -> { timerId, secondsLeft }
    };

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    document.addEventListener('DOMContentLoaded', function() {
        console.log('[Finishing] Initializing ORDER-BASED station v2.0...');
        initializeFinishingStation();
    });

    function initializeFinishingStation() {
        const config = window.STATION_CONFIG;

        if (!config || config.stationCode !== 'finishing') {
            console.error('[Finishing] Invalid station config');
            return;
        }

        state.config = config;
        console.log('[Finishing] Station config loaded:', config);

        // Attach event listeners to existing order cards
        const existingCards = document.querySelectorAll('.order-card');
        console.log(`[Finishing] Found ${existingCards.length} order cards on initial page load`);

        if (existingCards.length === 0) {
            console.log('[Finishing] No order cards on page - will fetch from API');
        }

        existingCards.forEach(card => {
            initializeOrderCard(card);
        });

        // Fetch today's m³
        fetchTodayM3();

        // POPRAWKA 1: Start datetime clock (updates every second)
        setInterval(updateCurrentDatetime, 1000);
        updateCurrentDatetime();

        // POPRAWKA 2: Perform initial fetch if no cards on page
        if (existingCards.length === 0) {
            console.log('[Finishing] Performing initial fetch...');
            performAutoRefresh();
        }

        // POPRAWKA 3: Start auto-refresh with countdown
        if (config.refreshInterval && config.refreshInterval > 0) {
            startAutoRefresh(config.refreshInterval);
            startRefreshCountdown(config.refreshInterval);
        }

        // Theme toggle
        setupThemeToggle();

        // Initialize connection monitor
        if (window.StationCommon && window.StationCommon.initConnectionMonitor) {
            window.StationCommon.initConnectionMonitor();
            console.log('[Finishing] Connection monitor initialized');

            // Register listener for connection changes
            if (window.StationCommon.onConnectionChange) {
                window.StationCommon.onConnectionChange(handleConnectionChange);
                console.log('[Finishing] Connection change listener registered');
            }
        }

        console.log('[Finishing] Station initialized successfully');
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

        console.log(`[Finishing] Refresh countdown started: ${intervalSeconds}s`);
    }

    // ========================================================================
    // ORDER CARD INITIALIZATION
    // ========================================================================

    function initializeOrderCard(card) {
        const orderNumber = card.dataset.orderNumber;

        if (!orderNumber) {
            console.warn('[Finishing] Order card missing order number');
            return;
        }

        console.log(`[Finishing] Initializing order card: ${orderNumber}`);

        // Hide empty product-params containers
        hideEmptyProductParams(card);

        // Load checkbox state from localStorage
        loadCheckboxState(card, orderNumber);

        // Attach checkbox listeners
        const checkboxes = card.querySelectorAll('.product-check');
        checkboxes.forEach(checkbox => {
            checkbox.addEventListener('change', function() {
                handleCheckboxChange(card, orderNumber);
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
        updateCheckedCounter(card);
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
    // CHECKBOX STATE MANAGEMENT
    // ========================================================================

    function loadCheckboxState(card, orderNumber) {
        const storageKey = `finishing_order_${orderNumber}`;
        const savedState = localStorage.getItem(storageKey);

        if (!savedState) {
            return;
        }

        try {
            const checkedProductIds = JSON.parse(savedState);

            if (!Array.isArray(checkedProductIds)) {
                return;
            }

            const checkboxes = card.querySelectorAll('.product-check');
            checkboxes.forEach(checkbox => {
                const productId = checkbox.dataset.productId;
                if (checkedProductIds.includes(productId)) {
                    checkbox.checked = true;
                }
            });

            console.log(`[Finishing] Loaded checkbox state for ${orderNumber}:`, checkedProductIds.length);
        } catch (error) {
            console.error(`[Finishing] Error loading checkbox state:`, error);
        }
    }

    function saveCheckboxState(card, orderNumber) {
        const checkedProductIds = getCheckedProductIds(card);
        const storageKey = `finishing_order_${orderNumber}`;

        localStorage.setItem(storageKey, JSON.stringify(checkedProductIds));

        console.log(`[Finishing] Saved checkbox state for ${orderNumber}:`, checkedProductIds.length);
    }

    function getCheckedProductIds(card) {
        const checkedProductIds = [];
        const checkboxes = card.querySelectorAll('.product-check:checked');

        checkboxes.forEach(checkbox => {
            checkedProductIds.push(checkbox.dataset.productId);
        });

        return checkedProductIds;
    }

    function clearCheckboxState(orderNumber) {
        const storageKey = `finishing_order_${orderNumber}`;
        localStorage.removeItem(storageKey);
        console.log(`[Finishing] Cleared checkbox state for ${orderNumber}`);
    }

    function handleCheckboxChange(card, orderNumber) {
        // Save state to localStorage
        saveCheckboxState(card, orderNumber);

        // Update complete button state
        updateCompleteButtonState(card);

        // Update checked counter in UI
        updateCheckedCounter(card);
    }

    function updateCheckedCounter(card) {
        const orderNumber = card.dataset.orderNumber;
        const totalProducts = parseInt(card.dataset.totalProducts) || 0;
        const checkedCount = card.querySelectorAll('.product-check:checked').length;

        const counterElement = document.querySelector(`.products-checked[data-order="${orderNumber}"]`);
        if (counterElement) {
            counterElement.textContent = checkedCount;
        }

        console.log(`[Finishing] Updated counter for ${orderNumber}: ${checkedCount}/${totalProducts}`);
    }

    // ========================================================================
    // CONNECTION STATUS HANDLING
    // ========================================================================

    function handleConnectionChange(isOnline) {
        console.log(`[Finishing] Connection status changed: ${isOnline ? 'ONLINE' : 'OFFLINE'}`);

        // Update all complete buttons
        const allCards = document.querySelectorAll('.order-card');
        allCards.forEach(card => {
            updateCompleteButtonState(card);
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
        completeBtn.textContent = 'ZAKOŃCZ';

        const totalProducts = parseInt(card.dataset.totalProducts) || 0;
        const checkedCount = card.querySelectorAll('.product-check:checked').length;

        // Enable button only if ALL products are checked
        if (checkedCount === totalProducts && totalProducts > 0) {
            completeBtn.disabled = false;
        } else {
            completeBtn.disabled = true;
        }
    }

    // ========================================================================
    // POPRAWKA 3: COUNTDOWN 10 SEKUND PRZED ZAKOŃCZENIEM
    // ========================================================================

    function handleCompleteClick(card, orderNumber) {
        console.log(`[Finishing] Complete button clicked for order: ${orderNumber}`);

        // Check online status first
        if (!window.StationCommon.isOnline()) {
            console.warn('[Finishing] Offline - cannot complete orders');
            showToast('warning', 'Brak połączenia - nie możesz zakończyć zamówienia');
            return;
        }

        const checkedProductIds = getCheckedProductIds(card);

        if (checkedProductIds.length === 0) {
            console.warn('[Finishing] No products checked');
            showToast('warning', 'Zaznacz produkty przed zakończeniem');
            return;
        }

        const totalProducts = parseInt(card.dataset.totalProducts) || 0;
        if (checkedProductIds.length !== totalProducts) {
            showToast('warning', 'Zaznacz wszystkie produkty przed zakończeniem');
            return;
        }

        // Mark card as in-progress
        card.dataset.inProgress = 'true';
        card.classList.add('processing');

        // Start 10-second countdown
        startCountdown(card, orderNumber, checkedProductIds);
    }

    function startCountdown(card, orderNumber, productIds) {
        console.log(`[Finishing] Starting 10-second countdown for ${orderNumber}`);

        const actionContainer = card.querySelector('.order-action');
        if (!actionContainer) {
            console.error('[Finishing] No action container found');
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

        console.log(`[Finishing] Countdown started for ${orderNumber}`);
    }

    function cancelCountdown(card, orderNumber, timerId) {
        console.log(`[Finishing] Countdown cancelled for ${orderNumber}`);

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
            actionContainer.innerHTML = '<button class="btn-complete" data-action="complete" disabled>ZAKOŃCZ</button>';

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

        showToast('info', 'Anulowano wykańczanie zamówienia');
    }

    // ========================================================================
    // BULK COMPLETION - Optimistic UI
    // ========================================================================

    async function completeOrder(card, orderNumber, productIds) {
        console.log(`[Finishing] Starting bulk completion for ${orderNumber}`, productIds);

        // BACKUP before removal
        const cardBackup = card.cloneNode(true);
        const checkboxStateBackup = getCheckedProductIds(card);

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
                    station: 'finishing',
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

            console.log('[Finishing] Order completed successfully:', result);

            // SUCCESS - show success state
            if (actionContainer) {
                actionContainer.innerHTML = '<button class="btn-complete success">Zapisano</button>';
            }

            showToast('success', `Zamówienie ${orderNumber} ukończone`);

            // Clear localStorage
            clearCheckboxState(orderNumber);

            // Update today's m³ statistics
            fetchTodayM3();

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
            console.error('[Finishing] Failed to complete order:', error);

            const ordersList = document.getElementById('orders-list');

            if (ordersList) {
                // Re-insert card
                ordersList.insertBefore(cardBackup, ordersList.firstChild);

                // Re-initialize the restored card
                initializeOrderCard(cardBackup);

                // Restore checkbox state
                const checkboxes = cardBackup.querySelectorAll('.product-check');
                checkboxes.forEach(checkbox => {
                    const productId = checkbox.dataset.productId;
                    if (checkboxStateBackup.includes(productId)) {
                        checkbox.checked = true;
                    }
                });

                saveCheckboxState(cardBackup, orderNumber);
                updateCompleteButtonState(cardBackup);
                updateCheckedCounter(cardBackup);
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

        console.log(`[Finishing] Remaining cards: ${remainingCards}`);
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

        console.log(`[Finishing] Updated header stats: ${totalProducts} products, ${totalVolume.toFixed(4)} m³`);
    }

    function showEmptyState() {
        const ordersList = document.getElementById('orders-list');

        if (!ordersList) {
            return;
        }

        ordersList.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">✅</div>
                <h2>Brak zamówień do wykańczania</h2>
                <p>Świetna robota! Wszystkie zamówienia zostały wykończone.</p>
            </div>
        `;

        console.log('[Finishing] Showing empty state');
    }

    // ========================================================================
    // TOAST NOTIFICATIONS
    // ========================================================================

    function showToast(type, message) {
        const prefix = type === 'success' ? '✅' : type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️';
        console.log(`[Finishing] ${prefix} ${message}`);

        // TODO: Implement visual toast notifications if needed
    }

    // ========================================================================
    // AUTO-REFRESH WITH SMART MERGE
    // ========================================================================

    function startAutoRefresh(intervalSeconds) {
        if (state.refreshTimer) {
            clearInterval(state.refreshTimer);
        }

        console.log(`[Finishing] Starting auto-refresh every ${intervalSeconds}s`);

        state.refreshTimer = setInterval(async () => {
            await performAutoRefresh();
        }, intervalSeconds * 1000);
    }

    async function performAutoRefresh() {
        console.log('[Finishing] Performing auto-refresh...');

        try {
            const response = await fetch('/production/stations/ajax/orders/finishing?sort=priority');

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const result = await response.json();
            console.log('[Finishing] API Response:', result);

            if (!result.success || !result.data || !result.data.orders) {
                throw new Error('Invalid response format');
            }

            console.log(`[Finishing] Fetched ${result.data.orders.length} orders`);
            console.log('[Finishing] Orders data:', JSON.stringify(result.data.orders, null, 2));

            smartMergeOrders(result.data.orders);

            // Update header statistics
            updateHeaderStats();

            // Update today's m³ statistics
            fetchTodayM3();

        } catch (error) {
            console.error('[Finishing] Auto-refresh failed:', error);
        }
    }

    function smartMergeOrders(newOrders) {
        console.log('[Finishing] smartMergeOrders called with:', newOrders.length, 'orders');

        const ordersList = document.getElementById('orders-list');

        if (!ordersList) {
            console.error('[Finishing] orders-list element not found!');
            return;
        }

        const existingCards = ordersList.querySelectorAll('.order-card');
        const existingOrderNumbers = new Map(); // Changed to Map to store card references

        console.log(`[Finishing] Existing cards on page: ${existingCards.length}`);
        existingCards.forEach(card => {
            const orderNum = card.dataset.orderNumber;
            existingOrderNumbers.set(orderNum, card);
            console.log(`[Finishing] Existing order: ${orderNum}`);
        });

        // Stwórz zbiór numerów zamówień z API
        const apiOrderNumbers = new Set(newOrders.map(order => order.order_number));

        // Add NEW orders or UPDATE existing ones if they're missing finish_state badges
        let addedCount = 0;
        let updatedCount = 0;
        newOrders.forEach(order => {
            console.log(`[Finishing] Checking order ${order.order_number}...`);
            const existingCard = existingOrderNumbers.get(order.order_number);

            if (!existingCard) {
                console.log(`[Finishing] Adding new order: ${order.order_number}`);
                addOrderCard(order);
                addedCount++;
            } else {
                // Check if existing card has finish_state badges
                const hasFinishBadge = existingCard.querySelector('.badge-finish');
                if (!hasFinishBadge && order.products.some(p => p.finish_state)) {
                    console.log(`[Finishing] Order ${order.order_number} missing finish badges, updating...`);
                    // Remove old card and add updated one
                    existingCard.remove();
                    addOrderCard(order);
                    updatedCount++;
                } else {
                    console.log(`[Finishing] Order ${order.order_number} already up-to-date, skipping`);
                }
            }
        });

        // Remove cards that are no longer in API response (but not if user is working on them)
        let removedCount = 0;
        existingCards.forEach(card => {
            const orderNumber = card.dataset.orderNumber;
            if (!apiOrderNumbers.has(orderNumber)) {
                const hasActiveCountdown = state.activeCountdowns.has(orderNumber);
                const isProcessing = card.classList.contains('processing');

                if (!hasActiveCountdown && !isProcessing) {
                    console.log(`[Finishing] Removing order no longer on station: ${orderNumber}`);
                    card.classList.add('removing');
                    setTimeout(() => {
                        card.remove();
                        checkAndShowEmptyState();
                    }, 300);
                    removedCount++;
                } else {
                    console.log(`[Finishing] Keeping order ${orderNumber} - user is working on it`);
                }
            }
        });

        console.log(`[Finishing] Smart merge completed: ${addedCount} added, ${updatedCount} updated, ${removedCount} removed`);
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
                        <h2>Brak zamówień do wykończenia</h2>
                        <p>Świetna robota! Wszystkie zamówienia zostały wykończone.</p>
                    </div>
                `;
            }
        }
    }

    function addOrderCard(orderData) {
        console.log('[Finishing] addOrderCard called for:', orderData.order_number);
        console.log('[Finishing] Order data:', orderData);

        const ordersList = document.getElementById('orders-list');

        if (!ordersList) {
            console.error('[Finishing] orders-list element not found in addOrderCard!');
            return;
        }

        // Remove empty state if present
        const emptyState = ordersList.querySelector('.empty-state');
        if (emptyState) {
            console.log('[Finishing] Removing empty state');
            emptyState.remove();
        }

        // Create card HTML
        const cardHTML = createOrderCardHTML(orderData);
        console.log('[Finishing] Generated HTML length:', cardHTML.length, 'chars');

        // Insert at the beginning (highest priority)
        ordersList.insertAdjacentHTML('afterbegin', cardHTML);
        console.log('[Finishing] Card HTML inserted');

        // Initialize the new card
        const newCard = ordersList.querySelector(`[data-order-number="${orderData.order_number}"]`);
        if (newCard) {
            console.log('[Finishing] New card found in DOM, initializing...');
            initializeOrderCard(newCard);

            // Re-initialize attachment handlers for the new card
            if (typeof window.reinitializeAttachmentHandlers === 'function') {
                window.reinitializeAttachmentHandlers();
            }
        } else {
            console.error('[Finishing] New card NOT found in DOM after insertion!');
        }
    }

    function createOrderCardHTML(order) {
        console.log('[Finishing] createOrderCardHTML called for order:', order.order_number);
        console.log('[Finishing] Order has', order.products.length, 'products');

        const productsHTML = order.products.map(product => {
            const attachmentHTML = product.attachment_file_url ? `
                <div class="attachment-icon-wrapper"
                     data-attachment-url="${product.attachment_file_url}"
                     data-attachment-name="${product.attachment_file_name}"
                     data-attachment-type="${product.attachment_file_name.toLowerCase().endsWith('.pdf') ? 'pdf' : 'image'}">
                    <svg class="attachment-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
                    </svg>
                </div>
            ` : '';

            // Debug: log finish_state
            console.log(`[DEBUG] Product ${product.id} finish_state:`, product.finish_state);

            // Małe badges z parametrami
            const paramsHTML = `
                ${product.wood_species ? `<span class="badge badge-species">${product.wood_species}</span>` : ''}
                ${product.technology ? `<span class="badge badge-technology">${product.technology}</span>` : ''}
                ${product.wood_class ? `<span class="badge badge-class">${product.wood_class}</span>` : ''}
                ${product.finish_state ? `<span class="badge badge-finish">${product.finish_state}</span>` : ''}
            `;

            // Duży badge z wymiarami lub nazwą + ikona załącznika
            let dimensionsRowHTML = '';
            if (product.dimensions) {
                const formattedDimensions = product.dimensions.replace(/x/g, ' x ').replace(/×/g, ' × ');
                dimensionsRowHTML = `<div class="product-dimensions">${formattedDimensions}</div>`;
            } else if (product.original_name) {
                dimensionsRowHTML = `<div class="product-dimensions product-name-label">${product.original_name}</div>`;
            } else if (product.attachment_file_url) {
                dimensionsRowHTML = `<div class="product-dimensions product-attachment-label">Zgodnie z załącznikiem</div>`;
            }

            const dimensionsHTML = `
                <div class="product-dimensions-row">
                    ${attachmentHTML}
                    ${dimensionsRowHTML}
                </div>
            `;

            return `
                <div class="product-row"
                     data-product-id="${product.id}"
                     data-status="${product.current_status}"
                     data-species="${product.wood_species || ''}"
                     data-technology="${product.technology || ''}"
                     data-wood-class="${product.wood_class || ''}">
                    <div class="product-left-col">
                        <div class="product-checkbox">
                            <input type="checkbox"
                                   class="product-check"
                                   id="check-${product.id}"
                                   data-product-id="${product.id}">
                            <label for="check-${product.id}"></label>
                        </div>
                        <div class="product-id-wrapper">
                            <span class="product-id">${product.id}</span>
                        </div>
                    </div>
                    <div class="product-info">
                        <div class="product-params">${paramsHTML}</div>
                        ${dimensionsHTML}
                    </div>
                </div>
            `;
        }).join('');

        const blBadge = order.baselinker_order_id ? `<span class="order-baselinker">BL-${order.baselinker_order_id}</span>` : '';

        return `
            <div class="order-card"
                 data-order-number="${order.order_number}"
                 data-priority-rank="${order.best_priority_rank}"
                 data-total-products="${order.total_products}"
                 data-total-volume="${order.total_volume}"
                 data-in-progress="false">
                <div class="order-header">
                    <div class="order-ids">
                        <span class="order-number">${order.order_number}</span>
                        ${blBadge}
                    </div>
                    <div class="order-stats">
                        <span class="products-checked" data-order="${order.order_number}">0</span>/${order.total_products} ${order.total_products === 1 ? 'produkt' : order.total_products < 5 ? 'produkty' : 'produktów'} • ${order.total_volume.toFixed(4)} m³
                    </div>
                </div>
                <div class="products-list">
                    ${productsHTML}
                </div>
                <div class="order-action">
                    <button class="btn-complete" data-action="complete" disabled>ZAKOŃCZ</button>
                </div>
            </div>
        `;
    }

    // ========================================================================
    // FETCH TODAY'S M³
    // ========================================================================

    async function fetchTodayM3() {
        try {
            const response = await fetch('/production/stations/ajax/station-today-m3/finishing');

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const result = await response.json();

            if (result.success && result.data) {
                const todayM3Element = document.getElementById('today-m3');
                if (todayM3Element) {
                    todayM3Element.textContent = result.data.today_m3.toFixed(4);
                }

                console.log(`[Finishing] Today's m³: ${result.data.today_m3}`);
            }

        } catch (error) {
            console.error('[Finishing] Failed to fetch today m³:', error);
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
            console.log('[Finishing] Cleared auto-refresh interval');
        }

        if (state.countdownTimer) {
            clearInterval(state.countdownTimer);
            console.log('[Finishing] Cleared countdown timer');
        }

        // Clear all active order countdowns
        state.activeCountdowns.forEach((countdown, orderNumber) => {
            if (countdown.timerId) {
                clearInterval(countdown.timerId);
                console.log(`[Finishing] Cleared countdown for ${orderNumber}`);
            }
        });
    });

    console.log('[Finishing] Module loaded v2.0 (order-based with countdown)');

})();
