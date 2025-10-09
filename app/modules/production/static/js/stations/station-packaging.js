// station-packaging.js - Dedykowana logika dla stanowiska pakowania
// Wersja 2.0 - Na bazie cutting/assembly z logiką checkboxów

/**
 * LocalStorage key prefix for checkbox states
 */
const STORAGE_PREFIX = 'packaging_order_';

/**
 * Initialize Packaging Station
 */
function initPackagingStation() {
    console.log('[Packaging] Initializing station v2.0...');

    // Load config
    const config = window.StationCommon.loadStationConfig();

    if (!config) {
        console.error('[Packaging] Failed to load config');
        window.StationCommon.showError('Błąd konfiguracji stanowiska');
        return;
    }

    // Attach event listeners to existing order cards
    const existingCards = document.querySelectorAll('.order-card');
    console.log(`[Packaging] Found ${existingCards.length} existing cards`);

    existingCards.forEach(card => {
        attachOrderCardListeners(card);
    });

    // Start auto-refresh
    if (config.autoRefreshEnabled) {
        window.StationCommon.startAutoRefresh(autoRefreshCallback);
        console.log(`[Packaging] Auto-refresh started (${config.refreshInterval}s)`);
    }

    // Initialize Connection Monitor
    window.StationCommon.initConnectionMonitor();

    // Register connection change handler
    window.StationCommon.onConnectionChange((isOnline) => {
        handleConnectionChange(isOnline);
    });

    // Fetch today's m3
    window.StationCommon.fetchTodayM3('packaging').catch(err => {
        console.error('[Packaging] Failed to load today m3:', err);
    });

    // Setup keyboard shortcuts
    setupKeyboardShortcuts();

    // Theme toggle
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
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

    console.log('[Packaging] Station initialized successfully');
}

/**
 * Auto-refresh callback
 */
async function autoRefreshCallback() {
    if (window.STATION_STATE.isRefreshing) {
        console.log('[Packaging] Refresh already in progress, skipping');
        return;
    }

    if (!window.StationCommon.isOnline()) {
        console.warn('[Packaging] Offline - skipping refresh');
        window.StationCommon.showWarning('Brak połączenia - pominięto odświeżanie');
        return;
    }

    window.STATION_STATE.isRefreshing = true;

    try {
        const stationCode = window.STATION_STATE.config.stationCode;
        console.log(`[Packaging] Fetching orders for station: ${stationCode}`);

        // Note: Używamy tego samego endpointa co inne stanowiska
        // Backend zwraca orders_grouped dla packaging
        const data = await window.StationCommon.fetchProducts(stationCode, 'priority');

        if (!data || !data.orders) {
            throw new Error('Invalid response data');
        }

        console.log(`[Packaging] Received ${data.orders.length} orders`);

        // Smart merge orders
        smartMergeOrders(data.orders);

        // Update stats
        if (data.stats) {
            window.StationCommon.updateStatsBar(data.stats);
        }

        // Refresh today m3
        window.StationCommon.fetchTodayM3('packaging').catch(err => {
            console.error('[Packaging] Failed to refresh today m3:', err);
        });

        console.log('[Packaging] Auto-refresh completed successfully');
    } catch (error) {
        console.error('[Packaging] Auto-refresh failed:', error);
        window.StationCommon.showError(`Błąd odświeżania: ${error.message}`);
    } finally {
        window.STATION_STATE.isRefreshing = false;

        if (typeof window.StationCommon.startRefreshCountdown === 'function') {
            window.StationCommon.startRefreshCountdown();
        }
    }
}

/**
 * Smart merge orders - add new, update existing, preserve in-progress
 */
function smartMergeOrders(newOrders) {
    const ordersList = document.getElementById('orders-list');

    if (!ordersList) {
        console.warn('[Packaging] Orders list not found in DOM');
        return;
    }

    const existingCards = Array.from(ordersList.querySelectorAll('.order-card'));
    const existingOrderNumbers = existingCards.map(card => card.dataset.orderNumber);

    console.log(`[Packaging] Smart merge: ${existingCards.length} existing, ${newOrders.length} new`);

    // Hide empty state if adding orders
    const emptyState = ordersList.querySelector('.empty-state');
    if (newOrders.length > 0 && emptyState) {
        emptyState.style.display = 'none';
    }

    // Find NEW orders
    const toAdd = newOrders.filter(order => !existingOrderNumbers.includes(order.order_number));

    // Add new order cards
    toAdd.forEach(order => {
        const cardHTML = createOrderCard(order);
        ordersList.insertAdjacentHTML('beforeend', cardHTML);

        const newCard = ordersList.querySelector(`[data-order-number="${order.order_number}"]`);
        if (newCard) {
            attachOrderCardListeners(newCard);
            console.log(`[Packaging] Added new order: ${order.order_number}`);
        }
    });

    // Update existing orders (skip in-progress)
    newOrders.forEach(newOrder => {
        const existingCard = ordersList.querySelector(`[data-order-number="${newOrder.order_number}"]`);

        if (!existingCard || existingCard.dataset.inProgress === 'true') {
            return;
        }

        // Update products and priority if needed
        updateOrderProducts(existingCard, newOrder);
    });

    // Remove orders that no longer exist
    const newOrderNumbers = newOrders.map(o => o.order_number);
    existingCards.forEach(card => {
        if (card.dataset.inProgress !== 'true' && !newOrderNumbers.includes(card.dataset.orderNumber)) {
            console.log(`[Packaging] Removing order: ${card.dataset.orderNumber}`);
            card.classList.add('removing');
            setTimeout(() => card.remove(), 300);
        }
    });

    // Show empty state if no orders
    if (newOrders.length === 0 && !emptyState) {
        ordersList.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">✅</div>
                <h2>Brak zamówień do spakowania</h2>
                <p>Świetna robota! Wszystkie zamówienia zostały spakowane.</p>
            </div>
        `;
    }

    if (toAdd.length > 0) {
        window.StationCommon.showInfo(`Dodano ${toAdd.length} ${toAdd.length === 1 ? 'nowe zamówienie' : 'nowych zamówień'}`);
    }
}

/**
 * Create HTML for order card
 */
function createOrderCard(order) {
    // SORTUJ PRODUKTY PO ID (od najmniejszej do największej)
    const sortedProducts = [...order.products].sort((a, b) => {
        const idA = a.id || '';
        const idB = b.id || '';
        return idA.localeCompare(idB, undefined, { numeric: true });
    });

    const productsHTML = sortedProducts.map(product => {
        const isNotReady = product.current_status !== 'czeka_na_pakowanie';
        const disabledAttr = isNotReady ? 'disabled' : '';
        const notReadyClass = isNotReady ? 'product-not-ready' : '';

        // Escape HTML
        const escapeHtml = (str) => {
            if (!str) return '';
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        };

        // Badges HTML
        const speciesBadge = product.wood_species
            ? `<span class="badge badge-species">${escapeHtml(product.wood_species)}</span>`
            : '';
        const techBadge = product.technology
            ? `<span class="badge badge-technology">${escapeHtml(product.technology)}</span>`
            : '';
        const classBadge = product.wood_class
            ? `<span class="badge badge-class">${escapeHtml(product.wood_class)}</span>`
            : '';
        const dimensionsBadge = product.dimensions
            ? `<span class="badge badge-dimensions">${escapeHtml(product.dimensions)}</span>`
            : '';

        // Data attributes for CSS styling
        const dataSpecies = product.wood_species ? `data-species="${escapeHtml(product.wood_species)}"` : '';
        const dataTechnology = product.technology ? `data-technology="${escapeHtml(product.technology)}"` : '';
        const dataWoodClass = product.wood_class ? `data-wood-class="${escapeHtml(product.wood_class)}"` : '';

        return `
            <div class="product-row ${notReadyClass}" 
                 data-product-id="${product.id}"
                 data-status="${product.current_status}"
                 ${dataSpecies}
                 ${dataTechnology}
                 ${dataWoodClass}>
                
                <div class="product-checkbox">
                    <input type="checkbox"
                           class="product-check"
                           id="check-${product.id}"
                           data-product-id="${product.id}"
                           ${disabledAttr}>
                    <label for="check-${product.id}"></label>
                </div>

                <span class="product-id">${product.id}</span>

                <div class="product-details">
                    <div class="product-badges">
                        ${speciesBadge}
                        ${techBadge}
                        ${classBadge}
                        ${dimensionsBadge}
                    </div>
                    
                    <span class="product-name">${escapeHtml(product.original_name || 'Brak nazwy')}</span>
                </div>
                
                <span class="product-volume">${product.volume_m3.toFixed(4)} m³</span>
            </div>
        `;
    }).join('');

    // Policz zaznaczone checkboxy (dla nowych kart zawsze 0)
    const checkedCount = 0;

    return `
        <div class="order-card"
             data-order-number="${order.order_number}"
             data-priority-rank="${order.best_priority_rank}"
             data-total-products="${order.total_products}"
             data-in-progress="false">

            <div class="order-header">
                <div class="order-title">
                    <span class="order-number">${order.order_number}</span>
                    ${order.baselinker_order_id ? `<span class="order-baselinker">BL-${order.baselinker_order_id}</span>` : ''}
                </div>
                <div class="order-summary">
                    <span class="deadline-info">📅 ${order.display_deadline}</span>
                    <span class="summary-stats">
                        <span class="products-checked" data-order="${order.order_number}">${checkedCount}</span>/${order.total_products} ${order.total_products === 1 ? 'produkt' : order.total_products < 5 ? 'produkty' : 'produktów'} • ${order.total_volume.toFixed(4)} m³
                    </span>
                </div>
            </div>

            <div class="products-list">
                ${productsHTML}
            </div>

            <div class="order-action">
                <button class="btn-complete" data-action="package" disabled>SPAKOWANE</button>
            </div>
        </div>
    `;
}

/**
 * Update products in existing order card
 */
function updateOrderProducts(card, order) {
    const productsList = card.querySelector('.products-list');
    if (!productsList) return;

    order.products.forEach(newProduct => {
        const existingRow = productsList.querySelector(`[data-product-id="${newProduct.id}"]`);

        if (existingRow) {
            const checkbox = existingRow.querySelector('.product-check');
            if (checkbox && newProduct.current_status !== 'czeka_na_pakowanie') {
                existingRow.classList.add('product-not-ready');
                checkbox.setAttribute('disabled', 'disabled');
                checkbox.disabled = true;
                checkbox.checked = false;
            }
        }
    });

    // Recalculate button state
    const checkboxes = card.querySelectorAll('.product-check');
    const packageBtn = card.querySelector('.btn-complete');
    if (packageBtn) {
        updatePackageButtonState(card, checkboxes, packageBtn);
    }
}

/**
 * Attach event listeners to order card
 */
function attachOrderCardListeners(card) {
    if (!card) {
        console.warn('[Packaging] Cannot attach listeners to null card');
        return;
    }

    const orderNumber = card.dataset.orderNumber;
    console.log(`[Packaging] Attaching listeners to order: ${orderNumber}`);

    const checkboxes = card.querySelectorAll('.product-check');
    const packageBtn = card.querySelector('.btn-complete');

    if (!packageBtn) {
        console.warn(`[Packaging] No package button found for ${orderNumber}`);
        return;
    }

    // Load saved checkbox states FIRST
    loadCheckboxStates(card, orderNumber);

    // Checkbox change listeners
    checkboxes.forEach(checkbox => {
        checkbox.addEventListener('change', function () {
            console.log(`[Packaging] Checkbox changed: ${this.dataset.productId}, checked: ${this.checked}`);

            saveCheckboxState(orderNumber, this.dataset.productId, this.checked);
            updatePackageButtonState(card, checkboxes, packageBtn);
            updateCheckedCount(card, checkboxes, orderNumber); // ✅ DODANE
        });
    });

    // Package button listener
    packageBtn.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();

        if (this.disabled) {
            console.log('[Packaging] Button disabled, ignoring click');
            return;
        }

        handlePackageClick(card, orderNumber);
    });

    packageBtn.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            if (!this.disabled) {
                handlePackageClick(card, orderNumber);
            }
        }
    });

    // Update button state AFTER loading checkboxes
    updatePackageButtonState(card, checkboxes, packageBtn);
    updateCheckedCount(card, checkboxes, orderNumber); // ✅ DODANE - aktualizuj licznik po załadowaniu

    console.log(`[Packaging] Listeners attached and button state updated for ${orderNumber}`);
}

/**
 * Load checkbox states from localStorage
 */
function loadCheckboxStates(card, orderNumber) {
    const storageKey = STORAGE_PREFIX + orderNumber;
    const savedStates = JSON.parse(localStorage.getItem(storageKey) || '{}');

    console.log(`[Packaging] Loading checkbox states for ${orderNumber}:`, savedStates);

    Object.keys(savedStates).forEach(productId => {
        const checkbox = card.querySelector(`.product-check[data-product-id="${productId}"]`);
        if (checkbox && !checkbox.disabled) {
            checkbox.checked = savedStates[productId];
            console.log(`[Packaging] Restored checkbox ${productId}: ${savedStates[productId]}`);
        }
    });
}

/**
 * Save checkbox state to localStorage
 */
function saveCheckboxState(orderNumber, productId, checked) {
    const storageKey = STORAGE_PREFIX + orderNumber;
    const savedStates = JSON.parse(localStorage.getItem(storageKey) || '{}');

    savedStates[productId] = checked;
    localStorage.setItem(storageKey, JSON.stringify(savedStates));
}

/**
 * Update package button state based on checkboxes
 */
function updatePackageButtonState(card, checkboxes, packageBtn) {
    const enabledCheckboxes = Array.from(checkboxes).filter(cb => !cb.disabled);
    const hasNotReady = Array.from(checkboxes).some(cb => cb.disabled);
    const allEnabledChecked = enabledCheckboxes.length > 0 && enabledCheckboxes.every(cb => cb.checked);

    const shouldEnable = !hasNotReady && allEnabledChecked;

    if (shouldEnable) {
        packageBtn.removeAttribute('disabled');
        packageBtn.disabled = false;
    } else {
        packageBtn.setAttribute('disabled', 'disabled');
        packageBtn.disabled = true;
    }

    console.log(`[Packaging] Button state: hasNotReady=${hasNotReady}, allChecked=${allEnabledChecked}, enabled=${shouldEnable}`);
}

/**
 * Update checked count display (Y/X produktów)
 */
function updateCheckedCount(card, checkboxes, orderNumber) {
    const checkedCount = Array.from(checkboxes).filter(cb => cb.checked && !cb.disabled).length;
    const counterElement = card.querySelector(`.products-checked[data-order="${orderNumber}"]`);

    if (counterElement) {
        counterElement.textContent = checkedCount;
        console.log(`[Packaging] Updated checked count for ${orderNumber}: ${checkedCount}`);
    }
}

/**
 * Handle package button click
 */
function handlePackageClick(card, orderNumber) {
    console.log(`[Packaging] Package clicked: ${orderNumber}`);

    // Check if online
    if (!window.StationCommon.isOnline()) {
        console.warn('[Packaging] Cannot package - offline');
        window.StationCommon.showWarning('Brak połączenia - poczekaj na powrót internetu');
        return;
    }

    if (card.dataset.inProgress === 'true') {
        console.warn(`[Packaging] Order already in progress: ${orderNumber}`);
        return;
    }

    if (!card || !card.parentElement) {
        console.error(`[Packaging] Invalid card state: ${orderNumber}`);
        return;
    }

    card.dataset.inProgress = 'true';
    card.classList.add('processing');

    startPackageCountdown(card, orderNumber);
}

/**
 * Start 10-second countdown before packaging
 */
function startPackageCountdown(card, orderNumber) {
    const packageBtn = card.querySelector('.btn-complete');
    const actionContainer = card.querySelector('.order-action');

    if (!packageBtn || !actionContainer) {
        console.error(`[Packaging] Missing button/container for ${orderNumber}`);
        return;
    }

    // Change button to processing state
    setButtonProcessing(packageBtn);

    // Create countdown container
    const countdownHTML = document.createElement('div');
    countdownHTML.className = 'action-countdown';
    countdownHTML.innerHTML = `
        <button class="btn-complete processing">
            <span class="spinner"></span>
            <span>PAKOWANIE... 10s</span>
        </button>
        <button class="btn-cancel" data-action="cancel">ANULUJ</button>
    `;

    // Replace button with countdown
    actionContainer.innerHTML = '';
    actionContainer.appendChild(countdownHTML);

    const processingBtn = countdownHTML.querySelector('.btn-complete');
    const cancelBtn = countdownHTML.querySelector('.btn-cancel');

    let secondsLeft = 10;
    let timerId = null;

    const updateCountdown = () => {
        if (!processingBtn || !processingBtn.parentElement) {
            console.warn(`[Packaging] Button removed during countdown: ${orderNumber}`);
            if (timerId) clearInterval(timerId);
            return;
        }

        const textSpan = processingBtn.querySelector('span:last-child');
        if (textSpan) {
            textSpan.textContent = `PAKOWANIE... ${secondsLeft}s`;
        }
    };

    timerId = setInterval(() => {
        secondsLeft--;

        if (secondsLeft > 0) {
            updateCountdown();
        } else {
            clearInterval(timerId);
            window.STATION_STATE.countdownTimers.delete(orderNumber);
            onCountdownComplete(card, orderNumber);
        }
    }, 1000);

    window.STATION_STATE.countdownTimers.set(orderNumber, timerId);

    // Cancel button listener
    const cancelHandler = (event) => {
        event.preventDefault();
        event.stopPropagation();
        console.log(`[Packaging] Cancel clicked for ${orderNumber}`);
        cancelCountdown(card, orderNumber, timerId);
    };

    cancelBtn.addEventListener('click', cancelHandler);
    cancelBtn.addEventListener('touchstart', cancelHandler, { passive: false });

    cancelBtn.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            cancelCountdown(card, orderNumber, timerId);
        }
    });

    console.log(`[Packaging] Countdown started for ${orderNumber} (10s)`);
}

/**
 * Cancel countdown and reset card
 */
function cancelCountdown(card, orderNumber, timerId) {
    console.log(`[Packaging] Countdown cancelled: ${orderNumber}`);

    if (timerId) {
        clearInterval(timerId);
        window.STATION_STATE.countdownTimers.delete(orderNumber);
    }

    if (!card || !card.parentElement) {
        console.warn(`[Packaging] Card no longer exists: ${orderNumber}`);
        return;
    }

    card.dataset.inProgress = 'false';
    card.classList.remove('processing');

    const actionContainer = card.querySelector('.order-action');
    if (actionContainer) {
        actionContainer.innerHTML = '<button class="btn-complete" data-action="package">SPAKOWANE</button>';

        const newPackageBtn = actionContainer.querySelector('.btn-complete');
        if (newPackageBtn) {
            if (!window.StationCommon.isOnline()) {
                newPackageBtn.classList.add('disabled-offline');
                newPackageBtn.disabled = true;
            }

            // Re-attach listeners
            attachOrderCardListeners(card);
        }
    }

    window.StationCommon.showInfo('Anulowano pakowanie zamówienia');
}

/**
 * Execute packaging after countdown
 */
async function onCountdownComplete(card, orderNumber) {
    console.log(`[Packaging] Completing packaging: ${orderNumber}`);

    const actionContainer = card.querySelector('.order-action');

    if (!card || !card.parentElement) {
        console.error(`[Packaging] Card removed during countdown: ${orderNumber}`);
        return;
    }

    // Get checked products and total volume BEFORE removing card
    const checkboxes = card.querySelectorAll('.product-check:checked:not(:disabled)');
    const completedProducts = Array.from(checkboxes).map(cb => cb.dataset.productId);

    let totalVolume = 0;
    const productRows = card.querySelectorAll('.product-row');
    productRows.forEach(row => {
        const volumeText = row.querySelector('.product-volume').textContent;
        const match = volumeText.match(/[\d.]+/);
        if (match) {
            totalVolume += parseFloat(match[0]);
        }
    });

    try {
        if (actionContainer) {
            actionContainer.innerHTML = `
                <button class="btn-complete processing">
                    <span class="spinner"></span>
                    <span>ZAPISYWANIE...</span>
                </button>
            `;
        }

        // Call API
        const response = await completePackaging(orderNumber, completedProducts);

        console.log(`[Packaging] Order completed successfully: ${orderNumber}`, response);

        // Increment today m3
        if (totalVolume > 0) {
            window.StationCommon.incrementTodayM3(totalVolume);
        }

        // Show success state
        if (actionContainer) {
            actionContainer.innerHTML = '<button class="btn-complete success">SPAKOWANO ✓</button>';
        }

        window.StationCommon.showSuccess(`Zamówienie ${orderNumber} spakowane`);

        // Clear localStorage
        const storageKey = STORAGE_PREFIX + orderNumber;
        localStorage.removeItem(storageKey);

        // Wait 1 second, then remove card
        setTimeout(() => {
            if (card && card.parentElement) {
                card.classList.add('removing');
                setTimeout(() => {
                    card.remove();
                    console.log(`[Packaging] Removed card: ${orderNumber}`);

                    updateStatsAfterCompletion();

                    const remainingCards = document.querySelectorAll('.order-card');
                    if (remainingCards.length === 0) {
                        console.log('[Packaging] No more orders - showing empty state');
                        const ordersList = document.getElementById('orders-list');
                        if (ordersList) {
                            ordersList.innerHTML = `
                                <div class="empty-state">
                                    <div class="empty-state-icon">✅</div>
                                    <h2>Brak zamówień do spakowania</h2>
                                    <p>Świetna robota! Wszystkie zamówienia zostały spakowane.</p>
                                </div>
                            `;
                        }
                    }
                }, 300);
            }
        }, 1000);

    } catch (error) {
        console.error(`[Packaging] Failed to complete order: ${orderNumber}`, error);
        window.StationCommon.showError(`Nie udało się spakować: ${error.message}`);

        if (card && card.parentElement) {
            card.dataset.inProgress = 'false';
            card.classList.remove('processing');

            if (actionContainer) {
                actionContainer.innerHTML = '<button class="btn-complete" data-action="package">SPAKOWANE</button>';
                attachOrderCardListeners(card);
            }
        }
    }
}

/**
 * API call to complete packaging
 */
async function completePackaging(orderNumber, productIds) {
    // Note: Ten endpoint musi być w station_routers.py lub api_routers.py
    const response = await fetch('/production/api/complete-packaging', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            internal_order_number: orderNumber,  // ✅ POPRAWKA: backend wymaga 'internal_order_number'
            product_ids: productIds
        })
    });

    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
    }

    return await response.json();
}

/**
 * Update stats bar
 */
function updateStatsBar(stats) {
    const elements = {
        'total-orders': stats.total_orders || 0,
        'high-priority': stats.high_priority_count || 0,
        'overdue-count': stats.overdue_count || 0
    };

    Object.keys(elements).forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = elements[id];
        }
    });
}

/**
 * Update stats after completion
 */
function updateStatsAfterCompletion() {
    const totalElement = document.getElementById('total-products');
    if (totalElement) {
        const current = parseInt(totalElement.textContent) || 0;
        if (current > 0) {
            totalElement.textContent = current - 1;
        }
    }

    const volumeElement = document.getElementById('total-volume');
    if (volumeElement) {
        const cards = document.querySelectorAll('.order-card');
        let totalVolume = 0;

        cards.forEach(card => {
            const summaryStats = card.querySelector('.summary-stats');
            if (summaryStats) {
                const match = summaryStats.textContent.match(/[\d.]+(?= m³)/);
                if (match) {
                    totalVolume += parseFloat(match[0]);
                }
            }
        });

        volumeElement.textContent = totalVolume.toFixed(4);
    }
}

/**
 * Set button to processing state
 */
function setButtonProcessing(button) {
    if (!button) return;
    button.classList.add('processing');
    button.classList.remove('success');
    button.disabled = true;
}

/**
 * Handle connection state changes
 */
function handleConnectionChange(isOnline) {
    console.log(`[Packaging] Connection changed: ${isOnline ? 'ONLINE' : 'OFFLINE'}`);

    const completeButtons = document.querySelectorAll('.btn-complete');
    const refreshCountdownElement = document.getElementById('refresh-countdown');

    if (isOnline) {
        completeButtons.forEach(btn => {
            btn.classList.remove('disabled-offline');
            // Re-evaluate if button should be enabled based on checkboxes
            const card = btn.closest('.order-card');
            if (card) {
                const checkboxes = card.querySelectorAll('.product-check');
                updatePackageButtonState(card, checkboxes, btn);
            }
        });
        console.log('[Packaging] All buttons re-evaluated');

        if (window.STATION_STATE.countdownTimer) {
            console.log('[Packaging] Refresh countdown already running');
        } else {
            console.log('[Packaging] Restarting refresh countdown');
            window.StationCommon.startRefreshCountdown();
        }

        if (refreshCountdownElement) {
            refreshCountdownElement.classList.remove('warning');
        }

    } else {
        completeButtons.forEach(btn => {
            btn.classList.add('disabled-offline');
            btn.disabled = true;
        });

        const activeTimers = window.STATION_STATE.countdownTimers;
        if (activeTimers.size > 0) {
            console.log(`[Packaging] Cancelling ${activeTimers.size} active countdowns due to offline`);
            activeTimers.forEach((timerId, orderNumber) => {
                const card = document.querySelector(`[data-order-number="${orderNumber}"]`);
                if (card) {
                    cancelCountdown(card, orderNumber, timerId);
                }
            });
            window.StationCommon.showWarning('Aktywne zadania anulowane - brak połączenia');
        }

        if (window.STATION_STATE.countdownTimer) {
            clearInterval(window.STATION_STATE.countdownTimer);
            window.STATION_STATE.countdownTimer = null;
            console.log('[Packaging] Refresh countdown stopped');
        }

        if (refreshCountdownElement) {
            refreshCountdownElement.textContent = 'OFFLINE';
            refreshCountdownElement.classList.add('warning');
        }

        console.log('[Packaging] All buttons disabled');
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
                console.log(`[Packaging] Escape pressed - cancelling ${activeTimers.size} countdowns`);
                activeTimers.forEach((timerId, orderNumber) => {
                    const card = document.querySelector(`[data-order-number="${orderNumber}"]`);
                    if (card) {
                        cancelCountdown(card, orderNumber, timerId);
                    }
                });
            }
        }

        // F5 or Ctrl+R - manual refresh
        if (event.key === 'F5' || (event.ctrlKey && event.key === 'r')) {
            console.log('[Packaging] Manual refresh triggered');
        }
    });
}

/**
 * Toggle debug mode
 */
function toggleDebugMode() {
    document.body.classList.toggle('debug-mode');
    console.log('[Packaging] Debug mode toggled');
    console.log('State:', window.STATION_STATE);
    window.StationCommon.showInfo('Debug mode toggled (check console)');
}

/**
 * Initialize on DOM ready
 */
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPackagingStation);
} else {
    initPackagingStation();
}

/**
 * Cleanup on page unload
 */
window.addEventListener('beforeunload', () => {
    console.log('[Packaging] Cleaning up...');
    window.StationCommon.stopAutoRefresh();

    window.STATION_STATE.countdownTimers.forEach((timerId, orderNumber) => {
        clearInterval(timerId);
        console.log(`[Packaging] Cleared timer for ${orderNumber}`);
    });
    window.STATION_STATE.countdownTimers.clear();
});

/**
 * Debug helpers
 */
window.PackagingDebug = {
    getState: () => window.STATION_STATE,
    getConfig: () => window.STATION_STATE.config,
    triggerRefresh: autoRefreshCallback,
    cancelAll: () => {
        window.STATION_STATE.countdownTimers.forEach((timerId, orderNumber) => {
            const card = document.querySelector(`[data-order-number="${orderNumber}"]`);
            if (card) cancelCountdown(card, orderNumber, timerId);
        });
    },
    listOrders: () => {
        const cards = document.querySelectorAll('.order-card');
        console.table(Array.from(cards).map(c => ({
            order: c.dataset.orderNumber,
            priority: c.dataset.priorityRank,
            products: c.dataset.totalProducts,
            inProgress: c.dataset.inProgress
        })));
    },
    getCheckboxStates: (orderNumber) => {
        const key = STORAGE_PREFIX + orderNumber;
        return JSON.parse(localStorage.getItem(key) || '{}');
    }
};

const debugBtn = document.getElementById('debug-toggle');
if (debugBtn) {
    debugBtn.addEventListener('click', toggleDebugMode);
}

console.log('[Packaging] Station module loaded v2.0');
console.log('[Packaging] Debug commands available via window.PackagingDebug');