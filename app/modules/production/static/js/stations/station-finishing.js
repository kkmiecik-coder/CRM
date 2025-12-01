/**
 * ============================================================================
 * STATION FINISHING - QUANTITY-BASED VERSION
 * ============================================================================
 *
 * Wersja z quantity buttons (+/-) zamiast checkboxów
 *
 * @author: Konrad Kmiecik
 * @date: 2025-11
 * @version: 3.0
 */

(function() {
    'use strict';

    const state = {
        config: null,
        refreshTimer: null,
        countdownTimer: null,
        activeCountdowns: new Map(),
        pendingRequests: new Map(),
        lastRequestTime: new Map()
    };

    const RATE_LIMIT_MS = 200;

    document.addEventListener('DOMContentLoaded', function() {
        console.log('[Finishing] Initializing QUANTITY-BASED station v3.0...');
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

        const existingCards = document.querySelectorAll('.order-card');
        console.log(`[Finishing] Found ${existingCards.length} order cards`);

        existingCards.forEach(card => {
            initializeOrderCard(card);
        });

        fetchTodayM3();

        setInterval(updateCurrentDatetime, 1000);
        updateCurrentDatetime();

        if (existingCards.length === 0) {
            console.log('[Finishing] Performing initial fetch...');
            performAutoRefresh();
        }

        if (config.refreshInterval && config.refreshInterval > 0) {
            startAutoRefresh(config.refreshInterval);
            startRefreshCountdown(config.refreshInterval);
        }

        setupThemeToggle();

        if (window.StationCommon && window.StationCommon.initConnectionMonitor) {
            window.StationCommon.initConnectionMonitor();
            if (window.StationCommon.onConnectionChange) {
                window.StationCommon.onConnectionChange(handleConnectionChange);
            }
        }

        console.log('[Finishing] Station initialized successfully');
    }

    function updateCurrentDatetime() {
        const datetimeElement = document.getElementById('current-datetime');
        if (!datetimeElement) return;

        const now = new Date();
        const days = ['Niedziela', 'Poniedziałek', 'Wtorek', 'Środa', 'Czwartek', 'Piątek', 'Sobota'];
        const dayName = days[now.getDay()];

        const date = now.toLocaleDateString('pl-PL', { day: '2-digit', month: '2-digit', year: 'numeric' });
        const time = now.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

        datetimeElement.textContent = `${date} • ${time}`;

        const labelElement = datetimeElement.previousElementSibling;
        if (labelElement && labelElement.classList.contains('stat-label')) {
            labelElement.textContent = dayName;
        }
    }

    function startRefreshCountdown(intervalSeconds) {
        if (state.countdownTimer) clearInterval(state.countdownTimer);

        let secondsLeft = intervalSeconds;
        const countdownElement = document.getElementById('refresh-countdown');
        const refreshIcon = document.querySelector('.refresh-icon');

        const updateCountdown = () => {
            if (countdownElement) {
                countdownElement.textContent = `${secondsLeft}s`;
                if (secondsLeft <= 10) countdownElement.classList.add('warning');
                else countdownElement.classList.remove('warning');
                if (secondsLeft <= 5 && refreshIcon) refreshIcon.classList.add('spinning');
                else if (refreshIcon) refreshIcon.classList.remove('spinning');
            }
        };

        updateCountdown();

        state.countdownTimer = setInterval(() => {
            secondsLeft--;
            if (secondsLeft <= 0) secondsLeft = intervalSeconds;
            updateCountdown();
        }, 1000);
    }

    function initializeOrderCard(card) {
        const orderNumber = card.dataset.orderNumber;
        if (!orderNumber) return;

        hideEmptyProductParams(card);

        const quantityButtons = card.querySelectorAll('.btn-qty');
        quantityButtons.forEach(button => {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                handleQuantityButtonClick(card, orderNumber, this);
            });
        });

        const completeBtn = card.querySelector('.btn-complete');
        if (completeBtn) {
            completeBtn.addEventListener('click', function() {
                handleCompleteClick(card, orderNumber);
            });
        }

        updateCompleteButtonState(card);
        updateOrderCounter(card);
    }

    function hideEmptyProductParams(card) {
        const productRows = card.querySelectorAll('.product-row');
        productRows.forEach(row => {
            const paramsContainer = row.querySelector('.product-params');
            if (!paramsContainer) return;
            const badges = paramsContainer.querySelectorAll('.badge');
            if (badges.length === 0) paramsContainer.style.display = 'none';
        });
    }

    async function handleQuantityButtonClick(card, orderNumber, button) {
        const productId = button.dataset.productId;
        const action = button.dataset.action;
        const productRow = button.closest('.product-row');

        if (!productId || !action || !productRow) return;

        const isOnline = window.StationCommon && window.StationCommon.isOnline ? window.StationCommon.isOnline() : true;
        if (!isOnline) {
            showToast('warning', 'Brak połączenia - nie można zapisać zmiany');
            return;
        }

        const qtyDoneEl = productRow.querySelector('.qty-done');
        const qtyTotalEl = productRow.querySelector('.qty-total');
        if (!qtyDoneEl || !qtyTotalEl) return;

        let qtyDone = parseInt(qtyDoneEl.textContent) || 0;
        const qtyTotal = parseInt(qtyTotalEl.textContent) || 0;

        let newQtyDone = qtyDone;
        switch (action) {
            case 'increment': newQtyDone = Math.min(qtyDone + 1, qtyTotal); break;
            case 'decrement': newQtyDone = Math.max(qtyDone - 1, 0); break;
            case 'increment10': newQtyDone = Math.min(qtyDone + 10, qtyTotal); break;
            case 'decrement10': newQtyDone = Math.max(qtyDone - 10, 0); break;
        }

        if (newQtyDone === qtyDone) return;

        qtyDoneEl.textContent = newQtyDone;
        productRow.dataset.quantityDone = newQtyDone;

        updateProductButtonStates(productRow, newQtyDone, qtyTotal);
        updateOrderCounter(card);
        updateCompleteButtonState(card);

        await sendQuantityUpdate(productId, action, productRow, qtyDone, card);
    }

    async function sendQuantityUpdate(productId, action, productRow, previousValue, card) {
        if (state.pendingRequests.has(productId)) {
            clearTimeout(state.pendingRequests.get(productId));
        }

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
                    body: JSON.stringify({ product_id: productId, station: 'finishing', action: action })
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || `HTTP ${response.status}`);
                }

                const result = await response.json();
                console.log(`[Finishing] Product ${productId} quantity updated:`, result);

                const qtyDoneEl = productRow.querySelector('.qty-done');
                if (qtyDoneEl && result.quantity_done !== undefined) {
                    qtyDoneEl.textContent = result.quantity_done;
                    productRow.dataset.quantityDone = result.quantity_done;
                    updateProductButtonStates(productRow, result.quantity_done, result.quantity);
                    updateOrderCounter(card);
                    updateCompleteButtonState(card);
                }

            } catch (error) {
                console.error('[Finishing] Failed to update quantity:', error);
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

        if (btnMinus) btnMinus.disabled = qtyDone <= 0;
        if (btnPlus) btnPlus.disabled = qtyDone >= qtyTotal;
        if (btnMinus10) btnMinus10.disabled = qtyDone < 10;
        if (btnPlus10) btnPlus10.disabled = (qtyTotal - qtyDone) < 10;

        if (qtyDone === qtyTotal) productRow.classList.add('product-complete');
        else productRow.classList.remove('product-complete');
    }

    function updateOrderCounter(card) {
        const orderNumber = card.dataset.orderNumber;
        const productRows = card.querySelectorAll('.product-row');

        let totalDone = 0;
        let totalQuantity = 0;

        productRows.forEach(row => {
            totalDone += parseInt(row.dataset.quantityDone) || 0;
            totalQuantity += parseInt(row.dataset.quantity) || 0;
        });

        const counterElement = document.querySelector(`.products-checked[data-order="${orderNumber}"]`);
        if (counterElement) counterElement.textContent = totalDone;
    }

    function handleConnectionChange(isOnline) {
        console.log(`[Finishing] Connection status changed: ${isOnline ? 'ONLINE' : 'OFFLINE'}`);

        const allCards = document.querySelectorAll('.order-card');
        allCards.forEach(card => {
            updateCompleteButtonState(card);
            const qtyButtons = card.querySelectorAll('.btn-qty');
            qtyButtons.forEach(btn => {
                if (!isOnline) btn.classList.add('offline-disabled');
                else btn.classList.remove('offline-disabled');
            });
        });
    }

    function updateCompleteButtonState(card) {
        const completeBtn = card.querySelector('.btn-complete');
        if (!completeBtn) return;

        const isOnline = window.StationCommon && window.StationCommon.isOnline ? window.StationCommon.isOnline() : true;

        if (!isOnline) {
            completeBtn.disabled = true;
            completeBtn.textContent = 'Jesteś offline';
            completeBtn.classList.add('offline');
            return;
        }

        completeBtn.classList.remove('offline');
        completeBtn.textContent = 'ZAKOŃCZ WYKAŃCZANIE';

        const productRows = card.querySelectorAll('.product-row');
        let allComplete = true;
        let hasProducts = false;

        productRows.forEach(row => {
            hasProducts = true;
            const qtyDone = parseInt(row.dataset.quantityDone) || 0;
            const qtyTotal = parseInt(row.dataset.quantity) || 0;
            if (qtyDone < qtyTotal) allComplete = false;
        });

        completeBtn.disabled = !(allComplete && hasProducts);
    }

    function handleCompleteClick(card, orderNumber) {
        if (!window.StationCommon.isOnline()) {
            showToast('warning', 'Brak połączenia - nie możesz zakończyć zamówienia');
            return;
        }

        const productIds = [];
        card.querySelectorAll('.product-row').forEach(row => {
            productIds.push(row.dataset.productId);
        });

        if (productIds.length === 0) {
            showToast('warning', 'Brak produktów w zamówieniu');
            return;
        }

        card.dataset.inProgress = 'true';
        card.classList.add('processing');

        startCountdown(card, orderNumber, productIds);
    }

    function startCountdown(card, orderNumber, productIds) {
        const actionContainer = card.querySelector('.order-action');
        if (!actionContainer) return;

        actionContainer.innerHTML = `
            <div class="action-countdown">
                <button class="btn-complete processing">
                    <span class="spinner"></span>
                    <span class="countdown-text">Zapisuje... 10s</span>
                </button>
                <button class="btn-cancel">ANULUJ</button>
            </div>
        `;

        const countdownText = actionContainer.querySelector('.countdown-text');
        const cancelBtn = actionContainer.querySelector('.btn-cancel');

        let secondsLeft = 10;

        const timerId = setInterval(() => {
            secondsLeft--;
            if (secondsLeft > 0) {
                countdownText.textContent = `Zapisuje... ${secondsLeft}s`;
            } else {
                clearInterval(timerId);
                state.activeCountdowns.delete(orderNumber);
                completeOrder(card, orderNumber, productIds);
            }
        }, 1000);

        state.activeCountdowns.set(orderNumber, { timerId, secondsLeft });

        cancelBtn.addEventListener('click', function(event) {
            event.preventDefault();
            cancelCountdown(card, orderNumber, timerId);
        });
    }

    function cancelCountdown(card, orderNumber, timerId) {
        if (timerId) {
            clearInterval(timerId);
            state.activeCountdowns.delete(orderNumber);
        }

        card.dataset.inProgress = 'false';
        card.classList.remove('processing');

        const actionContainer = card.querySelector('.order-action');
        if (actionContainer) {
            actionContainer.innerHTML = '<button class="btn-complete" data-action="complete" disabled>ZAKOŃCZ WYKAŃCZANIE</button>';
            const completeBtn = actionContainer.querySelector('.btn-complete');
            if (completeBtn) {
                completeBtn.addEventListener('click', function() {
                    handleCompleteClick(card, orderNumber);
                });
                updateCompleteButtonState(card);
            }
        }

        showToast('info', 'Anulowano wykończenie zamówienia');
    }

    async function completeOrder(card, orderNumber, productIds) {
        const cardBackup = card.cloneNode(true);

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
            const timeoutId = setTimeout(() => controller.abort(), 10000);

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
            console.log('[Finishing] Order completed:', result);

            if (actionContainer) {
                actionContainer.innerHTML = '<button class="btn-complete success">Zapisano</button>';
            }

            showToast('success', `Zamówienie ${orderNumber} ukończone`);
            fetchTodayM3();

            setTimeout(() => {
                card.classList.add('removing');
                setTimeout(() => {
                    card.remove();
                    updateStatsAfterRemoval();
                }, 300);
            }, 1000);

        } catch (error) {
            console.error('[Finishing] Failed to complete order:', error);

            const ordersList = document.getElementById('orders-list');
            if (ordersList) {
                ordersList.insertBefore(cardBackup, ordersList.firstChild);
                initializeOrderCard(cardBackup);
            }

            showToast('error', `Błąd ukończenia: ${error.message}`);
        }
    }

    function updateStatsAfterRemoval() {
        const remainingCards = document.querySelectorAll('.order-card').length;
        if (remainingCards === 0) showEmptyState();
        updateHeaderStats();
    }

    function updateHeaderStats() {
        const allCards = document.querySelectorAll('.order-card');
        let totalProducts = 0;
        let totalVolume = 0;

        allCards.forEach(card => {
            totalProducts += parseInt(card.dataset.totalProducts) || 0;
            totalVolume += parseFloat(card.dataset.totalVolume) || 0;
        });

        const totalProductsElement = document.getElementById('total-products');
        const totalVolumeElement = document.getElementById('total-volume');

        if (totalProductsElement) totalProductsElement.textContent = totalProducts;
        if (totalVolumeElement) totalVolumeElement.textContent = totalVolume.toFixed(4);
    }

    function showEmptyState() {
        const ordersList = document.getElementById('orders-list');
        if (!ordersList) return;

        ordersList.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">✅</div>
                <h2>Brak zamówień do wykańczania</h2>
                <p>Świetna robota! Wszystkie zamówienia zostały wykończone.</p>
            </div>
        `;
    }

    function showToast(type, message) {
        const prefix = type === 'success' ? '✅' : type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️';
        console.log(`[Finishing] ${prefix} ${message}`);
    }

    function startAutoRefresh(intervalSeconds) {
        if (state.refreshTimer) clearInterval(state.refreshTimer);
        state.refreshTimer = setInterval(performAutoRefresh, intervalSeconds * 1000);
    }

    async function performAutoRefresh() {
        try {
            const response = await fetch('/production/stations/ajax/orders/finishing?sort=priority');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const result = await response.json();
            if (!result.success || !result.data || !result.data.orders) throw new Error('Invalid response');

            smartMergeOrders(result.data.orders);
            updateHeaderStatsFromAPI(result.data.orders);
            fetchTodayM3();
        } catch (error) {
            console.error('[Finishing] Auto-refresh failed:', error);
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

        if (totalOrdersElement) totalOrdersElement.textContent = totalOrders;
        if (totalVolumeElement) totalVolumeElement.textContent = totalVolume.toFixed(4);
    }

    function smartMergeOrders(newOrders) {
        const ordersList = document.getElementById('orders-list');
        if (!ordersList) return;

        const existingCards = ordersList.querySelectorAll('.order-card');
        const existingOrderNumbers = new Set();
        existingCards.forEach(card => existingOrderNumbers.add(card.dataset.orderNumber));

        const apiOrderNumbers = new Set(newOrders.map(o => o.order_number));

        newOrders.forEach(order => {
            if (!existingOrderNumbers.has(order.order_number)) {
                addOrderCard(order);
            } else {
                updateExistingOrderCard(order);
            }
        });

        existingCards.forEach(card => {
            const orderNumber = card.dataset.orderNumber;
            if (!apiOrderNumbers.has(orderNumber)) {
                const hasActiveCountdown = state.activeCountdowns.has(orderNumber);
                const isProcessing = card.classList.contains('processing');

                if (!hasActiveCountdown && !isProcessing) {
                    card.classList.add('removing');
                    setTimeout(() => {
                        card.remove();
                        checkAndShowEmptyState();
                    }, 300);
                }
            }
        });
    }

    function updateExistingOrderCard(orderData) {
        const card = document.querySelector(`[data-order-number="${orderData.order_number}"]`);
        if (!card || card.dataset.inProgress === 'true') return;

        orderData.products.forEach(product => {
            const productRow = card.querySelector(`[data-product-id="${product.id}"]`);
            if (productRow) {
                const currentQtyDone = parseInt(productRow.dataset.quantityDone) || 0;
                const serverQtyDone = product.quantity_done || 0;

                if (currentQtyDone !== serverQtyDone && !state.pendingRequests.has(product.id)) {
                    productRow.dataset.quantityDone = serverQtyDone;
                    const qtyDoneEl = productRow.querySelector('.qty-done');
                    if (qtyDoneEl) qtyDoneEl.textContent = serverQtyDone;
                    updateProductButtonStates(productRow, serverQtyDone, product.quantity);
                }
            }
        });

        updateOrderCounter(card);
        updateCompleteButtonState(card);
    }

    function checkAndShowEmptyState() {
        const ordersList = document.getElementById('orders-list');
        if (!ordersList) return;

        const remainingCards = ordersList.querySelectorAll('.order-card:not(.removing)');
        if (remainingCards.length === 0) {
            const emptyState = ordersList.querySelector('.empty-state');
            if (!emptyState) showEmptyState();
        }
    }

    function addOrderCard(orderData) {
        const ordersList = document.getElementById('orders-list');
        if (!ordersList) return;

        const emptyState = ordersList.querySelector('.empty-state');
        if (emptyState) emptyState.remove();

        const cardHTML = createOrderCardHTML(orderData);
        ordersList.insertAdjacentHTML('afterbegin', cardHTML);

        const newCard = ordersList.querySelector(`[data-order-number="${orderData.order_number}"]`);
        if (newCard) {
            initializeOrderCard(newCard);
            if (typeof window.reinitializeAttachmentHandlers === 'function') {
                window.reinitializeAttachmentHandlers();
            }
        }
    }

    function createOrderCardHTML(order) {
        const productsHTML = order.products.map(product => {
            const quantity = product.quantity || 1;
            const quantityDone = product.quantity_done || 0;
            const hasLargeQty = quantity >= 10;

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

            const paramsHTML = `
                ${product.wood_species ? `<span class="badge badge-species">${product.wood_species}</span>` : ''}
                ${product.technology ? `<span class="badge badge-technology">${product.technology}</span>` : ''}
                ${product.wood_class ? `<span class="badge badge-class">${product.wood_class}</span>` : ''}
            `;

            let dimensionsRowHTML = '';
            if (product.dimensions) {
                dimensionsRowHTML = `<div class="product-dimensions">${product.dimensions.replace(/x/g, ' x ').replace(/×/g, ' × ')}</div>`;
            } else if (product.original_name) {
                dimensionsRowHTML = `<div class="product-dimensions product-name-label">${product.original_name}</div>`;
            } else if (product.attachment_file_url) {
                dimensionsRowHTML = `<div class="product-dimensions product-attachment-label">Zgodnie z załącznikiem</div>`;
            }

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

            return `
                <div class="product-row ${completeClass}"
                     data-product-id="${product.id}"
                     data-quantity="${quantity}"
                     data-quantity-done="${quantityDone}"
                     data-status="${product.current_status}"
                     data-species="${product.wood_species || ''}"
                     data-technology="${product.technology || ''}"
                     data-wood-class="${product.wood_class || ''}">
                    <div class="product-left-col">
                        <div class="product-id-line"><span class="product-id">${product.id}</span></div>
                        <div class="product-params">${paramsHTML}</div>
                        <div class="product-dimensions-row">${attachmentHTML}${dimensionsRowHTML}</div>
                    </div>
                    <div class="quantity-controls">
                        <div class="quantity-counter">
                            <span class="qty-done">${quantityDone}</span>
                            <span class="qty-separator">/</span>
                            <span class="qty-total">${quantity}</span>
                        </div>
                        <div class="quantity-buttons${gridClass}">${quantityButtonsHTML}</div>
                    </div>
                </div>
            `;
        }).join('');

        const blBadge = order.baselinker_order_id ? `<span class="order-baselinker">BL-${order.baselinker_order_id}</span>` : '';

        let totalDone = 0;
        let totalQty = 0;
        order.products.forEach(p => {
            totalDone += (p.quantity_done || 0);
            totalQty += (p.quantity || 1);
        });

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
                        <span class="products-checked" data-order="${order.order_number}">${totalDone}</span>/${totalQty} szt. • ${order.total_volume.toFixed(4)} m³
                    </div>
                </div>
                <div class="products-list">${productsHTML}</div>
                <div class="order-action">
                    <button class="btn-complete" data-action="complete" disabled>ZAKOŃCZ WYKAŃCZANIE</button>
                </div>
            </div>
        `;
    }

    async function fetchTodayM3() {
        try {
            const response = await fetch('/production/stations/ajax/station-today-m3/finishing');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const result = await response.json();
            if (result.success && result.data) {
                const todayM3Element = document.getElementById('today-m3');
                if (todayM3Element) todayM3Element.textContent = result.data.today_m3.toFixed(4);
            }
        } catch (error) {
            console.error('[Finishing] Failed to fetch today m³:', error);
        }
    }

    function setupThemeToggle() {
        const themeToggle = document.getElementById('theme-toggle');
        if (!themeToggle) return;

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

        const savedTheme = localStorage.getItem('theme');
        if (savedTheme === 'light') themeToggle.click();
    }

    window.addEventListener('beforeunload', function() {
        if (state.refreshTimer) clearInterval(state.refreshTimer);
        if (state.countdownTimer) clearInterval(state.countdownTimer);
        state.activeCountdowns.forEach(c => { if (c.timerId) clearInterval(c.timerId); });
        state.pendingRequests.forEach(t => clearTimeout(t));
    });

    console.log('[Finishing] Module loaded v3.0');
})();
