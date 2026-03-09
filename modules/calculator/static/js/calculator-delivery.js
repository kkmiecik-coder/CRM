// calculator-delivery.js
// Moduł dostawy - modal wyboru kuriera, cache wysyłki, obliczenia dostawy
// Funkcja do pokazywania rotujących komunikatów
function showRotatingMessages(overlay) {
    // Wyczyść poprzednie timeouty
    messageTimeouts.forEach(timeout => clearTimeout(timeout));
    messageTimeouts = [];

    // Pokaż pierwszy komunikat od razu
    overlay.innerHTML = `
        <div class="spinner"></div>
        <div class="loading-text">${shippingMessages[0].text}</div>
    `;

    // Zaplanuj kolejne komunikaty
    shippingMessages.slice(1).forEach((message, index) => {
        const timeout = setTimeout(() => {
            const loadingText = overlay.querySelector('.loading-text');
            if (loadingText) {
                loadingText.style.opacity = '0';
                setTimeout(() => {
                    loadingText.textContent = message.text;
                    loadingText.style.opacity = '1';
                }, 300);
            }
        }, message.delay);

        messageTimeouts.push(timeout);
    });
}

// Funkcja do zatrzymania komunikatów
function stopRotatingMessages() {
    messageTimeouts.forEach(timeout => clearTimeout(timeout));
    messageTimeouts = [];
}

// ========== CACHE WYSYŁKI W LOCALSTORAGE ==========
const SHIPPING_CACHE_KEY = 'calculator_shipping_cache';
const SHIPPING_CACHE_TTL = 24 * 60 * 60 * 1000; // 24h w ms

function getShippingParamsHash(params) {
    // Prosty hash: length_width_height_weight (zaokrąglone)
    return `${Math.round(params.length)}_${Math.round(params.width)}_${Math.round(params.height)}_${Math.round(params.weight)}`;
}

function getShippingCache(paramsHash) {
    try {
        const cached = localStorage.getItem(SHIPPING_CACHE_KEY);
        if (!cached) return null;

        const data = JSON.parse(cached);

        // Sprawdź czy hash się zgadza
        if (data.paramsHash !== paramsHash) return null;

        // Sprawdź TTL (24h)
        if (Date.now() - data.timestamp > SHIPPING_CACHE_TTL) {
            localStorage.removeItem(SHIPPING_CACHE_KEY);
            return null;
        }

        return data.quotes;
    } catch (e) {
        console.error('Błąd odczytu cache wysyłki:', e);
        return null;
    }
}

function setShippingCache(paramsHash, quotes) {
    try {
        localStorage.setItem(SHIPPING_CACHE_KEY, JSON.stringify({
            paramsHash,
            quotes,
            timestamp: Date.now()
        }));
    } catch (e) {
        console.error('Błąd zapisu cache wysyłki:', e);
    }
}

// Zmodyfikowana funkcja calculateDelivery
async function calculateDelivery() {
    const overlay = document.getElementById('loadingOverlay');

    if (overlay) {
        overlay.style.display = 'flex';
        showRotatingMessages(overlay); // ✅ ZACHOWANE - rotujące komunikaty
    }

    const shippingParams = computeAggregatedData();
    if (!shippingParams) {
        console.error("Brak danych wysyłki");
        if (overlay) {
            stopRotatingMessages();
            overlay.style.display = 'none';
        }
        return;
    }

    // Sprawdź cache
    const paramsHash = getShippingParamsHash(shippingParams);
    const cachedQuotes = getShippingCache(paramsHash);

    if (cachedQuotes) {
        // Zastosuj mnożnik pakowania (tak jak przy normalnej odpowiedzi)
        const quotes = cachedQuotes.map(option => ({
            carrierName: option.carrierName,
            rawGrossPrice: option.grossPrice,
            rawNetPrice: option.netPrice,
            grossPrice: option.grossPrice * shippingPackingMultiplier,
            netPrice: option.netPrice * shippingPackingMultiplier,
            carrierLogoLink: option.carrierLogoLink || ""
        }));

        const packingInfo = {
            multiplier: shippingPackingMultiplier,
            message: `Do cen wysyłki została doliczona kwota ${Math.round((shippingPackingMultiplier - 1) * 100)}% na pakowanie.`
        };

        if (overlay) {
            stopRotatingMessages();
            overlay.style.display = 'none';
        }
        showDeliveryModal(quotes, packingInfo);
        return;
    }

    try {
        const response = await fetch('/calculator/shipping_quote', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(shippingParams)
        });

        if (response.ok) {
            // ✅ ZACHOWANA cała sekcja sukcesu - bez zmian
            const quotesData = await response.json();
            const quotesList = Array.isArray(quotesData) ? quotesData : [quotesData];

            // Zapisz do cache (surowe dane bez mnożnika)
            setShippingCache(paramsHash, quotesList);

            const quotes = quotesList.map(option => {
                const rawGross = option.grossPrice;
                const rawNet = option.netPrice;
                return {
                    carrierName: option.carrierName,
                    rawGrossPrice: rawGross,
                    rawNetPrice: rawNet,
                    grossPrice: rawGross * shippingPackingMultiplier,
                    netPrice: rawNet * shippingPackingMultiplier,
                    carrierLogoLink: option.carrierLogoLink || ""
                };
            });

            if (quotes.length === 0) {
                showDeliveryErrorModal("Brak dostępnych metod dostawy.");
            } else {
                const packingInfo = {
                    multiplier: shippingPackingMultiplier,
                    message: `Do cen wysyłki została doliczona kwota ${Math.round((shippingPackingMultiplier - 1) * 100)}% na pakowanie.`
                };
                showDeliveryModal(quotes, packingInfo);
            }
        } else {
            // ===== ✨ NOWA CZĘŚĆ: Lepsza obsługa błędów HTTP =====
            let errorMessage = "Błąd podczas wyceny wysyłki.";

            try {
                const errorData = await response.json();

                // Użyj komunikatu z backendu jeśli istnieje
                if (errorData.error) {
                    errorMessage = errorData.error;
                } else {
                    // Mapowanie kodów HTTP na przyjazne komunikaty
                    switch (response.status) {
                        case 502:
                        case 503:
                        case 504:
                            errorMessage = "Serwis kurierski chwilowo niedostępny. Spróbuj ponownie za chwilę.";
                            break;
                        case 401:
                            errorMessage = "Problem z autoryzacją serwisu kurierskiego. Skontaktuj się z administratorem.";
                            break;
                        case 400:
                            errorMessage = "Nieprawidłowe dane wysyłki. Sprawdź wymiary i wagę paczki.";
                            break;
                        case 500:
                            errorMessage = "Błąd serwera. Spróbuj ponownie lub skontaktuj się z administratorem.";
                            break;
                        default:
                            errorMessage = `Błąd serwisu kurierskiego (kod: ${response.status}). Spróbuj ponownie.`;
                    }
                }
            } catch (e) {
                // Jeśli nie można sparsować JSON, użyj komunikatu opartego na kodzie HTTP
                console.error("Nie można sparsować odpowiedzi błędu:", e);

                if (response.status === 502 || response.status === 503 || response.status === 504) {
                    errorMessage = "Serwis kurierski chwilowo niedostępny. Spróbuj ponownie za chwilę.";
                }
            }

            console.error("Błąd w żądaniu wyceny wysyłki:", response.status, errorMessage);
            showDeliveryErrorModal(errorMessage);
        }
    } catch (error) {
        console.error("Wyjątek przy wycenie wysyłki:", error);

        // ===== ✨ NOWA CZĘŚĆ: Rozróżnienie typów błędów JavaScript =====
        let errorMessage;

        if (error.name === 'TypeError' && error.message.includes('fetch')) {
            errorMessage = "Brak połączenia z serwerem. Sprawdź połączenie internetowe.";
        } else if (error.name === 'AbortError') {
            errorMessage = "Zapytanie przekroczyło czas oczekiwania. Spróbuj ponownie.";
        } else {
            errorMessage = "Wystąpił nieoczekiwany błąd. Spróbuj ponownie lub skontaktuj się z administratorem.";
        }

        showDeliveryErrorModal(errorMessage);
    } finally {
        // ✅ ZACHOWANE - zatrzymaj rotujące komunikaty i ukryj overlay
        stopRotatingMessages();
        if (overlay) {
            overlay.style.display = 'none';
        }
    }
}

/**
 * Aktualizuje stan przycisków "Oblicz wysyłkę" i "Zapisz wycenę"
 */
function updateCalculateDeliveryButtonState() {
    const allComplete = areAllProductsComplete();

    const calcDeliveryBtn = document.querySelector('.calculate-delivery');
    const saveQuoteBtn = document.querySelector('.save-quote');
    const copyBtn = document.querySelector('.copy-to-clipboard');

    [calcDeliveryBtn, saveQuoteBtn, copyBtn].forEach(btn => {
        if (!btn) return;

        // W trybie edycji przycisk zapisu jest kontrolowany przez detekcje zmian
        // (QuoteEditLoader.checkForChanges) — nie nadpisujemy go tutaj
        if (btn === saveQuoteBtn && window.quoteEditMode?.isActive) {
            // Tylko dodaj/usun klase wizualna, nie ruszaj disabled
            if (!allComplete) btn.classList.add('btn-disabled');
            else btn.classList.remove('btn-disabled');
            return;
        }

        if (!allComplete) {
            btn.classList.add('btn-disabled');
            btn.disabled = true;
        } else {
            btn.classList.remove('btn-disabled');
            btn.disabled = false;
        }
    });
}

function updateDeliverySelection(selection) {
    // Sprawdź czy elementy istnieją
    if (!deliverySummaryEls.courier || !deliverySummaryEls.brutto || !deliverySummaryEls.netto) {
        console.error('Brakuje elementów deliverySummaryEls');
        return;
    }

    // Aktualizuj elementy podsumowania
    deliverySummaryEls.courier.textContent = selection.carrierName;
    deliverySummaryEls.brutto.textContent = formatPLN(selection.grossPrice);
    deliverySummaryEls.netto.textContent = formatPLN(selection.netPrice);

    // Przelicz całe podsumowanie
    updateGlobalSummary();

    // Pokaż przycisk czyszczenia kuriera
    const clearBtn = document.querySelector('.clear-delivery');
    if (clearBtn) clearBtn.style.display = 'flex';

    // Zapisz snapshot parametrow wysylki i ukryj badge nieaktualnosci
    deliveryParamsSnapshot = takeDeliveryParamsSnapshot();
    hideDeliveryStaleBadge();

    // Powiadom detekcje zmian (tryb edycji wyceny)
    document.dispatchEvent(new CustomEvent('delivery-changed'));
}

/**
 * Czyści wybranego kuriera z podsumowania
 */
function clearDeliverySelection() {
    // Reset elementów podsumowania
    deliverySummaryEls.courier.textContent = '';
    deliverySummaryEls.brutto.textContent = '0.00 PLN';
    deliverySummaryEls.netto.textContent = '0.00 PLN';

    // Ukryj przycisk X
    const clearBtn = document.querySelector('.clear-delivery');
    if (clearBtn) clearBtn.style.display = 'none';

    // Przelicz podsumowanie
    updateGlobalSummary();

    // Reset snapshotu i ukryj badge
    deliveryParamsSnapshot = null;
    hideDeliveryStaleBadge();

    // Powiadom detekcje zmian (tryb edycji wyceny)
    document.dispatchEvent(new CustomEvent('delivery-changed'));
}

/**
 * Attaches the calculateDelivery button listener
 */
function attachCalculateDeliveryListener() {
    const calculateDeliveryBtn = document.querySelector('.calculate-delivery');
    if (!calculateDeliveryBtn) {
        console.error("Brak przycisku .calculate-delivery w DOM");
        return;
    }
    calculateDeliveryBtn.addEventListener('click', calculateDelivery);

    // Listener dla przycisku czyszczenia kuriera
    const clearDeliveryBtn = document.querySelector('.clear-delivery');
    if (clearDeliveryBtn) {
        clearDeliveryBtn.addEventListener('click', clearDeliverySelection);
    }
}

/**
 * Klasa modala dostawy - obsługa wyboru kuriera, paginacja, własny kurier
 */
class DeliveryModal {
    constructor() {
        this.modal = null;
        this.quotes = [];
        this.currentPage = 1;
        this.itemsPerPage = 8; // domyślna wartość, przeliczana dynamicznie
        this.selectedOption = null;
        this.customCarrier = null;
        this.isCustomMode = false;
        this.VAT_RATE = 0.23;
        this.MARGIN_RATE = 0.30;

        this.init();
        this._resizeHandler = () => {
            if (this.modal && this.modal.classList.contains('active')) {
                this.calculateItemsPerPage();
                this.renderOptions();
            }
        };
        window.addEventListener('resize', this._resizeHandler);
    }

    init() {
        this.modal = document.getElementById('deliveryModal');
        if (!this.modal) {
            console.error('Delivery modal not found');
            return;
        }

        this.bindEvents();
    }

    bindEvents() {
        // Zamknięcie modala
        const closeBtn = document.getElementById('deliveryModalClose');
        const cancelBtn = document.getElementById('deliveryModalCancel');

        closeBtn?.addEventListener('click', () => this.hide());
        cancelBtn?.addEventListener('click', () => this.hide());

        // Zamknięcie przez kliknięcie w tło
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) {
                this.hide();
            }
        });

        // Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal.classList.contains('active')) {
                this.hide();
            }
        });

        // Przycisk dodania własnego kuriera
        const addCustomBtn = document.getElementById('addCustomCarrier');
        addCustomBtn?.addEventListener('click', () => this.showCustomForm());

        // Powrót do listy
        const backBtn = document.getElementById('backToDeliveryList');
        backBtn?.addEventListener('click', () => this.showMainView());

        // Paginacja
        const prevBtn = document.getElementById('deliveryPrevPage');
        const nextBtn = document.getElementById('deliveryNextPage');

        prevBtn?.addEventListener('click', () => this.goToPreviousPage());
        nextBtn?.addEventListener('click', () => this.goToNextPage());

        // Formularz własnego kuriera
        this.bindCustomFormEvents();

        // Potwierdzenie wyboru
        const confirmBtn = document.getElementById('deliveryModalConfirm');
        confirmBtn?.addEventListener('click', () => this.confirmSelection());
    }

    bindCustomFormEvents() {
        const nettoInput = document.getElementById('customCarrierNetto');
        const bruttoInput = document.getElementById('customCarrierBrutto');
        const nameInput = document.getElementById('customCarrierName');

        // Auto-kalkulacja netto <-> brutto
        nettoInput?.addEventListener('input', (e) => {
            const netto = parseFloat(e.target.value) || 0;
            const brutto = netto * (1 + this.VAT_RATE);
            bruttoInput.value = brutto.toFixed(2);
            this.updateCalculator(brutto);
            this.validateCustomForm();
        });

        bruttoInput?.addEventListener('input', (e) => {
            const brutto = parseFloat(e.target.value) || 0;
            const netto = brutto / (1 + this.VAT_RATE);
            nettoInput.value = netto.toFixed(2);
            this.updateCalculator(brutto);
            this.validateCustomForm();
        });

        nameInput?.addEventListener('input', () => {
            this.validateCustomForm();
        });
    }

    /**
     * Oblicza ile opcji mieści się w dostępnej przestrzeni modala
     */
    calculateItemsPerPage() {
        const container = this.modal?.querySelector('.delivery-modal-container');
        const optionsEl = this.modal?.querySelector('.delivery-modal-options');
        if (!container || !optionsEl) return;

        // Wysokość jednej opcji — zmierz z DOM lub użyj domyślnej
        const firstOption = this.modal.querySelector('.delivery-modal-option');
        const OPTION_HEIGHT = firstOption ? firstOption.offsetHeight + 2 : 46; // +2 za gap

        // Dostępna wysokość modala
        const modalMaxH = window.innerHeight * 0.9; // max-height: 90vh

        // Wysokość stałych elementów (header, nagłówki, paginacja, footer, paddingi)
        const header = this.modal.querySelector('.delivery-modal-header');
        const headers = this.modal.querySelector('.delivery-modal-headers');
        const addCustomBtn = this.modal.querySelector('.delivery-modal-add-custom');
        const pagination = this.modal.querySelector('.delivery-modal-pagination');
        const packingInfo = this.modal.querySelector('.delivery-modal-packing-info');
        const footer = this.modal.querySelector('.delivery-modal-footer');

        let fixedHeight = 32; // padding kontenera
        if (header) fixedHeight += header.offsetHeight + 24; // + margin-bottom
        if (headers) fixedHeight += headers.offsetHeight + 16;
        if (addCustomBtn) fixedHeight += addCustomBtn.offsetHeight + 12;
        if (pagination) fixedHeight += 50; // miejsce na paginację
        if (packingInfo && !packingInfo.classList.contains('delivery-modal-hidden')) fixedHeight += packingInfo.offsetHeight + 8;
        if (footer) fixedHeight += footer.offsetHeight;

        const availableHeight = modalMaxH - fixedHeight;
        const count = Math.max(3, Math.floor(availableHeight / OPTION_HEIGHT));

        this.itemsPerPage = count;
    }

    show(quotes, packingInfo = null) {
        this.quotes = quotes || [];
        this.currentPage = 1;
        this.selectedOption = null;
        this.customCarrier = null;

        // Sortuj opcje po cenie
        this.quotes.sort((a, b) => (a.grossPrice || 0) - (b.grossPrice || 0));

        this.showMainView();
        this.updatePackingInfo(packingInfo);
        this.updateConfirmButton();

        // Pokaż modal z animacją
        this.modal.style.display = 'flex';
        requestAnimationFrame(() => {
            this.modal.classList.add('active');
            // Oblicz po renderze żeby elementy miały wymiary
            requestAnimationFrame(() => {
                this.calculateItemsPerPage();
                this.renderOptions();
            });
        });
    }

    hide() {
        this.modal.classList.remove('active');
        setTimeout(() => {
            this.modal.style.display = 'none';
        }, 300);
    }

    showError(message) {
        this.hideAllStates();

        const errorEl = document.getElementById('deliveryError');
        const errorMsgEl = document.getElementById('deliveryErrorMessage');

        if (errorEl && errorMsgEl) {
            errorMsgEl.textContent = message;
            errorEl.classList.remove('delivery-modal-hidden');
        }

        this.updateConfirmButton();
    }

    showMainView() {
        this.isCustomMode = false;

        const mainView = document.getElementById('deliveryMainView');
        const customView = document.getElementById('deliveryCustomView');

        if (mainView) {
            mainView.classList.remove('delivery-modal-hidden');
        }

        if (customView) {
            customView.classList.add('delivery-modal-hidden');
            customView.style.display = 'none';
        }

        // Aktualizuj tytuł
        const title = document.querySelector('.delivery-modal-title');
        if (title) {
            title.textContent = 'Wybierz sposób dostawy';
        }

        this.updateConfirmButton();
    }

    showCustomForm() {
        this.isCustomMode = true;

        // ✅ POPRAWKA: Ukryj główny widok i pokaż formularz
        const mainView = document.getElementById('deliveryMainView');
        const customView = document.getElementById('deliveryCustomView');

        if (mainView) {
            mainView.classList.add('delivery-modal-hidden');
        }

        if (customView) {
            customView.classList.remove('delivery-modal-hidden');
            customView.style.display = 'block';  // ✅ DODAJ to!
            // LUB dodaj klasę active:
            // customView.classList.add('active');
        }

        // Aktualizuj tytuł
        const title = document.querySelector('.delivery-modal-title');
        if (title) {
            title.textContent = 'Dodaj własnego kuriera';
        }

        // Wyczyść formularz
        const nameInput = document.getElementById('customCarrierName');
        const nettoInput = document.getElementById('customCarrierNetto');
        const bruttoInput = document.getElementById('customCarrierBrutto');

        if (nameInput) nameInput.value = '';
        if (nettoInput) nettoInput.value = '';
        if (bruttoInput) bruttoInput.value = '';

        this.updateCalculator(0);

        this.selectedOption = null;
        this.customCarrier = null;
        this.updateConfirmButton();
    }

    renderOptions() {
        if (this.quotes.length === 0) {
            this.showEmptyState();
            return;
        }

        this.hideAllStates();

        const listEl = document.getElementById('deliveryOptionsList');
        if (!listEl) return;

        // Oblicz paginację
        const totalPages = Math.ceil(this.quotes.length / this.itemsPerPage);
        const startIndex = (this.currentPage - 1) * this.itemsPerPage;
        const endIndex = startIndex + this.itemsPerPage;
        const currentQuotes = this.quotes.slice(startIndex, endIndex);

        // Wyczyść listę
        listEl.innerHTML = '';

        // Renderuj opcje
        currentQuotes.forEach((quote, index) => {
            const optionEl = this.createOptionElement(quote, startIndex + index);
            listEl.appendChild(optionEl);
        });

        // Aktualizuj paginację
        this.updatePagination(totalPages);

        // Pokaż listę
        document.getElementById('deliveryOptionsList').classList.remove('delivery-modal-hidden');
    }

    createOptionElement(quote, index) {
        const div = document.createElement('div');
        div.className = 'delivery-modal-option';
        div.dataset.index = index;

        const radioId = `delivery-option-${index}`;

        div.innerHTML = `
            <input type="radio"
                name="deliveryOption"
                id="${radioId}"
                value="${quote.carrierName}"
                data-gross="${quote.grossPrice}"
                data-net="${quote.netPrice}"
                data-raw-gross="${quote.rawGrossPrice || quote.grossPrice}"
                data-raw-net="${quote.rawNetPrice || quote.netPrice}">

            <div class="delivery-modal-name-container">
                <img src="${quote.carrierLogoLink || '/static/images/default-carrier.png'}"
                    class="delivery-modal-logo"
                    alt="${quote.carrierName} logo"
                    onerror="this.src='/static/images/default-carrier.png'">
                <div class="delivery-modal-name">${quote.carrierName}</div>
            </div>

            <div class="delivery-modal-price delivery-modal-price-adjusted">
                <div class="delivery-modal-price-brutto">${(quote.grossPrice || 0).toFixed(2)} PLN</div>
                <div class="delivery-modal-price-netto">${(quote.netPrice || 0).toFixed(2)} PLN netto</div>
            </div>

            <div class="delivery-modal-price delivery-modal-price-original">
                <div class="delivery-modal-price-brutto">${(quote.rawGrossPrice || quote.grossPrice || 0).toFixed(2)} PLN</div>
                <div class="delivery-modal-price-netto">${(quote.rawNetPrice || quote.netPrice || 0).toFixed(2)} PLN netto</div>
            </div>
        `;

        // Event listenery
        const radio = div.querySelector('input[type="radio"]');

        div.addEventListener('click', () => {
            if (radio && !radio.checked) {
                radio.checked = true;
                this.selectOption(quote, index);
            }
        });

        radio.addEventListener('change', () => {
            if (radio.checked) {
                this.selectOption(quote, index);
            }
        });

        return div;
    }

    selectOption(quote, index) {
        // Usuń poprzednie zaznaczenie
        document.querySelectorAll('.delivery-modal-option').forEach(el => {
            el.classList.remove('selected');
        });

        // Zaznacz nową opcję
        const optionEl = document.querySelector(`[data-index="${index}"]`);
        if (optionEl) {
            optionEl.classList.add('selected');
        }

        this.selectedOption = {
            carrierName: quote.carrierName,
            grossPrice: quote.grossPrice,
            netPrice: quote.netPrice,
            rawGrossPrice: quote.rawGrossPrice || quote.grossPrice,
            rawNetPrice: quote.rawNetPrice || quote.netPrice,
            carrierLogoLink: quote.carrierLogoLink,
            type: 'api'
        };

        this.customCarrier = null;
        this.updateConfirmButton();
    }

    updatePagination(totalPages) {
        const paginationEl = document.getElementById('deliveryPagination');
        const prevBtn = document.getElementById('deliveryPrevPage');
        const nextBtn = document.getElementById('deliveryNextPage');
        const pageNumbersEl = document.getElementById('deliveryPageNumbers');

        if (!paginationEl) return;

        // Pokaż/ukryj paginację
        if (totalPages <= 1) {
            paginationEl.classList.add('delivery-modal-hidden');
            return;
        }

        paginationEl.classList.remove('delivery-modal-hidden');

        // Aktualizuj przyciski
        if (prevBtn) {
            prevBtn.disabled = this.currentPage <= 1;
        }
        if (nextBtn) {
            nextBtn.disabled = this.currentPage >= totalPages;
        }

        // Generuj numery stron
        if (pageNumbersEl) {
            pageNumbersEl.innerHTML = '';

            for (let i = 1; i <= totalPages; i++) {
                const pageBtn = document.createElement('button');
                pageBtn.className = 'delivery-modal-page-btn';
                pageBtn.textContent = i;
                pageBtn.dataset.page = i;

                if (i === this.currentPage) {
                    pageBtn.classList.add('active');
                }

                pageBtn.addEventListener('click', () => {
                    this.goToPage(i);
                });

                pageNumbersEl.appendChild(pageBtn);
            }
        }
    }

    goToPage(page) {
        const totalPages = Math.ceil(this.quotes.length / this.itemsPerPage);
        if (page < 1 || page > totalPages) return;

        this.currentPage = page;
        this.renderOptions();
    }

    goToPreviousPage() {
        this.goToPage(this.currentPage - 1);
    }

    goToNextPage() {
        this.goToPage(this.currentPage + 1);
    }

    updateCalculator(bruttoAmount) {
        const baseBruttoEl = document.getElementById('calcBaseBrutto');
        const marginEl = document.getElementById('calcMargin');
        const finalPriceEl = document.getElementById('calcFinalPrice');

        if (!baseBruttoEl || !marginEl || !finalPriceEl) return;

        const margin = bruttoAmount * this.MARGIN_RATE;
        const finalPrice = bruttoAmount + margin;

        baseBruttoEl.textContent = `${bruttoAmount.toFixed(2)} PLN`;
        marginEl.textContent = `${margin.toFixed(2)} PLN`;
        finalPriceEl.textContent = `${finalPrice.toFixed(2)} PLN`;
    }

    validateCustomForm() {
        const nameInput = document.getElementById('customCarrierName');
        const nettoInput = document.getElementById('customCarrierNetto');
        const bruttoInput = document.getElementById('customCarrierBrutto');

        if (!nameInput || !nettoInput || !bruttoInput) return false;

        const name = nameInput.value.trim();
        const netto = parseFloat(nettoInput.value) || 0;
        const brutto = parseFloat(bruttoInput.value) || 0;

        // Resetuj style błędów
        [nameInput, nettoInput, bruttoInput].forEach(input => {
            input.classList.remove('error');
        });

        let isValid = true;

        // Walidacja nazwy
        if (!name) {
            nameInput.classList.add('error');
            isValid = false;
        }

        // Walidacja kwot
        if (netto <= 0 || brutto <= 0) {
            if (netto <= 0) nettoInput.classList.add('error');
            if (brutto <= 0) bruttoInput.classList.add('error');
            isValid = false;
        }

        if (isValid) {
            // Oblicz końcową cenę z marżą
            const finalPrice = brutto * (1 + this.MARGIN_RATE);

            this.customCarrier = {
                carrierName: name,
                grossPrice: finalPrice,
                netPrice: finalPrice / (1 + this.VAT_RATE),
                rawGrossPrice: brutto,
                rawNetPrice: netto,
                type: 'custom'
            };
        } else {
            this.customCarrier = null;
        }

        this.updateConfirmButton();
        return isValid;
    }

    updateConfirmButton() {
        const confirmBtn = document.getElementById('deliveryModalConfirm');
        const confirmText = document.getElementById('deliveryConfirmText');

        if (!confirmBtn || !confirmText) return;

        const hasSelection = this.selectedOption || this.customCarrier;

        confirmBtn.disabled = !hasSelection;

        if (this.isCustomMode) {
            confirmText.textContent = this.customCarrier ? 'Dodaj kuriera' : 'Uzupełnij dane';
        } else {
            confirmText.textContent = this.selectedOption ? 'Zapisz' : 'Zapisz';
        }
    }

    updatePackingInfo(packingInfo) {
        const packingInfoEl = document.getElementById('deliveryPackingInfo');
        const headerAdjustedEl = document.getElementById('deliveryHeaderAdjusted');

        if (packingInfo && packingInfoEl) {
            const percent = Math.round((packingInfo.multiplier - 1) * 100);
            packingInfoEl.innerHTML = `ℹ️ ${packingInfo.message || `Do cen wysyłki została doliczona kwota ${percent}% na pakowanie.`}`;
            packingInfoEl.classList.remove('delivery-modal-hidden');

            if (headerAdjustedEl) {
                headerAdjustedEl.textContent = `Cena + ${percent}%`;
            }
        } else {
            packingInfoEl?.classList.add('delivery-modal-hidden');
        }
    }

    hideAllStates() {
        const states = ['deliveryLoading', 'deliveryEmpty', 'deliveryError'];
        states.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.classList.add('delivery-modal-hidden');
        });
    }

    showEmptyState() {
        this.hideAllStates();
        const emptyEl = document.getElementById('deliveryEmpty');
        if (emptyEl) {
            emptyEl.classList.remove('delivery-modal-hidden');
        }
        this.updateConfirmButton();
    }

    showLoadingState() {
        this.hideAllStates();
        const loadingEl = document.getElementById('deliveryLoading');
        if (loadingEl) {
            loadingEl.classList.remove('delivery-modal-hidden');
        }
    }

    confirmSelection() {
        const selection = this.isCustomMode ? this.customCarrier : this.selectedOption;

        if (!selection) {
            alert('Proszę wybrać opcję dostawy lub uzupełnić dane własnego kuriera.');
            return;
        }

        // Wywołaj callback lub event
        this.onSelectionConfirmed(selection);
        this.hide();
    }

    onSelectionConfirmed(selection) {
        // Ta metoda powinna być nadpisana lub można dodać event listener
        // Kompatybilność z istniejącym kodem
        if (typeof window.handleDeliverySelection === 'function') {
            window.handleDeliverySelection(selection);
        }

        // Wywołaj event
        const event = new CustomEvent('deliverySelected', {
            detail: selection
        });
        document.dispatchEvent(event);
    }
}

// Inicjalizacja
let deliveryModalInstance = null;

// Funkcje kompatybilności z istniejącym kodem
function showDeliveryModal(quotes, packingInfo = null) {
    if (!deliveryModalInstance) {
        deliveryModalInstance = new DeliveryModal();
    }

    // Przekształć dane do nowego formatu jeśli potrzeba
    const formattedQuotes = quotes.map(quote => ({
        carrierName: quote.carrierName || 'Nieznany kurier',
        grossPrice: quote.grossPrice || 0,
        netPrice: quote.netPrice || 0,
        rawGrossPrice: quote.rawGrossPrice || quote.grossPrice || 0,
        rawNetPrice: quote.rawNetPrice || quote.netPrice || 0,
        carrierLogoLink: quote.carrierLogoLink || '/static/images/default-carrier.png'
    }));

    deliveryModalInstance.show(formattedQuotes, packingInfo);
}

function showDeliveryErrorModal(errorMessage) {
    if (!deliveryModalInstance) {
        deliveryModalInstance = new DeliveryModal();
    }

    deliveryModalInstance.show([], null);
    deliveryModalInstance.showError(errorMessage);
}

// Event listener dla backward compatibility
document.addEventListener('deliverySelected', (event) => {
    const selection = event.detail;

    // Kompatybilność z istniejącym kodem calculator.js
    if (typeof updateDeliverySelection === 'function') {
        updateDeliverySelection(selection);
    }
});

// Auto-inicjalizacja gdy DOM jest gotowy
document.addEventListener('DOMContentLoaded', () => {
    if (!deliveryModalInstance) {
        deliveryModalInstance = new DeliveryModal();
    }
});

// ========== DETEKCJA NIEAKTUALNYCH KOSZTÓW WYSYŁKI ==========

let deliveryParamsSnapshot = null;

function takeDeliveryParamsSnapshot() {
    const forms = document.querySelectorAll('.quote-form');
    const products = [];
    forms.forEach(form => {
        products.push({
            length: form.querySelector('[data-field="length"]')?.value || '',
            width: form.querySelector('[data-field="width"]')?.value || '',
            thickness: form.querySelector('[data-field="thickness"]')?.value || '',
            quantity: form.querySelector('[data-field="quantity"]')?.value || '',
            shape: form.dataset.productShape || 'rectangular',
        });
    });
    return JSON.stringify({ count: forms.length, products });
}

function isDeliverySelected() {
    return deliverySummaryEls.courier && deliverySummaryEls.courier.textContent.trim() !== '';
}

function showDeliveryStaleBadge() {
    const badge = document.getElementById('deliveryStaleBadge');
    if (badge) badge.style.display = '';
    const summary = document.querySelector('.quote-summary');
    if (summary) summary.classList.add('delivery-stale');
}

function hideDeliveryStaleBadge() {
    const badge = document.getElementById('deliveryStaleBadge');
    if (badge) badge.style.display = 'none';
    const summary = document.querySelector('.quote-summary');
    if (summary) summary.classList.remove('delivery-stale');
}

function setDeliveryParamsSnapshot() {
    deliveryParamsSnapshot = takeDeliveryParamsSnapshot();
}

function checkDeliveryStale() {
    if (!deliveryParamsSnapshot || !isDeliverySelected()) return;
    const current = takeDeliveryParamsSnapshot();
    if (current !== deliveryParamsSnapshot) {
        showDeliveryStaleBadge();
    } else {
        hideDeliveryStaleBadge();
    }
}

// Inicjalizacja listenerow po DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
    // Badge klikniety = oblicz wysylke
    const badge = document.getElementById('deliveryStaleBadge');
    if (badge) {
        badge.addEventListener('click', () => {
            if (typeof calculateDelivery === 'function') {
                calculateDelivery();
            }
        });
    }

    // Nasluchuj zmian w kalkulatorze ktore wplywaja na wysylke
    const calculator = document.querySelector('.calculatorrr');
    if (calculator) {
        const handleShippingChange = () => {
            checkDeliveryStale();
            // Dodatkowy check z opoznieniem (np. po dodaniu produktu)
            setTimeout(checkDeliveryStale, 400);
        };
        calculator.addEventListener('input', handleShippingChange, true);
        calculator.addEventListener('change', handleShippingChange, true);
    }

    // Obserwuj dodawanie/usuwanie produktow (formularzy)
    const formsContainer = document.querySelector('.quote-forms');
    if (formsContainer) {
        new MutationObserver(() => {
            setTimeout(checkDeliveryStale, 200);
        }).observe(formsContainer, { childList: true });
    }
});

// Eksport do globalnego obiektu window
window.CalculatorDelivery = {
    showRotatingMessages,
    stopRotatingMessages,
    getShippingParamsHash,
    getShippingCache,
    setShippingCache,
    calculateDelivery,
    updateCalculateDeliveryButtonState,
    updateDeliverySelection,
    clearDeliverySelection,
    attachCalculateDeliveryListener,
    showDeliveryModal,
    showDeliveryErrorModal,
    DeliveryModal,
    checkDeliveryStale,
    hideDeliveryStaleBadge,
    setDeliveryParamsSnapshot
};
