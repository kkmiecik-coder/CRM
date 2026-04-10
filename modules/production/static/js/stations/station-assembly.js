/**
 * ============================================================================
 * STATION ASSEMBLY - FLAT PRODUCT TILES VERSION
 * ============================================================================
 *
 * Wersja z kafelkami produktów zamiast grupowanych kart zamówień.
 * Każdy kafelek to .order-card[data-product-id].
 *
 * Funkcjonalność:
 * - Przyciski +/- do zmiany quantity_done
 * - Przyciski +10/-10 dla ilości >= 10
 * - Natychmiastowy zapis do API (rate limiting 200ms)
 * - Completion pojedynczych produktów z countdown 5s
 * - Optimistic UI z error recovery
 * - Smart merge podczas auto-refresh
 * - Zegar odświeżany co sekundę
 * - Auto-refresh co 60s (z konfiguracji)
 *
 * @author: Konrad Kmiecik
 * @date: 2025-11
 * @version: 4.0
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
        activeCountdowns: new Map(), // productId -> { timerId, secondsLeft }
        pendingRequests: new Map(),  // productId -> timeoutId (rate limiting)
        lastRequestTime: new Map()   // productId -> timestamp
    };

    const RATE_LIMIT_MS = 200; // Minimalny odstęp między requestami dla tego samego produktu

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    document.addEventListener('DOMContentLoaded', function() {
        console.log('[Assembly] Initializing FLAT PRODUCT TILES station v4.0...');
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

        // Podpiecie listenerow do istniejących kafelków produktów
        const existingCards = document.querySelectorAll('.order-card[data-product-id]');
        console.log(`[Assembly] Found ${existingCards.length} product tiles`);

        existingCards.forEach(card => {
            initializeProductTile(card);
        });

        // Pobranie dzisiejszych m³
        fetchTodayM3();

        // Zegar aktualizowany co sekundę
        setInterval(updateCurrentDatetime, 1000);
        updateCurrentDatetime();

        // Auto-refresh z odliczaniem
        if (config.refreshInterval && config.refreshInterval > 0) {
            startAutoRefresh(config.refreshInterval);
            startRefreshCountdown(config.refreshInterval);
        }

        // Monitor połączenia
        if (window.StationCommon && window.StationCommon.initConnectionMonitor) {
            window.StationCommon.initConnectionMonitor();
            console.log('[Assembly] Connection monitor initialized');

            // Rejestracja listenera zmian połączenia
            if (window.StationCommon.onConnectionChange) {
                window.StationCommon.onConnectionChange(handleConnectionChange);
                console.log('[Assembly] Connection change listener registered');
            }
        }

        // Inicjalizacja ikon powiększenia dla trybu pełnoekranowego
        if (typeof window.initExpandIcons === 'function') {
            window.initExpandIcons();
            console.log('[Assembly] Expand icons initialized');
        }

        // Inicjalizacja przycisku wyszukiwania zamówień
        if (typeof window.initOrderSearchButton === 'function') {
            window.initOrderSearchButton();
            console.log('[Assembly] Order search button initialized');
        }

        console.log('[Assembly] Station initialized successfully');
    }

    function getVisibleProductIds() {
        // Kafelek produktu sam ma data-product-id
        const cards = document.querySelectorAll('.order-card[data-product-id]');
        const ids = [];
        cards.forEach(card => {
            const productId = card.dataset.productId;
            if (productId) {
                ids.push(productId);
            }
        });
        return ids;
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

        // Aktualizacja etykiety dnia
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

                // Klasa ostrzeżenia gdy < 10s
                if (secondsLeft <= 10) {
                    countdownElement.classList.add('warning');
                } else {
                    countdownElement.classList.remove('warning');
                }

                // Animacja ikony gdy <= 5s
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
    // INICJALIZACJA KAFELKA PRODUKTU
    // ========================================================================

    function initializeProductTile(card) {
        const productId = card.dataset.productId;

        if (!productId) {
            console.warn('[Assembly] Kafelek produktu bez product ID');
            return;
        }

        console.log(`[Assembly] Initializing product tile: ${productId}`);

        // Ukryj puste kontenery parametrów
        hideEmptyProductParams(card);

        // Podpięcie listenerów przycisków ilości
        card.querySelectorAll('.btn-qty').forEach(button => {
            button.addEventListener('click', (e) => {
                e.preventDefault();
                handleQuantityButtonClick(card, productId, button);
            });
        });

        // Podpięcie przycisku zakończenia
        const completeBtn = card.querySelector('.btn-complete');
        if (completeBtn) {
            completeBtn.addEventListener('click', (e) => {
                e.preventDefault();
                handleCompleteClick(card, productId);
            });
        }

        // Początkowy stan przycisków
        updateCompleteButtonState(card);
    }

    // ========================================================================
    // UKRYWANIE PUSTYCH PARAMETRÓW PRODUKTU
    // ========================================================================

    function hideEmptyProductParams(card) {
        // Kafelek sam zawiera product-params
        const paramsContainer = card.querySelector('.product-params');
        if (!paramsContainer) return;

        // Sprawdź czy są jakieś badge wewnątrz
        const badges = paramsContainer.querySelectorAll('.badge');

        // Jeśli brak badge, ukryj kontener
        if (badges.length === 0) {
            paramsContainer.style.display = 'none';
        }
    }

    // ========================================================================
    // OBSŁUGA PRZYCISKÓW ILOŚCI
    // ========================================================================

    async function handleQuantityButtonClick(card, productId, button) {
        const action = button.dataset.action;

        if (!action) {
            console.warn('[Assembly] Brak akcji na przycisku');
            return;
        }

        // Sprawdzenie statusu połączenia
        const isOnline = window.StationCommon && window.StationCommon.isOnline ? window.StationCommon.isOnline() : true;
        if (!isOnline) {
            showToast('warning', 'Brak połączenia - nie można zapisać zmiany');
            return;
        }

        // Pobranie aktualnych wartości z kafelka
        const qtyDoneEl = card.querySelector('.product-body .qty-done');
        const qtyTotalEl = card.querySelector('.product-body .qty-total');

        if (!qtyDoneEl || !qtyTotalEl) return;

        const qtyDone = parseInt(qtyDoneEl.textContent) || 0;
        const qtyTotal = parseInt(qtyTotalEl.textContent) || 1;

        // Obliczenie nowej wartości
        let newQtyDone = qtyDone;
        if (action === 'increment') newQtyDone = Math.min(qtyDone + 1, qtyTotal);
        else if (action === 'decrement') newQtyDone = Math.max(qtyDone - 1, 0);
        else if (action === 'increment10') newQtyDone = Math.min(qtyDone + 10, qtyTotal);
        else if (action === 'decrement10') newQtyDone = Math.max(qtyDone - 10, 0);

        // Pomiń jeśli bez zmian
        if (newQtyDone === qtyDone) return;

        // Optymistyczna aktualizacja UI
        qtyDoneEl.textContent = newQtyDone;
        card.dataset.quantityDone = newQtyDone;

        // Aktualizacja ilości w nagłówku
        const headerQtyDone = card.querySelector('.order-stats .qty-done');
        if (headerQtyDone) headerQtyDone.textContent = newQtyDone;

        // Aktualizacja stanów przycisków
        updateProductButtonStates(card, newQtyDone, qtyTotal);
        updateCompleteButtonState(card);

        // Wysłanie do API z rate limitingiem
        await sendQuantityUpdate(productId, action, card, qtyDone);
    }

    async function sendQuantityUpdate(productId, action, card, previousValue) {
        // Rate limiting - anuluj oczekujący request dla tego produktu
        if (state.pendingRequests.has(productId)) {
            clearTimeout(state.pendingRequests.get(productId));
        }

        // Sprawdź czy trzeba poczekać
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

                // Aktualizacja UI z odpowiedzi serwera
                const qtyDoneEl = card.querySelector('.product-body .qty-done');
                if (qtyDoneEl && result.quantity_done !== undefined) {
                    qtyDoneEl.textContent = result.quantity_done;
                    card.dataset.quantityDone = result.quantity_done;

                    // Aktualizacja ilości w nagłówku
                    const headerQtyDone = card.querySelector('.order-stats .qty-done');
                    if (headerQtyDone) headerQtyDone.textContent = result.quantity_done;

                    updateProductButtonStates(card, result.quantity_done, result.quantity);
                    updateCompleteButtonState(card);
                }

            } catch (error) {
                console.error('[Assembly] Błąd aktualizacji ilości:', error);

                // Przywrócenie UI przy błędzie
                const qtyDoneEl = card.querySelector('.product-body .qty-done');
                if (qtyDoneEl) {
                    qtyDoneEl.textContent = previousValue;
                    card.dataset.quantityDone = previousValue;

                    // Przywrócenie ilości w nagłówku
                    const headerQtyDone = card.querySelector('.order-stats .qty-done');
                    if (headerQtyDone) headerQtyDone.textContent = previousValue;

                    const qtyTotalEl = card.querySelector('.product-body .qty-total');
                    const qtyTotal = parseInt(qtyTotalEl ? qtyTotalEl.textContent : '0') || 0;
                    updateProductButtonStates(card, previousValue, qtyTotal);
                    updateCompleteButtonState(card);
                }

                showToast('error', `Błąd zapisu: ${error.message}`);
            }
        }, delay);

        state.pendingRequests.set(productId, timeoutId);
    }

    function updateProductButtonStates(card, qtyDone, qtyTotal) {
        const btnMinus = card.querySelector('.btn-minus');
        const btnPlus = card.querySelector('.btn-plus');
        const btnMinus10 = card.querySelector('.btn-minus-10');
        const btnPlus10 = card.querySelector('.btn-plus-10');

        if (btnMinus) btnMinus.disabled = qtyDone <= 0;
        if (btnPlus) btnPlus.disabled = qtyDone >= qtyTotal;
        if (btnMinus10) btnMinus10.disabled = qtyDone < 10;
        if (btnPlus10) btnPlus10.disabled = (qtyTotal - qtyDone) < 10;
    }

    // ========================================================================
    // STATUS POŁĄCZENIA
    // ========================================================================

    function handleConnectionChange(isOnline) {
        console.log(`[Assembly] Zmiana statusu połączenia: ${isOnline ? 'ONLINE' : 'OFFLINE'}`);

        // Aktualizacja wszystkich przycisków
        const allCards = document.querySelectorAll('.order-card[data-product-id]');
        allCards.forEach(card => {
            updateCompleteButtonState(card);

            // Wyłącz/włącz przyciski ilości
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
    // STAN PRZYCISKU ZAKOŃCZENIA
    // ========================================================================

    function updateCompleteButtonState(card) {
        const completeBtn = card.querySelector('.btn-complete');
        if (!completeBtn) return;

        // Sprawdź czy offline
        const isOnline = window.StationCommon && window.StationCommon.isOnline ? window.StationCommon.isOnline() : true;

        if (!isOnline) {
            completeBtn.disabled = true;
            completeBtn.textContent = 'Jesteś offline';
            completeBtn.classList.add('offline');
            return;
        }

        // Usunięcie stylowania offline jeśli było ustawione
        completeBtn.classList.remove('offline');
        completeBtn.textContent = 'ZAKOŃCZ SKŁADANIE';

        // Przycisk dostępny zawsze gdy online - operator sam decyduje kiedy skończył
        const qtyDone = parseInt(card.dataset.quantityDone) || 0;
        const qtyTotal = parseInt(card.dataset.quantity) || 1;
        completeBtn.disabled = (qtyDone < qtyTotal);
    }

    // ========================================================================
    // COUNTDOWN 10 SEKUND PRZED ZAKOŃCZENIEM
    // ========================================================================

    function handleCompleteClick(card, productId) {
        console.log(`[Assembly] Kliknięto zakończenie dla produktu: ${productId}`);

        // Sprawdź status połączenia
        if (!window.StationCommon.isOnline()) {
            console.warn('[Assembly] Offline - nie można zakończyć produktu');
            showToast('warning', 'Brak połączenia - nie możesz zakończyć produktu');
            return;
        }

        // Oznacz kafelek jako przetwarzany
        card.dataset.inProgress = 'true';
        card.classList.add('processing');

        // Uruchom 10-sekundowe odliczanie
        startCountdown(card, productId);
    }

    function startCountdown(card, productId) {
        console.log(`[Assembly] Rozpoczęcie 10-sekundowego odliczania dla ${productId}`);

        const actionContainer = card.querySelector('.order-action');
        if (!actionContainer) {
            console.error('[Assembly] Brak kontenera akcji');
            return;
        }

        // Zamiana przycisku na UI odliczania
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
                // Odliczanie zakończone - wykonaj completion
                clearInterval(timerId);
                state.activeCountdowns.delete(productId);
                completeProduct(card, productId);
            }
        }, 1000);

        // Zapisz ID timera
        state.activeCountdowns.set(productId, { timerId, secondsLeft });

        // Listener przycisku anulowania
        cancelBtn.addEventListener('click', function(event) {
            event.preventDefault();
            event.stopPropagation();
            cancelCountdown(card, productId, timerId);
        });

        console.log(`[Assembly] Odliczanie rozpoczęte dla ${productId}`);
    }

    function cancelCountdown(card, productId, timerId) {
        console.log(`[Assembly] Odliczanie anulowane dla ${productId}`);

        // Wyczyść timer
        if (timerId) {
            clearInterval(timerId);
            state.activeCountdowns.delete(productId);
        }

        // Reset stanu kafelka
        card.dataset.inProgress = 'false';
        card.classList.remove('processing');

        // Przywrócenie oryginalnego przycisku
        const actionContainer = card.querySelector('.order-action');
        if (actionContainer) {
            actionContainer.innerHTML = `<button class="btn-complete" data-product-id="${productId}" data-action="complete" disabled>ZAKOŃCZ SKŁADANIE</button>`;

            // Ponowne podpięcie listenera
            const completeBtn = actionContainer.querySelector('.btn-complete');
            if (completeBtn) {
                completeBtn.addEventListener('click', function() {
                    handleCompleteClick(card, productId);
                });

                // Aktualizacja stanu przycisku
                updateCompleteButtonState(card);
            }
        }

        showToast('info', 'Anulowano składanie produktu');
    }

    // ========================================================================
    // COMPLETION PRODUKTU - Optimistic UI
    // ========================================================================

    async function completeProduct(card, productId) {
        console.log(`[Assembly] Rozpoczęcie completion dla produktu ${productId}`);

        // BACKUP przed usunięciem
        const cardBackup = card.cloneNode(true);

        // Stan przetwarzania
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
                    order_number: card.dataset.internalOrder,  // wysylamy internal_order_number (np. "25/123") zamiast productId
                    product_ids: [productId],
                    station: window.STATION_CONFIG.stationCode,
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

            console.log('[Assembly] Produkt zakończony pomyślnie:', result);

            // SUKCES - pokaż stan sukcesu
            if (actionContainer) {
                actionContainer.innerHTML = '<button class="btn-complete success">Zapisano</button>';
            }

            showToast('success', `Produkt ${productId} ukończony`);

            // Aktualizacja statystyk dzisiejszych m³
            fetchTodayM3();

            // Zamknij tryb pełnoekranowy jeśli aktywny
            if (typeof window.closeFullscreenIfActive === 'function') {
                window.closeFullscreenIfActive(productId);
            }

            // Poczekaj 1 sekundę, potem usuń kafelek z animacją
            setTimeout(() => {
                card.classList.add('removing');
                setTimeout(() => {
                    card.remove();
                    updateStatsAfterRemoval();
                }, 300);
            }, 1000);

        } catch (error) {
            // BŁĄD - przywróć kafelek
            console.error('[Assembly] Błąd completion produktu:', error);

            const ordersList = document.getElementById('orders-list');

            if (ordersList) {
                // Ponowne wstawienie kafelka
                ordersList.insertBefore(cardBackup, ordersList.firstChild);

                // Ponowna inicjalizacja przywróconego kafelka
                initializeProductTile(cardBackup);
            }

            let errorMessage = error.message;
            if (error.name === 'AbortError') {
                errorMessage = 'Timeout - przekroczono 10 sekund';
            }

            showToast('error', `Błąd ukończenia: ${errorMessage}`);
        }
    }

    // ========================================================================
    // AKTUALIZACJA STATYSTYK
    // ========================================================================

    function updateStatsAfterRemoval() {
        // Policz pozostałe kafelki
        const remaining = document.querySelectorAll('.order-card[data-product-id]:not(.removing)');
        const el = document.getElementById('total-orders');
        if (el) el.textContent = remaining.length;

        // Sprawdź czy pokazać empty state
        if (remaining.length === 0) {
            showEmptyState();
        }

        console.log(`[Assembly] Pozostałe kafelki: ${remaining.length}`);
    }

    function updateHeaderStats() {
        const allCards = document.querySelectorAll('.order-card[data-product-id]');

        let totalVolume = 0;

        allCards.forEach(card => {
            const cardTotalVolume = parseFloat(card.dataset.totalVolume) || 0;
            totalVolume += cardTotalVolume;
        });

        // Aktualizacja DOM
        const totalOrdersElement = document.getElementById('total-orders');
        const totalVolumeElement = document.getElementById('total-volume');

        if (totalOrdersElement) {
            totalOrdersElement.textContent = allCards.length;
        }

        if (totalVolumeElement) {
            totalVolumeElement.textContent = totalVolume.toFixed(4);
        }

        console.log(`[Assembly] Zaktualizowano statystyki nagłówka: ${allCards.length} produktów, ${totalVolume.toFixed(4)} m³`);
    }

    function showEmptyState() {
        const ordersList = document.getElementById('orders-list');

        if (!ordersList) {
            return;
        }

        ordersList.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">✅</div>
                <h2>Brak produktów do składania</h2>
                <p>Świetna robota! Wszystkie produkty zostały złożone.</p>
            </div>
        `;

        console.log('[Assembly] Wyświetlanie pustego stanu');
    }

    // ========================================================================
    // TOAST NOTIFICATIONS
    // ========================================================================

    function showToast(type, message) {
        const prefix = type === 'success' ? '✅' : type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️';
        console.log(`[Assembly] ${prefix} ${message}`);

        // TODO: Implementacja wizualnych powiadomień toast jeśli potrzebne
    }

    // ========================================================================
    // AUTO-REFRESH ZE SMART MERGE
    // ========================================================================

    function startAutoRefresh(intervalSeconds) {
        if (state.refreshTimer) {
            clearInterval(state.refreshTimer);
        }

        console.log(`[Assembly] Rozpoczęcie auto-refresh co ${intervalSeconds}s`);

        state.refreshTimer = setInterval(async () => {
            await performAutoRefresh();
        }, intervalSeconds * 1000);
    }

    async function performAutoRefresh() {
        console.log('[Assembly] Wykonywanie auto-refresh...');

        try {
            const response = await fetch('/production/stations/ajax/orders/assembly?sort=priority');

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const result = await response.json();

            if (!result.success || !result.data || !result.data.products) {
                throw new Error('Nieprawidłowy format odpowiedzi');
            }

            console.log(`[Assembly] Pobrano ${result.data.products.length} produktów`);

            smartMergeProducts(result.data.products);

            // Aktualizacja statystyk nagłówka z danych API (bardziej wiarygodne niż DOM)
            updateHeaderStatsFromAPI(result.data.products);

            // Aktualizacja statystyk dzisiejszych m³
            fetchTodayM3();

        } catch (error) {
            console.error('[Assembly] Auto-refresh nieudany:', error);
        }
    }

    function updateHeaderStatsFromAPI(products) {
        const totalTiles = products.length;
        let totalVolume = 0;
        products.forEach(p => { totalVolume += (p.volume_m3 || 0) * (p.quantity || 1); });

        const el = document.getElementById('total-orders');
        if (el) el.textContent = totalTiles;

        const volEl = document.getElementById('total-volume');
        if (volEl) volEl.textContent = totalVolume.toFixed(4);

        console.log(`[Assembly] Zaktualizowano statystyki z API: ${totalTiles} produktów, ${totalVolume.toFixed(4)} m³`);
    }

    function smartMergeProducts(newProducts) {
        const ordersList = document.getElementById('orders-list');

        if (!ordersList) {
            return;
        }

        const existingCards = ordersList.querySelectorAll('.order-card[data-product-id]');
        const existingProductIds = new Set();

        existingCards.forEach(card => {
            existingProductIds.add(card.dataset.productId);
        });

        // Zbiór ID produktów z API
        const apiProductIds = new Set(newProducts.map(product => String(product.id)));

        // Dodaj tylko NOWE produkty (których jeszcze nie ma)
        newProducts.forEach(product => {
            const productIdStr = String(product.id);
            if (!existingProductIds.has(productIdStr)) {
                console.log(`[Assembly] Dodawanie nowego produktu: ${product.id}`);
                addProductTile(product);
            } else {
                // Aktualizacja istniejącego kafelka
                updateExistingProductTile(product);
            }
        });

        // Usunięcie kafelków nieobecnych w odpowiedzi API (ale nie jeśli użytkownik nad nimi pracuje)
        existingCards.forEach(card => {
            const productId = card.dataset.productId;
            if (!apiProductIds.has(productId)) {
                // Sprawdź czy kafelek nie jest w trakcie przetwarzania (aktywne odliczanie)
                const hasActiveCountdown = state.activeCountdowns.has(productId);
                const isProcessing = card.classList.contains('processing');

                if (!hasActiveCountdown && !isProcessing) {
                    console.log(`[Assembly] Usuwanie produktu nieobecnego na stanowisku: ${productId}`);
                    card.classList.add('removing');
                    setTimeout(() => {
                        card.remove();
                        // Jeśli nie ma już żadnych kafelków, pokaż empty state
                        checkAndShowEmptyState();
                    }, 300);
                } else {
                    console.log(`[Assembly] Zachowanie produktu ${productId} - użytkownik nad nim pracuje`);
                }
            }
        });

        console.log('[Assembly] Smart merge zakończony');
    }

    function updateExistingProductTile(productData) {
        const card = document.querySelector(`.order-card[data-product-id="${productData.id}"]`);
        if (!card) return;

        // Pomiń jeśli kafelek jest przetwarzany
        if (card.dataset.inProgress === 'true') return;

        const productId = String(productData.id);
        const currentQtyDone = parseInt(card.dataset.quantityDone) || 0;
        const serverQtyDone = productData.quantity_done || 0;

        // Aktualizuj tylko jeśli wartość serwera jest inna i nie ma oczekującego requestu
        if (currentQtyDone !== serverQtyDone && !state.pendingRequests.has(productId)) {
            card.dataset.quantityDone = serverQtyDone;

            // Aktualizacja ilości w ciele kafelka
            const qtyDoneEl = card.querySelector('.product-body .qty-done');
            if (qtyDoneEl) {
                qtyDoneEl.textContent = serverQtyDone;
            }

            // Aktualizacja ilości w nagłówku
            const headerQtyDone = card.querySelector('.order-stats .qty-done');
            if (headerQtyDone) {
                headerQtyDone.textContent = serverQtyDone;
            }

            updateProductButtonStates(card, serverQtyDone, productData.quantity);
            updateCompleteButtonState(card);
        }

        // Aktualizacja statusu priorytetu
        const currentPriority = card.dataset.isPriority === 'true';
        const serverPriority = productData.is_priority || false;
        if (currentPriority !== serverPriority) {
            card.dataset.isPriority = serverPriority ? 'true' : 'false';
            if (serverPriority) {
                card.classList.add('priority-order');
            } else {
                card.classList.remove('priority-order');
            }
        }
    }

    function checkAndShowEmptyState() {
        const ordersList = document.getElementById('orders-list');
        if (!ordersList) return;

        const remainingCards = ordersList.querySelectorAll('.order-card[data-product-id]:not(.removing)');
        if (remainingCards.length === 0) {
            const emptyState = ordersList.querySelector('.empty-state');
            if (!emptyState) {
                ordersList.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">✅</div>
                        <h2>Brak produktów do składania</h2>
                        <p>Świetna robota! Wszystkie produkty zostały złożone.</p>
                    </div>
                `;
            }
        }
    }

    function addProductTile(product) {
        const ordersList = document.getElementById('orders-list');

        if (!ordersList) {
            return;
        }

        // Usunięcie empty state jeśli obecny
        const emptyState = ordersList.querySelector('.empty-state');
        if (emptyState) {
            emptyState.remove();
        }

        // Stworzenie HTML kafelka
        const tileHTML = createProductTileHTML(product);

        // Wstawienie na początek (najwyższy priorytet)
        ordersList.insertAdjacentHTML('afterbegin', tileHTML);

        // Inicjalizacja nowego kafelka
        const newCard = ordersList.querySelector(`.order-card[data-product-id="${product.id}"]`);
        if (newCard) {
            initializeProductTile(newCard);

            // Ponowna inicjalizacja handlerów załączników
            if (typeof window.reinitializeAttachmentHandlers === 'function') {
                window.reinitializeAttachmentHandlers();
            }

            // Ponowna inicjalizacja ikon powiększenia
            if (typeof window.initExpandIcons === 'function') {
                window.initExpandIcons();
            }
        }
    }

    function createProductTileHTML(product) {
        const quantity = product.quantity || 1;
        const quantityDone = product.quantity_done || 0;
        const hasLargeQty = quantity >= 10;

        // Badge z parametrami - dla assembly pokazujemy postęp wycinania (badge-cut z nożyczkami)
        let paramsHTML = '';
        if (product.quantity_done_cutting > 0) {
            paramsHTML += `<span class="badge badge-cut">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="6" cy="6" r="3"></circle>
                    <circle cx="6" cy="18" r="3"></circle>
                    <line x1="20" y1="4" x2="8.12" y2="15.88"></line>
                    <line x1="14.47" y1="14.48" x2="20" y2="20"></line>
                    <line x1="8.12" y1="8.12" x2="12" y2="12"></line>
                </svg>
                <span class="cut-counter">${product.quantity_done_cutting}/${quantity}</span>
            </span>`;
        }
        if (product.wood_species) paramsHTML += `<span class="badge badge-species">${product.wood_species}</span>`;
        if (product.technology) paramsHTML += `<span class="badge badge-technology">${product.technology}</span>`;
        if (product.wood_class) paramsHTML += `<span class="badge badge-class">${product.wood_class}</span>`;

        // Wymiary - badge
        let dimensionsBadge = '';
        if (product.dimensions) {
            const formattedDimensions = product.dimensions.replace(/x/g, ' x ').replace(/×/g, ' × ');
            dimensionsBadge = `<span class="badge badge-dimensions">${formattedDimensions}</span>`;
        } else if (product.original_name) {
            dimensionsBadge = `<span class="badge badge-dimensions">${product.original_name}</span>`;
        } else if (product.attachment_file_url) {
            dimensionsBadge = `<span class="badge badge-dimensions">Zgodnie z załącznikiem</span>`;
        }

        // Przyciski ilości
        const minusDisabled = quantityDone <= 0 ? 'disabled' : '';
        const plusDisabled = quantityDone >= quantity ? 'disabled' : '';
        const minus10Disabled = quantityDone < 10 ? 'disabled' : '';
        const plus10Disabled = (quantity - quantityDone) < 10 ? 'disabled' : '';

        const quantityControlsHTML = hasLargeQty ? `
            <button class="btn-qty btn-minus-10" data-action="decrement10" ${minus10Disabled}>−10</button>
            <button class="btn-qty btn-minus" data-action="decrement" ${minusDisabled}>−</button>
            <div class="quantity-counter">
                <span class="qty-done">${quantityDone}</span>
                <span class="qty-separator">/</span>
                <span class="qty-total">${quantity}</span>
            </div>
            <button class="btn-qty btn-plus" data-action="increment" ${plusDisabled}>+</button>
            <button class="btn-qty btn-plus-10" data-action="increment10" ${plus10Disabled}>+10</button>
        ` : `
            <button class="btn-qty btn-minus" data-action="decrement" ${minusDisabled}>−</button>
            <div class="quantity-counter">
                <span class="qty-done">${quantityDone}</span>
                <span class="qty-separator">/</span>
                <span class="qty-total">${quantity}</span>
            </div>
            <button class="btn-qty btn-plus" data-action="increment" ${plusDisabled}>+</button>
        `;

        // Ikony nagłówka
        let iconsHTML = '';

        if (product.attachment_file_url) {
            const attachmentType = product.attachment_file_name && product.attachment_file_name.toLowerCase().endsWith('.pdf') ? 'pdf' : 'image';
            iconsHTML += `
                <div class="header-icon-wrapper attachment-icon-wrapper"
                     data-attachment-url="${product.attachment_file_url}"
                     data-attachment-name="${product.attachment_file_name || ''}"
                     data-attachment-type="${attachmentType}">
                    <svg class="header-icon" width="18" height="18"><use href="${window.STATION_CONFIG.iconsUrl}#icon-attachment"/></svg>
                </div>
            `;
        }
        if (product.order_notes) {
            const truncatedNotes = product.order_notes.length > 100
                ? product.order_notes.substring(0, 100) + '...'
                : product.order_notes;
            iconsHTML += `
                <div class="header-icon-wrapper notes-icon-wrapper"
                     data-notes="${product.order_notes.replace(/"/g, '&quot;')}"
                     title="${truncatedNotes.replace(/"/g, '&quot;')}">
                    <svg class="header-icon" width="18" height="18"><use href="${window.STATION_CONFIG.iconsUrl}#icon-notes"/></svg>
                </div>
            `;
        }
        iconsHTML += `
            <div class="header-icon-wrapper expand-icon-wrapper">
                <svg class="header-icon" width="18" height="18"><use href="${window.STATION_CONFIG.iconsUrl}#icon-expand"/></svg>
            </div>
        `;

        // Numery
        const internalOrderHTML = product.client_order_number ? `<span class="order-internal">${product.client_order_number}</span>` : '';
        const blOrderHTML = product.baselinker_order_id ? `<span class="order-baselinker">BL-${product.baselinker_order_id}</span>` : '';

        // Klasa priorytetu
        const priorityClass = product.is_priority ? ' priority-order' : '';

        return `
            <div class="order-card${priorityClass}"
                 data-product-id="${product.id}"
                 data-internal-order="${product.internal_order || ''}"
                 data-quantity="${quantity}"
                 data-quantity-done="${quantityDone}"
                 data-in-progress="false"
                 data-is-priority="${product.is_priority ? 'true' : 'false'}">
                <div class="order-header">
                    <div class="order-header-row order-ids-row">
                        <span class="order-number">${product.id}</span>
                        ${internalOrderHTML}
                        ${blOrderHTML}
                    </div>
                    <div class="order-header-row order-stats-row">
                        <div class="order-stats">
                            <span class="qty-done">${quantityDone}</span>/<span class="qty-total">${quantity}</span> szt.
                        </div>
                        <div class="order-icons">${iconsHTML}</div>
                    </div>
                </div>
                <div class="product-body">
                    <div class="product-params">${paramsHTML}</div>
                    <div class="product-dimensions-row">
                        ${dimensionsBadge}
                        <div class="quantity-controls">
                            ${quantityControlsHTML}
                        </div>
                    </div>
                </div>
                <div class="order-action">
                    <button class="btn-complete" data-product-id="${product.id}" data-action="complete" disabled>ZAKOŃCZ SKŁADANIE</button>
                </div>
            </div>
        `;
    }

    // ========================================================================
    // POBRANIE DZISIEJSZYCH M³
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

                console.log(`[Assembly] Dzisiejsze m³: ${result.data.today_m3}`);
            }

        } catch (error) {
            console.error('[Assembly] Błąd pobierania dzisiejszych m³:', error);
        }
    }

    // ========================================================================
    // CZYSZCZENIE PRZY ZAMKNIĘCIU
    // ========================================================================

    window.addEventListener('beforeunload', function() {
        if (state.refreshTimer) {
            clearInterval(state.refreshTimer);
            console.log('[Assembly] Wyczyszczono interwał auto-refresh');
        }

        if (state.countdownTimer) {
            clearInterval(state.countdownTimer);
            console.log('[Assembly] Wyczyszczono timer odliczania');
        }

        // Wyczyść wszystkie aktywne odliczania produktów
        state.activeCountdowns.forEach((countdown, productId) => {
            if (countdown.timerId) {
                clearInterval(countdown.timerId);
                console.log(`[Assembly] Wyczyszczono odliczanie dla ${productId}`);
            }
        });

        // Wyczyść oczekujące requesty
        state.pendingRequests.forEach((timeoutId) => {
            clearTimeout(timeoutId);
        });
    });

    console.log('[Assembly] Moduł załadowany v4.0 (kafelki produktów z przyciskami +/-)');

})();
