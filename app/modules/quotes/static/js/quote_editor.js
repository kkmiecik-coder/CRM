/**
 * Quote Editor - Edycja wycen w module quotes
 * Wykorzystuje logikę z modułu calculator
 * ZOPTYMALIZOWANA WERSJA
 */

// ==================== ZMIENNE GLOBALNE ====================
let currentEditingQuoteData = null;
let activeProductIndex = null;
let clientTypesCache = null;
let finishingDataCache = null;
let calculatorScriptLoaded = false;
let calculatorInitialized = false;

// Optimized logging - centralized debug control
const DEBUG_LOGS = {
    editor: true,
    calculator: false,
    finishing: false,
    sync: true
};

// Centralized logger to reduce repetitive logging
function log(category, message, data = null) {
    if (DEBUG_LOGS[category] || DEBUG_LOGS.editor) {
        const prefix = `[QUOTE EDITOR ${category.toUpperCase()}]`;
        if (data) {
            console.log(prefix, message, data);
        } else {
            console.log(prefix, message);
        }
    }
}

// ==================== GŁÓWNE FUNKCJE EDYTORA ====================

function debugIncomingQuoteData(quoteData, context = 'unknown') {
    console.log(`=== DEBUG INCOMING DATA (${context}) ===`);
    console.log('Quote ID:', quoteData?.id);
    console.log('Wszystkich pozycji:', quoteData?.items?.length || 0);

    if (quoteData?.items) {
        console.log('=== ANALIZA POZYCJI ===');
        quoteData.items.forEach((item, index) => {
            console.log(`Pozycja ${index}:`, {
                id: item.id,
                variant_code: item.variant_code,
                product_index: item.product_index,
                show_on_client_page: item.show_on_client_page,
                is_selected: item.is_selected
            });
        });

        console.log('=== UNIKALNE VARIANT_CODE ===');
        const uniqueVariants = [...new Set(quoteData.items.map(item => item.variant_code))];
        console.log('Unikalne warianty:', uniqueVariants);
        console.log('Liczba unikalnych wariantów:', uniqueVariants.length);
    }

    console.log('=== KONIEC DEBUG DATA ===');
}

/**
 * Główna funkcja otwierania edytora - zoptymalizowana
 */
async function openQuoteEditor(quoteData) {
    log('editor', '===== OTWIERANIE EDYTORA WYCENY =====');

    // DEBUGOWANIE: Sprawdź dane wejściowe
    debugIncomingQuoteData(quoteData, 'openQuoteEditor - wejście');

    // Walidacja wstępna
    if (!validateQuoteData(quoteData)) return;

    // DEBUGOWANIE: Sprawdź czy dane nie są modyfikowane po walidacji
    debugIncomingQuoteData(quoteData, 'openQuoteEditor - po walidacji');

    // Przygotowanie środowiska
    currentEditingQuoteData = quoteData;

    // DEBUGOWANIE: Sprawdź currentEditingQuoteData po przypisaniu
    console.log('=== DEBUG currentEditingQuoteData PO PRZYPISANIU ===');
    debugIncomingQuoteData(currentEditingQuoteData, 'currentEditingQuoteData - po przypisaniu');

    const modal = initializeModal();
    if (!modal) return;

    // Batch operations - grupuj operacje DOM
    updateModalHeader(quoteData);
    modal.style.display = 'flex';

    try {
        // Asynchroniczne ładowanie w odpowiedniej kolejności
        await Promise.all([
            loadCalculatorIfNeeded(),
            loadClientTypesFromDatabase()
        ]);

        await initializeFinishingPrices();

        // DEBUGOWANIE: Sprawdź dane przed loadQuoteDataToEditor
        console.log('=== DEBUG PRZED loadQuoteDataToEditor ===');
        debugIncomingQuoteData(currentEditingQuoteData, 'przed loadQuoteDataToEditor');

        // Synchroniczne operacje po załadowaniu danych
        loadQuoteDataToEditor(quoteData);

        // DEBUGOWANIE: Sprawdź dane po loadQuoteDataToEditor
        console.log('=== DEBUG PO loadQuoteDataToEditor ===');
        debugIncomingQuoteData(currentEditingQuoteData, 'po loadQuoteDataToEditor');

        initializeEventListeners();

        // Finalizacja
        setupModalCloseHandlers();
        performInitialCalculations(quoteData);

        log('editor', '✅ Edytor wyceny otwarty pomyślnie');

    } catch (error) {
        console.error('[QUOTE EDITOR] ❌ BŁĄD podczas ładowania:', error);
    }
}

/**
 * Walidacja danych wyceny - wydzielona funkcja
 */
function validateQuoteData(quoteData) {
    if (!quoteData?.id) {
        console.error('[QUOTE EDITOR] ❌ Brak danych wyceny');
        alert('Błąd: Brak danych wyceny do edycji');
        return false;
    }

    if (!canEditQuote(quoteData)) {
        console.warn('[QUOTE EDITOR] ⚠️ Wycena nie może być edytowana');
        alert(`Ta wycena nie może być edytowana (status: ${quoteData.status_name || 'nieznany'})`);
        return false;
    }

    return true;
}

/**
 * Inicjalizacja modalu - wydzielona funkcja
 */
function initializeModal() {
    const modal = document.getElementById('quote-editor-modal');
    if (!modal) {
        console.error('[QUOTE EDITOR] ❌ Nie znaleziono modalu edytora');
        return null;
    }
    return modal;
}

/**
 * Aktualizacja nagłówka modalu - batch DOM operations
 */
function updateModalHeader(quoteData) {
    const updates = [
        { id: 'edit-quote-number', text: `Wycena: ${quoteData.quote_number || 'N/A'}` },
        { id: 'edit-client-name', text: `Klient: ${quoteData.client?.client_name || quoteData.client?.client_number || 'N/A'}` }
    ];

    updates.forEach(({ id, text }) => {
        const element = document.getElementById(id);
        if (element) element.textContent = text;
    });
}

/**
 * Zoptymalizowane ładowanie calculator.js
 */
async function loadCalculatorIfNeeded() {
    if (calculatorScriptLoaded) {
        log('calculator', 'Calculator.js już załadowany');
        return true;
    }

    try {
        // Parallel loading of scripts
        await Promise.all([
            loadScript('/calculator/static/js/calculator.js'),
            loadScript('/calculator/static/js/save_quote.js')
        ]);

        calculatorScriptLoaded = true;
        initializeCalculatorForEditor();
        return true;

    } catch (error) {
        console.error('[QUOTE EDITOR] ❌ Błąd ładowania calculator.js:', error);
        return false;
    }
}

/**
 * Zoptymalizowana inicjalizacja event listeners
 */
function initializeEventListeners() {
    log('editor', 'Inicjalizacja event listeners...');

    const modal = document.getElementById('quote-editor-modal');
    if (!modal) {
        log('editor', '❌ Nie znaleziono modalu edytora');
        return;
    }

    // ✅ Event delegation dla wydajności
    modal.addEventListener('input', handleInputChange);
    modal.addEventListener('change', handleSelectChange);
    modal.addEventListener('click', handleButtonClick);

    // ✅ KLUCZOWA POPRAWKA: Specjalny listener dla grupy cenowej
    const clientTypeSelect = document.getElementById('edit-clientType');
    if (clientTypeSelect) {
        // Usuń poprzednie listenery dla pewności
        clientTypeSelect.removeEventListener('change', onClientTypeChange);

        // Dodaj nowy listener z większym priorytetem
        clientTypeSelect.addEventListener('change', onClientTypeChange);

        log('editor', '✅ Dodano specjalny listener dla grupy cenowej');
    }

    log('editor', '✅ Event listeners zainicjalizowane');
}

/**
 * Centralizowana obsługa zmian w inputach - debounced
 */
const handleInputChange = debounce((e) => {
    const target = e.target;

    if (target.matches('#edit-length, #edit-width, #edit-thickness, #edit-quantity')) {
        log('sync', `Input change: ${target.id} = "${target.value}"`);
        syncEditorToMockForm();
        onFormDataChange();
    }

    refreshProductCards();

}, 300);

/**
 * Centralizowana obsługa zmian w select-ach
 */
function handleSelectChange(e) {
    const radio = e.target;
    if (radio.type !== 'radio' || radio.name !== 'edit-variantOption') return;

    log('sync', `Variant change: ${radio.value}`);

    // Wywołaj oryginalną logikę
    onFormDataChange();

    // DODANE: Synchronizuj dataset po zmianie wariantu
    setTimeout(() => {
        syncRadioDatasetWithMockForm();
        // Odśwież podsumowanie po synchronizacji
        updateQuoteSummary();
        updateProductsSummaryTotals();
    }, 100);

    refreshProductCards();
}

/**
 * Centralizowana obsługa kliknięć w przyciski
 */
function handleButtonClick(e) {
    const target = e.target;

    // Color buttons (check first in case they contain inner elements)
    const colorButton = target.closest('.color-btn');
    if (colorButton) {
        handleColorButtonClick(colorButton);
        return;
    }

    // Finishing buttons
    const finishingButton = target.closest('.finishing-btn');
    if (finishingButton) {
        handleFinishingButtonClick(finishingButton);
        return;
    }

    // Copy product buttons
    const copyBtn = target.closest('.copy-product-btn');
    if (copyBtn) {
        e.stopPropagation();
        const productIndex = parseInt(copyBtn.dataset.index);
        copyProductInQuote(productIndex);
        return;
    }

    // Remove product buttons
    const removeBtn = target.closest('.remove-product-btn');
    if (removeBtn) {
        e.stopPropagation();
        const productIndex = parseInt(removeBtn.dataset.index);
        removeProductFromQuote(productIndex);
        return;
    }

    // Product cards (jeśli nie kliknięto w przyciski)
    const productCard = target.closest('.product-card');
    if (productCard && !target.closest('.product-card-actions')) {
        const productIndex = parseInt(productCard.dataset.index);
        activateProductInEditor(productIndex);
        return;
    }

    // Action buttons
    if (target.id === 'save-quote-changes') {
        saveQuoteChanges();
        return;
    }

    const addBtn = target.closest('#edit-add-product-btn');
    if (addBtn) {
        e.stopPropagation();
        // Zachowaj dane i koszty aktywnego produktu zanim dodamy nowy
        const activeProductCosts = calculateActiveProductCosts();
        const activeFinishingCosts = calculateActiveProductFinishingCosts();
        saveActiveProductFormData();
        updateActiveProductCostsInData(activeProductCosts, activeFinishingCosts);
        updateQuoteSummary();
        updateProductsSummaryTotals();
        // Defer execution to avoid interference with ongoing loops
        setTimeout(() => addNewProductToQuote(), 0);
        return;
    }

    if (target.id === 'close-quote-editor') {
        window.QuoteEditor.close();
        return;
    }

    // Obsługa zmiany grupy cenowej przez select
    if (target.id === 'edit-clientType') {
        handleClientTypeChange(e);
        return;
    }
}

// ==================== OPTIMIZED CALCULATOR INTEGRATION ====================

/**
 * Zoptymalizowana konfiguracja kalkulatora - NAPRAWIONA KOLEJNOŚĆ
 */
function setupCalculatorForEditor() {
    try {
        const container = findOrCreateContainer();
        const form = findOrCreateForm();

        if (!container || !form) {
            log('calculator', '❌ Nie można utworzyć kontenera lub formularza');
            return false;
        }

        // Ustawienie globalnych zmiennych z calculator.js
        window.quoteFormsContainer = container;
        window.activeQuoteForm = form;

        // POPRAWKA: Użyj bezpiecznej wersji zamiast oryginalnej funkcji
        try {
            // Sprawdź czy mamy bezpieczną wersję
            if (typeof safeAttachFinishingUIListeners === 'function') {
                safeAttachFinishingUIListeners(form);
                log('calculator', '✅ Zainicjalizowano przyciski wykończenia (bezpieczna wersja)');
            } else {
                // Fallback: spróbuj oryginalnej funkcji z error handling
                if (typeof attachFinishingUIListeners === 'function') {
                    attachFinishingUIListeners(form);
                    log('calculator', '✅ Zainicjalizowano przyciski wykończenia (oryginalna wersja)');
                }
            }
        } catch (error) {
            log('calculator', '⚠️ Błąd inicjalizacji przycisków wykończenia:', error);
            // Nie blokuj dalszej konfiguracji - aplikacja może działać bez wykończenia
        }

        addVariantsToCalculatorForm();
        log('calculator', '✅ Calculator.js skonfigurowany pomyślnie');
        return true;

    } catch (error) {
        console.error('[QUOTE EDITOR] ❌ Błąd konfiguracji calculator.js:', error);
        return false;
    }
}

/**
 * Znajdź lub stwórz kontener - POPRAWIONA WERSJA z lepszym error handling
 */
function findOrCreateContainer() {
    const modal = document.getElementById('quote-editor-modal');
    if (!modal) {
        console.error('[QUOTE EDITOR] Nie znaleziono modalu edytora');
        return null;
    }

    let container = modal.querySelector('.quote-forms-container');

    if (!container) {
        container = createElement('div', {
            className: 'quote-forms-container',
            style: 'display: none'
        });
        modal.appendChild(container);
        log('calculator', 'Utworzono nowy kontener formularzy');
    }

    return container;
}

/**
 * Znajdź lub stwórz formularz - POPRAWIONA WERSJA
 */
function findOrCreateForm() {
    // Najpierw upewnij się że container istnieje
    const container = window.quoteFormsContainer || findOrCreateContainer();
    if (!container) {
        console.error('[QUOTE EDITOR] Nie można znaleźć ani utworzyć kontenera');
        return null;
    }

    let form = container.querySelector('.quote-form');

    if (!form) {
        form = createElement('div', {
            className: 'quote-form',
            style: 'display: none',
            innerHTML: createMockFormHTML()
        });
        container.appendChild(form);
        log('calculator', 'Utworzono nowy formularz calculator.js');
    }

    return form;
}

/**
 * Helper do tworzenia elementów DOM
 */
function createElement(tag, options = {}) {
    const element = document.createElement(tag);

    Object.entries(options).forEach(([key, value]) => {
        if (key === 'style' && typeof value === 'string') {
            element.style.cssText = value;
        } else {
            element[key] = value;
        }
    });

    return element;
}

/**
 * Generowanie HTML dla mock formularza
 */
function createMockFormHTML() {
    return `
        <div class="product-inputs">
            <select data-field="clientType" style="display: none;">
                <option value="">Wybierz grupę</option>
                <option value="Florek">Florek</option>
                <option value="Hurt">Hurt</option>
                <option value="Detal">Detal</option>
                <option value="Detal+">Detal+</option>
            </select>
            <input type="number" data-field="length" style="display: none;">
            <input type="number" data-field="width" style="display: none;">
            <input type="number" data-field="thickness" style="display: none;">
            <input type="number" data-field="quantity" value="1" style="display: none;">
        </div>
        <div class="variants" style="display: none;"></div>
        
        <!-- ✅ SEKCJA WYKOŃCZENIA - KLUCZOWA POPRAWKA -->
        <div class="finishing-section" style="display: none;">
            <div class="finishing-type-group">
                <button type="button" class="finishing-btn active" data-finishing-type="Surowe">Surowe</button>
                <button type="button" class="finishing-btn" data-finishing-type="Lakierowanie">Lakierowanie</button>
                <button type="button" class="finishing-btn" data-finishing-type="Olejowanie">Olejowanie</button>
            </div>
            
            <div class="finishing-variant-wrapper" style="display: none;">
                <button type="button" class="finishing-btn" data-finishing-variant="Bezbarwne">Bezbarwne</button>
                <button type="button" class="finishing-btn" data-finishing-variant="Barwne">Barwne</button>
            </div>
            
            <div class="finishing-color-wrapper" style="display: none;">
                <div class="color-group">
                    <!-- Kolory będą dodane dynamicznie -->
                </div>
            </div>
            
            <div class="finishing-gloss-wrapper" style="display: none;">
                <button type="button" class="finishing-btn" data-finishing-gloss="Matowy">Matowy</button>
                <button type="button" class="finishing-btn" data-finishing-gloss="Półmatowy">Półmatowy</button>
                <button type="button" class="finishing-btn" data-finishing-gloss="Połysk">Połysk</button>
            </div>
        </div>
    `;
}

// ==================== OPTIMIZED DATA LOADING ====================

/**
 * Zoptymalizowane ładowanie danych wyceny
 */
function loadQuoteDataToEditor(quoteData) {
    log('editor', 'Ładowanie danych do edytora...');

    // Ustal pierwszy produkt na podstawie items
    if (quoteData.items?.length > 0) {
        const firstItem = quoteData.items
            .sort((a, b) => a.product_index - b.product_index)[0];
        if (firstItem) {
            activeProductIndex = firstItem.product_index;
            loadProductDataToForm(firstItem);
        }
    }

    // Batch update form fields
    updateFormFields(quoteData);

    // Load products and costs
    loadProductsToEditor(quoteData);
    loadCostsToSummary(quoteData);

    // ✅ POPRAWKA: Najpierw synchronizuj checkboxy dostępności
    if (activeProductIndex !== null) {
        applyVariantAvailabilityFromQuoteData(quoteData, activeProductIndex);
        log('editor', 'Zsynchronizowano checkboxy dostępności dla aktywnego produktu');
    }

    // ✅ POPRAWKA: Następnie ustaw wybrane warianty
    setSelectedVariantsByQuote(quoteData);

    // Zainicjalizuj event listenery dla checkboxów
    initializeVariantAvailabilityListeners();

    log('editor', '✅ Dane wyceny załadowane do edytora');
}

/**
 * Batch update form fields
 */
function updateFormFields(quoteData) {
    const updates = [
        { id: 'edit-clientType', value: quoteData.quote_client_type },
        { id: 'edit-courier-name', textContent: quoteData.courier_name }
    ];

    updates.forEach(({ id, value, textContent }) => {
        const element = document.getElementById(id);
        if (!element) return;
        if (textContent !== undefined && textContent !== null) {
            element.textContent = textContent;
        } else if (value !== undefined && value !== null) {
            element.value = value;
        }
    });
}

/**
 * Zoptymalizowane ładowanie kosztów do podsumowania
 */
function loadCostsToSummary(quoteData) {
    const { costs } = quoteData;
    if (!costs) return;

    // Oblicz sumę za produkt
    const productTotalBrutto = costs.products.brutto + costs.finishing.brutto;
    const productTotalNetto = costs.products.netto + costs.finishing.netto;

    // Batch DOM updates z nową strukturą
    const costUpdates = [
        { selector: '.edit-order-brutto', value: costs.products.brutto },
        { selector: '.edit-order-netto', value: costs.products.netto, suffix: ' netto' },
        { selector: '.edit-finishing-brutto', value: costs.finishing.brutto },
        { selector: '.edit-finishing-netto', value: costs.finishing.netto, suffix: ' netto' },

        // NOWE: Suma za produkt
        { selector: '.edit-product-total-brutto', value: productTotalBrutto },
        { selector: '.edit-product-total-netto', value: productTotalNetto, suffix: ' netto' },

        { selector: '.edit-delivery-brutto', value: costs.shipping.brutto },
        { selector: '.edit-delivery-netto', value: costs.shipping.netto, suffix: ' netto' },
        { selector: '.edit-final-brutto', value: costs.total.brutto },
        { selector: '.edit-final-netto', value: costs.total.netto, suffix: ' netto' }
    ];

    // Single DOM update cycle
    requestAnimationFrame(() => {
        costUpdates.forEach(({ selector, value, suffix = '' }) => {
            const element = document.querySelector(selector);
            if (element) {
                element.textContent = `${value.toFixed(2)} PLN${suffix}`;
            }
        });
    });
}

// ==================== OPTIMIZED PRODUCT MANAGEMENT ====================

/**
 * Zoptymalizowane ładowanie produktów
 */
function loadProductsToEditor(quoteData) {
    const { items } = quoteData;
    if (!items?.length) return;

    const container = document.getElementById('edit-products-summary-container');
    if (!container) return;

    // Clear and rebuild in one operation
    const fragment = document.createDocumentFragment();

    // POPRAWKA: Grupuj tylko wybrane warianty (is_selected: true)
    const selectedItems = items.filter(item => item.is_selected === true);
    const groupedProducts = groupProductsByIndex(selectedItems);
    const totalProducts = Object.keys(groupedProducts).length;

    console.log('[loadProductsToEditor] Wybrane pozycje:', selectedItems.length);
    console.log('[loadProductsToEditor] Unikalne produkty:', totalProducts);

    Object.keys(groupedProducts)
        .sort((a, b) => parseInt(a) - parseInt(b))
        .forEach((productIndex, displayIndex) => {
            const productCard = createProductCard(
                groupedProducts[productIndex],
                productIndex,
                displayIndex + 1,
                totalProducts
            );
            fragment.appendChild(productCard);
        });

    // Single DOM operation
    container.innerHTML = '';
    container.appendChild(fragment);

    updateProductsSummaryTotals();

    log('editor', `✅ Załadowano ${totalProducts} produktów (tylko wybrane warianty)`);
}

/**
 * Helper - grupowanie produktów po indeksie
 */
function groupProductsByIndex(items) {
    return items.reduce((groups, item) => {
        const index = item.product_index;
        if (!groups[index]) groups[index] = [];
        groups[index].push(item);
        return groups;
    }, {});
}

/**
 * Tworzenie karty produktu - zoptymalizowane
 */
function createProductCard(productItems, productIndex, displayNumber, totalProducts = null) {
    const firstItem = productItems[0];
    const description = generateProductDescriptionForQuote(firstItem, productItems);
    const isActive = parseInt(productIndex) === activeProductIndex;

    // Sprawdź kompletność
    let isComplete;
    if (isActive) {
        isComplete = checkProductCompletenessInEditor();
    } else {
        isComplete = firstItem.length_cm > 0 && firstItem.width_cm > 0 && firstItem.thickness_cm > 0 &&
            firstItem.quantity > 0 && firstItem.variant_code &&
            firstItem.final_price_netto > 0 && firstItem.final_price_brutto > 0;
    }

    const card = document.createElement('div');
    card.className = `product-card ${isActive ? 'active' : ''} ${!isComplete ? 'error' : ''}`;
    card.dataset.index = productIndex;

    // Jeśli totalProducts nie podano, pobierz z currentEditingQuoteData
    if (totalProducts === null) {
        totalProducts = getUniqueProductsCount(currentEditingQuoteData?.items?.filter(item => item.is_selected) || []);
    }
    const showButtons = totalProducts > 1;

    card.innerHTML = `
        <div class="product-card-content">
            <div class="product-card-number">${displayNumber}</div>
            <div class="product-card-details">
                <div class="product-card-main-info">${description.main}</div>
                ${description.sub ? `<div class="product-card-sub-info">${description.sub}</div>` : ''}
            </div>
            <div class="product-card-actions" style="display: ${showButtons ? 'flex' : 'none'};">
                <button class="copy-product-btn" data-index="${productIndex}" title="Kopiuj produkt">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                </button>
                <button class="remove-product-btn" data-index="${productIndex}" title="Usuń produkt">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            </div>
        </div>
    `;

    // Event listener dla kliknięcia w kartę (ale nie w przyciski)
    card.addEventListener('click', (e) => {
        if (!e.target.closest('.product-card-actions')) {
            activateProductInEditor(parseInt(productIndex));
        }
    });

    return card;
}

/**
 * NOWA FUNKCJA - Odśwież karty produktów po zmianie w formularzu
 */
function refreshProductCards() {
    // Znajdź aktywną kartę i odśwież jej opis
    const activeCard = document.querySelector('.product-card.active');
    if (activeCard && activeProductIndex !== null) {
        const selectedItems = currentEditingQuoteData?.items?.filter(item => item.is_selected) || [];
        const activeItem = selectedItems.find(item => item.product_index === activeProductIndex);

        if (activeItem) {
            const description = generateProductDescriptionForQuote(activeItem);
            const isComplete = checkProductCompletenessInEditor();

            // Aktualizuj klasę error
            activeCard.classList.toggle('error', !isComplete);

            // Aktualizuj tekst
            const mainInfo = activeCard.querySelector('.product-card-main-info');
            const subInfo = activeCard.querySelector('.product-card-sub-info');

            if (mainInfo) mainInfo.textContent = description.main;
            if (subInfo) subInfo.textContent = description.sub;
            else if (description.sub) {
                // Dodaj sub-info jeśli nie istnieje
                const details = activeCard.querySelector('.product-card-details');
                const subDiv = document.createElement('div');
                subDiv.className = 'product-card-sub-info';
                subDiv.textContent = description.sub;
                details.appendChild(subDiv);
            }
        }
    }
}

/**
 * NOWA FUNKCJA - Kopiuje produkt w edytorze wyceny
 */
function copyProductInQuote(sourceProductIndex) {
    log('editor', `Kopiowanie produktu: ${sourceProductIndex}`);

    if (!confirm('Czy na pewno chcesz skopiować ten produkt?')) return;

    // TODO: Implementacja kopiowania produktu w wycenie
    alert(`Kopiowanie produktu ${sourceProductIndex} będzie dostępne wkrótce!`);
    updateProductsSummaryTotals();
    refreshProductCards();
}

// ==================== OPTIMIZED CALCULATION FUNCTIONS ====================

/**
 * ULEPSZONA funkcja onFormDataChange z lepszym error handling
 */
function onFormDataChange() {
    log('sync', 'Dane formularza zostały zmienione');

    if (!checkCalculatorReadiness()) {
        log('sync', 'Calculator.js nie gotowy - używam fallback');
        calculateEditorPrices();
        updateQuoteSummary();
        saveActiveProductFormData();
        updateProductsSummaryTotals();
        return;
    }

    try {
        // ✅ POPRAWKA: Sprawdź setup PRZED dalszymi operacjami
        if (!setupCalculatorForEditor()) {
            log('calculator', 'Setup calculator.js nie powiódł się - fallback');
            calculateEditorPrices();
            updateQuoteSummary();
            saveActiveProductFormData();
            updateProductsSummaryTotals();
            return;
        }

        // ✅ POPRAWKA: Sprawdź sync PRZED calculation
        if (!syncEditorDataToCalculatorForm()) {
            log('sync', 'Sync danych nie powiódł się - fallback');
            calculateEditorPrices();
            updateQuoteSummary();
            return;
        }

        // ✅ KLUCZOWA POPRAWKA: Aktualizuj przelicznik PRZED obliczeniami
        updateMultiplierFromEditor();

        // ✅ POPRAWKA: Bezpieczne wywołania
        copyVariantMappingToEditor();
        createCustomUpdatePricesForEditor();

        // ✅ KLUCZOWA POPRAWKA: Synchronizuj wykończenie PRZED calculation
        syncFinishingStateToMockForm();

        callUpdatePricesSecurely();
        copyCalculationResults();
        updateQuoteSummary();

        log('calculator', '✅ Obliczenia zakończone pomyślnie');

    } catch (error) {
        console.error('[QUOTE EDITOR] ❌ Błąd w obliczeniach:', error);
        log('editor', 'Używam fallback z powodu błędu');
        calculateEditorPrices();
        updateQuoteSummary();
    }
    saveActiveProductFormData();
    updateProductsSummaryTotals();
}

/**
 * DODAJ funkcję do bezpiecznego wyszukiwania elementów z fallback
 */
function safeQuerySelector(container, selector, context = 'unknown') {
    if (!container) {
        log('editor', `❌ Container undefined w ${context}`);
        return null;
    }

    if (typeof container.querySelector !== 'function') {
        log('editor', `❌ Container nie ma querySelector w ${context}:`, container);
        return null;
    }

    try {
        return container.querySelector(selector);
    } catch (error) {
        log('editor', `❌ Błąd querySelector w ${context}:`, error);
        return null;
    }
}

/**
 * POPRAWIONA funkcja syncEditorDataToCalculatorForm z lepszym error handling
 */
function syncEditorDataToCalculatorForm() {
    if (!window.activeQuoteForm) {
        log('sync', '❌ Brak activeQuoteForm do synchronizacji');
        return false;
    }

    const syncMappings = [
        { editorId: 'edit-length', calculatorField: 'length' },
        { editorId: 'edit-width', calculatorField: 'width' },
        { editorId: 'edit-thickness', calculatorField: 'thickness' },
        { editorId: 'edit-quantity', calculatorField: 'quantity' },
        { editorId: 'edit-clientType', calculatorField: 'clientType' }
    ];

    let syncedCount = 0;

    // Single loop for all syncing z lepszym error handling
    syncMappings.forEach(({ editorId, calculatorField }) => {
        const editorElement = document.getElementById(editorId);
        const calculatorElement = safeQuerySelector(
            window.activeQuoteForm,
            `[data-field="${calculatorField}"]`,
            `sync ${calculatorField}`
        );

        if (editorElement && calculatorElement) {
            calculatorElement.value = editorElement.value || '';
            syncedCount++;
            if (DEBUG_LOGS.sync) {
                log('sync', `✅ ${calculatorField}: ${editorElement.value}`);
            }
        } else {
            log('sync', `⚠️ Nie można zsynchronizować ${calculatorField}`);
        }
    });

    if (syncedCount === 0) {
        log('sync', '❌ Żadne pole nie zostało zsynchronizowane');
        return false;
    }

    syncSelectedVariant();
    log('sync', `✅ Zsynchronizowano ${syncedCount}/${syncMappings.length} pól`);
    return true;
}

// ==================== OPTIMIZED FINISHING SECTION ====================

/**
 * Zoptymalizowana obsługa wykończenia
 */
function handleFinishingButtonClick(button) {
    const finishingType = button.dataset.finishingType;
    const finishingVariant = button.dataset.finishingVariant;
    const finishingGloss = button.dataset.finishingGloss;

    // Determine button group and handle accordingly
    if (finishingType) {
        // Najpierw wyczyść poprzedni stan i ustaw aktywny przycisk, aby dalsze funkcje widziały prawidłowy wybór
        clearFinishingSelections();
        setActiveFinishingButton(button, '#edit-finishing-type-group');
        handleFinishingTypeChange(finishingType);
    } else if (finishingVariant) {
        setActiveFinishingButton(button, '#edit-finishing-variant-wrapper');
        handleFinishingVariantChange(finishingVariant);
    } else if (finishingGloss) {
        setActiveFinishingButton(button, '#edit-finishing-gloss-wrapper');
        // Dodaj przeliczenie po zmianie połysku
        syncFinishingStateToMockForm();
        if (typeof calculateFinishingCost === 'function' && window.activeQuoteForm) {
            try {
                calculateFinishingCost(window.activeQuoteForm);
            } catch (err) {
                log('finishing', 'Błąd przeliczania po zmianie połysku', err);
            }
        }
        updateQuoteSummary();
    }

    // ✅ ZAWSZE wywołaj onFormDataChange po kliknięciu przycisku wykończenia
    onFormDataChange();

    refreshProductCards();
}

/**
 * Zoptymalizowana obsługa kolorów
 */
function handleColorButtonClick(button) {
    setActiveColorButton(button);
    log('finishing', `Wybrano kolor: ${button.dataset.finishingColor}`);

    // ✅ Synchronizuj stan koloru do mock formularza
    onFormDataChange();

    // ✅ DODANE: Zawsze aktualizuj podsumowanie po zmianie koloru
    updateQuoteSummary();
    updateProductsSummaryTotals();
    refreshProductCards();
}

/**
 * Zoptymalizowana obsługa typu wykończenia
 */
function handleFinishingTypeChange(finishingType) {
    const elements = {
        variantWrapper: document.getElementById('edit-finishing-variant-wrapper'),
        colorWrapper: document.getElementById('edit-finishing-color-wrapper')
    };

    // Hide all by default
    Object.values(elements).forEach(el => {
        if (el) el.style.display = 'none';
    });

    // Show relevant sections based on type
    if (finishingType === 'Lakierowanie' && elements.variantWrapper) {
        elements.variantWrapper.style.display = 'flex';
    }

    log('finishing', `Typ wykończenia: ${finishingType}`);

    // ✅ SPECJALNA OBSŁUGA DLA "SUROWE": Wymuś resetowanie kosztów PRZED synchronizacją
    if (finishingType === 'Surowe' && window.activeQuoteForm) {
        // Bezpośrednio wyzeruj dataset
        window.activeQuoteForm.dataset.finishingBrutto = '0';
        window.activeQuoteForm.dataset.finishingNetto = '0';
        log('finishing', '✅ WYMUSZONO zerowanie kosztów dla "Surowe"');

        // ✅ NOWA POPRAWKA: Wymuś natychmiastowe przeliczenie dla "Surowe"
        if (typeof calculateFinishingCost === 'function') {
            try {
                const result = calculateFinishingCost(window.activeQuoteForm);
                log('finishing', `✅ NATYCHMIASTOWE przeliczenie dla "Surowe": ${result?.brutto || 0} PLN brutto`);
            } catch (err) {
                log('finishing', '❌ Błąd natychmiastowego przeliczania dla "Surowe":', err);
            }
        }
    }

    // KLUCZOWA POPRAWKA: Synchronizuj do mock formularza
    syncFinishingStateToMockForm();

    // ✅ NOWA POPRAWKA: Dodatkowe przeliczenie po synchronizacji (dla wszystkich typów)
    if (typeof calculateFinishingCost === 'function' && window.activeQuoteForm) {
        setTimeout(() => {
            try {
                const result = calculateFinishingCost(window.activeQuoteForm);
                log('finishing', `Przeliczono koszty wykończenia po zmianie typu: ${result?.brutto || 0} PLN brutto`);

                // ✅ KLUCZOWA POPRAWKA: Wymuś aktualizację podsumowania po każdej zmianie typu
                setTimeout(() => {
                    updateQuoteSummary();
                    log('finishing', '✅ Zaktualizowano podsumowanie po zmianie typu wykończenia');
                }, 100);

            } catch (err) {
                log('finishing', 'Błąd przeliczania wykończenia po zmianie typu', err);
            }
        }, 100);
    }

    // Odśwież karty produktów po zmianie typu wykończenia
    refreshProductCards();
}

/**
 * Obsługa zmiany wariantu wykończenia
 */
function handleFinishingVariantChange(variant) {
    const colorWrapper = document.getElementById('edit-finishing-color-wrapper');
    if (!colorWrapper) return;

    // Reset active color buttons
    colorWrapper.querySelectorAll('.color-btn').forEach(btn => btn.classList.remove('active'));

    // Show colors only for "Barwne" variant
    colorWrapper.style.display = variant === 'Barwne' ? 'flex' : 'none';

    log('finishing', `Wariant wykończenia: ${variant}`);

    // ✅ DODAJ: Synchronizuj i przelicz
    syncFinishingStateToMockForm();

    if (typeof calculateFinishingCost === 'function' && window.activeQuoteForm) {
        try {
            calculateFinishingCost(window.activeQuoteForm);
            log('finishing', 'Przeliczono koszty wykończenia po zmianie wariantu');
        } catch (err) {
            log('finishing', 'Błąd przeliczania wykończenia po zmianie wariantu', err);
        }
    }

    updateQuoteSummary();


    // ✅ Odśwież karty produktów po zmianie wariantu wykończenia
    refreshProductCards();
}

/**
 * Uniwersalna funkcja ustawiania aktywnego przycisku
 */
function setActiveFinishingButton(clickedButton, wrapperSelector) {
    const wrapper = document.querySelector(wrapperSelector);
    if (!wrapper) return;

    // Batch class updates
    const buttons = wrapper.querySelectorAll('.finishing-btn');
    buttons.forEach(btn => btn.classList.remove('active'));
    clickedButton.classList.add('active');
}

/**
 * Uniwersalna funkcja ustawiania aktywnego koloru
 */
function setActiveColorButton(clickedButton) {
    const colorButtons = document.querySelectorAll('#edit-finishing-color-wrapper .color-btn');
    colorButtons.forEach(btn => btn.classList.remove('active'));
    clickedButton.classList.add('active');
}

// ==================== OPTIMIZED DATA MANAGEMENT ====================

/**
 * Zoptymalizowane ładowanie grup cenowych
 */
async function loadClientTypesFromDatabase() {
    if (clientTypesCache) {
        log('editor', 'Używam cache grup cenowych');
        populateClientTypeSelect(clientTypesCache);
        return clientTypesCache;
    }

    try {
        const response = await fetch('/quotes/api/multipliers');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

        const multipliers = await response.json();
        clientTypesCache = multipliers; // Cache result

        populateClientTypeSelect(multipliers);
        log('editor', `✅ Załadowano ${multipliers.length} grup cenowych`);

        return multipliers;

    } catch (error) {
        console.error('[QUOTE EDITOR] ❌ Błąd ładowania grup cenowych:', error);
        loadDefaultClientTypes();
        return null;
    }
}

/**
 * Wypełnianie select-a grup cenowych - zoptymalizowane
 */
function populateClientTypeSelect(multipliers) {
    const select = document.getElementById('edit-clientType');
    if (!select) return;

    // Create fragment for batch DOM operations
    const fragment = document.createDocumentFragment();

    // Add placeholder
    const placeholder = createElement('option', {
        value: '',
        disabled: true,
        selected: true,
        textContent: 'Wybierz grupę'
    });
    fragment.appendChild(placeholder);

    // Add options
    multipliers.forEach(multiplier => {
        const option = createElement('option', {
            value: multiplier.client_type,
            textContent: `${multiplier.client_type} (${multiplier.multiplier})`
        });
        option.dataset.multiplierValue = multiplier.multiplier;
        option.dataset.multiplierId = multiplier.id;
        fragment.appendChild(option);
    });

    // Single DOM operation
    select.innerHTML = '';
    select.appendChild(fragment);
}

// ==================== OPTIMIZED CALCULATION CORE ====================

/**
 * Zoptymalizowana funkcja updatePrices dla edytora
 */
function createCustomUpdatePricesForEditor() {
    // Backup original function once
    if (!window.originalUpdatePrices && typeof updatePrices === 'function') {
        window.originalUpdatePrices = updatePrices;
    }

    // Create optimized version
    window.updatePrices = function () {
        log('calculator', 'Wywołano zoptymalizowaną updatePrices');

        const form = window.activeQuoteForm;
        if (!form) return;

        // Get form data in one pass
        const formData = extractFormData(form);
        if (!formData.isValid) {
            showErrorForAllVariants(formData.error, form.querySelector('.variants'));
            clearFormDataset(form);
            return;
        }

        // Process variants efficiently
        processVariantsOptimized(form, formData);

        // Calculate finishing costs if available
        if (typeof calculateFinishingCost === 'function') {
            try {
                calculateFinishingCost(form);
            } catch (error) {
                log('calculator', 'Błąd obliczania wykończenia:', error);
            }
        }
    };
}

/**
 * Ekstraktowanie danych formularza - zoptymalizowane
 */
function extractFormData(form) {
    const selectors = {
        length: 'input[data-field="length"]',
        width: 'input[data-field="width"]',
        thickness: 'input[data-field="thickness"]',
        quantity: 'input[data-field="quantity"]',
        clientType: 'select[data-field="clientType"]'
    };

    const data = {};
    let error = "";

    // Extract all values in one loop
    Object.entries(selectors).forEach(([key, selector]) => {
        const element = form.querySelector(selector);
        if (element) {
            data[key] = key === 'clientType' ? element.value : parseFloat(element.value);
        }
    });

    // Validation
    if (isNaN(data.length)) error = "Brak dług.";
    else if (isNaN(data.width)) error = "Brak szer.";
    else if (isNaN(data.thickness)) error = "Brak grub.";
    else if (!data.clientType) error = "Brak grupy";

    // Fix quantity
    if (isNaN(data.quantity) || data.quantity < 1) {
        data.quantity = 1;
        const quantityEl = form.querySelector(selectors.quantity);
        if (quantityEl) quantityEl.value = 1;
    }

    return {
        ...data,
        isValid: !error,
        error,
        volume: error ? 0 : calculateSingleVolume(data.length, data.width, Math.ceil(data.thickness)),
        multiplier: getMultiplierValue(data.clientType)
    };
}

/**
 * Zoptymalizowane przetwarzanie wariantów
 */
function processVariantsOptimized(form, formData) {
    const variants = form.querySelectorAll('.variants .variant-item');
    let selectedVariantData = null;

    // Process all variants in single loop
    variants.forEach(variant => {
        const radio = variant.querySelector('input[type="radio"]');
        if (!radio) return;

        const result = calculateVariantPrice(radio.value, formData);
        updateVariantDisplay(variant, result);

        if (radio.checked) {
            selectedVariantData = result;
            // Highlight selected variant
            variant.querySelectorAll('*').forEach(el => el.style.color = "#ED6B24");
        }
    });

    // Update form dataset
    if (selectedVariantData) {
        form.dataset.orderBrutto = selectedVariantData.totalBrutto.toFixed(2);
        form.dataset.orderNetto = selectedVariantData.totalNetto.toFixed(2);
    } else {
        clearFormDataset(form);
    }
}

/**
 * Obliczanie ceny wariantu - zoptymalizowane
 */
function calculateVariantPrice(variantCode, formData) {
    const config = window.variantMapping?.[variantCode];
    if (!config) {
        return { unitBrutto: 0, unitNetto: 0, totalBrutto: 0, totalNetto: 0 };
    }

    let basePrice = 0;

    // Try to get price from database
    if (window.priceIndex) {
        const match = getEditorPrice(config.species, config.technology, config.wood_class, formData.thickness, formData.length);
        if (match) {
            basePrice = match.price_per_m3;
        }
    }

    // Fallback prices if needed
    if (basePrice === 0) {
        const fallbackPrices = {
            'dab-lity-ab': 14500, 'dab-lity-bb': 13000, 'dab-micro-ab': 10000, 'dab-micro-bb': 10000,
            'jes-lity-ab': 13000, 'jes-micro-ab': 11000, 'buk-lity-ab': 9000, 'buk-micro-ab': 8500
        };
        basePrice = fallbackPrices[variantCode] || 10000;
    }

    // Calculate prices
    const unitNetto = formData.volume * basePrice * formData.multiplier;
    const unitBrutto = unitNetto * 1.23;
    const totalNetto = unitNetto * formData.quantity;
    const totalBrutto = unitBrutto * formData.quantity;

    return { unitNetto, unitBrutto, totalNetto, totalBrutto };
}

/**
 * Aktualizacja wyświetlania wariantu - zoptymalizowane
 */
function updateVariantDisplay(variant, prices) {
    const elements = {
        unitBrutto: variant.querySelector('.unit-brutto'),
        unitNetto: variant.querySelector('.unit-netto'),
        totalBrutto: variant.querySelector('.total-brutto'),
        totalNetto: variant.querySelector('.total-netto')
    };

    // Batch DOM updates
    Object.entries(elements).forEach(([key, element]) => {
        if (element) {
            const value = prices[key];
            element.textContent = formatPLN ? formatPLN(value) : `${value.toFixed(2)} PLN`;
        }
    });
}

/**
 * Pomocnicze funkcje dla obliczeń
 */
function getMultiplierValue(clientType) {
    if (typeof window.isPartner === 'boolean' && window.isPartner) {
        return window.userMultiplier || 1.0;
    }

    if (window.multiplierMapping?.[clientType]) {
        return window.multiplierMapping[clientType];
    }

    const fallback = { 'Florek': 1.0, 'Hurt': 1.1, 'Detal': 1.3, 'Detal+': 1.5 };
    return fallback[clientType] || 1.0;
}

function clearFormDataset(form) {
    form.dataset.orderBrutto = "";
    form.dataset.orderNetto = "";
}

function calculateSingleVolume(length, width, thickness) {
    return (length / 100) * (width / 100) * (thickness / 100);
}

// ==================== OPTIMIZED SUMMARY UPDATES ====================

/**
 * Zoptymalizowane odświeżanie podsumowania
 */
function updateQuoteSummary() {
    log('editor', '=== ODŚWIEŻANIE PODSUMOWANIA EDYTORA ===');

    try {
        // ✅ Oblicz koszty aktywnego produktu (do pokazania w formularzu)
        const activeProductCosts = calculateActiveProductCosts();
        const activeFinishingCosts = calculateActiveProductFinishingCosts();
        const activeProductTotal = {
            brutto: activeProductCosts.brutto + activeFinishingCosts.brutto,
            netto: activeProductCosts.netto + activeFinishingCosts.netto
        };

        // ✅ KLUCZOWA POPRAWKA: Zapisz aktualne koszty aktywnego produktu do danych wyceny
        updateActiveProductCostsInData(activeProductCosts, activeFinishingCosts);

        // ✅ KLUCZOWA POPRAWKA: Oblicz sumę WSZYSTKICH produktów w wycenie (z wykończeniem)
        const orderTotals = calculateOrderTotals();
        const shippingCosts = getShippingCosts();

        // ✅ Finalna suma = wszystkie produkty (z wykończeniem) + dostawa
        const finalOrderTotal = {
            brutto: orderTotals.products.brutto + shippingCosts.brutto,
            netto: orderTotals.products.netto + shippingCosts.netto
        };

        // ✅ Aktualizacja UI - pokaż koszty aktywnego produktu + sumę całego zamówienia
        updateSummaryElementsFixed(
            activeProductCosts,      // Tylko aktywny produkt (do pokazania w formularzu)
            activeFinishingCosts,    // Wykończenie aktywnego produktu
            activeProductTotal,      // Suma aktywnego produktu
            orderTotals,            // ✅ WSZYSTKIE produkty w zamówieniu
            shippingCosts,          // Dostawa
            finalOrderTotal         // Suma końcowa
        );

        // ✅ Debug logging
        const summaryObject = {
            aktywny_produkt: {
                surowe: activeProductCosts,
                wykończenie: activeFinishingCosts,
                suma: activeProductTotal
            },
            całe_zamówienie: {
                wszystkie_produkty: orderTotals.products,
                dostawa: shippingCosts,
                suma_końcowa: finalOrderTotal
            }
        };

        log('editor', '✅ Podsumowanie zaktualizowane:', summaryObject);

    } catch (error) {
        console.error('[QUOTE EDITOR] ❌ Błąd odświeżania podsumowania:', error);
    }
}
/**
 * NOWA funkcja - aktualizuj elementy z nową strukturą
 */
function updateSummaryElementsFixed(activeProductCosts, activeFinishingCosts, activeProductTotal, orderTotals, shippingCosts, finalOrderTotal) {
    // ✅ POPRAWKA: Dodana walidacja parametrów przed użyciem
    if (!activeProductCosts || !activeFinishingCosts || !activeProductTotal || !orderTotals || !shippingCosts || !finalOrderTotal) {
        console.error('[updateSummaryElementsFixed] ❌ Brak wymaganych parametrów:', {
            activeProductCosts: !!activeProductCosts,
            activeFinishingCosts: !!activeFinishingCosts,
            activeProductTotal: !!activeProductTotal,
            orderTotals: !!orderTotals,
            shippingCosts: !!shippingCosts,
            finalOrderTotal: !!finalOrderTotal
        });
        return;
    }

    const updates = [
        // Pokazuj koszty tylko aktywnego produktu w górnych wierszach
        { selector: '.edit-order-brutto', value: activeProductCosts.brutto },
        { selector: '.edit-order-netto', value: activeProductCosts.netto, suffix: ' netto' },
        { selector: '.edit-finishing-brutto', value: activeFinishingCosts.brutto },
        { selector: '.edit-finishing-netto', value: activeFinishingCosts.netto, suffix: ' netto' },

        // Suma za aktywny produkt
        { selector: '.edit-product-total-brutto', value: activeProductTotal.brutto },
        { selector: '.edit-product-total-netto', value: activeProductTotal.netto, suffix: ' netto' },

        // Dostawa (bez zmian)
        { selector: '.edit-delivery-brutto', value: shippingCosts.brutto },
        { selector: '.edit-delivery-netto', value: shippingCosts.netto, suffix: ' netto' },

        // ✅ POPRAWKA: Suma zamówienia = WSZYSTKIE produkty (z wykończeniem) + dostawa (używamy orderTotals + shippingCosts)
        { selector: '.edit-final-brutto', value: finalOrderTotal.brutto },
        { selector: '.edit-final-netto', value: finalOrderTotal.netto, suffix: ' netto' }
    ];

    // ✅ POPRAWKA: Dodana walidacja przed toFixed()
    const isValidNumber = (val) => typeof val === 'number' && !isNaN(val);

    // Batch DOM update z walidacją
    requestAnimationFrame(() => {
        updates.forEach(({ selector, value, suffix = '' }) => {
            const element = document.querySelector(selector);
            if (element) {
                if (isValidNumber(value)) {
                    element.textContent = `${value.toFixed(2)} PLN${suffix}`;
                } else {
                    console.warn(`[updateSummaryElementsFixed] ❌ Nieprawidłowa wartość dla ${selector}:`, value);
                    element.textContent = `0.00 PLN${suffix}`;
                }
            }
        });
    });
}

function formatPLN(value) {
    if (typeof value !== 'number' || isNaN(value)) {
        return '0.00 PLN';
    }
    return `${value.toFixed(2)} PLN`;
}

/**
 * DODATKOWA FUNKCJA: Synchronizacja dataset radio button z mock form
 * Ta funkcja powinna być wywoływana po każdej zmianie wariantu
 */
function syncRadioDatasetWithMockForm() {
    const selectedRadio = document.querySelector('input[name="edit-variantOption"]:checked');
    const mockForm = window.activeQuoteForm;

    if (selectedRadio && mockForm && mockForm.dataset) {
        // Kopiuj dane z mock form do radio button
        selectedRadio.dataset.orderBrutto = mockForm.dataset.orderBrutto || '0';
        selectedRadio.dataset.orderNetto = mockForm.dataset.orderNetto || '0';

        log('sync', `✅ Zsynchronizowano dataset wariantu: ${selectedRadio.value}`);
        log('sync', `   - Brutto: ${selectedRadio.dataset.orderBrutto} PLN`);
        log('sync', `   - Netto: ${selectedRadio.dataset.orderNetto} PLN`);
    }
}

/**
 * NOWA funkcja - oblicza sumę produktów dla aktywnego produktu (do wyświetlenia w formularzu)
 */
function calculateActiveProductCosts() {
    log('editor', '=== OBLICZANIE KOSZTÓW AKTYWNEGO PRODUKTU ===');

    // ✅ PRIORYTET 1: Sprawdź dane z calculator.js dla aktywnego formularza
    if (window.activeQuoteForm?.dataset) {
        const formBrutto = parseFloat(window.activeQuoteForm.dataset.orderBrutto) || 0;
        const formNetto = parseFloat(window.activeQuoteForm.dataset.orderNetto) || 0;

        if (formBrutto > 0 || formNetto > 0) {
            log('editor', `✅ Aktywny produkt (z calculator): ${formBrutto.toFixed(2)} PLN brutto`);
            return { brutto: formBrutto, netto: formNetto };
        }
    }

    // ✅ PRIORYTET 2: Sprawdź zachowane obliczenia aktywnego produktu
    if (activeProductIndex !== null && currentEditingQuoteData?.items) {
        const activeItem = currentEditingQuoteData.items.find(item =>
            item.product_index === activeProductIndex && item.is_selected
        );

        if (activeItem) {
            // ✅ Użyj zachowanych obliczeń jeśli są dostępne
            const calculatedBrutto = parseFloat(activeItem.calculated_price_brutto || 0);
            const calculatedNetto = parseFloat(activeItem.calculated_price_netto || 0);

            if (calculatedBrutto > 0 || calculatedNetto > 0) {
                log('editor', `✅ Aktywny produkt (zachowane obliczenia): ${calculatedBrutto.toFixed(2)} PLN brutto`);
                return { brutto: calculatedBrutto, netto: calculatedNetto };
            }

            // ✅ Fallback - użyj oryginalnych danych produktu
            let itemBrutto = 0;
            let itemNetto = 0;

            // Sprawdź różne pola w kolejności priorytetów
            if (activeItem.final_price_brutto && activeItem.final_price_netto) {
                itemBrutto = parseFloat(activeItem.final_price_brutto);
                itemNetto = parseFloat(activeItem.final_price_netto);
            } else if (activeItem.total_brutto && activeItem.total_netto) {
                itemBrutto = parseFloat(activeItem.total_brutto);
                itemNetto = parseFloat(activeItem.total_netto);
            } else {
                // Oblicz z ceny jednostkowej
                const quantity = activeItem.quantity || 1;
                const unitBrutto = parseFloat(activeItem.unit_price_brutto || activeItem.price_brutto || 0);
                const unitNetto = parseFloat(activeItem.unit_price_netto || activeItem.price_netto || 0);
                itemBrutto = unitBrutto * quantity;
                itemNetto = unitNetto * quantity;
            }

            if (itemBrutto > 0 || itemNetto > 0) {
                log('editor', `✅ Aktywny produkt (z danych wyceny): ${itemBrutto.toFixed(2)} PLN brutto`);
                return { brutto: itemBrutto, netto: itemNetto };
            }
        }
    }

    log('editor', '⚠️ Brak danych aktywnego produktu - zwracam 0');
    return { brutto: 0, netto: 0 };
}

/**
 * NOWA funkcja - oblicza wykończenie tylko dla aktywnego produktu
 */
function calculateActiveProductFinishingCosts() {
    log('finishing', '=== OBLICZANIE WYKOŃCZENIA AKTYWNEGO PRODUKTU ===');

    // ✅ KLUCZOWA POPRAWKA: Zawsze sprawdź aktualny stan przycisków wykończenia
    const finishingType = getSelectedFinishingType();

    // ✅ SPECJALNA OBSŁUGA dla "Surowe" - zawsze zwróć 0
    if (finishingType === 'Surowe') {
        log('finishing', 'Wykończenie aktywnego produktu (Surowe): 0.00 PLN brutto');
        return { brutto: 0, netto: 0 };
    }

    // Sprawdź dane z calculator.js
    if (window.activeQuoteForm?.dataset) {
        const finishingBrutto = parseFloat(window.activeQuoteForm.dataset.finishingBrutto) || 0;
        const finishingNetto = parseFloat(window.activeQuoteForm.dataset.finishingNetto) || 0;

        // ✅ POPRAWKA: Akceptuj też wartość 0 (nie tylko > 0)
        log('finishing', `Wykończenie aktywnego produktu (z calculator): ${finishingBrutto.toFixed(2)} PLN brutto`);
        return { brutto: finishingBrutto, netto: finishingNetto };
    }

    // Fallback - znajdź wykończenie aktywnego produktu w danych wyceny
    if (activeProductIndex !== null && currentEditingQuoteData?.finishing) {
        const activeFinishing = currentEditingQuoteData.finishing.find(f =>
            f.product_index === activeProductIndex
        );

        if (activeFinishing) {
            // finishing_price to już wartość całkowita dla produktu
            const finishingBrutto = parseFloat(activeFinishing.finishing_price_brutto || 0);
            const finishingNetto = parseFloat(activeFinishing.finishing_price_netto || 0);

            log('finishing', `Wykończenie aktywnego produktu ${activeProductIndex}: ${finishingBrutto.toFixed(2)} PLN brutto`);
            return { brutto: finishingBrutto, netto: finishingNetto };
        }
    }

    log('finishing', 'Brak wykończenia dla aktywnego produktu');
    return { brutto: 0, netto: 0 };
}

/**
 * Oblicza łączny koszt wszystkich produktów w wycenie
 * wykorzystując dane zapisane w currentEditingQuoteData.items
 */
function calculateOrderTotals() {
    const totals = {
        products: { brutto: 0, netto: 0 },
        finishing: { brutto: 0, netto: 0 }
    };

    log('editor', '=== OBLICZANIE CAŁKOWITEJ SUMY ZAMÓWIENIA ===');

    if (currentEditingQuoteData?.items) {
        currentEditingQuoteData.items.forEach(item => {
            if (!item.is_selected) return;

            const productBrutto = parseFloat(item.calculated_price_brutto ?? item.final_price_brutto ?? 0);
            const productNetto = parseFloat(item.calculated_price_netto ?? item.final_price_netto ?? 0);

            // Pobierz koszt wykończenia z wielu możliwych źródeł
            let finishingBrutto = parseFloat(
                item.calculated_finishing_brutto ??
                item.finishing_price_brutto ??
                0
            );
            let finishingNetto = parseFloat(
                item.calculated_finishing_netto ??
                item.finishing_price_netto ??
                0
            );

            // Jeśli koszt wykończenia nie został zapisany w item, sprawdź tabelę finishing
            if ((finishingBrutto === 0 && finishingNetto === 0) && currentEditingQuoteData?.finishing) {
                const finishingItem = currentEditingQuoteData.finishing.find(f => f.product_index === item.product_index);
                if (finishingItem) {
                    finishingBrutto = parseFloat(finishingItem.finishing_price_brutto || 0);
                    finishingNetto = parseFloat(finishingItem.finishing_price_netto || 0);
                }
            }

            const totalBrutto = productBrutto + finishingBrutto;
            const totalNetto = productNetto + finishingNetto;

            // Do sumy zamówienia dodajemy pełny koszt produktu (surowe + wykończenie)
            totals.products.brutto += totalBrutto;
            totals.products.netto += totalNetto;

            // Zachowaj osobne sumy wykończeń do ewentualnego debugowania
            totals.finishing.brutto += finishingBrutto;
            totals.finishing.netto += finishingNetto;
        });
    }

    log('editor', '🏁 SUMA CAŁKOWITA:', {
        produkty_z_wykończeniem: `${totals.products.brutto.toFixed(2)} PLN brutto, ${totals.products.netto.toFixed(2)} PLN netto`,
        wykończenie: `${totals.finishing.brutto.toFixed(2)} PLN brutto, ${totals.finishing.netto.toFixed(2)} PLN netto`
    });

    return totals;
}

/**
 * NOWA FUNKCJA - dodaj na końcu pliku
 * Aktualizuje koszty aktywnego produktu w danych wyceny (żeby były zachowane)
 */
function updateActiveProductCostsInData(activeProductCosts, activeFinishingCosts) {
    if (activeProductIndex === null || !currentEditingQuoteData?.items) {
        return;
    }

    const activeItem = currentEditingQuoteData.items.find(item =>
        item.product_index === activeProductIndex
    );

    if (activeItem) {
        // ✅ KLUCZOWA POPRAWKA: Zapisz aktualne koszty aktywnego produktu
        activeItem.calculated_price_brutto = activeProductCosts.brutto;
        activeItem.calculated_price_netto = activeProductCosts.netto;
        activeItem.calculated_finishing_brutto = activeFinishingCosts.brutto;
        activeItem.calculated_finishing_netto = activeFinishingCosts.netto;

        // ✅ NOWA POPRAWKA: Aktualizuj także dane wykończenia w tabeli finishing
        const finishingType = getSelectedFinishingType();
        const finishingVariant = getSelectedFinishingVariant();
        const finishingColor = getSelectedFinishingColor();

        if (currentEditingQuoteData.finishing) {
            let finishingItem = currentEditingQuoteData.finishing.find(f =>
                f.product_index === activeProductIndex
            );

            if (finishingItem) {
                // Aktualizuj istniejący wpis wykończenia
                finishingItem.finishing_price_brutto = activeFinishingCosts.brutto;
                finishingItem.finishing_price_netto = activeFinishingCosts.netto;
                finishingItem.finishing_type = finishingType;
                finishingItem.finishing_variant = finishingVariant;
                finishingItem.finishing_color = finishingColor;
                log('finishing', `✅ Zaktualizowano wykończenie w tabeli finishing dla produktu ${activeProductIndex}: ${activeFinishingCosts.brutto.toFixed(2)} PLN brutto`);
            } else if (activeFinishingCosts.brutto > 0 || activeFinishingCosts.netto > 0 || finishingType !== 'Surowe') {
                // Utwórz nowy wpis wykończenia nawet przy koszcie 0 jeśli wybrano inne niż "Surowe"
                currentEditingQuoteData.finishing.push({
                    product_index: activeProductIndex,
                    finishing_price_brutto: activeFinishingCosts.brutto,
                    finishing_price_netto: activeFinishingCosts.netto,
                    finishing_type: finishingType,
                    finishing_variant: finishingVariant,
                    finishing_color: finishingColor
                });
                log('finishing', `✅ Utworzono nowy wpis wykończenia dla produktu ${activeProductIndex}: ${activeFinishingCosts.brutto.toFixed(2)} PLN brutto`);
            }
        } else {
            // Utwórz tablicę finishing jeśli nie istnieje
            currentEditingQuoteData.finishing = [];
            if (activeFinishingCosts.brutto > 0 || activeFinishingCosts.netto > 0 || finishingType !== 'Surowe') {
                currentEditingQuoteData.finishing.push({
                    product_index: activeProductIndex,
                    finishing_price_brutto: activeFinishingCosts.brutto,
                    finishing_price_netto: activeFinishingCosts.netto,
                    finishing_type: finishingType,
                    finishing_variant: finishingVariant,
                    finishing_color: finishingColor
                });
                log('finishing', `✅ Utworzono tablicę finishing i dodano wpis dla produktu ${activeProductIndex}: ${activeFinishingCosts.brutto.toFixed(2)} PLN brutto`);
            }
        }

        // ✅ Również zaktualizuj standardowe pola dla kompatybilności
        activeItem.total_brutto = activeProductCosts.brutto;
        activeItem.total_netto = activeProductCosts.netto;

        log('editor', `✅ Zachowano koszty produktu ${activeProductIndex}: ${activeProductCosts.brutto.toFixed(2)} PLN brutto`);
    } else {
        log('editor', `⚠️ Nie znaleziono aktywnego produktu ${activeProductIndex} do aktualizacji kosztów`);
    }
}

/**
 * Fallback - domyślne ceny jeśli nie udało się załadować z bazy
 */
function loadDefaultFinishingData() {
    console.warn('[QUOTE EDITOR] Używam domyślnych cen wykończenia jako fallback');

    window.finishingPrices = {
        'Surowe': 0,
        'Lakierowane bezbarwne': 200,
        'Lakierowane barwne': 250,
        'Olejowanie': 250
    };

    // Zbuduj podstawowe dane dla interfejsu
    const defaultData = {
        finishing_types: [
            { id: 1, name: 'Surowe', price_netto: 0 },
            { id: 2, name: 'Lakierowane bezbarwne', price_netto: 200 },
            { id: 3, name: 'Lakierowane barwne', price_netto: 250 },
            { id: 4, name: 'Olejowanie', price_netto: 250 }
        ],
        finishing_colors: [
            { id: 1, name: 'Brak', image_path: null, image_url: null },
            { id: 2, name: 'Biały', image_path: 'images/colors/white.jpg', image_url: '/calculator/static/images/colors/white.jpg' },
            { id: 3, name: 'Czarny', image_path: 'images/colors/black.jpg', image_url: '/calculator/static/images/colors/black.jpg' }
        ]
    };

    renderFinishingUI(defaultData);
    finishingDataCache = defaultData;

    log('finishing', 'Załadowano domyślne dane wykończenia');
}

/**
 * Pomocnicze funkcje dla obliczeń
 */
function getCurrentDimensions() {
    const length = parseFloat(document.getElementById('edit-length')?.value) || 0;
    const width = parseFloat(document.getElementById('edit-width')?.value) || 0;
    const thickness = parseFloat(document.getElementById('edit-thickness')?.value) || 0;
    const quantity = parseInt(document.getElementById('edit-quantity')?.value) || 1;

    return {
        length,
        width,
        thickness,
        quantity,
        isValid: length > 0 && width > 0 && thickness > 0 && quantity > 0
    };
}

function getShippingCosts() {
    if (currentEditingQuoteData?.shipping_cost_brutto || currentEditingQuoteData?.shipping_cost_netto) {
        return {
            brutto: parseFloat(currentEditingQuoteData.shipping_cost_brutto) || 0,
            netto: parseFloat(currentEditingQuoteData.shipping_cost_netto) || 0
        };
    }
    if (currentEditingQuoteData?.costs?.shipping) {
        return {
            brutto: parseFloat(currentEditingQuoteData.costs.shipping.brutto) || 0,
            netto: parseFloat(currentEditingQuoteData.costs.shipping.netto) || 0
        };
    }
    if (currentEditingQuoteData?.cost_shipping) {
        const brutto = parseFloat(currentEditingQuoteData.cost_shipping) || 0;
        return { brutto, netto: brutto / 1.23 };
    }
    return { brutto: 0, netto: 0 };
}

// ==================== OPTIMIZED UTILITY FUNCTIONS ====================

/**
 * Uniwersalna funkcja debounce
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

/**
 * Uniwersalne funkcje getter dla wykończenia
 */
function getSelectedFinishingType() {
    const activeBtn = document.querySelector('#edit-finishing-type-group .finishing-btn.active');
    return activeBtn?.dataset.finishingType || 'Surowe';
}

function getSelectedFinishingVariant() {
    const activeBtn = document.querySelector('#edit-finishing-variant-wrapper .finishing-btn.active');
    return activeBtn?.dataset.finishingVariant || null;
}

function getSelectedFinishingColor() {
    const activeBtn = document.querySelector('#edit-finishing-color-wrapper .color-btn.active');
    return activeBtn?.dataset.finishingColor || null;
}

/**
 * Zoptymalizowane czyszczenie selekcji
 */
function clearFinishingSelections() {
    const selectors = [
        '#edit-finishing-type-group .finishing-btn',
        '#edit-finishing-variant-wrapper .finishing-btn',
        '#edit-finishing-color-wrapper .color-btn',
        '#edit-finishing-gloss-wrapper .finishing-btn'
    ];

    selectors.forEach(selector => {
        document.querySelectorAll(selector).forEach(btn => btn.classList.remove('active'));
    });

    ['#edit-finishing-variant-wrapper', '#edit-finishing-color-wrapper', '#edit-finishing-gloss-wrapper']
        .forEach(sel => {
            const el = document.querySelector(sel);
            if (el) el.style.display = 'none';
        });

    // ✅ KLUCZOWA POPRAWKA: Agresywnie resetuj koszty wykończenia w mock formularzu
    if (window.activeQuoteForm) {
        // Bezpośrednie zerowanie dataset
        window.activeQuoteForm.dataset.finishingBrutto = '0';
        window.activeQuoteForm.dataset.finishingNetto = '0';

        log('finishing', '✅ WYMUSZONO zerowanie dataset.finishingBrutto/Netto w clearFinishingSelections');

        // ✅ NOWA DODATKOWA POPRAWKA: Wymuś wywołanie calculateFinishingCost po czyszczeniu
        if (typeof calculateFinishingCost === 'function') {
            setTimeout(() => {
                try {
                    const result = calculateFinishingCost(window.activeQuoteForm);
                    log('finishing', `✅ WYMUSZONE przeliczenie po clearFinishingSelections: ${result?.brutto || 0} PLN brutto`);
                } catch (err) {
                    log('finishing', '❌ Błąd przeliczania po clearFinishingSelections:', err);
                }
            }, 50);
        }

        // ✅ DODATKOWE WYMUSZENIE: Bezpośrednio aktualizuj elementy UI
        const finishingBruttoEl = window.activeQuoteForm.querySelector('.finishing-brutto');
        const finishingNettoEl = window.activeQuoteForm.querySelector('.finishing-netto');

        if (finishingBruttoEl) finishingBruttoEl.textContent = '0.00 PLN';
        if (finishingNettoEl) finishingNettoEl.textContent = '0.00 PLN';

        log('finishing', '✅ Zresetowano koszty wykończenia w formularzu (agresywnie)');
    }
}

function safeAttachFinishingUIListeners(form) {
    if (!form) {
        log('calculator', '❌ Brak formularza dla attachFinishingUIListeners');
        return;
    }

    try {
        // Sprawdź czy formularz ma klasę quote-form
        if (!form.classList.contains('quote-form')) {
            form.classList.add('quote-form');
        }

        // Znajdź przyciski w formularzu
        const typeButtons = form.querySelectorAll('.finishing-btn[data-finishing-type]');
        const variantButtons = form.querySelectorAll('.finishing-btn[data-finishing-variant]');
        const colorButtons = form.querySelectorAll('.color-btn[data-finishing-color]');

        log('calculator', `Znaleziono przyciski: ${typeButtons.length} typów, ${variantButtons.length} wariantów, ${colorButtons.length} kolorów`);

        // Dodaj event listenery bez błędów
        typeButtons.forEach(btn => {
            // Usuń poprzednie listenery (jeśli istnieją)
            btn.replaceWith(btn.cloneNode(true));
            const newBtn = form.querySelector(`[data-finishing-type="${btn.dataset.finishingType}"]`);

            newBtn.addEventListener('click', function () {
                // Reset innych przycisków typu
                typeButtons.forEach(b => b.classList.remove('active'));
                this.classList.add('active');

                // Wywołaj calculation
                if (typeof calculateFinishingCost === 'function') {
                    try {
                        calculateFinishingCost(form);
                    } catch (calcError) {
                        log('calculator', '⚠️ Błąd w calculateFinishingCost:', calcError);
                    }
                }
            });
        });

        variantButtons.forEach(btn => {
            // Usuń poprzednie listenery (jeśli istnieją)
            btn.replaceWith(btn.cloneNode(true));
            const newBtn = form.querySelector(`[data-finishing-variant="${btn.dataset.finishingVariant}"]`);

            newBtn.addEventListener('click', function () {
                // Reset innych przycisków wariantu
                variantButtons.forEach(b => b.classList.remove('active'));
                this.classList.add('active');

                // Wywołaj calculation
                if (typeof calculateFinishingCost === 'function') {
                    try {
                        calculateFinishingCost(form);
                    } catch (calcError) {
                        log('calculator', '⚠️ Błąd w calculateFinishingCost:', calcError);
                    }
                }
            });
        });

        colorButtons.forEach(btn => {
            // Usuń poprzednie listenery (jeśli istnieją)
            btn.replaceWith(btn.cloneNode(true));
            const newBtn = form.querySelector(`[data-finishing-color="${btn.dataset.finishingColor}"]`);

            newBtn.addEventListener('click', function () {
                // Reset innych przycisków koloru
                colorButtons.forEach(b => b.classList.remove('active'));
                this.classList.add('active');
            });
        });

        log('calculator', '✅ Event listenery wykończenia dodane pomyślnie');

    } catch (error) {
        log('calculator', '❌ Błąd w safeAttachFinishingUIListeners:', error);
    }
}

/**
 * Uniwersalna funkcja ładowania skryptów
 */
function loadScript(src) {
    return new Promise((resolve, reject) => {
        if (document.querySelector(`script[src="${src}"]`)) {
            resolve();
            return;
        }

        const script = createElement('script', { src });
        script.onload = resolve;
        script.onerror = () => reject(new Error(`Failed to load: ${src}`));
        document.head.appendChild(script);
    });
}

// ==================== VARIANT MANAGEMENT ====================

/**
 * Zoptymalizowane zarządzanie wariantami
 */
function updateEditorVariantAvailability(checkbox) {
    const variantOption = checkbox.closest('.variant-option');
    if (!variantOption) return;

    const radioButton = variantOption.querySelector('input[type="radio"]');
    const isAvailable = checkbox.checked;

    // Batch class and state updates
    variantOption.classList.toggle('unavailable', !isAvailable);
    if (radioButton) {
        radioButton.disabled = !isAvailable;

        if (!isAvailable && radioButton.checked) {
            radioButton.checked = false;
            selectFirstAvailableVariant();
        }
    }

    log('sync', `Wariant ${checkbox.dataset.variant}: ${isAvailable ? 'dostępny' : 'niedostępny'}`);
}

function selectFirstAvailableVariant() {
    const availableRadio = document.querySelector('input[name="edit-variantOption"]:not(:disabled)');
    if (availableRadio) {
        availableRadio.checked = true;
        updateSelectedVariant(availableRadio);
        onFormDataChange();
    }
}

function updateSelectedVariant(selectedRadio) {
    // Batch class updates
    document.querySelectorAll('.variant-option').forEach(option => {
        option.classList.remove('selected');
    });

    const selectedOption = selectedRadio.closest('.variant-option');
    if (selectedOption) {
        selectedOption.classList.add('selected');
    }

    // ✅ KLUCZOWA POPRAWKA: Po zmianie wariantu skopiuj ceny z mock formularza
    setTimeout(() => {
        copyCalculationResults();
        updateQuoteSummary();
        log('sync', `✅ Zaktualizowano ceny po zmianie wariantu: ${selectedRadio.value}`);
    }, 100); // Krótki delay żeby calculator.js zdążył przeliczyć
}
// ==================== OPTIMIZED CALCULATOR INTEGRATION ====================

/**
 * Zoptymalizowana synchronizacja do mock form
 */
function syncEditorToMockForm() {
    if (!window.activeQuoteForm) {
        log('sync', '❌ Brak activeQuoteForm do synchronizacji');
        return false;
    }

    const syncMappings = [
        { editor: 'edit-clientType', calculator: '[data-field="clientType"]' },
        { editor: 'edit-length', calculator: '[data-field="length"]' },
        { editor: 'edit-width', calculator: '[data-field="width"]' },
        { editor: 'edit-thickness', calculator: '[data-field="thickness"]' },
        { editor: 'edit-quantity', calculator: '[data-field="quantity"]' }
    ];

    let syncedCount = 0;

    // ✅ POPRAWIONA synchronizacja z logowaniem
    syncMappings.forEach(({ editor, calculator }) => {
        const editorEl = document.getElementById(editor);
        const calcEl = window.activeQuoteForm.querySelector(calculator);

        if (editorEl && calcEl) {
            const editorValue = editorEl.value || '';
            const calcValue = calcEl.value || '';

            if (editorValue !== calcValue) {
                calcEl.value = editorValue;
                log('sync', `✅ Zsynchronizowano ${editor}: "${editorValue}"`);
                syncedCount++;
            }
        } else {
            log('sync', `⚠️ Nie można zsynchronizować ${editor}`);
        }
    });

    // ✅ KLUCZOWA POPRAWKA: Po synchronizacji pól wymuś aktualizację przelicznika
    updateCalculatorMultiplier();

    syncAvailabilityStates(window.activeQuoteForm);
    syncSelectedVariant();

    log('sync', `✅ Zsynchronizowano ${syncedCount}/${syncMappings.length} pól`);
    return syncedCount > 0;
}

/**
 * Zoptymalizowana kopia results
 */
function copyCalculationResults() {
    if (!window.activeQuoteForm) {
        log('sync', '❌ Brak activeQuoteForm do kopiowania wyników');
        return;
    }

    const calculatorVariants = window.activeQuoteForm.querySelectorAll('.variant-item');
    const editorVariants = document.querySelectorAll('.variant-option');

    log('sync', `Kopiowanie wyników: ${calculatorVariants.length} calculator → ${editorVariants.length} editor`);

    // Create mapping for efficient lookup
    const editorVariantMap = new Map();
    editorVariants.forEach(variant => {
        const radio = variant.querySelector('input[type="radio"]');
        if (radio) editorVariantMap.set(radio.value, variant);
    });

    let copiedCount = 0;

    // Copy prices between variants
    calculatorVariants.forEach(calcVariant => {
        const calcRadio = calcVariant.querySelector('input[type="radio"]');
        if (!calcRadio) return;

        const editorVariant = editorVariantMap.get(calcRadio.value);
        if (!editorVariant) return;

        const copied = copyPricesBetweenVariants(calcVariant, editorVariant);
        if (copied) copiedCount++;
    });

    log('sync', `✅ Skopiowano ceny dla ${copiedCount} wariantów`);

    // ✅ KLUCZOWA POPRAWKA: Skopiuj dataset z wybranego wariantu
    copySelectedVariantDataset();

    // ✅ POPRAWKA: Zaktualizuj totały w aktywnym produkcie
    updateActiveProductTotals();
}

function copyPricesBetweenVariants(source, target) {
    if (!source || !target) return false;

    const priceFields = ['unit-brutto', 'unit-netto', 'total-brutto', 'total-netto'];
    let copiedFields = 0;

    priceFields.forEach(field => {
        const sourceEl = source.querySelector(`.${field}`);
        const targetEl = target.querySelector(`.${field}`);

        if (sourceEl && targetEl && sourceEl.textContent) {
            targetEl.textContent = sourceEl.textContent;
            copiedFields++;
        }
    });

    return copiedFields > 0;
}

/**
 * NOWA funkcja kopiowania datasetu wybranego wariantu
 */
function copySelectedVariantDataset() {
    if (!window.activeQuoteForm) return;

    const selectedMockRadio = window.activeQuoteForm.querySelector('input[type="radio"]:checked');
    const selectedEditorRadio = document.querySelector('input[name="edit-variantOption"]:checked');

    if (selectedMockRadio && selectedEditorRadio) {
        // Skopiuj dataset z mock radio do editor radio
        const datasetFields = ['totalBrutto', 'totalNetto', 'unitBrutto', 'unitNetto'];

        datasetFields.forEach(field => {
            if (selectedMockRadio.dataset[field]) {
                selectedEditorRadio.dataset[field] = selectedMockRadio.dataset[field];
            }
        });

        log('sync', `✅ Skopiowano dataset wariantu: ${selectedEditorRadio.value}`);
    }
}

// ==================== OPTIMIZED VALIDATION ====================

/**
 * Zoptymalizowana walidacja formularza
 */
function validateFormBeforeSave() {
    const validationRules = [
        { field: 'edit-clientType', message: 'Wybierz grupę cenową', validator: (v) => !!v },
        { field: 'edit-length', message: 'Podaj poprawną długość', validator: (v) => v > 0 },
        { field: 'edit-width', message: 'Podaj poprawną szerokość', validator: (v) => v > 0 },
        { field: 'edit-thickness', message: 'Podaj poprawną grubość', validator: (v) => v > 0 },
        { field: 'edit-quantity', message: 'Podaj poprawną ilość', validator: (v) => v > 0 }
    ];

    // Check all fields in single loop
    for (const rule of validationRules) {
        const element = document.getElementById(rule.field);
        const value = element?.value;
        const numValue = parseFloat(value);

        if (!rule.validator(rule.field === 'edit-clientType' ? value : numValue)) {
            alert(rule.message);
            return false;
        }
    }

    // Validate variant selection
    const selectedVariant = document.querySelector('input[name="edit-variantOption"]:checked');
    if (!selectedVariant) {
        alert('Wybierz wariant produktu');
        return false;
    }

    if (selectedVariant.disabled) {
        alert('Wybrany wariant jest niedostępny. Wybierz dostępny wariant.');
        return false;
    }

    // Check available variants
    const availableVariants = document.querySelectorAll('.variant-availability-checkbox:checked');
    if (availableVariants.length === 0) {
        alert('Musi być dostępny przynajmniej jeden wariant');
        return false;
    }

    return true;
}

// ==================== OPTIMIZED HELPER FUNCTIONS ====================

/**
 * Sprawdzanie gotowości kalkulatora - zoptymalizowane
 */
function checkCalculatorReadiness() {
    const requirements = [
        calculatorScriptLoaded,
        calculatorInitialized,
        typeof updatePrices === 'function',
        typeof window.pricesFromDatabase !== 'undefined',
        typeof window.multiplierMapping !== 'undefined'
    ];

    const isReady = requirements.every(Boolean);

    if (DEBUG_LOGS.calculator) {
        log('calculator', 'Stan calculator.js:', {
            scriptLoaded: calculatorScriptLoaded,
            initialized: calculatorInitialized,
            updatePricesAvailable: typeof updatePrices === 'function',
            pricesDataAvailable: typeof window.pricesFromDatabase !== 'undefined',
            multipliersAvailable: typeof window.multiplierMapping !== 'undefined',
            ready: isReady
        });
    }

    return isReady;
}

/**
 * Sprawdzanie czy wycena może być edytowana - zoptymalizowane
 */
function canEditQuote(quoteData) {
    const nonEditableStatuses = ['Zaakceptowane', 'Zamówione', 'Zrealizowane', 'Anulowane'];

    if (nonEditableStatuses.includes(quoteData.status_name)) {
        return false;
    }

    if (quoteData.accepted_by_email && quoteData.acceptance_date) {
        return false;
    }

    return true;
}

/**
 * Zoptymalizowana inicjalizacja kalkulatora
 */
function initializeCalculatorForEditor() {
    if (calculatorInitialized) return;

    // Batch initialization
    const initTasks = [
        initializePriceIndex,
        initializeMultiplierMapping,
        copyVariantMappingToEditor
    ];

    initTasks.forEach(task => {
        try {
            task();
        } catch (error) {
            console.warn(`[QUOTE EDITOR] Błąd w ${task.name}:`, error);
        }
    });

    calculatorInitialized = true;
    log('calculator', '✅ Calculator.js zainicjalizowany');
}

function initializePriceIndex() {
    const pricesDataEl = document.getElementById('prices-data');
    if (pricesDataEl) {
        const pricesFromDatabase = JSON.parse(pricesDataEl.textContent);
        window.pricesFromDatabase = pricesFromDatabase;

        // Build index efficiently
        window.priceIndex = pricesFromDatabase.reduce((index, entry) => {
            const key = `${entry.species}::${entry.technology}::${entry.wood_class}`;
            if (!index[key]) index[key] = [];
            index[key].push(entry);
            return index;
        }, {});

        log('calculator', '✅ Zainicjalizowano priceIndex');
    }
}

function initializeMultiplierMapping() {
    if (typeof window.multiplierMapping === 'undefined') {
        const multipliersDataEl = document.getElementById('multipliers-data');
        if (multipliersDataEl) {
            const multipliersFromDB = JSON.parse(multipliersDataEl.textContent);
            window.multiplierMapping = multipliersFromDB.reduce((mapping, m) => {
                mapping[m.label] = m.value;
                return mapping;
            }, {});

            log('calculator', '✅ Zainicjalizowano multiplierMapping');
        }
    }
}

function copyVariantMappingToEditor() {
    if (typeof window.variantMapping === 'undefined') {
        window.variantMapping = {
            'dab-lity-ab': { species: 'Dąb', technology: 'Lity', wood_class: 'A/B' },
            'dab-lity-bb': { species: 'Dąb', technology: 'Lity', wood_class: 'B/B' },
            'dab-micro-ab': { species: 'Dąb', technology: 'Mikrowczep', wood_class: 'A/B' },
            'dab-micro-bb': { species: 'Dąb', technology: 'Mikrowczep', wood_class: 'B/B' },
            'jes-lity-ab': { species: 'Jesion', technology: 'Lity', wood_class: 'A/B' },
            'jes-micro-ab': { species: 'Jesion', technology: 'Mikrowczep', wood_class: 'A/B' },
            'buk-lity-ab': { species: 'Buk', technology: 'Lity', wood_class: 'A/B' },
            'buk-micro-ab': { species: 'Buk', technology: 'Mikrowczep', wood_class: 'A/B' }
        };
        log('calculator', '✅ Skopiowano variantMapping');
    }
}

// ==================== OPTIMIZED PRODUCT MANAGEMENT ====================

/**
 * NOWA FUNKCJA - dodaj na końcu pliku, przed ostatnim komentarzem
 * Aktualizuje przelicznik w calculator.js z danych edytora
 */
function updateMultiplierFromEditor() {
    const clientTypeSelect = document.getElementById('edit-clientType');
    if (!clientTypeSelect || !clientTypeSelect.value) {
        log('sync', '⚠️ Brak grupy cenowej w edytorze');
        return;
    }

    const selectedOption = clientTypeSelect.options[clientTypeSelect.selectedIndex];
    if (!selectedOption || !selectedOption.dataset.multiplierValue) {
        log('sync', '⚠️ Brak danych przelicznika dla wybranej grupy');
        return;
    }

    const clientType = selectedOption.value;
    const multiplierValue = parseFloat(selectedOption.dataset.multiplierValue);

    // ✅ KLUCZOWA POPRAWKA: Zaktualizuj zmienne globalne calculator.js
    if (typeof window.currentClientType !== 'undefined') {
        window.currentClientType = clientType;
        log('sync', `✅ Zaktualizowano currentClientType: ${clientType}`);
    }

    if (typeof window.currentMultiplier !== 'undefined') {
        window.currentMultiplier = multiplierValue;
        log('sync', `✅ Zaktualizowano currentMultiplier: ${multiplierValue}`);
    }

    // ✅ Zaktualizuj multiplierMapping jeśli istnieje
    if (typeof window.multiplierMapping === 'object' && window.multiplierMapping) {
        window.multiplierMapping[clientType] = multiplierValue;
        log('sync', `✅ Zaktualizowano multiplierMapping[${clientType}] = ${multiplierValue}`);
    }
}

/**
 * NOWA FUNKCJA - dodaj na końcu pliku, przed ostatnim komentarzem
 * Synchronizuje grupę cenową na wszystkich produktach w wycenie
 */
function syncClientTypeAcrossAllProducts(clientType, multiplierValue) {
    log('sync', `Synchronizuję grupę ${clientType} (${multiplierValue}) na wszystkich produktach`);

    if (!currentEditingQuoteData?.items) {
        log('sync', '⚠️ Brak produktów do synchronizacji');
        return;
    }

    // ✅ Zaktualizuj grupę cenową w danych każdego produktu
    currentEditingQuoteData.items.forEach((item, index) => {
        if (item) {
            item.client_type = clientType;
            item.multiplier = multiplierValue;
            log('sync', `✅ Zaktualizowano grupę w produkcie ${index}: ${clientType}`);
        }
    });

    // ✅ Zaktualizuj kartki produktów (jeśli są wyświetlane)
    const productCards = document.querySelectorAll('.product-card');
    productCards.forEach((card, index) => {
        const multiplierDisplay = card.querySelector('.product-multiplier');
        if (multiplierDisplay) {
            multiplierDisplay.textContent = `${clientType} (${multiplierValue})`;
        }
    });

    // ✅ Zaktualizuj dane głównej wyceny
    if (currentEditingQuoteData) {
        currentEditingQuoteData.quote_client_type = clientType;
        currentEditingQuoteData.quote_multiplier = multiplierValue;
        log('sync', `✅ Zaktualizowano główne dane wyceny: ${clientType} (${multiplierValue})`);
    }

    log('sync', '✅ Synchronizacja grupy cenowej zakończona');
}

/**
 * NOWA FUNKCJA - dodaj na końcu pliku, przed ostatnim komentarzem
 * Aktualizuje przelicznik w calculator.js (wersja uproszczona dla syncEditorToMockForm)
 */
function updateCalculatorMultiplier() {
    const clientTypeSelect = document.getElementById('edit-clientType');
    if (!clientTypeSelect || !clientTypeSelect.value) {
        return;
    }

    const selectedOption = clientTypeSelect.options[clientTypeSelect.selectedIndex];
    if (!selectedOption || !selectedOption.dataset.multiplierValue) {
        return;
    }

    const clientType = selectedOption.value;
    const multiplierValue = parseFloat(selectedOption.dataset.multiplierValue);

    // ✅ Bezpieczna aktualizacja zmiennych globalnych
    try {
        if (typeof window.currentClientType !== 'undefined') {
            window.currentClientType = clientType;
        }

        if (typeof window.currentMultiplier !== 'undefined') {
            window.currentMultiplier = multiplierValue;
        }

        if (typeof window.multiplierMapping === 'object' && window.multiplierMapping) {
            window.multiplierMapping[clientType] = multiplierValue;
        }

        log('sync', `✅ Zaktualizowano przelicznik calculator.js: ${clientType} (${multiplierValue})`);
    } catch (error) {
        log('sync', '❌ Błąd aktualizacji przelicznika:', error);
    }
}

/**
 * NOWA FUNKCJA - dodaj na końcu pliku, przed ostatnim komentarzem
 * Kopiuje dataset z wybranego wariantu (używana w copyCalculationResults)
 */
function copySelectedVariantDataset() {
    if (!window.activeQuoteForm) return;

    const selectedMockRadio = window.activeQuoteForm.querySelector('input[type="radio"]:checked');
    if (!selectedMockRadio) {
        log('sync', '⚠️ Brak zaznaczonego wariantu w mock formularzu');
        return;
    }

    // ✅ Skopiuj dataset z mock formularza do zmiennych globalnych
    const datasetKeys = ['orderBrutto', 'orderNetto', 'totalBrutto', 'totalNetto'];

    datasetKeys.forEach(key => {
        if (window.activeQuoteForm.dataset[key]) {
            // Zapisz w globalnej zmiennej dla aktywnego produktu
            window.currentActiveProductData = window.currentActiveProductData || {};
            window.currentActiveProductData[key] = window.activeQuoteForm.dataset[key];

            log('sync', `✅ Skopiowano ${key}: ${window.activeQuoteForm.dataset[key]}`);
        }
    });
}

/**
 * NOWA FUNKCJA - dodaj na końcu pliku, przed ostatnim komentarzem
 * Aktualizuje totały aktywnego produktu na podstawie obliczeń
 */
function updateActiveProductTotals() {
    if (!window.currentActiveProductData || activeProductIndex === null) {
        return;
    }

    const activeProduct = currentEditingQuoteData?.items?.find(
        item => item.product_index === activeProductIndex
    );

    if (activeProduct && window.currentActiveProductData.orderBrutto) {
        // ✅ Zaktualizuj totały w danych produktu
        activeProduct.total_brutto = parseFloat(window.currentActiveProductData.orderBrutto);
        activeProduct.total_netto = parseFloat(window.currentActiveProductData.orderNetto);

        log('sync', `✅ Zaktualizowano totały produktu ${activeProductIndex}:`, {
            brutto: activeProduct.total_brutto,
            netto: activeProduct.total_netto
        });
    }
}

/**
 * Saves current active product form data into currentEditingQuoteData
 * so switching between products keeps the changes in memory
 */
function saveActiveProductFormData() {
    if (!currentEditingQuoteData || activeProductIndex === null) {
        log('sync', '❌ Brak danych do zapisania');
        return;
    }

    const formElements = {
        length: document.getElementById('edit-length')?.value,
        width: document.getElementById('edit-width')?.value,
        thickness: document.getElementById('edit-thickness')?.value,
        quantity: document.getElementById('edit-quantity')?.value,
        finishingType: document.getElementById('finishing-type')?.textContent?.trim(),
        finishingVariant: document.getElementById('finishing-variant')?.textContent?.trim(),
        finishingColor: document.getElementById('finishing-color')?.textContent?.trim(),
        finishingGloss: document.getElementById('finishing-gloss-level')?.textContent?.trim()
    };

    const selectedVariant = document.querySelector('input[name="edit-variantOption"]:checked');

    // Aktualizuj podstawowe dane produktu (bez zmiany show_on_client_page)
    currentEditingQuoteData.items
        .filter(item => item.product_index === activeProductIndex)
        .forEach(item => {
            item.length_cm = formElements.length;
            item.width_cm = formElements.width;
            item.thickness_cm = formElements.thickness;
            item.quantity = formElements.quantity;
            item.finishing_type = formElements.finishingType;
            item.finishing_variant = formElements.finishingVariant;
            item.finishing_color = formElements.finishingColor;
            item.finishing_gloss = formElements.finishingGloss;
        });

    // Aktualizuj is_selected tylko dla wybranego wariantu
    if (selectedVariant) {
        const selectedVariantCode = selectedVariant.value;

        // Odznacz wszystkie warianty dla tego produktu
        currentEditingQuoteData.items
            .filter(item => item.product_index === activeProductIndex)
            .forEach(item => {
                item.is_selected = false;
            });

        // Zaznacz tylko wybrany wariant
        const selectedItem = currentEditingQuoteData.items.find(
            item => item.product_index === activeProductIndex && item.variant_code === selectedVariantCode
        );

        if (selectedItem) {
            selectedItem.is_selected = true;
            log('sync', `✅ Ustawiono jako wybrany wariant: ${selectedVariantCode} (id: ${selectedItem.id})`);
        } else {
            log('sync', `⚠️ Nie znaleziono pozycji dla wybranego wariantu: ${selectedVariantCode}`);
        }
    }

    // ✅ KLUCZOWA POPRAWKA: Aktualizuj show_on_client_page tylko na podstawie checkboxów
    // ALE TYLKO wtedy gdy checkboxy faktycznie zmieniły się względem danych z backend-u
    const availabilityCheckboxes = document.querySelectorAll('.variant-availability-checkbox');
    availabilityCheckboxes.forEach(cb => {
        const variant = cb.dataset.variant;
        const item = currentEditingQuoteData.items.find(
            i => i.product_index === activeProductIndex && i.variant_code === variant
        );

        if (item) {
            // Sprawdź czy checkbox różni się od stanu w danych
            const currentBackendValue = item.show_on_client_page;
            const checkboxValue = cb.checked;

            // Konwertuj backend value na boolean dla porównania
            const backendBoolean = currentBackendValue === true || currentBackendValue === 1 || currentBackendValue === '1';

            // Aktualizuj TYLKO jeśli wartość się zmieniła
            if (backendBoolean !== checkboxValue) {
                // POPRAWKA: Zachowaj typ danych zgodny z backend-em (boolean)
                item.show_on_client_page = checkboxValue;
                log('sync', `Zaktualizowano dostępność wariantu ${variant}: ${checkboxValue ? 'true (widoczny)' : 'false (niewidoczny)'}`);
            } else {
                log('sync', `Dostępność wariantu ${variant}: bez zmian (${backendBoolean ? 'widoczny' : 'niewidoczny'})`);
            }
        }
    });

    log('sync', '✅ Zapisano dane aktywnego produktu (bez nadpisywania oryginalnych wartości)');
}

/**
 * Zoptymalizowana aktywacja produktu
 */
function activateProductInEditor(productIndex) {
    // Zachowaj poprzedni indeks przed zmianą
    const previousIndex = activeProductIndex;

    // Zachowaj dane aktualnie edytowanego produktu przed zmianą
    saveActiveProductFormData();

    // NOWE: przed zmianą aktywnego produktu zapisz również jego koszty
    if (previousIndex !== null && currentEditingQuoteData) {
        updateQuoteSummary();
        updateProductsSummaryTotals();
    }

    if (!currentEditingQuoteData) {
        log('editor', '❌ Brak danych wyceny');
        return;
    }

    const productItem = currentEditingQuoteData.items.find(item => item.product_index === productIndex);
    if (!productItem) {
        log('editor', `❌ Nie znaleziono produktu o indeksie: ${productIndex}`);
        return;
    }

    activeProductIndex = productIndex;

    // Wyzeruj dataset kalkulatora, aby nie przenosić kosztów między produktami
    if (window.activeQuoteForm?.dataset) {
        window.activeQuoteForm.dataset.orderBrutto = '0';
        window.activeQuoteForm.dataset.orderNetto = '0';
        window.activeQuoteForm.dataset.finishingBrutto = '0';
        window.activeQuoteForm.dataset.finishingNetto = '0';
    }

    // Usuń zapisane wyniki poprzedniego produktu
    window.currentActiveProductData = {};

    // ✅ KLUCZOWA POPRAWKA: Zachowaj aktualną grupę cenową
    const currentClientType = document.getElementById('edit-clientType')?.value;

    // Batch UI updates
    updateProductCardStates(productIndex);
    loadProductDataToForm(productItem);

    // ✅ POPRAWKA: Przywróć grupę cenową po załadowaniu produktu
    if (currentClientType) {
        const clientTypeSelect = document.getElementById('edit-clientType');
        if (clientTypeSelect && clientTypeSelect.value !== currentClientType) {
            clientTypeSelect.value = currentClientType;
            log('editor', `✅ Przywrócono grupę cenową: ${currentClientType}`);
        }
    }

    // DODAJ TO: Ustaw odpowiedni wariant dla aktywnego produktu
    if (currentEditingQuoteData) {
        setSelectedVariantForActiveProduct(productIndex);
    }

    // Ustaw dostępność wariantów dla aktywnego produktu
    applyVariantAvailabilityFromQuoteData(currentEditingQuoteData, productIndex);

    // ✅ POPRAWKA: Wymuś przeliczenie po aktywacji produktu
    setTimeout(() => {
        onFormDataChange();
    }, 100);

    // ✅ DODANE: Zawsze aktualizuj podsumowanie po zmianie aktywnego produktu
    updateQuoteSummary();

    log('editor', `✅ Aktywowano produkt: ${productIndex}`);
}

function updateProductCardStates(activeIndex) {
    const cards = document.querySelectorAll('.product-card');
    cards.forEach(card => {
        card.classList.toggle('active', parseInt(card.dataset.index) === activeIndex);
    });
}

/**
 * Zoptymalizowane ładowanie danych produktu
 */
function loadProductDataToForm(productItem) {
    const fieldMappings = [
        { field: 'edit-length', value: productItem.length_cm },
        { field: 'edit-width', value: productItem.width_cm },
        { field: 'edit-thickness', value: productItem.thickness_cm },
        { field: 'edit-quantity', value: productItem.quantity || 1 }
    ];

    // Batch field updates
    fieldMappings.forEach(({ field, value }) => {
        const element = document.getElementById(field);
        if (element) element.value = value || '';
    });

    // Załaduj wykończenie dla tego produktu
    loadFinishingDataToForm(productItem);

    // Handle variant selection
    if (productItem.variant_code) {
        selectVariantByCode(productItem.variant_code);
    }
}

/**
 * DODAJ TĘ FUNKCJĘ - Główna funkcja ustawiająca wybrane warianty na podstawie danych z wyceny
 */
function setSelectedVariantsByQuote(quoteData) {
    log('editor', 'Ustawianie wybranych wariantów z wyceny...');

    if (!quoteData?.items?.length) {
        log('editor', 'Brak pozycji w wycenie - używam domyślnych ustawień');
        setDefaultVariantSelection();
        return;
    }

    // Zbierz wybrane warianty dla każdego produktu
    const selectedVariantsByProduct = new Map();

    quoteData.items.forEach(item => {
        if (isVariantSelected(item) && item.variant_code) {
            selectedVariantsByProduct.set(item.product_index, item.variant_code);
            log('editor', `Produkt ${item.product_index}: wybrany wariant ${item.variant_code}`);
        }
    });

    // Jeśli nie ma wybranych wariantów, ustaw domyślne
    if (selectedVariantsByProduct.size === 0) {
        log('editor', 'Brak wybranych wariantów - używam domyślnych');
        setDefaultVariantSelection();
        return;
    }

    // Ustaw warianty w interfejsie edytora
    setVariantsInEditor(selectedVariantsByProduct);
}

/**
 * ✅ NOWA FUNKCJA POMOCNICZA - Sprawdza czy wariant jest wybrany
 */
function isVariantSelected(item) {
    const value = item.is_selected;
    return value === true || value === 1 || value === '1' || value === 'true';
}

/**
 * DODAJ TĘ FUNKCJĘ - Ustawia warianty w interfejsie edytora na podstawie mapy wybranych wariantów
 */
function setVariantsInEditor(selectedVariantsByProduct) {
    // Najpierw wyczyść wszystkie zaznaczenia
    clearAllVariantSelections();

    // Dla aktywnego produktu ustaw odpowiedni wariant
    if (activeProductIndex !== null && selectedVariantsByProduct.has(activeProductIndex)) {
        const variantCode = selectedVariantsByProduct.get(activeProductIndex);
        selectVariantByCode(variantCode);
        log('editor', `Ustawiono wariant ${variantCode} dla aktywnego produktu ${activeProductIndex}`);
    } else {
        // Jeśli aktywny produkt nie ma wybranego wariantu, ustaw pierwszy dostępny
        selectFirstAvailableVariant();
        log('editor', 'Ustawiono pierwszy dostępny wariant dla aktywnego produktu');
    }
}

/**
 * DODAJ TĘ FUNKCJĘ - Wyczyść wszystkie zaznaczenia wariantów
 */
function clearAllVariantSelections() {
    document.querySelectorAll('input[name="edit-variantOption"]').forEach(radio => {
        radio.checked = false;
    });

    // Usuń klasy selected z variant-option
    document.querySelectorAll('.variant-option').forEach(option => {
        option.classList.remove('selected');
    });

    log('editor', 'Wyczyszczono wszystkie zaznaczenia wariantów');
}

/**
 * DODAJ TĘ FUNKCJĘ - Ustawianie domyślnego wariantu (gdy brak danych z wyceny)
 */
function setDefaultVariantSelection() {
    log('editor', 'Ustawianie domyślnego wariantu...');

    // Sprawdź czy istnieje preferowany wariant "dab-lity-ab"
    const defaultVariant = document.querySelector('input[name="edit-variantOption"][value="dab-lity-ab"]');

    if (defaultVariant && !defaultVariant.disabled) {
        defaultVariant.checked = true;
        updateSelectedVariant(defaultVariant);
        log('editor', 'Ustawiono domyślny wariant: dab-lity-ab');
    } else {
        // Jeśli domyślny wariant nie jest dostępny, wybierz pierwszy dostępny
        selectFirstAvailableVariant();
        log('editor', 'Domyślny wariant niedostępny - wybrano pierwszy dostępny');
    }
}

/**
 * DODAJ TĘ FUNKCJĘ - Pomocnicza funkcja do sprawdzania wybranych wariantów
 */
function getSelectedVariantForProduct(quoteData, productIndex) {
    if (!quoteData?.items) return null;

    const selectedItem = quoteData.items.find(item =>
        item.product_index === productIndex && item.is_selected
    );

    return selectedItem?.variant_code || null;
}

/**
 * DODAJ TĘ FUNKCJĘ - Funkcja do sprawdzania czy wariant jest dostępny w edytorze
 */
function isVariantAvailableInEditor(variantCode) {
    const radioButton = document.querySelector(`input[name="edit-variantOption"][value="${variantCode}"]`);
    return radioButton && !radioButton.disabled;
}

/**
 * DODAJ TĘ FUNKCJĘ - Funkcja pomocnicza dla aktywnego produktu - ustaw odpowiedni wariant
 */
function setSelectedVariantForActiveProduct(productIndex) {
    // Znajdź wybrany wariant dla tego produktu
    const selectedVariant = getSelectedVariantForProduct(currentEditingQuoteData, productIndex);

    if (selectedVariant && isVariantAvailableInEditor(selectedVariant)) {
        selectVariantByCode(selectedVariant);
        log('editor', `Ustawiono wariant ${selectedVariant} dla produktu ${productIndex}`);
    } else {
        // Fallback - ustaw pierwszy dostępny wariant
        selectFirstAvailableVariant();
        log('editor', `Nie znaleziono wybranego wariantu - ustawiono pierwszy dostępny dla produktu ${productIndex}`);
    }
}

function selectVariantByCode(variantCode) {
    if (!variantCode) {
        log('editor', 'Brak kodu wariantu - pomijam selekcję');
        return;
    }

    // Wyczyść poprzednie zaznaczenia
    clearAllVariantSelections();

    // Znajdź odpowiedni radio button
    const radioButton = document.querySelector(`input[name="edit-variantOption"][value="${variantCode}"]`);

    if (radioButton) {
        // Sprawdź czy wariant jest dostępny
        if (radioButton.disabled) {
            log('editor', `Wariant ${variantCode} jest niedostępny - wybierz pierwszy dostępny`);
            selectFirstAvailableVariant();
            return;
        }

        // Zaznacz wariant
        radioButton.checked = true;
        updateSelectedVariant(radioButton);

        // Wywołaj event change dla aktualizacji cen
        radioButton.dispatchEvent(new Event('change', { bubbles: true }));

        log('editor', `✅ Wybrano wariant: ${variantCode}`);
    } else {
        log('editor', `❌ Nie znaleziono radio button dla wariantu: ${variantCode}`);
        selectFirstAvailableVariant();
    }
}

// ==================== OPTIMIZED MODAL MANAGEMENT ====================

/**
 * Zoptymalizowana konfiguracja zamykania modalu
 */
function setupModalCloseHandlers() {
    const modal = document.getElementById('quote-editor-modal');
    const closeElements = [
        '#close-quote-editor',
        '#cancel-quote-edit'
    ];

    const closeModal = () => {
        modal.style.display = 'none';
        resetEditorState(); // ✅ Używaj resetEditorState zamiast clearEditorData
    };

    // Attach close handlers
    closeElements.forEach(selector => {
        const element = document.querySelector(selector);
        if (element) element.onclick = closeModal;
    });

    // ✅ DODAJ: Pełne czyszczenie tylko przy rzeczywistym opuszczeniu strony
    window.addEventListener('beforeunload', clearEditorData);
}

/**
 * ✅ POPRAWIONA FUNKCJA - Reset stanu edytora z zachowaniem danych
 */
function resetEditorState() {
    log('editor', 'Reset stanu edytora...');

    // ✅ POPRAWKA: NIE resetuj currentEditingQuoteData od razu
    // Zostaw dane dostępne do następnego otwarcia

    // Reset tylko aktywnego produktu
    activeProductIndex = null;

    // Reset kalkulatora
    resetCalculatorAfterEditor();

    // ✅ POPRAWKA: Usuń event listenery
    const checkboxes = document.querySelectorAll('#quote-editor-modal .variant-availability-checkbox');
    checkboxes.forEach(checkbox => {
        checkbox.removeEventListener('change', handleVariantAvailabilityChange);
    });

    log('editor', '✅ Stan edytora zresetowany (dane zachowane)');
}

/**
 * ✅ NOWA FUNKCJA - Pełne czyszczenie danych edytora (tylko przy rzeczywistym zamknięciu)
 */
function clearEditorData() {
    log('editor', 'Pełne czyszczenie danych edytora...');
    currentEditingQuoteData = null;
    activeProductIndex = null;
    resetCalculatorAfterEditor();
}

/**
 * Zoptymalizowany reset kalkulatora
 */
function resetCalculatorAfterEditor() {
    log('calculator', 'Reset konfiguracji calculator.js...');

    // Restore original functions
    const restoreFunctions = [
        { backup: 'originalUpdatePrices', target: 'updatePrices' },
        { backup: 'originalUpdateVariantAvailability', target: 'updateVariantAvailability' }
    ];

    restoreFunctions.forEach(({ backup, target }) => {
        if (window[backup]) {
            window[target] = window[backup];
            delete window[backup];
        }
    });

    // Restore original variables
    const restoreVariables = [
        { backup: 'originalQuoteFormsContainer', target: 'quoteFormsContainer' },
        { backup: 'originalActiveQuoteForm', target: 'activeQuoteForm' }
    ];

    restoreVariables.forEach(({ backup, target }) => {
        if (window[backup]) {
            window[target] = window[backup];
            delete window[backup];
        } else {
            window[target] = null;
        }
    });

    // Remove temporary container
    const tempContainer = document.querySelector('#quote-editor-modal .quote-forms-container');
    if (tempContainer) tempContainer.remove();
}

// ==================== OPTIMIZED SAVE FUNCTIONALITY ====================

/**
 * Zoptymalizowane zapisywanie zmian
 */
function saveQuoteChanges() {
    log('editor', 'Zapisywanie zmian w wycenie...');

    // Zachowaj bieżące dane produktu przed zapisem
    saveActiveProductFormData();

    if (!currentEditingQuoteData) {
        alert('Błąd: Brak danych wyceny do zapisu');
        return;
    }

    if (!validateFormBeforeSave()) return;

    const updatedData = collectUpdatedQuoteData();
    if (!updatedData) {
        alert('Błąd: Nie udało się zebrać danych z formularza');
        return;
    }

    log('editor', 'Dane do zapisu:', updatedData);

    // TODO: Implement actual save to backend
    alert('Zapisywanie zmian będzie dostępne wkrótce!\n\nZebrane dane:\n' + JSON.stringify(updatedData, null, 2));
}

/**
 * Zbieranie danych do zapisu - zoptymalizowane
 */
function collectUpdatedQuoteData() {
    try {
        const formFields = ['edit-clientType', 'edit-length', 'edit-width', 'edit-thickness', 'edit-quantity'];
        const data = {};

        formFields.forEach(fieldId => {
            const element = document.getElementById(fieldId);
            if (element) {
                const key = fieldId.replace('edit-', '');
                data[key] = fieldId === 'edit-clientType' ? element.value : parseFloat(element.value) || 0;
            }
        });

        const selectedVariant = document.querySelector('input[name="edit-variantOption"]:checked');

        return {
            quote_id: currentEditingQuoteData.id,
            client_type: data.clientType,
            active_product: {
                index: activeProductIndex,
                length_cm: data.length,
                width_cm: data.width,
                thickness_cm: data.thickness,
                quantity: parseInt(data.quantity) || 1,
                variant_code: selectedVariant?.value || null,
                variant_name: selectedVariant?.dataset.variantName || null
            }
        };
    } catch (error) {
        console.error('[QUOTE EDITOR] Błąd zbierania danych:', error);
        return null;
    }
}

// ==================== OPTIMIZED FINISHING DATA LOADING ====================

/**
 * Zoptymalizowane ładowanie danych wykończenia z pobraniem cen z bazy danych
 */
async function loadFinishingDataFromDatabase() {
    if (finishingDataCache) {
        log('finishing', 'Używam cache danych wykończenia');
        renderFinishingUI(finishingDataCache);
        return finishingDataCache;
    }

    try {
        // Pobierz dane wykończenia z quotes API (zawiera więcej informacji)
        const response = await fetch('/quotes/api/finishing-data');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

        const data = await response.json();
        finishingDataCache = data; // Cache result

        // Przygotuj mapę cen dla łatwego dostępu
        window.finishingPrices = {};
        data.finishing_types.forEach(type => {
            window.finishingPrices[type.name] = parseFloat(type.price_netto);
        });

        renderFinishingUI(data);
        log('finishing', `✅ Załadowano dane wykończenia z bazy danych (${data.finishing_types.length} typów, ${data.finishing_colors.length} kolorów)`);
        log('finishing', 'Ceny wykończeń z bazy:', window.finishingPrices);

        return data;

    } catch (error) {
        console.error('[QUOTE EDITOR] ❌ Błąd ładowania danych wykończenia:', error);
        loadDefaultFinishingData();
        return null;
    }
}

/**
 * Inicjalizacja ładowania cen wykończenia przy starcie edytora
 */
async function initializeFinishingPrices() {
    log('finishing', 'Inicjalizacja cen wykończenia...');

    try {
        await loadFinishingDataFromDatabase();
        log('finishing', '✅ Ceny wykończenia zainicjalizowane');
    } catch (error) {
        console.error('[QUOTE EDITOR] ❌ Błąd inicjalizacji cen wykończenia:', error);
        loadDefaultFinishingData();
    }
}

function renderFinishingUI(data) {
    renderFinishingTypeButtonsFromDb(data.finishing_types);
    generateFinishingColorOptions(data.finishing_colors);
}

function renderFinishingTypeButtonsFromDb(finishingTypes) {
    const container = document.getElementById('edit-finishing-type-group');
    if (!container) return;

    const allowedTypes = ['Surowe', 'Lakierowanie', 'Olejowanie'];
    const fragment = document.createDocumentFragment();

    allowedTypes.forEach((type, index) => {
        const btn = createElement('button', {
            className: `finishing-btn${index === 0 ? ' active' : ''}`,
            textContent: type
        });
        btn.dataset.finishingType = type;
        fragment.appendChild(btn);
    });

    container.innerHTML = '';
    container.appendChild(fragment);
}

/**
 * Zoptymalizowane generowanie opcji kolorów
 */
function generateFinishingColorOptions(finishingColors) {
    const container = document.querySelector('#edit-finishing-color-wrapper .color-group');
    if (!container) return;

    const fragment = document.createDocumentFragment();

    finishingColors.forEach(color => {
        const button = createElement('button', {
            className: 'color-btn'
        });
        button.dataset.finishingColor = color.name;

        if (color.image_url) {
            const img = createElement('img', {
                src: color.image_url,
                alt: color.name
            });
            img.onerror = () => img.style.display = 'none';
            button.appendChild(img);
        }

        const span = createElement('span', {
            textContent: color.name
        });
        button.appendChild(span);

        fragment.appendChild(button);
    });

    container.innerHTML = '';
    container.appendChild(fragment);
}

// ==================== OPTIMIZED VARIANT MANAGEMENT ====================

/**
 * Zoptymalizowane dodawanie wariantów do formularza kalkulatora
 */
function addVariantsToCalculatorForm() {
    if (!window.activeQuoteForm) return;

    const variantsContainer = window.activeQuoteForm.querySelector('.variants');
    if (!variantsContainer || variantsContainer.children.length > 0) return;

    const editorVariants = document.querySelectorAll('.variant-option');
    const allForms = window.quoteFormsContainer.querySelectorAll('.quote-form');
    const tabIndex = Array.from(allForms).indexOf(window.activeQuoteForm);

    const fragment = document.createDocumentFragment();

    editorVariants.forEach(editorVariant => {
        const radio = editorVariant.querySelector('input[type="radio"]');
        if (!radio) return;

        const calculatorVariant = createCalculatorVariant(radio, tabIndex);
        fragment.appendChild(calculatorVariant);
    });

    variantsContainer.appendChild(fragment);
    log('calculator', `✅ Dodano ${editorVariants.length} wariantów do kalkulatora (tabIndex: ${tabIndex})`);
}

function createCalculatorVariant(sourceRadio, tabIndex) {
    const container = createElement('div', {
        className: 'variant-item',
        style: 'display: none'
    });

    // ✅ POPRAWKA: Poprawna nazwa radio button
    const radio = createElement('input', {
        type: 'radio',
        name: `variant-product-${tabIndex}-selected`, // Prawidłowa nazwa
        id: `calc-${sourceRadio.id}-${tabIndex}`, // Unikalne ID
        value: sourceRadio.value,
        checked: sourceRadio.checked
    });

    // Create price spans
    const priceSpans = ['unit-brutto', 'unit-netto', 'total-brutto', 'total-netto'];
    const elements = [radio];

    priceSpans.forEach(className => {
        elements.push(createElement('span', {
            className,
            textContent: 'Obliczanie...' // Domyślny tekst
        }));
    });

    elements.forEach(el => container.appendChild(el));
    return container;
}

// ==================== OPTIMIZED SYNC FUNCTIONS ====================

/**
 * Zoptymalizowana synchronizacja stanów dostępności
 */
function syncAvailabilityStates(mockForm) {
    const editorCheckboxes = document.querySelectorAll('#quote-editor-modal .variant-availability-checkbox');

    editorCheckboxes.forEach(editorCheckbox => {
        const variant = editorCheckbox.dataset.variant;
        if (!variant) return;

        const mockCheckbox = mockForm.querySelector(`[data-variant="${variant}"]`);
        if (mockCheckbox) {
            mockCheckbox.checked = editorCheckbox.checked;

            const mockRadio = mockCheckbox.parentElement.querySelector('input[type="radio"]');
            if (mockRadio) {
                mockRadio.disabled = !editorCheckbox.checked;
            }
        }
    });
}

function syncSelectedVariant() {
    if (!window.activeQuoteForm) return;

    const selectedEditorRadio = document.querySelector('.variant-option input[type="radio"]:checked');
    if (!selectedEditorRadio) return;

    const calculatorRadio = window.activeQuoteForm.querySelector(`input[value="${selectedEditorRadio.value}"]`);
    if (calculatorRadio) {
        calculatorRadio.checked = true;
    }
}

// ==================== OPTIMIZED PRICE CALCULATION ====================

/**
 * Zoptymalizowana funkcja getEditorPrice
 */
function getEditorPrice(species, technology, wood_class, thickness, length) {
    const roundedThickness = Math.ceil(thickness);
    const key = `${species}::${technology}::${wood_class}`;
    const entries = window.priceIndex?.[key] || [];

    if (entries.length === 0) return null;

    // Optimized search - break early when found
    for (const entry of entries) {
        const thickOk = roundedThickness >= entry.thickness_min && roundedThickness <= entry.thickness_max;
        const lengthOk = length >= entry.length_min && length <= entry.length_max;

        if (thickOk && lengthOk) {
            return entry;
        }
    }

    return null;
}

/**
 * POPRAWIONA FUNKCJA - syncFinishingStateToMockForm
 * Zastąp obecną funkcję syncFinishingStateToMockForm tym kodem
 */
function syncFinishingStateToMockForm() {
    const finishingType = getSelectedFinishingType();
    const finishingVariant = getSelectedFinishingVariant();
    const finishingColor = getSelectedFinishingColor();

    log('finishing', `Synchronizacja wykończenia: ${finishingType} ${finishingVariant || ''} ${finishingColor || ''}`);

    if (!window.activeQuoteForm) {
        log('finishing', '❌ Brak activeQuoteForm do synchronizacji');
        return;
    }

    const mockForm = window.activeQuoteForm;

    // Resetuj wszystkie active buttony
    mockForm.querySelectorAll('.finishing-btn.active').forEach(btn => {
        btn.classList.remove('active');
    });

    // ✅ KLUCZOWA POPRAWKA: Dla "Surowe" - wymuś resetowanie dataset PRZED ustawieniem przycisku
    if (finishingType === 'Surowe') {
        mockForm.dataset.finishingBrutto = '0';
        mockForm.dataset.finishingNetto = '0';
        log('finishing', '✅ WYMUSZONO zerowanie dataset dla "Surowe" PRZED synchronizacją');
    }

    // Ustaw active dla odpowiednich przycisków
    if (finishingType) {
        const typeBtn = mockForm.querySelector(`[data-finishing-type="${finishingType}"]`);
        if (typeBtn) {
            typeBtn.classList.add('active');
            log('finishing', `Zsynchronizowano typ: ${finishingType}`);
        }
    }

    if (finishingVariant) {
        const variantBtn = mockForm.querySelector(`[data-finishing-variant="${finishingVariant}"]`);
        if (variantBtn) {
            variantBtn.classList.add('active');
            log('finishing', `Zsynchronizowano wariant: ${finishingVariant}`);
        }
    }

    if (finishingColor) {
        const colorBtn = mockForm.querySelector(`[data-finishing-color="${finishingColor}"]`);
        if (colorBtn) {
            colorBtn.classList.add('active');
            log('finishing', `Zsynchronizowano kolor: ${finishingColor}`);
        }
    }

    // ✅ DODATKOWA POPRAWKA: Po synchronizacji dla "Surowe" - wymuś przeliczenie
    if (finishingType === 'Surowe' && typeof calculateFinishingCost === 'function') {
        setTimeout(() => {
            try {
                const result = calculateFinishingCost(mockForm);
                log('finishing', `✅ WYMUSZONE przeliczenie po sync "Surowe": ${result?.brutto || 0} PLN brutto`);

                // ✅ NOWA POPRAWKA: Po przeliczeniu wymuś aktualizację podsumowania
                setTimeout(() => {
                    updateQuoteSummary();
                    log('finishing', '✅ WYMUSZONA aktualizacja podsumowania po sync "Surowe"');
                }, 50);

            } catch (err) {
                log('finishing', '❌ Błąd przeliczania po sync:', err);
            }
        }, 50);
    }
}

// ==================== OPTIMIZED HELPER FUNCTIONS ====================

/**
 * Zoptymalizowane funkcje pomocnicze
 */
function translateVariantCode(variantCode) {
    if (!variantCode) return 'Nieznany wariant';

    const translations = {
        'dab-lity-ab': 'Klejonka dębowa lita A/B',
        'dab-lity-bb': 'Klejonka dębowa lita B/B',
        'dab-micro-ab': 'Klejonka dębowa mikrowczep A/B',
        'dab-micro-bb': 'Klejonka dębowa mikrowczep B/B',
        'jes-lity-ab': 'Klejonka jesionowa lita A/B',
        'jes-micro-ab': 'Klejonka jesionowa mikrowczep A/B',
        'buk-lity-ab': 'Klejonka bukowa lita A/B',
        'buk-micro-ab': 'Klejonka bukowa mikrowczep A/B'
    };

    return translations[variantCode] || variantCode;
}
/**
 * POPRAWKA FUNKCJI generateProductDescriptionForQuote - dodaj kolor do opisu
 */
function generateProductDescriptionForQuote(item, productItems) {
    if (!item) {
        console.log('[generateProductDescriptionForQuote] Brak item');
        return { main: 'Błąd produktu', sub: '' };
    }

    // POPRAWKA: Sprawdź kompletność na podstawie formularza (tylko dla aktywnego produktu)
    const isActiveProduct = parseInt(item.product_index) === activeProductIndex;
    let isComplete;

    if (isActiveProduct) {
        // Dla aktywnego produktu - sprawdź formularz
        isComplete = checkProductCompletenessInEditor();
        console.log('[generateProductDescriptionForQuote] Aktywny produkt - sprawdzam formularz:', isComplete);
    } else {
        // Dla nieaktywnych produktów - sprawdź dane z bazy (podstawowa walidacja)
        isComplete = item.length_cm > 0 && item.width_cm > 0 && item.thickness_cm > 0 &&
            item.quantity > 0 && item.variant_code &&
            item.final_price_netto > 0 && item.final_price_brutto > 0;
        console.log('[generateProductDescriptionForQuote] Nieaktywny produkt - sprawdzam dane z bazy:', isComplete);
    }

    if (!isComplete) {
        console.log('[generateProductDescriptionForQuote] Produkt niekompletny - zwracam komunikat błędu');
        return { main: 'Dokończ wycenę produktu', sub: '' };
    }

    // Dla aktywnego produktu - użyj danych z formularza
    let length, width, thickness, quantity, variantCode;

    if (isActiveProduct) {
        length = parseFloat(document.getElementById('edit-length')?.value) || item.length_cm;
        width = parseFloat(document.getElementById('edit-width')?.value) || item.width_cm;
        thickness = parseFloat(document.getElementById('edit-thickness')?.value) || item.thickness_cm;
        quantity = parseInt(document.getElementById('edit-quantity')?.value) || item.quantity;

        const selectedVariant = document.querySelector('input[name="edit-variantOption"]:checked');
        variantCode = selectedVariant?.value || item.variant_code;
    } else {
        // Dla nieaktywnych - użyj danych z bazy
        length = item.length_cm;
        width = item.width_cm;
        thickness = item.thickness_cm;
        quantity = item.quantity;
        variantCode = item.variant_code;
    }

    const translatedVariant = translateVariantCode(variantCode);
    const dimensions = `${length}×${width}×${thickness} cm`;

    // POPRAWKA: Ulepszona logika wykończenia z kolorem - zawsze dodaj typ
    let finishing = '';
    if (isActiveProduct) {
        // Sprawdź przyciski wykończenia w edytorze
        const finishingType = getSelectedFinishingType?.() || 'Surowe';
        if (finishingType) {
            finishing = ` | ${finishingType}`;

            // Dodaj wariant i kolor tylko jeśli nie jest "Surowe"
            if (finishingType !== 'Surowe') {
                const finishingVariant = getSelectedFinishingVariant?.();
                if (finishingVariant) {
                    finishing += ` ${finishingVariant}`;

                    // DODAJ KOLOR jeśli wariant to "Barwne"
                    if (finishingVariant === 'Barwne') {
                        const finishingColor = getSelectedFinishingColor?.();
                        if (finishingColor && finishingColor !== 'Brak') {
                            finishing += ` ${finishingColor}`;
                        }
                    }
                }
            }
        }
    } else {
        // Dla nieaktywnego - sprawdź dane wykończenia z bazy
        if (currentEditingQuoteData?.finishing) {
            const finishingDetails = currentEditingQuoteData.finishing.find(f =>
                f.product_index === item.product_index
            );
            if (finishingDetails && finishingDetails.finishing_type) {
                finishing = ` | ${finishingDetails.finishing_type}`;

                // Dodaj wariant i kolor tylko jeśli nie jest "Surowe"
                if (finishingDetails.finishing_type !== 'Surowe') {
                    // Dodaj wariant jeśli istnieje
                    if (finishingDetails.finishing_variant) {
                        finishing += ` ${finishingDetails.finishing_variant}`;
                    }

                    // DODAJ KOLOR z bazy danych
                    if (finishingDetails.finishing_color && finishingDetails.finishing_color !== 'Brak') {
                        finishing += ` ${finishingDetails.finishing_color}`;
                    }
                }
            }
        }
    }

    const quantityText = ` | ${quantity} szt.`;
    const main = `${translatedVariant} ${dimensions}${finishing}${quantityText}`;

    // Oblicz objętość i wagę
    const volume = calculateSingleVolume(length, width, thickness) * quantity;
    const weight = volume * 800; // gęstość drewna
    const volumeText = volume ? `${volume.toFixed(3)} m³` : '0.000 m³';
    const weightText = formatWeightDisplay ? formatWeightDisplay(weight) : `${weight.toFixed(1)} kg`;
    const sub = `${volumeText} | ${weightText}`;

    console.log('[generateProductDescriptionForQuote] Wygenerowany opis z kolorem:', {
        main, sub, isActiveProduct, length, width, thickness, quantity, variantCode, finishing
    });
    return { main, sub };
}

/**
 * NOWA FUNKCJA POMOCNICZA - Oblicz objętość pojedynczego produktu (cm³ -> m³)
 */
function calculateSingleVolume(length, width, thickness) {
    if (!length || !width || !thickness || length <= 0 || width <= 0 || thickness <= 0) {
        return 0;
    }
    // Konwersja z cm³ na m³
    return (length * width * thickness) / 1000000;
}

/**
 * Sprawdza kompletność produktu na podstawie formularza w modalu
 * Podobnie jak checkProductCompleteness w calculator.js
 */
function checkProductCompletenessInEditor() {
    // Sprawdź czy wszystkie pola formularza są wypełnione
    const length = document.getElementById('edit-length')?.value;
    const width = document.getElementById('edit-width')?.value;
    const thickness = document.getElementById('edit-thickness')?.value;
    const quantity = document.getElementById('edit-quantity')?.value;

    // Sprawdź czy jest wybrany wariant (radio button)
    const selectedVariant = document.querySelector('input[name="edit-variantOption"]:checked');

    const hasBasicData = length && parseFloat(length) > 0 &&
        width && parseFloat(width) > 0 &&
        thickness && parseFloat(thickness) > 0 &&
        quantity && parseInt(quantity) > 0;

    const hasVariant = selectedVariant !== null;

    // ✅ NOWA WALIDACJA WYKOŃCZENIA
    const finishingType = getSelectedFinishingType();
    const finishingVariant = getSelectedFinishingVariant();
    const finishingColor = getSelectedFinishingColor();

    let hasValidFinishing = true;
    let finishingErrorMessage = '';

    // Sprawdź czy wykończenie jest kompletne według nowych zasad
    if (finishingType === 'Lakierowanie') {
        if (!finishingVariant) {
            hasValidFinishing = false;
            finishingErrorMessage = 'Wybierz wariant lakierowania (Bezbarwne/Barwne)';
        } else if (finishingVariant === 'Barwne' && !finishingColor) {
            hasValidFinishing = false;
            finishingErrorMessage = 'Wybierz kolor dla barwnego lakierowania';
        }
    }
    // "Surowe" i "Olejowanie" są zawsze kompletne bez dodatkowych wyborów

    const isComplete = hasBasicData && hasVariant && hasValidFinishing;

    console.log('[checkProductCompletenessInEditor] Walidacja formularza:', {
        length: length,
        width: width,
        thickness: thickness,
        quantity: quantity,
        hasBasicData: hasBasicData,
        selectedVariant: selectedVariant?.value,
        hasVariant: hasVariant,
        finishingType: finishingType,
        finishingVariant: finishingVariant,
        finishingColor: finishingColor,
        hasValidFinishing: hasValidFinishing,
        finishingErrorMessage: finishingErrorMessage,
        isComplete: isComplete
    });

    // ✅ OPCJONALNE: Pokaż komunikat błędu wykończenia w konsoli do debugowania
    if (!hasValidFinishing) {
        console.warn('[checkProductCompletenessInEditor] Wykończenie niekompletne:', finishingErrorMessage);
    }

    return isComplete;
}

/**
 * NOWA funkcja - oblicza objętość produktu na podstawie danych z item
 */
function calculateProductVolumeFromItem(item) {
    if (!item.length_cm || !item.width_cm || !item.thickness_cm || !item.quantity) {
        return 0;
    }

    const length = parseFloat(item.length_cm) || 0;
    const width = parseFloat(item.width_cm) || 0;
    const thickness = parseFloat(item.thickness_cm) || 0;
    const quantity = parseInt(item.quantity) || 1;

    if (length <= 0 || width <= 0 || thickness <= 0) {
        return 0;
    }

    // Oblicz objętość: wymiary w cm → metry → m³
    const singleVolumeM3 = (length / 100) * (width / 100) * (thickness / 100);
    const totalVolumeM3 = singleVolumeM3 * quantity;

    return totalVolumeM3;
}

/**
 * NOWA funkcja - aktualizuje podsumowanie objętości i wagi w edytorze wyceny
 * Można wywołać po zmianie danych produktu
 */
function updateProductsSummaryTotals() {
    if (!currentEditingQuoteData) return;

    const { totalVolume, totalWeight } =
        calculateTotalVolumeAndWeightFromQuoteFixed(currentEditingQuoteData);

    // POPRAWKA: Znajdź główną sekcję produktów, nie kontener scroll
    const mainSection = document.querySelector('.edit-products-summary-main');
    if (!mainSection) {
        console.error('Nie znaleziono głównej sekcji produktów');
        return;
    }

    // POPRAWKA: Usuń istniejące podsumowanie jeśli istnieje
    let summaryElement = mainSection.querySelector('.products-total-summary');
    if (summaryElement) {
        summaryElement.remove();
    }

    // POPRAWKA: Utwórz nowe podsumowanie tylko jeśli są dane
    if (totalVolume > 0 || totalWeight > 0) {
        summaryElement = document.createElement('div');
        summaryElement.className = 'products-total-summary';
        summaryElement.innerHTML = `
            <div class="products-total-title">Łączne podsumowanie:</div>
            <div class="products-total-details">
                <span class="products-total-volume">${formatVolumeDisplay(totalVolume)}</span>
                <span class="products-total-weight">${formatWeightDisplay(totalWeight)}</span>
            </div>
        `;

        // KLUCZOWE: Dodaj podsumowanie na końcu głównej sekcji, NIE do scroll container
        mainSection.appendChild(summaryElement);
    }

    log('editor', `Zaktualizowano podsumowanie (poza scrollem): ${formatVolumeDisplay(totalVolume)} | ${formatWeightDisplay(totalWeight)}`);
}

function calculateTotalVolumeAndWeightFromQuoteFixed(quoteData) {
    if (!quoteData?.items?.length) {
        return { totalVolume: 0, totalWeight: 0 };
    }

    let totalVolume = 0;
    let totalWeight = 0;

    quoteData.items.forEach(item => {
        if (item.is_selected !== true) return;
        if (!checkProductCompletenessForQuote(item)) return;

        const length = parseFloat(item.length_cm);
        const width = parseFloat(item.width_cm);
        const thickness = parseFloat(item.thickness_cm);
        const quantity = parseFloat(item.quantity);

        if ([length, width, thickness, quantity].some(v => isNaN(v) || v <= 0)) {
            return;
        }

        const singleVolumeM3 = (length / 100) * (width / 100) * (thickness / 100);
        const itemTotalVolume = singleVolumeM3 * quantity;
        const itemTotalWeight = itemTotalVolume * 800; // gęstość drewna 800 kg/m³

        totalVolume += itemTotalVolume;
        totalWeight += itemTotalWeight;
    });

    return {
        totalVolume: Math.round(totalVolume * 1000) / 1000,
        totalWeight: Math.round(totalWeight * 10) / 10
    };
}

/**
 * NOWA funkcja - formatuje wagę do wyświetlenia
 */
function formatWeightDisplay(weight) {
    if (!weight || weight <= 0) {
        return "0.0 kg";
    }

    // Jeśli waga >= 1000 kg, pokaż w tonach
    if (weight >= 1000) {
        return `${(weight / 1000).toFixed(2)} t`;
    }

    return `${weight.toFixed(1)} kg`;
}

/**
 * NOWA funkcja - formatuje objętość do wyświetlenia
 */
function formatVolumeDisplay(volume) {
    if (!volume || volume <= 0) {
        return "0.000 m³";
    }

    return `${volume.toFixed(3)} m³`;
}

function checkProductCompletenessForQuote(item) {
    if (!item) {
        console.log('[checkProductCompletenessForQuote] Brak item');
        return false;
    }

    // Debugging - sprawdź wszystkie pola
    console.log('[checkProductCompletenessForQuote] Sprawdzanie produktu (struktura quotes):', {
        length_cm: item.length_cm,
        width_cm: item.width_cm,
        thickness_cm: item.thickness_cm,
        quantity: item.quantity,
        variant_code: item.variant_code,
        final_price_netto: item.final_price_netto,
        final_price_brutto: item.final_price_brutto,
        // W quotes nie ma finishing_type w QuoteItem - tylko w QuoteItemDetails
        is_selected: item.is_selected
    });

    // POPRAWKA: W module quotes sprawdzamy tylko podstawowe pola
    // finishing_type jest w osobnej tabeli QuoteItemDetails
    const requiredFields = [
        item.length_cm,
        item.width_cm,
        item.thickness_cm,
        item.quantity,
        item.variant_code,
        // USUNIĘTO: item.finishing_type - nie ma w QuoteItem
        item.final_price_netto,
        item.final_price_brutto
    ];

    const isComplete = requiredFields.every(field => {
        const isValid = field !== null && field !== undefined && field !== '';
        if (!isValid) {
            console.log('[checkProductCompletenessForQuote] Brakuje pola:', field);
        }
        return isValid;
    });

    console.log('[checkProductCompletenessForQuote] Produkt jest kompletny:', isComplete);
    return isComplete;
}

/**
 * NOWA FUNKCJA - Ładuje dane wykończenia z wyceny do interfejsu edytora
 * Wkleić na końcu pliku quote_editor.js, przed ostatnim komentarzem
 */
function loadFinishingDataToForm(productItem) {
    log('finishing', `=== ŁADOWANIE WYKOŃCZENIA DLA PRODUKTU ${productItem.product_index} ===`);

    // ✅ Znajdź dane wykończenia dla tego produktu w currentEditingQuoteData
    let finishingData = null;

    if (currentEditingQuoteData?.finishing) {
        finishingData = currentEditingQuoteData.finishing.find(f =>
            f.product_index === productItem.product_index
        );
    }

    // ✅ Reset wszystkich przycisków wykończenia
    clearFinishingSelections();

    // ✅ Ustaw domyślnie "Surowe" jako aktywne
    const surowiBtn = document.querySelector('#edit-finishing-type-group .finishing-btn[data-finishing-type="Surowe"]');
    if (surowiBtn) {
        surowiBtn.classList.add('active');
    }

    // ✅ Ukryj sekcje wariantów i kolorów
    const variantWrapper = document.getElementById('edit-finishing-variant-wrapper');
    const colorWrapper = document.getElementById('edit-finishing-color-wrapper');
    const glossWrapper = document.getElementById('edit-finishing-gloss-wrapper');

    if (variantWrapper) variantWrapper.style.display = 'none';
    if (colorWrapper) colorWrapper.style.display = 'none';
    if (glossWrapper) glossWrapper.style.display = 'none';

    // ✅ Jeśli mamy dane wykończenia z bazy, ustaw je w interfejsie
    if (finishingData && finishingData.finishing_type && finishingData.finishing_type !== 'Surowe') {
        log('finishing', `Ładuję wykończenie z bazy: ${finishingData.finishing_type}`);

        // ✅ 1. Ustaw typ wykończenia
        const typeButton = document.querySelector(`#edit-finishing-type-group .finishing-btn[data-finishing-type="${finishingData.finishing_type}"]`);
        if (typeButton) {
            // Usuń active z "Surowe"
            if (surowiBtn) surowiBtn.classList.remove('active');

            // Ustaw active na właściwym typie
            typeButton.classList.add('active');
            log('finishing', `✅ Ustawiono typ wykończenia: ${finishingData.finishing_type}`);

            // ✅ 2. Jeśli to lakierowanie, pokaż sekcję wariantów
            if (finishingData.finishing_type === 'Lakierowanie') {
                if (variantWrapper) variantWrapper.style.display = 'flex';

                // ✅ 3. Ustaw wariant jeśli istnieje
                if (finishingData.finishing_variant) {
                    const variantButton = document.querySelector(`#edit-finishing-variant-wrapper .finishing-btn[data-finishing-variant="${finishingData.finishing_variant}"]`);
                    if (variantButton) {
                        variantButton.classList.add('active');
                        log('finishing', `✅ Ustawiono wariant wykończenia: ${finishingData.finishing_variant}`);

                        // ✅ 4. Jeśli to "Barwne", pokaż kolory
                        if (finishingData.finishing_variant === 'Barwne') {
                            if (colorWrapper) colorWrapper.style.display = 'flex';

                            // ✅ 5. Ustaw kolor jeśli istnieje
                            if (finishingData.finishing_color) {
                                const colorButton = document.querySelector(`#edit-finishing-color-wrapper .color-btn[data-finishing-color="${finishingData.finishing_color}"]`);
                                if (colorButton) {
                                    colorButton.classList.add('active');
                                    log('finishing', `✅ Ustawiono kolor wykończenia: ${finishingData.finishing_color}`);
                                }
                            }
                        }
                    }
                }
            }
        }
    } else {
        log('finishing', 'Brak danych wykończenia w bazie lub wykończenie surowe - pozostawiam "Surowe"');
    }

    // ✅ KLUCZOWA POPRAWKA: Synchronizuj stan do mock formularza DOPIERO po ustawieniu przycisków
    setTimeout(() => {
        syncFinishingStateToMockForm();

        // ✅ Przelicz koszty wykończenia
        if (typeof calculateFinishingCost === 'function' && window.activeQuoteForm) {
            try {
                calculateFinishingCost(window.activeQuoteForm);
                log('finishing', '✅ Przeliczono koszty wykończenia po załadowaniu danych');
            } catch (err) {
                log('finishing', '❌ Błąd przeliczania wykończenia po załadowaniu danych', err);
            }
        }
    }, 50);
}

// ==================== FALLBACK FUNCTIONS ====================

/**
 * Domyślne dane wykończenia
 */
function loadDefaultFinishingData() {
    const defaultData = {
        finishing_types: [
            { name: 'Surowe', price_netto: 0 },
            { name: 'Lakierowanie bezbarwne', price_netto: 200 },
            { name: 'Lakierowanie barwne', price_netto: 250 },
            { name: 'Olejowanie', price_netto: 250 }
        ],
        finishing_colors: [
            { name: 'POPIEL 20-07', image_url: '/calculator/static/images/finishing_colors/popiel-20-07.jpg' },
            { name: 'BEŻ BN-125/09', image_url: '/calculator/static/images/finishing_colors/bez-bn-125-09.jpg' },
            { name: 'BRUNAT 22-10', image_url: '/calculator/static/images/finishing_colors/brunat-22-10.jpg' }
        ]
    };

    finishingDataCache = defaultData;
    renderFinishingUI(defaultData);
}

function loadDefaultClientTypes() {
    const defaultGroups = [
        { client_type: 'Partner', multiplier: 1.0 },
        { client_type: 'Hurt', multiplier: 1.1 },
        { client_type: 'Detal', multiplier: 1.3 },
        { client_type: 'Detal+', multiplier: 1.5 }
    ];

    clientTypesCache = defaultGroups;
    populateClientTypeSelect(defaultGroups);
}

/**
 * Fallback calculation gdy calculator.js niedostępny
 */
function calculateEditorPrices() {
    log('editor', 'Wykonuję obliczenia fallback...');

    const dimensions = getCurrentDimensions();
    if (!dimensions.isValid) {
        showVariantErrors('Brak wymiarów');
        return;
    }

    const volume =
        (dimensions.length / 1000) *
        (dimensions.width / 1000) *
        (dimensions.thickness / 1000) *
        dimensions.quantity;

    // Show calculating state
    document.querySelectorAll('.variant-option').forEach(variant => {
        const priceElements = variant.querySelectorAll('.unit-brutto, .unit-netto, .total-brutto, .total-netto');
        priceElements.forEach(el => el.textContent = 'Obliczanie...');
    });

    log('editor', `✅ Fallback calculation - objętość: ${volume}`);
}

function showVariantErrors(errorMessage) {
    document.querySelectorAll('.variant-option').forEach(option => {
        const priceElements = option.querySelectorAll('.unit-brutto, .total-brutto');
        priceElements.forEach(el => el.textContent = errorMessage);

        const emptyElements = option.querySelectorAll('.unit-netto, .total-netto');
        emptyElements.forEach(el => el.textContent = '');
    });
}



// ==================== INITIALIZATION AND CLEANUP ====================

/**
 * Zoptymalizowane operacje początkowe
 */
function performInitialCalculations(quoteData) {
    // Batch initial operations
    const operations = [
        () => triggerSyntheticRecalc(),
        () => applyVariantAvailabilityFromQuoteData(quoteData, activeProductIndex),
        () => initializeSummaryUpdates()
    ];

    operations.forEach((operation, index) => {
        setTimeout(operation, index * 100); // Staggered execution
    });
}

function triggerSyntheticRecalc() {
    // Trigger events on all inputs at once
    const inputs = document.querySelectorAll('#quote-editor-modal input, #quote-editor-modal select');
    const events = ['input', 'change'];

    inputs.forEach(el => {
        events.forEach(eventType => {
            el.dispatchEvent(new Event(eventType, { bubbles: true }));
        });
    });

    // Call recalculation function if available
    const recalcFunctions = ['recalculateEditorTotals', 'onFormDataChange'];
    for (const funcName of recalcFunctions) {
        if (typeof window[funcName] === 'function') {
            window[funcName]();
            break;
        }
    }
}
function applyVariantAvailabilityFromQuoteData(quoteData, productIndex) {
    if (!quoteData?.items || productIndex === null || productIndex === undefined) {
        log('sync', '❌ Brak danych do synchronizacji checkboxów');
        return;
    }

    // Znajdź pozycje dla tego produktu
    const productItems = quoteData.items.filter(item => item.product_index === productIndex);

    log('sync', `Synchronizuję checkboxy i selecty dla produktu ${productIndex}, znalezionych pozycji: ${productItems.length}`);

    // Stwórz mapę dostępności na podstawie rzeczywistych danych z backend-u
    const availabilityMap = new Map();
    const selectedVariant = productItems.find(item => item.is_selected === true)?.variant_code;

    productItems.forEach(item => {
        // Prawidłowe mapowanie wartości z backend-u
        const rawValue = item.show_on_client_page;
        const isVisible = rawValue === true || rawValue === 1 || rawValue === '1';

        availabilityMap.set(item.variant_code, isVisible);

        log('sync', `Mapowanie wariantu ${item.variant_code}: raw=${rawValue} (${typeof rawValue}) → visible=${isVisible}`);
    });

    // Lista wszystkich wariantów do zsynchronizowania
    const allVariants = ['dab-lity-ab', 'dab-lity-bb', 'dab-micro-ab', 'dab-micro-bb',
        'jes-lity-ab', 'jes-micro-ab', 'buk-lity-ab', 'buk-micro-ab'];

    // 1. SYNCHRONIZACJA CHECKBOXÓW (widoczność wariantów)
    log('sync', '--- Synchronizacja checkboxów dostępności ---');
    allVariants.forEach(variantCode => {
        const checkbox = document.querySelector(`#quote-editor-modal .variant-availability-checkbox[data-variant="${variantCode}"]`);

        if (checkbox) {
            if (availabilityMap.has(variantCode)) {
                const isVisible = availabilityMap.get(variantCode);
                checkbox.checked = isVisible;
                log('sync', `✅ Checkbox ${variantCode}: visible=${isVisible}`);
            } else {
                // Jeśli wariant nie ma danych w bazie, domyślnie niewidoczny
                checkbox.checked = false;
                log('sync', `⚠️ Checkbox ${variantCode}: brak w bazie → visible=false`);
            }
        } else {
            log('sync', `❌ Nie znaleziono checkboxa dla wariantu: ${variantCode}`);
        }
    });

    // 2. SYNCHRONIZACJA RADIO BUTTONS (wybrany wariant)
    log('sync', '--- Synchronizacja radio buttons ---');
    if (selectedVariant) {
        log('sync', `Szukam radio button dla wybranego wariantu: ${selectedVariant}`);

        // Sprawdź wszystkie możliwe selektory radio buttons
        const possibleSelectors = [
            `#quote-editor-modal input[name="edit-variantOption"][value="${selectedVariant}"]`,
            `#quote-editor-modal input[name="variant-product-0-selected"][value="${selectedVariant}"]`,
            `#quote-editor-modal input[name="variant-product-${productIndex}-selected"][value="${selectedVariant}"]`,
            `#quote-editor-modal input[type="radio"][value="${selectedVariant}"]`
        ];

        let radioFound = false;
        for (const selector of possibleSelectors) {
            const radio = document.querySelector(selector);
            if (radio) {
                // Odznacz wszystkie radio buttons w tej grupie
                const allRadiosInGroup = document.querySelectorAll(`#quote-editor-modal input[name="${radio.name}"]`);
                allRadiosInGroup.forEach(r => r.checked = false);

                // Zaznacz właściwy radio button
                radio.checked = true;
                log('sync', `✅ Zaznaczono radio button: ${selector}`);

                // Wywołaj zdarzenie change aby zaktualizować interfejs
                radio.dispatchEvent(new Event('change', { bubbles: true }));
                radioFound = true;
                break;
            }
        }

        if (!radioFound) {
            log('sync', `❌ Nie znaleziono radio button dla wybranego wariantu: ${selectedVariant}`);
            log('sync', `Sprawdzone selektory:`, possibleSelectors);
        }
    } else {
        log('sync', '⚠️ Brak wybranego wariantu w danych z backend-u');
    }

    // 3. SYNCHRONIZACJA WIZUALNYCH ELEMENTÓW (DIV.variant-option)
    log('sync', '--- Synchronizacja wizualnych elementów ---');
    allVariants.forEach(variantCode => {
        const visualElement = document.querySelector(`#quote-editor-modal .${variantCode}-option.variant-option`);
        if (visualElement) {
            if (selectedVariant === variantCode) {
                visualElement.classList.add('selected');
                log('sync', `✅ Dodano klasę 'selected' do elementu: ${variantCode}`);
            } else {
                visualElement.classList.remove('selected');
            }
        }
    });

    // ✅ DODAJ: Aktualizuj dostępność radio buttonów na podstawie checkboxów
    syncRadioButtonAvailability();

    // ✅ DODAJ: Wymuś przeliczenie cen po synchronizacji
    setTimeout(() => {
        if (typeof onFormDataChange === 'function') {
            onFormDataChange();
        }
    }, 100);

    log('sync', '✅ Synchronizacja checkboxów i radio buttonów zakończona');
}

/**
 * ✅ NOWA FUNKCJA - Inicjalizuje event listenery dla checkboxów dostępności
 */
function initializeVariantAvailabilityListeners() {
    // Usuń poprzednie listenery aby uniknąć duplikacji
    const existingCheckboxes = document.querySelectorAll('#quote-editor-modal .variant-availability-checkbox');
    existingCheckboxes.forEach(checkbox => {
        checkbox.removeEventListener('change', handleVariantAvailabilityChange);
    });

    // Dodaj nowe listenery
    const checkboxes = document.querySelectorAll('#quote-editor-modal .variant-availability-checkbox');
    checkboxes.forEach(checkbox => {
        checkbox.addEventListener('change', handleVariantAvailabilityChange);
    });

    log('sync', `✅ Zainicjalizowano ${checkboxes.length} event listenerów dla checkboxów`);
}

/**
 * ✅ NOWA FUNKCJA - Obsługuje zmianę stanu checkboxa dostępności
 */
function handleVariantAvailabilityChange(event) {
    const checkbox = event.target;
    const variantCode = checkbox.dataset.variant;
    const isChecked = checkbox.checked;

    log('sync', `Ręczna zmiana checkboxa ${variantCode}: ${isChecked ? 'zaznaczony' : 'odznaczony'}`);

    // Znajdź odpowiedni radio button i kontener wariantu
    const radioButton = document.querySelector(`input[name="edit-variantOption"][value="${variantCode}"]`);
    const variantOption = radioButton?.closest('.variant-option');

    if (radioButton && variantOption) {
        // Ustaw dostępność radio buttona
        radioButton.disabled = !isChecked;

        // Dodaj/usuń klasę CSS
        if (isChecked) {
            variantOption.classList.remove('unavailable');
            log('sync', `✅ Aktywowano wariant ${variantCode}`);
        } else {
            variantOption.classList.add('unavailable');

            // Jeśli niedostępny wariant był zaznaczony, odznacz go i wybierz inny
            if (radioButton.checked) {
                radioButton.checked = false;
                variantOption.classList.remove('selected');
                selectFirstAvailableVariant();
                log('sync', `⚠️ Odznaczono wybrany wariant ${variantCode} - wybrano pierwszy dostępny`);
            }
            log('sync', `❌ Dezaktywowano wariant ${variantCode}`);
        }

        // Wymuś przeliczenie po zmianie
        setTimeout(() => {
            if (typeof onFormDataChange === 'function') {
                onFormDataChange();
            }
        }, 100);
    }
}

/**
 * ✅ NOWA FUNKCJA - Synchronizuje dostępność radio buttonów na podstawie stanu checkboxów
 */
function syncRadioButtonAvailability() {
    const checkboxes = document.querySelectorAll('#quote-editor-modal .variant-availability-checkbox');

    checkboxes.forEach(checkbox => {
        const variantCode = checkbox.dataset.variant;
        const radioButton = document.querySelector(`input[name="edit-variantOption"][value="${variantCode}"]`);
        const variantOption = radioButton?.closest('.variant-option');

        if (radioButton && variantOption) {
            const isAvailable = checkbox.checked;

            // Ustaw dostępność radio buttona
            radioButton.disabled = !isAvailable;

            // Dodaj/usuń klasę CSS
            if (isAvailable) {
                variantOption.classList.remove('unavailable');
            } else {
                variantOption.classList.add('unavailable');
                // Jeśli niedostępny wariant był zaznaczony, odznacz go
                if (radioButton.checked) {
                    radioButton.checked = false;
                    selectFirstAvailableVariant();
                }
            }

            log('sync', `Radio button ${variantCode}: ${isAvailable ? 'dostępny' : 'niedostępny'}`);
        }
    });
}

/**
 * Zoptymalizowana inicjalizacja automatycznego odświeżania
 */
function initializeSummaryUpdates() {
    log('editor', 'Inicjalizacja automatycznego odświeżania...');

    // Single timeout for initial summary update
    setTimeout(updateQuoteSummary, 500);
}

// ==================== CLIENT TYPE MANAGEMENT ====================

/**
 * Zoptymalizowana obsługa zmiany grupy cenowej
 */
function onClientTypeChange() {
    const clientTypeSelect = document.getElementById('edit-clientType');
    if (!clientTypeSelect) return;

    const selectedOption = clientTypeSelect.options[clientTypeSelect.selectedIndex];
    if (!selectedOption) return;

    const multiplierValue = selectedOption.dataset.multiplierValue;
    const clientType = selectedOption.value;

    log('sync', `Zmiana grupy cenowej: ${clientType} (mnożnik: ${multiplierValue})`);

    // ✅ KLUCZOWA POPRAWKA: Synchronizuj grupę cenową na wszystkich produktach
    syncClientTypeAcrossAllProducts(clientType, multiplierValue);

    // ✅ Zaktualizuj zmienne globalne calculator.js
    updateMultiplierFromEditor();

    // ✅ Wywołaj przeliczenie po krótkiej pauzie
    setTimeout(() => {
        onFormDataChange();
        updateQuoteSummary();
        updateProductsSummaryTotals();
    }, 50);
    updateQuoteSummary();
    updateProductsSummaryTotals();
    refreshProductCards();
}

// ==================== PLACEHOLDER FUNCTIONS (TODO) ====================

/**
 * Add a new empty product to the quote editor
 */
function addNewProductToQuote() {
    log('editor', 'Dodawanie nowego produktu...');

    if (!currentEditingQuoteData) {
        log('editor', '❌ Brak danych wyceny');
        return;
    }

    // Save current product before creating a new one
    saveActiveProductFormData();
    // Przelicz koszty i podsumowanie zanim przełączymy produkt
    updateQuoteSummary();
    updateProductsSummaryTotals();

    currentEditingQuoteData.items = currentEditingQuoteData.items || [];
    const items = currentEditingQuoteData.items;
    const maxIndex = items.length ? Math.max(...items.map(i => i.product_index)) : -1;
    const newIndex = maxIndex + 1;

    const variantCodes = [
        'dab-lity-ab',
        'dab-lity-bb',
        'dab-micro-ab',
        'dab-micro-bb',
        'jes-lity-ab',
        'jes-micro-ab',
        'buk-lity-ab',
        'buk-micro-ab'
    ];

    variantCodes.forEach(code => {
        items.push({
            product_index: newIndex,
            length_cm: 0,
            width_cm: 0,
            thickness_cm: 0,
            quantity: 1,
            variant_code: code,
            is_selected: code === 'dab-lity-ab',
            // Default availability: hide specific variants on client page
            show_on_client_page: code === 'buk-micro-ab' || code === 'jes-micro-ab' ? 0 : 1,
            final_price_brutto: 0,
            final_price_netto: 0,
            calculated_price_brutto: 0,
            calculated_price_netto: 0,
            calculated_finishing_brutto: 0,
            calculated_finishing_netto: 0
        });
    });

    // Ensure finishing array has placeholder for this product
    currentEditingQuoteData.finishing = currentEditingQuoteData.finishing || [];
    currentEditingQuoteData.finishing.push({
        product_index: newIndex,
        finishing_price_brutto: 0,
        finishing_price_netto: 0,
        finishing_type: 'Surowe',
        finishing_variant: null,
        finishing_color: null
    });

    // Refresh UI with new product and activate it
    loadProductsToEditor(currentEditingQuoteData);
    activateProductInEditor(newIndex);
    refreshProductCards();
    updateQuoteSummary();
    updateProductsSummaryTotals();

    log('editor', `✅ Dodano nowy produkt ${newIndex}`);
}

function removeProductFromQuote(productIndex) {
    log('editor', `Usuwanie produktu: ${productIndex}`);

    if (!confirm('Czy na pewno chcesz usunąć ten produkt?')) return;

    alert(`Usuwanie produktu ${productIndex} będzie dostępne wkrótce!`);
    updateProductsSummaryTotals();
}

// ==================== ERROR HANDLING ====================

/**
 * Centralized error display
 */
function showErrorForAllVariants(errorMsg, variantContainer) {
    const variantItems = Array.from(variantContainer.children)
        .filter(child => child.querySelector('input[type="radio"]'));

    const priceSelectors = ['.unit-brutto', '.total-brutto'];
    const emptySelectors = ['.unit-netto', '.total-netto'];

    variantItems.forEach(variant => {
        priceSelectors.forEach(selector => {
            const el = variant.querySelector(selector);
            if (el) el.textContent = errorMsg;
        });

        emptySelectors.forEach(selector => {
            const el = variant.querySelector(selector);
            if (el) el.textContent = '';
        });
    });
}

// ==================== MAIN INITIALIZATION ====================

/**
 * Zoptymalizowana inicjalizacja modułu
 */
function initQuoteEditor() {
    log('editor', 'Inicjalizacja modułu Quote Editor');

    const modal = document.getElementById('quote-editor-modal');
    if (!modal) {
        console.warn('[QUOTE EDITOR] Modal edytora nie został znaleziony');
        return;
    }

    log('editor', '✅ Quote Editor gotowy do użycia');
}

// ==================== REMAINING HELPER FUNCTIONS ====================

/**
 * Pozostałe funkcje pomocnicze zachowane dla kompatybilności
 */
function getUniqueProductsCount(items) {
    if (!items?.length) return 0;
    return new Set(items.map(item => item.product_index)).size;
}

function callUpdatePricesSecurely() {
    if (!window.activeQuoteForm) {
        console.error('[QUOTE EDITOR] ❌ activeQuoteForm nie jest ustawiony!');
        return;
    }

    try {
        updatePrices();
        log('calculator', '✅ updatePrices() wykonany pomyślnie');
    } catch (error) {
        console.error('[QUOTE EDITOR] ❌ Błąd w updatePrices():', error);
    }
}

// ==================== INITIALIZATION ====================

/**
 * DOM Content Loaded - zoptymalizowana inicjalizacja
 */
document.addEventListener('DOMContentLoaded', function () {
    initQuoteEditor();

    // Load finishing data if needed
    if (!finishingDataCache) {
        loadFinishingDataFromDatabase().catch(() => {
            log('finishing', 'Używam domyślnych danych wykończenia');
        });
    }
});

// ==================== EXPORT FUNCTIONS ====================

/**
 * Export głównych funkcji dla kompatybilności
 */
window.QuoteEditor = {
    open: openQuoteEditor,
    close: () => {

        // Zachowaj dane bieżącego produktu przed zamknięciem
        saveActiveProductFormData();

        const modal = document.getElementById('quote-editor-modal');
        if (modal) modal.style.display = 'none';
        resetEditorState();
    },
    save: saveQuoteChanges,
    updateSummary: updateQuoteSummary,
    handleFinishingVariantChange,
    // Debug helpers
    setDebugLevel: (category, enabled) => {
        DEBUG_LOGS[category] = enabled;
    },
    getState: () => ({
        currentQuote: currentEditingQuoteData,
        activeProduct: activeProductIndex,
        calculatorReady: checkCalculatorReadiness()
    })
};

// Override attachFinishingUIListeners z calculator.js
window.originalAttachFinishingUIListeners = window.attachFinishingUIListeners;
window.attachFinishingUIListeners = safeAttachFinishingUIListeners;