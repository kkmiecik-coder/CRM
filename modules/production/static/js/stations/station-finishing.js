/**
 * ============================================================================
 * STATION FINISHING - PER-PRODUCT VERSION (Produkcja / Lakiernia)
 * ============================================================================
 *
 * Wersja z flat product cards i per-product completion.
 * Obsługuje zakładki: tab=production (finishing) i tab=painting (lakiernia).
 *
 * @author: Konrad Kmiecik
 * @date: 2025-11
 * @version: 4.0
 */

(function() {
    'use strict';

    const state = {
        config: null,
        refreshTimer: null,
        countdownTimer: null,
        pendingRequests: new Map(),
        lastRequestTime: new Map()
    };

    const RATE_LIMIT_MS = 200;

    document.addEventListener('DOMContentLoaded', function() {
        console.log('[Finishing] Initializing PER-PRODUCT station v4.0...');
        initializeFinishingStation();
    });

    function initializeFinishingStation() {
        const config = window.STATION_CONFIG;

        if (!config || (config.stationCode !== 'finishing' && config.stationCode !== 'painting')) {
            console.error('[Finishing] Invalid station config');
            return;
        }

        state.config = config;
        console.log('[Finishing] Station config loaded:', config);

        const existingCards = document.querySelectorAll('.order-card');
        console.log(`[Finishing] Found ${existingCards.length} product cards`);

        existingCards.forEach(card => {
            initializeProductTile(card);
        });

        fetchTodayM3();

        setInterval(updateCurrentDatetime, 1000);
        updateCurrentDatetime();

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

        // Inicjalizacja ikon powiększenia (fullscreen)
        if (typeof window.initExpandIcons === 'function') {
            window.initExpandIcons();
        }

        // Inicjalizacja przycisku szukania zamówień
        if (typeof window.initOrderSearchButton === 'function') {
            window.initOrderSearchButton();
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

    function startRefreshCountdown(intervalMs) {
        if (state.countdownTimer) clearInterval(state.countdownTimer);

        const intervalSeconds = Math.round(intervalMs / 1000);
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

    // ========================================================================
    // INICJALIZACJA KAFELKA PRODUKTU
    // ========================================================================

    function initializeProductTile(card) {
        const productId = card.dataset.productId;
        if (!productId) return;

        // Ukryj puste sekcje parametrów
        const paramsContainer = card.querySelector('.product-params');
        if (paramsContainer) {
            const badges = paramsContainer.querySelectorAll('.badge');
            if (badges.length === 0) paramsContainer.style.display = 'none';
        }

        // Przyciski ilości
        const quantityButtons = card.querySelectorAll('.btn-qty');
        quantityButtons.forEach(button => {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                handleQuantityButtonClick(card, this);
            });
        });

        // Przycisk zakończenia
        const completeBtn = card.querySelector('.btn-complete');
        if (completeBtn) {
            completeBtn.addEventListener('click', function() {
                completeProduct(card, productId);
            });
        }

        updateCompleteButtonState(card);
    }

    // ========================================================================
    // OBSŁUGA ILOŚCI
    // ========================================================================

    async function handleQuantityButtonClick(card, button) {
        const productId = button.dataset.productId;
        const action = button.dataset.action;

        if (!productId || !action) return;

        const isOnline = window.StationCommon && window.StationCommon.isOnline ? window.StationCommon.isOnline() : true;
        if (!isOnline) {
            showToast('warning', 'Brak połączenia - nie można zapisać zmiany');
            return;
        }

        const qtyDoneEl = card.querySelector('.qty-done');
        const qtyTotalEl = card.querySelector('.qty-total');
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

        // Optimistic update — counter + header
        qtyDoneEl.textContent = newQtyDone;
        syncHeaderQty(card, newQtyDone);
        card.dataset.quantityDone = newQtyDone;

        updateButtonStates(card, newQtyDone, qtyTotal);
        updateCompleteButtonState(card);

        await sendQuantityUpdate(productId, action, card, qtyDone);
    }

    async function sendQuantityUpdate(productId, action, card, previousValue) {
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
                    body: JSON.stringify({
                        product_id: productId,
                        station: state.config.stationCode,
                        action: action
                    })
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || `HTTP ${response.status}`);
                }

                const result = await response.json();
                console.log(`[Finishing] Product ${productId} quantity updated:`, result);

                // Sync z serwerem
                const qtyDoneEl = card.querySelector('.qty-done');
                if (qtyDoneEl && result.quantity_done !== undefined) {
                    qtyDoneEl.textContent = result.quantity_done;
                    syncHeaderQty(card, result.quantity_done);
                    card.dataset.quantityDone = result.quantity_done;
                    updateButtonStates(card, result.quantity_done, result.quantity);
                    updateCompleteButtonState(card);
                }

            } catch (error) {
                console.error('[Finishing] Failed to update quantity:', error);
                // Rollback
                const qtyDoneEl = card.querySelector('.qty-done');
                if (qtyDoneEl) {
                    qtyDoneEl.textContent = previousValue;
                    syncHeaderQty(card, previousValue);
                    card.dataset.quantityDone = previousValue;
                    const qtyTotal = parseInt(card.dataset.quantity) || 0;
                    updateButtonStates(card, previousValue, qtyTotal);
                    updateCompleteButtonState(card);
                }
                showToast('error', `Błąd zapisu: ${error.message}`);
            }
        }, delay);

        state.pendingRequests.set(productId, timeoutId);
    }

    function syncHeaderQty(card, qtyDone) {
        const headerQtyDone = card.querySelector('.header-qty-done');
        if (headerQtyDone) headerQtyDone.textContent = qtyDone;
    }

    function updateButtonStates(card, qtyDone, qtyTotal) {
        const btnMinus = card.querySelector('.btn-minus');
        const btnPlus = card.querySelector('.btn-plus');
        const btnMinus10 = card.querySelector('.btn-minus-10');
        const btnPlus10 = card.querySelector('.btn-plus-10');

        if (btnMinus) btnMinus.disabled = qtyDone <= 0;
        if (btnPlus) btnPlus.disabled = qtyDone >= qtyTotal;
        if (btnMinus10) btnMinus10.disabled = qtyDone < 10;
        if (btnPlus10) btnPlus10.disabled = (qtyTotal - qtyDone) < 10;

        if (qtyDone === qtyTotal) card.classList.add('product-complete');
        else card.classList.remove('product-complete');
    }

    // ========================================================================
    // ZAKOŃCZENIE PRODUKTU
    // ========================================================================

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

        const isPainting = state.config && state.config.stationCode === 'painting';
        completeBtn.textContent = isPainting ? 'ZAKOŃCZ LAKIERNIĘ' : 'ZAKOŃCZ WYKAŃCZANIE';

        const qtyDone = parseInt(card.querySelector('.qty-done')?.textContent) || 0;
        const qtyTotal = parseInt(card.dataset.quantity) || 1;

        completeBtn.disabled = (qtyDone < qtyTotal);
    }

    function completeProduct(card, productId) {
        const isOnline = window.StationCommon && window.StationCommon.isOnline ? window.StationCommon.isOnline() : true;
        if (!isOnline) {
            showToast('warning', 'Brak połączenia - nie możesz zakończyć produktu');
            return;
        }

        // Uruchom odliczanie z opcją anulowania
        startCompletionCountdown(card, productId);
    }

    function startCompletionCountdown(card, productId) {
        const actionContainer = card.querySelector('.order-action');
        if (!actionContainer) return;

        card.classList.add('processing');

        const isPainting = state.config && state.config.stationCode === 'painting';
        const stationLabel = isPainting ? 'lakiernię' : 'wykańczanie';

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
                sendCompleteRequest(card, productId);
            }
        }, 1000);

        cancelBtn.addEventListener('click', function(e) {
            e.preventDefault();
            clearInterval(timerId);
            card.classList.remove('processing');

            const btnLabel = isPainting ? 'ZAKOŃCZ LAKIERNIĘ' : 'ZAKOŃCZ WYKAŃCZANIE';
            actionContainer.innerHTML = `<button class="btn-complete" data-product-id="${productId}" data-action="complete" disabled>${btnLabel}</button>`;

            const completeBtn = actionContainer.querySelector('.btn-complete');
            if (completeBtn) {
                completeBtn.addEventListener('click', function() {
                    completeProduct(card, productId);
                });
                updateCompleteButtonState(card);
            }

            showToast('info', 'Anulowano zakończenie produktu');
        });
    }

    async function sendCompleteRequest(card, productId) {
        console.log(`[Finishing] Wysyłanie completion dla produktu ${productId}`);

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
                    order_number: card.dataset.internalOrder,
                    product_ids: [productId],
                    station: state.config.stationCode,
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
            console.log('[Finishing] Produkt zakończony pomyślnie:', result);

            if (actionContainer) {
                actionContainer.innerHTML = '<button class="btn-complete success">Zapisano</button>';
            }

            showToast('success', `Produkt ${productId} ukończony`);
            fetchTodayM3();

            // Aktualizuj liczniki zakładek
            const nextStatus = result.data ? result.data.next_status : null;
            updateTabCounts(nextStatus);

            // Zamknij fullscreen jeśli aktywny
            if (typeof window.closeFullscreenIfActive === 'function') {
                window.closeFullscreenIfActive(productId);
            }

            // Usuń kafelek z animacją
            setTimeout(() => {
                card.classList.add('removing');
                setTimeout(() => {
                    card.remove();
                    updateStatsAfterRemoval();
                }, 300);
            }, 1000);

        } catch (error) {
            console.error('[Finishing] Błąd completion produktu:', error);

            const ordersList = document.getElementById('orders-list');
            if (ordersList) {
                card.classList.remove('processing');
                ordersList.insertBefore(cardBackup, ordersList.firstChild);
                initializeProductTile(cardBackup);
            }

            showToast('error', `Błąd ukończenia: ${error.message}`);
        }
    }

    function updateTabCounts(nextStatus) {
        // Aktualizuj liczniki w belce zakładek po zakończeniu produktu
        const tabBtns = document.querySelectorAll('.tab-btn .tab-count');
        if (tabBtns.length < 2) return;

        const productionCountEl = tabBtns[0]; // Produkcja
        const paintingCountEl = tabBtns[1];   // Lakiernia

        const activeTab = state.config ? state.config.tab : 'production';

        // Zmniejsz licznik aktywnej zakładki o 1
        const activeCountEl = activeTab === 'production' ? productionCountEl : paintingCountEl;
        const activeMatch = activeCountEl.textContent.match(/\((\d+)\)/);
        if (activeMatch) {
            const newCount = Math.max(0, parseInt(activeMatch[1]) - 1);
            activeCountEl.textContent = `(${newCount})`;
        }

        // Jeśli produkt trafił do lakierni, zwiększ licznik lakierni
        if (nextStatus === 'czeka_na_lakiernie') {
            const paintingMatch = paintingCountEl.textContent.match(/\((\d+)\)/);
            if (paintingMatch) {
                const newCount = parseInt(paintingMatch[1]) + 1;
                paintingCountEl.textContent = `(${newCount})`;
            }
        }
    }

    // ========================================================================
    // CONNECTION MONITOR
    // ========================================================================

    function handleConnectionChange(isOnline) {
        console.log(`[Finishing] Connection status: ${isOnline ? 'ONLINE' : 'OFFLINE'}`);

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

    // ========================================================================
    // STATYSTYKI I STANY
    // ========================================================================

    function updateStatsAfterRemoval() {
        const remainingCards = document.querySelectorAll('.order-card');
        if (remainingCards.length === 0) showEmptyState();
        updateHeaderStats();
    }

    function updateHeaderStats() {
        const allCards = document.querySelectorAll('.order-card');
        let totalProducts = 0;

        allCards.forEach(card => {
            totalProducts += parseInt(card.dataset.quantity) || 1;
        });

        const totalProductsElement = document.getElementById('total-products');
        if (totalProductsElement) totalProductsElement.textContent = totalProducts;
    }

    function showEmptyState() {
        const ordersList = document.getElementById('orders-list');
        if (!ordersList) return;

        const isPainting = state.config && state.config.stationCode === 'painting';

        ordersList.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">✅</div>
                <h2>${isPainting ? 'Brak produktów w lakierni' : 'Brak produktów do wykańczania'}</h2>
                <p>Świetna robota! ${isPainting ? 'Wszystkie produkty zostały polakierowane.' : 'Wszystkie produkty zostały wykończone.'}</p>
            </div>
        `;
    }

    function showToast(type, message) {
        const prefix = type === 'success' ? '✅' : type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️';
        console.log(`[Finishing] ${prefix} ${message}`);
    }

    // ========================================================================
    // AUTO-REFRESH (przeładowanie strony)
    // ========================================================================

    function startAutoRefresh(intervalMs) {
        if (state.refreshTimer) clearInterval(state.refreshTimer);
        state.refreshTimer = setInterval(performAutoRefresh, intervalMs);
    }

    async function performAutoRefresh() {
        try {
            const stationCode = state.config ? state.config.stationCode : 'finishing';
            const response = await fetch(`/production/stations/ajax/products/${stationCode}?sort=priority`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const result = await response.json();
            if (!result.success || !result.data || !result.data.products) throw new Error('Invalid response');

            smartMergeProducts(result.data.products);
            fetchTodayM3();
        } catch (error) {
            console.error('[Finishing] Auto-refresh failed:', error);
        }
    }

    function smartMergeProducts(newProducts) {
        const ordersList = document.getElementById('orders-list');
        if (!ordersList) return;

        const existingCards = ordersList.querySelectorAll('.order-card');
        const existingIds = new Set();
        existingCards.forEach(card => existingIds.add(card.dataset.productId));

        const apiIds = new Set(newProducts.map(p => p.id));

        // Nowe produkty — dodaj
        newProducts.forEach(product => {
            if (!existingIds.has(product.id)) {
                // Nowy produkt — przeładuj stronę żeby go wyświetlić
                // (prostsze niż budowanie HTML dynamicznie)
                window.location.reload();
            }
        });

        // Aktualizuj istniejące
        newProducts.forEach(product => {
            const card = ordersList.querySelector(`[data-product-id="${product.id}"]`);
            if (!card) return;

            // Nie aktualizuj karty w trakcie przetwarzania
            if (card.classList.contains('processing')) return;

            // Aktualizuj quantity_done jeśli nie ma oczekujących requestów
            if (!state.pendingRequests.has(product.id)) {
                const currentQtyDone = parseInt(card.dataset.quantityDone) || 0;
                const serverQtyDone = product.quantity_done || 0;

                if (currentQtyDone !== serverQtyDone) {
                    card.dataset.quantityDone = serverQtyDone;
                    const qtyDoneEl = card.querySelector('.qty-done');
                    if (qtyDoneEl) qtyDoneEl.textContent = serverQtyDone;
                    syncHeaderQty(card, serverQtyDone);
                    updateButtonStates(card, serverQtyDone, product.quantity);
                    updateCompleteButtonState(card);
                }
            }

            // Aktualizuj priorytet
            const serverPriority = product.is_priority || false;
            if (serverPriority) card.classList.add('priority-order');
            else card.classList.remove('priority-order');
        });

        // Usunięte produkty — usuń kafelki
        existingCards.forEach(card => {
            const productId = card.dataset.productId;
            if (!apiIds.has(productId) && !card.classList.contains('processing')) {
                card.classList.add('removing');
                setTimeout(() => {
                    card.remove();
                    const remaining = ordersList.querySelectorAll('.order-card');
                    if (remaining.length === 0) showEmptyState();
                }, 300);
            }
        });
    }

    // ========================================================================
    // TODAY M³
    // ========================================================================

    async function fetchTodayM3() {
        try {
            const stationCode = state.config ? state.config.stationCode : 'finishing';
            const response = await fetch(`/production/stations/ajax/station-today-m3/${stationCode}`);
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

    // ========================================================================
    // THEME TOGGLE
    // ========================================================================

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
                if (sunIcon) sunIcon.style.display = 'none';
                if (moonIcon) moonIcon.style.display = 'block';
                if (themeText) themeText.textContent = 'Tryb ciemny';
            } else {
                if (sunIcon) sunIcon.style.display = 'block';
                if (moonIcon) moonIcon.style.display = 'none';
                if (themeText) themeText.textContent = 'Tryb jasny';
            }

            localStorage.setItem('theme', isLight ? 'light' : 'dark');
        });

        const savedTheme = localStorage.getItem('theme');
        if (savedTheme === 'light') themeToggle.click();
    }

    // ========================================================================
    // CLEANUP
    // ========================================================================

    window.addEventListener('beforeunload', function() {
        if (state.refreshTimer) clearInterval(state.refreshTimer);
        if (state.countdownTimer) clearInterval(state.countdownTimer);
        state.pendingRequests.forEach(t => clearTimeout(t));
    });

    // Eksportuj initializeProductTile dla ewentualnego użycia zewnętrznego
    window.initializeProductTile = initializeProductTile;

    console.log('[Finishing] Module loaded v4.0');
})();
