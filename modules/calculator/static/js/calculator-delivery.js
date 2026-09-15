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

/**
 * Pyta backend o ceny końcowe wysyłki dla podanych cen surowych z GlobKuriera.
 *
 * Formuła (narzut % + dopłata progowa) żyje WYŁĄCZNIE w backendzie
 * (shipping_pricing.py). Tutaj tylko pytamy o wynik — dzięki temu kalkulator
 * i bot Dębuś nie mogą podać klientowi dwóch różnych cen tej samej paczki.
 */
async function fetchShippingMarkup(grossPrices) {
    const response = await fetch('/calculator/api/shipping-markup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gross_prices: grossPrices })
    });

    if (!response.ok) {
        throw new Error(`shipping-markup: HTTP ${response.status}`);
    }

    // Wygasła sesja potrafi odpowiedzieć 200 OK stroną logowania (HTML), nie
    // JSON-em — response.ok jest wtedy `true`, więc bez tej kontroli błąd
    // ujawniłby się dopiero jako SyntaxError z response.json().
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
        throw new Error('shipping-markup: odpowiedź nie jest w formacie JSON (wygasła sesja?)');
    }

    return response.json();
}

async function calculateDelivery() {
    const overlay = document.getElementById('loadingOverlay');

    if (overlay) {
        overlay.style.display = 'flex';
        showRotatingMessages(overlay);
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

    const paramsHash = getShippingParamsHash(shippingParams);

    try {
        // Cache trzyma SUROWE odpowiedzi GlobKuriera (TTL 24 h). Narzut dolicza
        // backend przy każdym otwarciu modala, więc zmiana ustawień w panelu
        // działa natychmiast — także na przeglądarce z ciepłym cache'em.
        let quotesList = getShippingCache(paramsHash);

        if (!quotesList) {
            const response = await fetch('/calculator/shipping_quote', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(shippingParams)
            });

            if (!response.ok) {
                let errorMessage = "Błąd podczas wyceny wysyłki.";

                try {
                    const errorData = await response.json();

                    if (errorData.error) {
                        errorMessage = errorData.error;
                    } else {
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
                    console.error("Nie można sparsować odpowiedzi błędu:", e);

                    if (response.status === 502 || response.status === 503 || response.status === 504) {
                        errorMessage = "Serwis kurierski chwilowo niedostępny. Spróbuj ponownie za chwilę.";
                    }
                }

                console.error("Błąd w żądaniu wyceny wysyłki:", response.status, errorMessage);
                showDeliveryErrorModal(errorMessage);
                return;
            }

            const quotesData = await response.json();
            quotesList = Array.isArray(quotesData) ? quotesData : [quotesData];
            setShippingCache(paramsHash, quotesList);
        }

        // Serwer odrzuca oferty bez liczbowej ceny u źródła (serializuj_oferty
        // w shipping_service.py), ale ten filtr działa tylko przy świeżym
        // zapytaniu do GlobKuriera. Cache w localStorage trzyma surowe
        // odpowiedzi do 24h (SHIPPING_CACHE_TTL) — oferta zapisana w cache'u
        // PRZED tą poprawką wciąż może go ominąć, więc filtrujemy też tutaj,
        // niezależnie od filtra serwerowego. Nie usuwaj jako "duplikat" —
        // to jedyna ochrona dla ciepłego cache'a sprzed zmiany.
        quotesList = quotesList.filter(
            option => typeof option.grossPrice === 'number' && isFinite(option.grossPrice)
        );

        if (quotesList.length === 0) {
            showDeliveryErrorModal("Brak dostępnych metod dostawy.");
            return;
        }

        const markup = await fetchShippingMarkup(quotesList.map(option => option.grossPrice));

        const quotes = quotesList.map((option, index) => {
            const wyliczenie = markup.items[index];
            return {
                carrierName: option.carrierName,
                rawGrossPrice: wyliczenie.raw_brutto,
                rawNetPrice: wyliczenie.raw_netto,
                grossPrice: wyliczenie.final_brutto,
                netPrice: wyliczenie.final_netto,
                carrierLogoLink: option.carrierLogoLink || ""
            };
        });

        showDeliveryModal(quotes, { info: markup.info, config: markup.config });
    } catch (error) {
        console.error("Wyjątek przy wycenie wysyłki:", error);

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
        // VAT zostaje — służy przeliczaniu netto<->brutto w formularzu własnego
        // kuriera. Narzut na pakowanie NIE jest już liczony w JS.
        this.VAT_RATE = 0.23;
        // Ostatni rozkład ceny z /calculator/api/shipping-markup i konfiguracja,
        // którą przysłał backend (potrzebna do etykiet).
        this.markup = null;
        this.markupConfig = null;
        this.customMarkupTimer = null;
        this.customMarkupSeq = 0;

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

        // Auto-kalkulacja netto <-> brutto. To sam VAT, nie narzut na pakowanie
        // — dlatego zostaje po stronie przeglądarki.
        nettoInput?.addEventListener('input', (e) => {
            const netto = parseFloat(e.target.value) || 0;
            const brutto = netto * (1 + this.VAT_RATE);
            bruttoInput.value = brutto.toFixed(2);
            this.scheduleCustomMarkup(brutto);
        });

        bruttoInput?.addEventListener('input', (e) => {
            const brutto = parseFloat(e.target.value) || 0;
            const netto = brutto / (1 + this.VAT_RATE);
            nettoInput.value = netto.toFixed(2);
            this.scheduleCustomMarkup(brutto);
        });

        nameInput?.addEventListener('input', () => {
            this.validateCustomForm();
        });
    }

    /**
     * Pyta backend o rozkład ceny dla ręcznie wpisanej kwoty własnego kuriera.
     * Debounce, żeby nie strzelać żądaniem na każdy znak.
     *
     * Numer żądania jest konieczny obok debounce'u: clearTimeout anuluje timer,
     * który jeszcze nie wystartował, ale NIE anuluje zapytania już wysłanego.
     * Odpowiedzi potrafią wrócić w odwrotnej kolejności i bez tego strażnika
     * starsza nadpisałaby nowszą — w this.markup zostałaby cena niepasująca do
     * pola formularza i taka trafiłaby do wyceny klienta.
     */
    scheduleCustomMarkup(bruttoAmount) {
        clearTimeout(this.customMarkupTimer);
        const numerZadania = ++this.customMarkupSeq;

        if (!(bruttoAmount > 0)) {
            this.markup = null;
            this.updateCalculator(null);
            this.validateCustomForm();
            return;
        }

        this.customMarkupTimer = setTimeout(async () => {
            try {
                const odpowiedz = await fetchShippingMarkup([bruttoAmount]);
                if (numerZadania !== this.customMarkupSeq) return;
                this.markup = odpowiedz.items[0];
                this.markupConfig = odpowiedz.config;
                this.hideCustomMarkupError();
            } catch (error) {
                if (numerZadania !== this.customMarkupSeq) return;
                console.error('Nie udało się przeliczyć ceny własnego kuriera:', error);
                this.markup = null;
                // Bez tego handlowiec widzi tylko wyzerowany panel i zablokowany
                // przycisk "Uzupełnij dane" — bez żadnej wskazówki, co poszło nie tak.
                this.showCustomMarkupError();
            }
            this.updateCalculator(this.markup);
            this.validateCustomForm();
        }, 300);
    }

    /**
     * Widoczny komunikat błędu przeliczenia ceny własnego kuriera. Bez niego
     * awaria endpointu /api/shipping-markup objawia się tylko zerami w
     * kalkulatorze i wiecznie zablokowanym przyciskiem "Uzupełnij dane".
     */
    showCustomMarkupError() {
        const el = document.getElementById('customCarrierMarkupError');
        if (el) el.classList.remove('delivery-modal-hidden');
    }

    hideCustomMarkupError() {
        const el = document.getElementById('customCarrierMarkupError');
        if (el) el.classList.add('delivery-modal-hidden');
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

    show(quotes, markupInfo = null) {
        this.quotes = quotes || [];
        this.currentPage = 1;
        this.selectedOption = null;
        this.customCarrier = null;
        this.markup = null;
        // Unieważnij ewentualne oczekujące żądanie sprzed otwarcia modala —
        // strażnik w scheduleCustomMarkup broni tylko odpowiedzi już wysłanego
        // żądania, nie samego resetu stanu, więc bez tego spóźniona odpowiedź
        // nadal wyglądałaby na aktualną.
        clearTimeout(this.customMarkupTimer);
        ++this.customMarkupSeq;

        // Sortowanie po cenie KOŃCOWEJ — grossPrice niesie już narzut i dopłatę.
        this.quotes.sort((a, b) => (a.grossPrice || 0) - (b.grossPrice || 0));

        this.showMainView();
        this.updatePackingInfo(markupInfo);
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

        this.markup = null;
        // Jak w show() — anuluj timer i podbij licznik, żeby żądanie
        // wystrzelone tuż przed ponownym otwarciem formularza nie nadpisało
        // świeżo wyczyszczonego stanu spóźnioną odpowiedzią.
        clearTimeout(this.customMarkupTimer);
        ++this.customMarkupSeq;
        this.hideCustomMarkupError();
        this.updateCalculator(null);

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

    /**
     * Renderuje rozkład ceny w panelu „Kalkulacja końcowej ceny".
     * Przyjmuje gotowy wynik z backendu albo null (wyzerowanie panelu).
     */
    updateCalculator(markup) {
        const baseBruttoEl = document.getElementById('calcBaseBrutto');
        const marginEl = document.getElementById('calcMargin');
        const marginLabelEl = document.getElementById('calcMarginLabel');
        const surchargeRowEl = document.getElementById('calcSurchargeRow');
        const surchargeEl = document.getElementById('calcSurcharge');
        const finalPriceEl = document.getElementById('calcFinalPrice');

        if (!baseBruttoEl || !marginEl || !finalPriceEl) return;

        const puste = { raw_brutto: 0, markup_brutto: 0, surcharge_brutto: 0, final_brutto: 0 };
        const dane = markup || puste;

        baseBruttoEl.textContent = `${dane.raw_brutto.toFixed(2)} PLN`;
        marginEl.textContent = `${dane.markup_brutto.toFixed(2)} PLN`;
        finalPriceEl.textContent = `${dane.final_brutto.toFixed(2)} PLN`;

        if (marginLabelEl) {
            marginLabelEl.textContent = `Koszty pakowania (+${this.formatPercent()}):`;
        }

        if (surchargeRowEl && surchargeEl) {
            const maDoplate = dane.surcharge_brutto > 0;
            surchargeEl.textContent = `${dane.surcharge_brutto.toFixed(2)} PLN`;
            surchargeRowEl.classList.toggle('delivery-modal-hidden', !maDoplate);
        }
    }

    /**
     * Tekst procentu narzutu (np. „30%") w postaci przysłanej przez backend
     * (config.percent_label z /calculator/api/shipping-markup). Liczbę
     * formatuje WYŁĄCZNIE backend (_procent w shipping_pricing.py) — dwie
     * niezależne implementacje (zaokrąglenie bankierskie w Pythonie kontra
     * toFixed w JS, zawsze od zera) przy remisie potrafiły dać różny tekst.
     * Znak „+" dopisują wywołujący, w otaczającym tekście — patrz wywołania
     * niżej. Bez konfiguracji z backendu zwraca pusty placeholder, nie
     * zmyśla liczby.
     */
    formatPercent() {
        return this.markupConfig?.percent_label ?? 'narzut';
    }

    validateCustomForm() {
        const nameInput = document.getElementById('customCarrierName');
        const nettoInput = document.getElementById('customCarrierNetto');
        const bruttoInput = document.getElementById('customCarrierBrutto');

        if (!nameInput || !nettoInput || !bruttoInput) return false;

        const name = nameInput.value.trim();
        const netto = parseFloat(nettoInput.value) || 0;
        const brutto = parseFloat(bruttoInput.value) || 0;

        [nameInput, nettoInput, bruttoInput].forEach(input => {
            input.classList.remove('error');
        });

        let isValid = true;

        if (!name) {
            nameInput.classList.add('error');
            isValid = false;
        }

        if (netto <= 0 || brutto <= 0) {
            if (netto <= 0) nettoInput.classList.add('error');
            if (brutto <= 0) bruttoInput.classList.add('error');
            isValid = false;
        }

        // Kwota końcowa pochodzi z backendu (this.markup). Dopóki jej nie ma,
        // kuriera nie da się zatwierdzić — lepiej zablokowany przycisk niż
        // zapisana wycena z ceną bez narzutu.
        if (isValid && this.markup) {
            this.customCarrier = {
                carrierName: name,
                grossPrice: this.markup.final_brutto,
                netPrice: this.markup.final_netto,
                rawGrossPrice: this.markup.raw_brutto,
                rawNetPrice: this.markup.raw_netto,
                type: 'custom'
            };
        } else {
            this.customCarrier = null;
            isValid = false;
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

    /**
     * Wyświetla opis narzutu przysłany przez backend. Nie składamy tu zdania
     * z mnożnika — tekst przychodzi gotowy z describe_shipping_markup().
     */
    updatePackingInfo(markupInfo) {
        const packingInfoEl = document.getElementById('deliveryPackingInfo');
        const headerAdjustedEl = document.getElementById('deliveryHeaderAdjusted');

        if (markupInfo && markupInfo.info && packingInfoEl) {
            this.markupConfig = markupInfo.config || null;
            packingInfoEl.innerHTML = `ℹ️ ${markupInfo.info}`;
            packingInfoEl.classList.remove('delivery-modal-hidden');

            if (headerAdjustedEl) {
                headerAdjustedEl.textContent = `Cena +${this.formatPercent()}`;
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
function showDeliveryModal(quotes, markupInfo = null) {
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

    deliveryModalInstance.show(formattedQuotes, markupInfo);
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
