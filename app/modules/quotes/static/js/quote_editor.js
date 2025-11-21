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
let isRecalculating = false; // ✅ NOWE: Flaga zapobiegająca nieskończonej pętli

// Optimized logging - centralized debug control
const DEBUG_LOGS = {
    editor: true,      // Główne operacje edytora
    calculator: false,  // Operacje kalkulatora (wyłączone - zbyt dużo)
    finishing: false,   // Operacje wykończenia (wyłączone - zbyt dużo)
    sync: false,        // Synchronizacja pól (wyłączone - zbyt dużo)
    debug: false        // Szczegółowe debugowanie danych (wyłączone - powtórzenia)
};

// Centralized logger to reduce repetitive logging
function log(category, message, data = null) {
    // Sprawdź tylko specyficzną kategorię, NIE nadpisuj ustawieniem editor
    if (!DEBUG_LOGS[category]) return;

    const prefix = `[QUOTE EDITOR ${category.toUpperCase()}]`;
    if (data) {
        console.log(prefix, message, data);
    } else {
        console.log(prefix, message);
    }
}

// ==================== GŁÓWNE FUNKCJE EDYTORA ====================

function debugIncomingQuoteData(quoteData, context = 'unknown') {
    if (!DEBUG_LOGS.debug) return; // ✅ Wyłącz gdy debug=false
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

    // ✅ KRYTYCZNA POPRAWKA: Zrób głęboką kopię quoteData aby zachować oryginalne wartości
    // To zapobiega nadpisywaniu show_on_client_page podczas edycji
    const originalQuoteData = JSON.parse(JSON.stringify(quoteData));
    window.originalQuoteData = originalQuoteData;  // Zapisz dla późniejszego użycia
    log('editor', '✅ Zapisano oryginalną kopię danych wyceny');

    // ✅ NOWE: Zablokuj problematyczne funkcje calculator.js w kontekście edytora
    if (!window._originalCalculatorFunctions) {
        window._originalCalculatorFunctions = {
            handleClientTypeChange: window.handleClientTypeChange,
            syncClientTypeAcrossProducts: window.syncClientTypeAcrossProducts
        };
        log('editor', '✅ Zapisano oryginalne funkcje calculator.js');
    }

    // Nadpisz funkcje calculator.js pustymi wersjami (zapobiega błędom DOM)
    window.handleClientTypeChange = function (event) {
        log('editor', '⚠️ Zablokowano handleClientTypeChange z calculator.js (użyj onClientTypeChange z edytora)');
        // Nie rób nic - zapobiega błędowi "Cannot read properties of null"
    };

    window.syncClientTypeAcrossProducts = function (selectedType, sourceForm) {
        log('editor', '⚠️ Zablokowano syncClientTypeAcrossProducts z calculator.js (użyj syncClientTypeAcrossAllProducts z edytora)');
        // Nie rób nic - zapobiega błędowi "Cannot read properties of null"
    };

    log('editor', '✅ Zablokowano problematyczne funkcje calculator.js');

    // Walidacja wstępna
    if (!validateQuoteData(quoteData)) return;

    // DEBUGOWANIE: Sprawdź dane wejściowe (tylko gdy debug=true)
    debugIncomingQuoteData(quoteData, 'openQuoteEditor');

    // Przygotowanie środowiska
    currentEditingQuoteData = quoteData;

    // ✅ KRYTYCZNA POPRAWKA: Backend zwraca dane wykończenia w "finishing", ale frontend używa "details"
    // Mapuj finishing → details
    if (quoteData.finishing && Array.isArray(quoteData.finishing)) {
        currentEditingQuoteData.details = quoteData.finishing.map(f => ({
            product_index: f.product_index,
            quantity: f.quantity || 1,
            finishing_type: f.finishing_type || 'Surowe',
            finishing_variant: f.finishing_variant || null,
            finishing_color: f.finishing_color || null,
            finishing_gloss_level: f.finishing_gloss_level || null,
            finishing_price_netto: f.finishing_price_netto || 0,
            finishing_price_brutto: f.finishing_price_brutto || 0
        }));
        console.log(`[INIT DETAILS] Zmapowano ${quoteData.finishing.length} rekordów z finishing → details`);
    } else if (!currentEditingQuoteData.details) {
        currentEditingQuoteData.details = [];
    }

    // Sprawdź wszystkie produkty i stwórz brakujące rekordy details
    if (currentEditingQuoteData.items) {
        const uniqueProductIndexes = [...new Set(currentEditingQuoteData.items.map(item => item.product_index))];

        uniqueProductIndexes.forEach(productIndex => {
            // Sprawdź czy istnieje rekord details dla tego produktu
            const existingDetail = currentEditingQuoteData.details.find(d => d.product_index === productIndex);

            if (!existingDetail) {
                // Utwórz nowy rekord details z wartościami domyślnymi
                currentEditingQuoteData.details.push({
                    product_index: productIndex,
                    quantity: 1,
                    finishing_type: 'Surowe',
                    finishing_variant: null,
                    finishing_color: null,
                    finishing_gloss_level: null,
                    finishing_price_netto: 0,
                    finishing_price_brutto: 0
                });
                console.log(`[INIT DETAILS] Utworzono rekord details dla produktu ${productIndex}`);
            } else {
                console.log(`[INIT DETAILS] Produkt ${productIndex} ma już rekord details:`, existingDetail);
            }
        });
    }

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

        // Synchroniczne operacje po załadowaniu danych
        loadQuoteDataToEditor(quoteData);

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
 * ✅ NOWA FUNKCJA: Przywracanie oryginalnych funkcji calculator.js
 * Wywołaj ją przy zamykaniu modalu edytora
 */
function restoreCalculatorFunctions() {
    if (window._originalCalculatorFunctions) {
        window.handleClientTypeChange = window._originalCalculatorFunctions.handleClientTypeChange;
        window.syncClientTypeAcrossProducts = window._originalCalculatorFunctions.syncClientTypeAcrossProducts;
        log('editor', '✅ Przywrócono oryginalne funkcje calculator.js');
        delete window._originalCalculatorFunctions;
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
 * ✅ NOWA FUNKCJA: Walidacja wymiarów produktu
 */
function validateDimensions() {
    const lengthInput = document.getElementById('edit-length');
    const widthInput = document.getElementById('edit-width');
    const thicknessInput = document.getElementById('edit-thickness');

    const length = parseFloat(lengthInput?.value) || 0;
    const width = parseFloat(widthInput?.value) || 0;
    const thickness = parseFloat(thicknessInput?.value) || 0;

    const MAX_LENGTH = 500;
    const MAX_WIDTH = 120;
    const MAX_THICKNESS = 8;

    const errors = [];

    // Sprawdź limity wymiarów
    if (length > MAX_LENGTH) {
        errors.push(`Długość nie może przekraczać ${MAX_LENGTH} cm`);
        lengthInput?.classList.add('dimension-error');
    } else {
        lengthInput?.classList.remove('dimension-error');
    }

    if (width > MAX_WIDTH) {
        errors.push(`Szerokość nie może przekraczać ${MAX_WIDTH} cm`);
        widthInput?.classList.add('dimension-error');
    } else {
        widthInput?.classList.remove('dimension-error');
    }

    if (thickness > MAX_THICKNESS) {
        errors.push(`Grubość nie może przekraczać ${MAX_THICKNESS} cm`);
        thicknessInput?.classList.add('dimension-error');
    } else {
        thicknessInput?.classList.remove('dimension-error');
    }

    // Wyświetl komunikaty walidacji
    displayValidationMessages(errors);

    return errors.length === 0;
}

/**
 * ✅ NOWA FUNKCJA: Wyświetlanie komunikatów walidacji
 */
function displayValidationMessages(errors) {
    // Usuń poprzednie komunikaty
    const existingAlert = document.querySelector('.dimension-validation-alert');
    if (existingAlert) {
        existingAlert.remove();
    }

    if (errors.length === 0) return;

    // Stwórz nowy komunikat
    const alert = document.createElement('div');
    alert.className = 'dimension-validation-alert';
    alert.innerHTML = `
        <div class="validation-alert-content">
            <svg width="20" height="20" viewBox="0 0 16 16" fill="currentColor">
                <path d="M8.982 1.566a1.13 1.13 0 0 0-1.96 0L.165 13.233c-.457.778.091 1.767.98 1.767h13.713c.889 0 1.438-.99.98-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/>
            </svg>
            <div class="validation-alert-messages">
                ${errors.map(err => `<div>${err}</div>`).join('')}
            </div>
        </div>
    `;

    // Wstaw komunikat pod formularzem wymiarów
    const dimensionsContainer = document.querySelector('.edit-dimensions-row') ||
                                 document.getElementById('edit-length')?.closest('.form-group');
    if (dimensionsContainer) {
        dimensionsContainer.insertAdjacentElement('afterend', alert);
    }
}

/**
 * Centralizowana obsługa zmian w inputach - debounced
 */
const handleInputChange = debounce((e) => {
    const target = e.target;

    if (target.matches('#edit-length, #edit-width, #edit-thickness, #edit-quantity')) {
        log('sync', `Input change: ${target.id} = "${target.value}"`);

        // ✅ POPRAWKA: Waliduj wymiary przed dalszym przetwarzaniem
        if (target.matches('#edit-length, #edit-width, #edit-thickness')) {
            validateDimensions();
        }

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

    // ✅ POPRAWKA: Zaktualizuj klasę .selected na wierszu wariantu
    updateSelectedVariant(radio);

    // Wywołaj oryginalną logikę
    onFormDataChange();

    // ✅ POPRAWKA: Odśwież karty produktów DOPIERO po zakończeniu obliczeń
    setTimeout(() => {
        syncRadioDatasetWithMockForm();
        // Odśwież podsumowanie po synchronizacji
        updateQuoteSummary();
        updateProductsSummaryTotals();
        // Odśwież karty produktów (z aktualnymi danymi)
        refreshProductCards();
    }, 100);
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

    // ✅ NOWE: Obsługa przycisku obliczania wysyłki
    if (target.id === 'edit-calculate-shipping-btn') {
        calculateEditorDelivery();
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
            <select data-field="clientType" id="mock-clientType" style="display: none;">
                <option value="">Wybierz grupę</option>
                <option value="Bazowy">Bazowy</option>
                <option value="Hurt">Hurt</option>
                <option value="Detal">Detal</option>
                <option value="Detal+">Detal+</option>
                <option value="Czernecki netto">Czernecki netto</option>
                <option value="Czernecki FV">Czernecki FV</option>
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

/**
 * Zoptymalizowane ładowanie danych wyceny
 */
function loadQuoteDataToEditor(quoteData) {
    log('editor', 'Ładowanie danych do edytora...');

    // ✅ NOWE: Inicjalizuj zmienne globalne dla calculator.js NA SAMYM POCZĄTKU
    const clientType = quoteData.quote_client_type || 'Hurt';
    const multiplier = parseFloat(quoteData.quote_multiplier) || 1.1;

    window.currentClientType = clientType;
    window.currentMultiplier = multiplier;

    log('editor', `✅ Zainicjalizowano grupę cenową: ${clientType} (${multiplier})`);

    // ✅ NOWE: Zaktualizuj multiplierMapping jeśli istnieje
    if (window.multiplierMapping) {
        window.multiplierMapping[clientType] = multiplier;
        log('editor', `✅ Dodano do multiplierMapping: ${clientType} = ${multiplier}`);
    }

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

    // ✅ NOWE: Wymuś przeliczenie po załadowaniu danych
    setTimeout(() => {
        if (typeof window.calculateVariantPrices === 'function') {
            try {
                window.calculateVariantPrices();
                log('editor', '✅ Wywołano przeliczenie po załadowaniu danych');
            } catch (error) {
                log('editor', '⚠️ Błąd przeliczenia po załadowaniu:', error);
            }
        }
    }, 200);

    log('editor', '✅ Dane wyceny załadowane do edytora');
}

/**
 * POMOCNICZA FUNKCJA: Bezpieczne wywołanie funkcji calculator.js
 * Sprawdza czy funkcja istnieje przed wywołaniem
 */
function safeCallCalculatorFunction(functionName, ...args) {
    if (typeof window[functionName] === 'function') {
        try {
            window[functionName](...args);
            log('sync', `✅ Wywołano ${functionName}()`);
            return true;
        } catch (error) {
            log('sync', `⚠️ Błąd w ${functionName}():`, error);
            return false;
        }
    } else {
        log('sync', `⚠️ Funkcja ${functionName} nie istnieje`);
        return false;
    }
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

    // ✅ POPRAWKA: Przycisk kopiowania zawsze widoczny, usuwania tylko gdy >1 produkt
    const showRemoveButton = totalProducts > 1;

    card.innerHTML = `
        <div class="product-card-content">
            <div class="product-card-number">${displayNumber}</div>
            <div class="product-card-details">
                <div class="product-card-main-info">${description.main}</div>
                ${description.sub ? `<div class="product-card-sub-info">${description.sub}</div>` : ''}
            </div>
            <div class="product-card-actions">
                <button class="copy-product-btn" data-index="${productIndex}" title="Kopiuj produkt">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                </button>
                <button class="remove-product-btn" data-index="${productIndex}" title="Usuń produkt" style="display: ${showRemoveButton ? 'inline-flex' : 'none'};">
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

    if (!currentEditingQuoteData || !currentEditingQuoteData.items) {
        log('editor', '❌ Brak danych wyceny');
        return;
    }

    // Zapisz aktywny produkt przed kopiowaniem
    saveActiveProductFormData();

    // Znajdź wszystkie itemy (warianty) źródłowego produktu
    const sourceItems = currentEditingQuoteData.items.filter(
        item => item.product_index === sourceProductIndex
    );

    if (sourceItems.length === 0) {
        log('editor', '❌ Nie znaleziono produktu do skopiowania');
        return;
    }

    // Znajdź maksymalny product_index i zwiększ o 1
    const maxProductIndex = Math.max(...currentEditingQuoteData.items.map(item => item.product_index));
    const newProductIndex = maxProductIndex + 1;

    log('editor', `Kopiowanie ${sourceItems.length} wariantów z produktu ${sourceProductIndex} do ${newProductIndex}`);

    // Skopiuj wszystkie warianty
    const newItems = sourceItems.map(sourceItem => {
        // Utwórz głęboką kopię itemu
        const newItem = { ...sourceItem };

        // Zmień product_index na nowy
        newItem.product_index = newProductIndex;

        // Usuń ID (będzie nadane przez backend przy zapisie)
        delete newItem.id;

        // Zachowaj is_selected dla wybranego wariantu
        // Pozostałe właściwości kopiujemy 1:1

        return newItem;
    });

    // Dodaj nowe itemy do currentEditingQuoteData
    currentEditingQuoteData.items.push(...newItems);

    // ✅ POPRAWKA: Dodaj również do originalQuoteData aby checkboxy dostępności działały
    if (window.originalQuoteData && window.originalQuoteData.items) {
        window.originalQuoteData.items.push(...newItems);
        log('editor', '✅ Dodano skopiowane warianty również do originalQuoteData');
    }

    // Skopiuj wykończenie jeśli istnieje
    if (currentEditingQuoteData.finishing) {
        const sourceFinishing = currentEditingQuoteData.finishing.find(
            f => f.product_index === sourceProductIndex
        );

        if (sourceFinishing) {
            const newFinishing = { ...sourceFinishing };
            newFinishing.product_index = newProductIndex;
            delete newFinishing.id;
            currentEditingQuoteData.finishing.push(newFinishing);

            // ✅ POPRAWKA: Dodaj również do originalQuoteData
            if (window.originalQuoteData && window.originalQuoteData.finishing) {
                window.originalQuoteData.finishing.push({ ...newFinishing });
            }

            log('editor', '✅ Skopiowano wykończenie');
        }
    }

    log('editor', `✅ Skopiowano produkt: ${sourceProductIndex} → ${newProductIndex}`);

    // Odśwież listę produktów
    loadProductsToEditor(currentEditingQuoteData);

    // Aktywuj nowo skopiowany produkt
    setTimeout(() => {
        activateProductInEditor(newProductIndex);
    }, 100);
}

// ==================== OPTIMIZED CALCULATION FUNCTIONS ====================

/**
 * ULEPSZONA funkcja onFormDataChange z lepszym error handling
 */
function onFormDataChange() {
    // ✅ KRYTYCZNA POPRAWKA: Zapobiegnij nieskończonej pętli
    if (isRecalculating) {
        log('sync', '⚠️ Przeliczenie już w toku - pomijam wywołanie');
        return;
    }

    isRecalculating = true;
    log('sync', 'Dane formularza zostały zmienione');

    if (!checkCalculatorReadiness()) {
        log('sync', 'Calculator.js nie gotowy - używam fallback');
        calculateEditorPrices();
        updateQuoteSummary();
        saveActiveProductFormData();
        updateProductsSummaryTotals();
        isRecalculating = false; // ✅ Zwolnij flagę
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
            isRecalculating = false; // ✅ Zwolnij flagę
            return;
        }

        // ✅ POPRAWKA: Sprawdź sync PRZED calculation
        if (!syncEditorDataToCalculatorForm()) {
            log('sync', 'Sync danych nie powiódł się - fallback');
            calculateEditorPrices();
            updateQuoteSummary();
            isRecalculating = false; // ✅ Zwolnij flagę
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

        // ✅ POPRAWKA: Zapisz dane formularza PRZED kopiowaniem wyników
        // (żeby is_selected był ustawiony prawidłowo)
        saveActiveProductFormData();

        copyCalculationResults();
        updateQuoteSummary();

        log('calculator', '✅ Obliczenia zakończone pomyślnie');

    } catch (error) {
        console.error('[QUOTE EDITOR] ❌ Błąd w obliczeniach:', error);
        log('editor', 'Używam fallback z powodu błędu');
        calculateEditorPrices();
        updateQuoteSummary();
        saveActiveProductFormData(); // ✅ Zapisz także w przypadku błędu
    } finally {
        // ✅ KRYTYCZNA POPRAWKA: ZAWSZE zwolnij flagę (nawet przy błędzie)
        updateProductsSummaryTotals();
        isRecalculating = false;
    }
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

        if (calculatorElement) {
            // Dla clientType: jeśli element nie istnieje (ukryty dla partnera), użyj data-client-type
            if (!editorElement && calculatorField === 'clientType') {
                const userClientType = document.body.dataset.clientType;
                if (userClientType) {
                    calculatorElement.value = userClientType;
                    syncedCount++;
                    log('sync', `✅ ${calculatorField}: ${userClientType} (z body.dataset)`);
                } else {
                    log('sync', `⚠️ Brak wartości clientType w body.dataset`);
                }
            } else if (editorElement) {
                calculatorElement.value = editorElement.value || '';
                syncedCount++;
                if (DEBUG_LOGS.sync) {
                    log('sync', `✅ ${calculatorField}: ${editorElement.value}`);
                }
            } else {
                log('sync', `⚠️ Nie można zsynchronizować ${calculatorField} - brak elementu #${editorId}`);
            }
        } else {
            log('sync', `⚠️ Nie można zsynchronizować ${calculatorField} - brak pola w formularzu`);
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

    // ✅ NOWE: Dla standardowych partnerów ustaw automatycznie ich grupę cenową i ukryj pole
    const userRole = document.body.dataset.role;
    const isFlexiblePartner = document.body.dataset.flexiblePartner === 'true';
    const isPartner = userRole === 'partner';

    if (isPartner && !isFlexiblePartner) {
        const userClientType = document.body.dataset.clientType;
        log('editor', `[PARTNER SETUP] userClientType z body: "${userClientType}"`);
        log('editor', `[PARTNER SETUP] Dostępne opcje w select:`, Array.from(select.options).map(opt => `"${opt.value}"`));

        // Ustaw wartość PRZED ukryciem pola
        if (userClientType) {
            select.value = userClientType;
            log('editor', `[PARTNER SETUP] Ustawiono select.value na: "${userClientType}"`);
            log('editor', `[PARTNER SETUP] Aktualna wartość select.value po ustawieniu: "${select.value}"`);
            log('editor', `[PARTNER SETUP] selectedIndex: ${select.selectedIndex}`);

            // Sprawdź czy wartość została faktycznie ustawiona
            if (select.value === userClientType) {
                log('editor', `✅ Pomyślnie ustawiono grupę cenową partnera: ${userClientType}`);
            } else {
                log('editor', `❌ BŁĄD: Nie udało się ustawić wartości "${userClientType}". Aktualna wartość: "${select.value}"`);
                // Spróbuj znaleźć opcję ręcznie (case-insensitive)
                const matchingOption = Array.from(select.options).find(opt =>
                    opt.value.toLowerCase() === userClientType.toLowerCase()
                );
                if (matchingOption) {
                    matchingOption.selected = true;
                    log('editor', `✅ Ustawiono przez matchingOption: ${matchingOption.value}`);
                }
            }
        }

        // Ukryj pole grupy cenowej
        const wrapper = select.closest('.client-type');
        if (wrapper) {
            wrapper.style.display = 'none';
            log('editor', '✅ Ukryto pole grupy cenowej dla standardowego partnera');
        }

        // Wywołaj event change aby przeliczenia się wykonały (jeśli wartość została ustawiona)
        if (userClientType && select.value) {
            const event = new Event('change', { bubbles: true });
            select.dispatchEvent(event);
            log('editor', `✅ Wywołano event change dla wartości: "${select.value}"`);
        }
    } else {
        log('editor', `✅ Pole grupy cenowej pozostaje widoczne (flexible partner lub admin)`);
    }
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

        // ✅ NOWE: Zapisz price_per_m3 i volume_m3 do dataset
        if (result.price_per_m3 !== undefined) {
            radio.dataset.pricePerM3 = result.price_per_m3;
        }
        if (result.volume_m3 !== undefined) {
            radio.dataset.volumeM3 = result.volume_m3;
        }

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
        return { unitBrutto: 0, unitNetto: 0, totalBrutto: 0, totalNetto: 0, noPrice: true };
    }

    let basePrice = 0;

    // Try to get price from database
    if (window.priceIndex) {
        const match = getEditorPrice(config.species, config.technology, config.wood_class, formData.thickness, formData.length);
        if (match) {
            basePrice = match.price_per_m3;
        }
    }

    // ✅ POPRAWKA: Jeśli nie ma ceny w bazie (wymiary poza limitami), zwróć noPrice: true
    if (basePrice === 0) {
        return {
            unitBrutto: 0,
            unitNetto: 0,
            totalBrutto: 0,
            totalNetto: 0,
            noPrice: true,
            price_per_m3: 0,
            volume_m3: formData.volume
        };
    }

    // Calculate prices
    const pricePerM3WithMultiplier = basePrice * formData.multiplier; // ✅ Cena za m³ PO przeliczniku
    const unitNetto = formData.volume * pricePerM3WithMultiplier;
    const unitBrutto = unitNetto * 1.23;
    const totalNetto = unitNetto * formData.quantity;
    const totalBrutto = unitBrutto * formData.quantity;

    return {
        unitNetto,
        unitBrutto,
        totalNetto,
        totalBrutto,
        noPrice: false,
        price_per_m3: pricePerM3WithMultiplier, // ✅ POPRAWKA: Zapisz cenę PO przeliczniku
        volume_m3: formData.volume
    };
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

    // ✅ POPRAWKA: Jeśli brak ceny (wymiary poza limitami z bazy), wyświetl "Brak ceny"
    if (prices.noPrice) {
        Object.values(elements).forEach(element => {
            if (element) {
                element.textContent = 'Brak ceny';
            }
        });
        return;
    }

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

    const fallback = {
        'Bazowy': 1.0,
        'Hurt': 1.1,
        'Detal': 1.3,
        'Detal+': 1.5,
        'Czernecki netto': 0.935,
        'Czernecki FV': 1.015
    };
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
 * ✅ NOWA FUNKCJA: Wyświetla koszt wykończenia aktywnego produktu w sekcji finishing
 */
function updateActiveFinishingCostDisplay(activeFinishingCosts) {
    const displayDiv = document.getElementById('edit-active-finishing-cost');
    const bruttoSpan = document.querySelector('.edit-active-finishing-brutto-display');
    const nettoSpan = document.querySelector('.edit-active-finishing-netto-display');

    if (!displayDiv || !bruttoSpan || !nettoSpan) return;

    // Pokaż div tylko jeśli wykończenie > 0 lub nie jest "Surowe"
    const finishingType = getSelectedFinishingType();
    const hasFinishing = finishingType !== 'Surowe' || activeFinishingCosts.brutto > 0;

    displayDiv.style.display = hasFinishing ? 'block' : 'none';

    if (hasFinishing) {
        bruttoSpan.textContent = `${activeFinishingCosts.brutto.toFixed(2)} PLN brutto`;
        nettoSpan.textContent = `${activeFinishingCosts.netto.toFixed(2)} PLN netto`;
        log('finishing', `✅ Wyświetlono koszt wykończenia aktywnego produktu: ${activeFinishingCosts.brutto.toFixed(2)} PLN`);
    }
}

/**
 * Zoptymalizowane odświeżanie podsumowania
 */
function updateQuoteSummary() {
    log('editor', '=== ODŚWIEŻANIE PODSUMOWANIA EDYTORA ===');

    try {
        // ✅ Oblicz koszty aktywnego produktu (do pokazania w formularzu)
        const activeProductCosts = calculateActiveProductCosts();
        const activeFinishingCosts = calculateActiveProductFinishingCosts();

        // ✅ NOWE: Zaktualizuj wyświetlanie kosztu wykończenia w sekcji finishing
        updateActiveFinishingCostDisplay(activeFinishingCosts);
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
        // ✅ ZMIANA: Pokazuj sumy WSZYSTKICH surowych produktów (nie tylko aktywnego)
        { selector: '.edit-order-brutto', value: orderTotals.productsRaw.brutto },
        { selector: '.edit-order-netto', value: orderTotals.productsRaw.netto, suffix: ' netto' },

        // ✅ ZMIANA: Pokazuj sumy wykończeń WSZYSTKICH produktów (nie tylko aktywnego)
        { selector: '.edit-finishing-brutto', value: orderTotals.finishing.brutto },
        { selector: '.edit-finishing-netto', value: orderTotals.finishing.netto, suffix: ' netto' },

        // ✅ ZMIANA: Pokazuj sumy WSZYSTKICH produktów (surowe + wykończenia)
        { selector: '.edit-product-total-brutto', value: orderTotals.products.brutto },
        { selector: '.edit-product-total-netto', value: orderTotals.products.netto, suffix: ' netto' },

        // Dostawa (bez zmian)
        { selector: '.edit-delivery-brutto', value: shippingCosts.brutto },
        { selector: '.edit-delivery-netto', value: shippingCosts.netto, suffix: ' netto' },

        // Suma zamówienia = WSZYSTKIE produkty (z wykończeniem) + dostawa
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
        productsRaw: { brutto: 0, netto: 0 },    // ✅ NOWE: suma surowych produktów (bez wykończeń)
        finishing: { brutto: 0, netto: 0 },      // suma wykończeń
        products: { brutto: 0, netto: 0 }        // suma całkowita (surowe + wykończenia)
    };

    log('editor', '=== OBLICZANIE CAŁKOWITEJ SUMY ZAMÓWIENIA ===');

    if (currentEditingQuoteData?.items) {
        currentEditingQuoteData.items.forEach(item => {
            if (!item.is_selected) return;

            // ✅ POPRAWKA: Użyj calculated_price jeśli dostępny (aktywny produkt),
            // w przeciwnym razie użyj final_price (nieaktywne produkty z bazy)
            const productBrutto = parseFloat(item.calculated_price_brutto || item.final_price_brutto || 0);
            const productNetto = parseFloat(item.calculated_price_netto || item.final_price_netto || 0);

            // ✅ DEBUG: Wyloguj szczegóły każdego produktu
            log('editor', `📦 Produkt ${item.product_index}: ${productBrutto.toFixed(2)} PLN brutto (calculated: ${item.calculated_price_brutto}, final: ${item.final_price_brutto})`);

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

            // ✅ NOWE: Dodaj do surowych produktów (bez wykończeń)
            totals.productsRaw.brutto += productBrutto;
            totals.productsRaw.netto += productNetto;

            // Dodaj do sumy wykończeń
            totals.finishing.brutto += finishingBrutto;
            totals.finishing.netto += finishingNetto;

            // Dodaj do sumy całkowitej produktów (surowe + wykończenie)
            totals.products.brutto += totalBrutto;
            totals.products.netto += totalNetto;
        });
    }

    log('editor', '🏁 SUMA CAŁKOWITA:', {
        surowe_produkty: `${totals.productsRaw.brutto.toFixed(2)} PLN brutto, ${totals.productsRaw.netto.toFixed(2)} PLN netto`,
        wykończenie: `${totals.finishing.brutto.toFixed(2)} PLN brutto, ${totals.finishing.netto.toFixed(2)} PLN netto`,
        produkty_z_wykończeniem: `${totals.products.brutto.toFixed(2)} PLN brutto, ${totals.products.netto.toFixed(2)} PLN netto`
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

// ==================== SHIPPING CALCULATION (GLOBKURIER) ====================

/**
 * ✅ POPRAWIONA FUNKCJA: Obliczanie wymiarów agregowanych dla wysyłki
 */
function computeEditorAggregatedData() {
    if (!currentEditingQuoteData?.items || currentEditingQuoteData.items.length === 0) {
        console.error("Brak produktów w wycenie");
        return null;
    }

    let maxLength = 0;
    let maxWidth = 0;
    let totalThickness = 0;
    let totalWeight = 0;

    // Grupuj items według product_index (jeden produkt może mieć kilka wariantów)
    const productGroups = {};
    currentEditingQuoteData.items.forEach(item => {
        const productIndex = item.product_index;
        if (!productGroups[productIndex]) {
            productGroups[productIndex] = [];
        }
        productGroups[productIndex].push(item);
    });

    // Iteruj przez grupy produktów (bierzemy tylko pierwszy item z każdej grupy dla wymiarów)
    Object.keys(productGroups).forEach(productIndex => {
        const items = productGroups[productIndex];
        const firstItem = items[0]; // Wszystkie warianty mają te same wymiary

        const lengthVal = parseFloat(firstItem.length_cm) || 0;
        const widthVal = parseFloat(firstItem.width_cm) || 0;
        const thicknessVal = parseFloat(firstItem.thickness_cm) || 0;

        // Pobierz ilość z details (jeśli istnieje)
        let quantityVal = 1;
        if (currentEditingQuoteData.details) {
            const detail = currentEditingQuoteData.details.find(d => d.product_index === parseInt(productIndex));
            if (detail) {
                quantityVal = parseInt(detail.quantity) || 1;
            }
        }

        console.log(`📦 Produkt ${productIndex}:`, {
            length: lengthVal,
            width: widthVal,
            thickness: thicknessVal,
            quantity: quantityVal
        });

        if (lengthVal > maxLength) maxLength = lengthVal;
        if (widthVal > maxWidth) maxWidth = widthVal;

        totalThickness += thicknessVal * quantityVal;

        // Oblicz wagę (objętość * gęstość drewna 800 kg/m³)
        const volume = (lengthVal / 100) * (widthVal / 100) * (thicknessVal / 100);
        const productWeight = volume * 800 * quantityVal;
        totalWeight += productWeight;
    });

    // Dodaj margines bezpieczeństwa
    const aggregatedLength = maxLength + 5;
    const aggregatedWidth = maxWidth + 5;
    const aggregatedThickness = totalThickness + 5;

    console.log('📦 Wymiary agregowane dla wysyłki:', {
        length: aggregatedLength,
        width: aggregatedWidth,
        height: aggregatedThickness,
        weight: totalWeight
    });

    return {
        length: aggregatedLength,
        width: aggregatedWidth,
        height: aggregatedThickness,
        weight: totalWeight,
        quantity: 1,
        senderCountryId: "1",
        receiverCountryId: "1"
    };
}

/**
 * ✅ NOWA FUNKCJA: Główna funkcja obliczania wysyłki w edytorze
 */
async function calculateEditorDelivery() {
    console.log('🚚 Rozpoczynam obliczanie wysyłki...');

    const button = document.getElementById('edit-calculate-shipping-btn');
    if (button) {
        button.disabled = true;
        button.innerHTML = `
            <span class="btn-loading-dots">
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="dot"></span>
            </span>
            Obliczam...
        `;
    }

    const shippingParams = computeEditorAggregatedData();
    if (!shippingParams) {
        console.error("❌ Brak danych wysyłki");
        if (button) {
            button.disabled = false;
            button.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M0 3.5A1.5 1.5 0 0 1 1.5 2h9A1.5 1.5 0 0 1 12 3.5V5h1.02a1.5 1.5 0 0 1 1.17.563l1.481 1.85a1.5 1.5 0 0 1 .329.938V10.5a1.5 1.5 0 0 1-1.5 1.5H14a2 2 0 1 1-4 0H5a2 2 0 1 1-3.998-.085A1.5 1.5 0 0 1 0 10.5v-7zm1.294 7.456A1.999 1.999 0 0 1 4.732 11h5.536a2.01 2.01 0 0 1 .732-.732V3.5a.5.5 0 0 0-.5-.5h-9a.5.5 0 0 0-.5.5v7a.5.5 0 0 0 .294.456zM12 10a2 2 0 0 1 1.732 1h.768a.5.5 0 0 0 .5-.5V8.35a.5.5 0 0 0-.11-.312l-1.48-1.85A.5.5 0 0 0 13.02 6H12v4zm-9 1a1 1 0 1 0 0 2 1 1 0 0 0 0-2zm9 0a1 1 0 1 0 0 2 1 1 0 0 0 0-2z"/></svg> Oblicz wysyłkę';
        }
        alert('Brak produktów w wycenie do obliczenia wysyłki.');
        return;
    }

    try {
        const response = await fetch('/calculator/shipping_quote', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(shippingParams)
        });

        if (response.ok) {
            const quotesData = await response.json();
            const quotesList = Array.isArray(quotesData) ? quotesData : [quotesData];

            // Zastosuj mnożnik pakowania (tak jak w calculator)
            const shippingPackingMultiplier = 1.15;
            const quotes = quotesList.map(option => ({
                carrierName: option.carrierName,
                rawGrossPrice: option.grossPrice,
                rawNetPrice: option.netPrice,
                grossPrice: option.grossPrice * shippingPackingMultiplier,
                netPrice: option.netPrice * shippingPackingMultiplier,
                carrierLogoLink: option.carrierLogoLink || ""
            }));

            console.log('✅ Otrzymano wyceny wysyłki:', quotes);

            if (quotes.length === 0) {
                alert('Brak dostępnych metod dostawy.');
            } else {
                // Użyj modalu delivery z calculator (teraz dostępny w quotes dzięki przekopiowaniu HTML i CSS)
                const packingInfo = {
                    multiplier: shippingPackingMultiplier,
                    message: `Do cen wysyłki została doliczona kwota ${Math.round((shippingPackingMultiplier - 1) * 100)}% na pakowanie.`
                };

                // Użyj dedykowanego modalu delivery który został przekopiowany do quotes
                showQuotesDeliveryModal(quotes, packingInfo);
            }
        } else {
            let errorMessage = "Błąd podczas wyceny wysyłki.";
            try {
                const errorData = await response.json();
                if (errorData.error) {
                    errorMessage = errorData.error;
                }
            } catch (parseError) {
                console.error("Nie udało się sparsować odpowiedzi błędu:", parseError);
            }
            console.error('❌ Błąd HTTP:', response.status, errorMessage);
            alert(errorMessage);
        }
    } catch (err) {
        console.error('❌ Wyjątek podczas pobierania wyceny:', err);
        let userMessage = "Błąd połączenia. Sprawdź połączenie internetowe.";
        if (err.name === 'TypeError' && err.message.includes('fetch')) {
            userMessage = "Nie można połączyć się z serwerem. Sprawdź połączenie internetowe.";
        }
        alert(userMessage);
    } finally {
        if (button) {
            button.disabled = false;
            button.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M0 3.5A1.5 1.5 0 0 1 1.5 2h9A1.5 1.5 0 0 1 12 3.5V5h1.02a1.5 1.5 0 0 1 1.17.563l1.481 1.85a1.5 1.5 0 0 1 .329.938V10.5a1.5 1.5 0 0 1-1.5 1.5H14a2 2 0 1 1-4 0H5a2 2 0 1 1-3.998-.085A1.5 1.5 0 0 1 0 10.5v-7zm1.294 7.456A1.999 1.999 0 0 1 4.732 11h5.536a2.01 2.01 0 0 1 .732-.732V3.5a.5.5 0 0 0-.5-.5h-9a.5.5 0 0 0-.5.5v7a.5.5 0 0 0 .294.456zM12 10a2 2 0 0 1 1.732 1h.768a.5.5 0 0 0 .5-.5V8.35a.5.5 0 0 0-.11-.312l-1.48-1.85A.5.5 0 0 0 13.02 6H12v4zm-9 1a1 1 0 1 0 0 2 1 1 0 0 0 0-2zm9 0a1 1 0 1 0 0 2 1 1 0 0 0 0-2z"/></svg> Oblicz wysyłkę';
        }
    }
}

/**
 * ✅ NOWA FUNKCJA: Modal delivery dla quotes (wykorzystuje przekopiowany HTML z calculator)
 */
function showQuotesDeliveryModal(quotes, packingInfo) {
    const modal = document.getElementById('deliveryModal');
    if (!modal) {
        console.error('❌ Nie znaleziono elementu #deliveryModal');
        return;
    }

    const optionsList = document.getElementById('deliveryOptionsList');
    const packingInfoEl = document.getElementById('deliveryPackingInfo');
    const headerAdjusted = document.getElementById('deliveryHeaderAdjusted');
    let confirmBtn = document.getElementById('deliveryModalConfirm');
    let closeBtn = document.getElementById('deliveryModalClose');
    let cancelBtn = document.getElementById('deliveryModalCancel');

    // Wyczyść poprzednie opcje
    optionsList.innerHTML = '';

    // Ustaw informację o pakowaniu
    if (packingInfo && packingInfoEl) {
        packingInfoEl.textContent = `ℹ️ ${packingInfo.message}`;
        packingInfoEl.classList.remove('delivery-modal-hidden');
        if (headerAdjusted) {
            headerAdjusted.textContent = `Cena + ${Math.round((packingInfo.multiplier - 1) * 100)}%`;
        }
    }

    // Dodaj event listenery (usuń stare przed dodaniem nowych) - PRZED generowaniem opcji
    confirmBtn.replaceWith(confirmBtn.cloneNode(true));
    closeBtn.replaceWith(closeBtn.cloneNode(true));
    cancelBtn.replaceWith(cancelBtn.cloneNode(true));

    // Pobierz nowe referencje
    confirmBtn = document.getElementById('deliveryModalConfirm');
    closeBtn = document.getElementById('deliveryModalClose');
    cancelBtn = document.getElementById('deliveryModalCancel');

    // Generuj opcje kurierów
    quotes.forEach((quote, index) => {
        const option = document.createElement('div');
        option.className = 'delivery-modal-option';
        option.innerHTML = `
            <input type="radio" name="deliveryOption" value="${index}" id="delivery-opt-${index}">
            <div class="delivery-modal-name-container">
                ${quote.carrierLogoLink ? `<img src="${quote.carrierLogoLink}" alt="${quote.carrierName}" class="delivery-modal-logo">` : ''}
                <span class="delivery-modal-name">${quote.carrierName}</span>
            </div>
            <div class="delivery-modal-price">
                <div class="delivery-modal-price-brutto">${formatPLN(quote.grossPrice)}</div>
                <div class="delivery-modal-price-netto">${formatPLN(quote.netPrice)} netto</div>
            </div>
            <div class="delivery-modal-price">
                <div class="delivery-modal-price-brutto">${formatPLN(quote.rawGrossPrice)}</div>
                <div class="delivery-modal-price-netto">${formatPLN(quote.rawNetPrice)} netto</div>
            </div>
        `;

        // Obsługa kliknięcia w opcję
        option.addEventListener('click', () => {
            // Zaznacz radio
            const radio = option.querySelector('input[type="radio"]');
            radio.checked = true;

            // Usuń selected z innych
            document.querySelectorAll('.delivery-modal-option').forEach(opt => {
                opt.classList.remove('selected');
            });
            option.classList.add('selected');

            // Aktywuj przycisk potwierdzenia (teraz mamy poprawną referencję)
            confirmBtn.disabled = false;
        });

        optionsList.appendChild(option);
    });

    // Obsługa potwierdzenia
    const handleConfirm = () => {
        const selectedRadio = document.querySelector('input[name="deliveryOption"]:checked');
        if (!selectedRadio) return;

        const selectedIndex = parseInt(selectedRadio.value);
        const selectedQuote = quotes[selectedIndex];

        // Zapisz do currentEditingQuoteData
        currentEditingQuoteData.shipping_cost_brutto = selectedQuote.grossPrice;
        currentEditingQuoteData.shipping_cost_netto = selectedQuote.netPrice;
        currentEditingQuoteData.courier_name = selectedQuote.carrierName;

        // Zaktualizuj wyświetlanie
        document.getElementById('edit-courier-name').textContent = selectedQuote.carrierName;
        document.querySelector('.edit-delivery-brutto').textContent = formatPLN(selectedQuote.grossPrice);
        document.querySelector('.edit-delivery-netto').textContent = formatPLN(selectedQuote.netPrice) + ' netto';

        // Przelicz sumy
        updateQuoteSummary();

        console.log('✅ Wybrano kuriera:', selectedQuote.carrierName);

        // Zamknij modal
        modal.classList.remove('active');
    };

    // Obsługa zamknięcia
    const handleClose = () => {
        modal.classList.remove('active');
        confirmBtn.disabled = true;
        document.querySelectorAll('.delivery-modal-option').forEach(opt => {
            opt.classList.remove('selected');
        });
    };

    confirmBtn.addEventListener('click', handleConfirm);
    closeBtn.addEventListener('click', handleClose);
    cancelBtn.addEventListener('click', handleClose);

    // ✅ NOWE: Obsługa dodawania własnego kuriera
    const addCustomBtn = document.getElementById('addCustomCarrier');
    const backToListBtn = document.getElementById('backToDeliveryList');
    const mainView = document.getElementById('deliveryMainView');
    const customView = document.getElementById('deliveryCustomView');

    if (addCustomBtn) {
        addCustomBtn.addEventListener('click', () => {
            // Pokaż formularz własnego kuriera
            mainView?.classList.add('delivery-modal-hidden');
            customView?.classList.remove('delivery-modal-hidden');
            confirmBtn.disabled = true;
            document.getElementById('deliveryConfirmText').textContent = 'Dodaj kuriera';
        });
    }

    if (backToListBtn) {
        backToListBtn.addEventListener('click', () => {
            // Wróć do listy kurierów
            customView?.classList.add('delivery-modal-hidden');
            mainView?.classList.remove('delivery-modal-hidden');
            confirmBtn.disabled = true;
            document.getElementById('deliveryConfirmText').textContent = 'Zapisz';
        });
    }

    // ✅ NOWE: Walidacja i kalkulacja formularza własnego kuriera
    const customNameInput = document.getElementById('customCarrierName');
    const customNettoInput = document.getElementById('customCarrierNetto');
    const customBruttoInput = document.getElementById('customCarrierBrutto');

    const validateCustomForm = () => {
        const name = customNameInput?.value.trim();
        const netto = parseFloat(customNettoInput?.value) || 0;
        const brutto = parseFloat(customBruttoInput?.value) || 0;

        // Aktywuj przycisk tylko jeśli wszystkie pola wypełnione
        const isValid = name && (netto > 0 || brutto > 0);
        confirmBtn.disabled = !isValid;

        return { name, netto, brutto, isValid };
    };

    // Auto-kalkulacja netto <-> brutto
    if (customNettoInput) {
        customNettoInput.addEventListener('input', (e) => {
            const netto = parseFloat(e.target.value) || 0;
            const brutto = netto * 1.23;
            if (customBruttoInput) {
                customBruttoInput.value = brutto.toFixed(2);
            }

            // Aktualizuj kalkulator
            const baseEl = document.getElementById('calcBaseBrutto');
            const marginEl = document.getElementById('calcMargin');
            const finalEl = document.getElementById('calcFinalPrice');

            if (baseEl) baseEl.textContent = brutto.toFixed(2) + ' PLN';

            const margin = brutto * 0.15;
            if (marginEl) marginEl.textContent = margin.toFixed(2) + ' PLN';

            const finalPrice = brutto * 1.15;
            if (finalEl) finalEl.textContent = finalPrice.toFixed(2) + ' PLN';

            validateCustomForm();
        });
    }

    if (customBruttoInput) {
        customBruttoInput.addEventListener('input', (e) => {
            const brutto = parseFloat(e.target.value) || 0;
            const netto = brutto / 1.23;
            if (customNettoInput) {
                customNettoInput.value = netto.toFixed(2);
            }

            // Aktualizuj kalkulator
            const baseEl = document.getElementById('calcBaseBrutto');
            const marginEl = document.getElementById('calcMargin');
            const finalEl = document.getElementById('calcFinalPrice');

            if (baseEl) baseEl.textContent = brutto.toFixed(2) + ' PLN';

            const margin = brutto * 0.15;
            if (marginEl) marginEl.textContent = margin.toFixed(2) + ' PLN';

            const finalPrice = brutto * 1.15;
            if (finalEl) finalEl.textContent = finalPrice.toFixed(2) + ' PLN';

            validateCustomForm();
        });
    }

    if (customNameInput) {
        customNameInput.addEventListener('input', () => {
            validateCustomForm();
        });
    }

    // ✅ NOWE: Modyfikacja handleConfirm - obsługa własnego kuriera
    const originalHandleConfirm = handleConfirm;
    const newHandleConfirm = () => {
        // Sprawdź czy jesteśmy w widoku własnego kuriera
        if (!customView?.classList.contains('delivery-modal-hidden')) {
            const { name, netto, brutto, isValid } = validateCustomForm();

            if (!isValid) {
                alert('Wypełnij wszystkie pola formularza');
                return;
            }

            // Oblicz końcowe ceny z marżą pakowania
            const finalBrutto = brutto * 1.15;
            const finalNetto = netto * 1.15;

            // Zapisz własnego kuriera
            currentEditingQuoteData.shipping_cost_brutto = finalBrutto;
            currentEditingQuoteData.shipping_cost_netto = finalNetto;
            currentEditingQuoteData.courier_name = name;

            // Zaktualizuj wyświetlanie
            document.getElementById('edit-courier-name').textContent = name;
            document.querySelector('.edit-delivery-brutto').textContent = formatPLN(finalBrutto);
            document.querySelector('.edit-delivery-netto').textContent = formatPLN(finalNetto) + ' netto';

            // Przelicz sumy
            updateQuoteSummary();

            console.log('✅ Dodano własnego kuriera:', name, finalBrutto);

            // Wyczyść formularz
            customNameInput.value = '';
            customNettoInput.value = '';
            customBruttoInput.value = '';

            // Zamknij modal
            modal.classList.remove('active');
        } else {
            // Standardowy przepływ wyboru kuriera z listy
            originalHandleConfirm();
        }
    };

    // Zastąp event listener na przycisku confirm
    confirmBtn.removeEventListener('click', handleConfirm);
    confirmBtn.addEventListener('click', newHandleConfirm);

    // Zamknij na kliknięcie w overlay
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            handleClose();
        }
    });

    // Pokaż modal
    confirmBtn.disabled = true;
    modal.classList.add('active');

    console.log('✅ Modal delivery otwarty z', quotes.length, 'opcjami');
}

/**
 * ✅ NOWA FUNKCJA: Prosty modal wyboru kuriera (dedykowany dla edytora) - FALLBACK
 */
function showEditorShippingModal(quotes, packingInfo) {
    const modal = document.createElement('div');
    modal.className = 'simple-shipping-modal-overlay';
    modal.innerHTML = `
        <div class="simple-shipping-modal-box">
            <div class="simple-shipping-modal-header">
                <h3>Wybierz kuriera</h3>
                <button class="simple-shipping-modal-close">&times;</button>
            </div>
            ${packingInfo ? `
                <div class="shipping-packing-info">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M8 16A8 8 0 1 0 8 0a8 8 0 0 0 0 16zm.93-9.412-1 4.705c-.07.34.029.533.304.533.194 0 .487-.07.686-.246l-.088.416c-.287.346-.92.598-1.465.598-.703 0-1.002-.422-.808-1.319l.738-3.468c.064-.293.006-.399-.287-.47l-.451-.081.082-.381 2.29-.287zM8 5.5a1 1 0 1 1 0-2 1 1 0 0 1 0 2z"/>
                    </svg>
                    <span>${packingInfo.message}</span>
                </div>
            ` : ''}
            <div class="simple-shipping-modal-content">
                ${quotes.map((quote, index) => `
                    <div class="shipping-option" data-index="${index}">
                        <div class="shipping-option-name">${quote.carrierName}</div>
                        <div class="shipping-option-price">
                            <span class="price-brutto">${formatPLN(quote.grossPrice)}</span>
                            <span class="price-netto">${formatPLN(quote.netPrice)} netto</span>
                        </div>
                        <button class="btn-select-shipping" data-index="${index}">Wybierz</button>
                    </div>
                `).join('')}
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // Zamknięcie modalu
    const closeModal = () => modal.remove();
    modal.querySelector('.simple-shipping-modal-close').addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });

    // Wybór kuriera
    modal.querySelectorAll('.btn-select-shipping').forEach(btn => {
        btn.addEventListener('click', () => {
            const index = parseInt(btn.dataset.index);
            const selectedQuote = quotes[index];

            // Zapisz do currentEditingQuoteData
            currentEditingQuoteData.shipping_cost_brutto = selectedQuote.grossPrice;
            currentEditingQuoteData.shipping_cost_netto = selectedQuote.netPrice;
            currentEditingQuoteData.courier_name = selectedQuote.carrierName;

            // Zaktualizuj wyświetlanie
            document.getElementById('edit-courier-name').textContent = selectedQuote.carrierName;
            document.querySelector('.edit-delivery-brutto').textContent = formatPLN(selectedQuote.grossPrice);
            document.querySelector('.edit-delivery-netto').textContent = formatPLN(selectedQuote.netPrice) + ' netto';

            // Przelicz sumy
            updateQuoteSummary();

            console.log('✅ Wybrano kuriera:', selectedQuote.carrierName);
            closeModal();
        });
    });
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

        // ✅ POPRAWKA: Dla clientType sprawdź także body.dataset jeśli element nie istnieje (partner)
        if (rule.field === 'edit-clientType') {
            const value = element?.value || document.body.dataset.clientType;
            if (!rule.validator(value)) {
                alert(rule.message);
                return false;
            }
            continue; // Przejdź do następnej reguły
        }

        const value = element?.value;
        const numValue = parseFloat(value);

        if (!rule.validator(numValue)) {
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
    // Szukaj w edytorze wyceny ALBO w mock formie kalkulatora
    let clientTypeSelect = document.getElementById('edit-clientType');
    if (!clientTypeSelect) {
        clientTypeSelect = document.getElementById('mock-clientType');
    }
    // Alternatywnie: szukaj po data-field w active form
    if (!clientTypeSelect && window.activeQuoteForm) {
        clientTypeSelect = window.activeQuoteForm.querySelector('select[data-field="clientType"]');
    }

    log('sync', `[MULTIPLIER UPDATE] Rozpoczynam aktualizację przelicznika...`);
    log('sync', `[MULTIPLIER UPDATE] clientTypeSelect istnieje: ${!!clientTypeSelect}`);
    log('sync', `[MULTIPLIER UPDATE] Znaleziono w: ${clientTypeSelect?.id || 'data-field selector'}`);

    if (!clientTypeSelect) {
        log('sync', '❌ Brak elementu clientType (sprawdzono: #edit-clientType, #mock-clientType, activeQuoteForm)');
        return;
    }

    log('sync', `[MULTIPLIER UPDATE] select.value: "${clientTypeSelect.value}"`);
    log('sync', `[MULTIPLIER UPDATE] selectedIndex: ${clientTypeSelect.selectedIndex}`);
    log('sync', `[MULTIPLIER UPDATE] Liczba opcji: ${clientTypeSelect.options.length}`);

    if (!clientTypeSelect.value) {
        log('sync', '⚠️ Brak grupy cenowej w edytorze (select.value jest puste)');
        log('sync', '[MULTIPLIER UPDATE] Dostępne opcje:', Array.from(clientTypeSelect.options).map(opt => `"${opt.value}"`));
        return;
    }

    const selectedOption = clientTypeSelect.options[clientTypeSelect.selectedIndex];
    log('sync', `[MULTIPLIER UPDATE] selectedOption istnieje: ${!!selectedOption}`);

    if (!selectedOption) {
        log('sync', '❌ Brak wybranej opcji (selectedOption jest null)');
        return;
    }

    log('sync', `[MULTIPLIER UPDATE] selectedOption.value: "${selectedOption.value}"`);
    log('sync', `[MULTIPLIER UPDATE] selectedOption.dataset.multiplierValue: "${selectedOption.dataset.multiplierValue}"`);

    if (!selectedOption.dataset.multiplierValue) {
        log('sync', '⚠️ Brak danych przelicznika dla wybranej grupy');
        return;
    }

    const clientType = selectedOption.value;
    const multiplierValue = parseFloat(selectedOption.dataset.multiplierValue);

    log('sync', `[MULTIPLIER UPDATE] Finalne wartości: clientType="${clientType}", multiplier=${multiplierValue}`);

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

    // ✅ KLUCZOWA POPRAWKA: Znajdź WYBRANY wariant (is_selected), nie pierwszy z product_index
    const activeProduct = currentEditingQuoteData?.items?.find(
        item => item.product_index === activeProductIndex && item.is_selected === true
    );

    if (activeProduct && window.currentActiveProductData.orderBrutto) {
        // ✅ Zaktualizuj totały w danych produktu
        activeProduct.total_brutto = parseFloat(window.currentActiveProductData.orderBrutto);
        activeProduct.total_netto = parseFloat(window.currentActiveProductData.orderNetto);

        // ✅ KLUCZOWA POPRAWKA: Zaktualizuj także calculated_price_* które używa calculateOrderTotals()
        activeProduct.calculated_price_brutto = parseFloat(window.currentActiveProductData.orderBrutto);
        activeProduct.calculated_price_netto = parseFloat(window.currentActiveProductData.orderNetto);

        log('sync', `✅ Zaktualizowano totały WYBRANEGO wariantu produktu ${activeProductIndex}:`, {
            variant_code: activeProduct.variant_code,
            brutto: activeProduct.total_brutto,
            netto: activeProduct.total_netto,
            calculated_brutto: activeProduct.calculated_price_brutto,
            calculated_netto: activeProduct.calculated_price_netto
        });
    } else {
        log('sync', `⚠️ Nie znaleziono wybranego wariantu dla produktu ${activeProductIndex}`);
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

    // ✅ Pobierz dane wykończenia z aktywnych przycisków (tak jak collectFinishingFromUI)
    const finishingTypeBtn = document.querySelector('#quote-editor-modal .finishing-btn[data-finishing-type].active');
    const finishingVariantBtn = document.querySelector('#quote-editor-modal .finishing-btn[data-finishing-variant].active');
    const finishingColorBtn = document.querySelector('#quote-editor-modal .color-btn.active');
    const finishingGlossBtn = document.querySelector('#quote-editor-modal .finishing-btn[data-finishing-gloss].active');

    const formElements = {
        length: parseFloat(document.getElementById('edit-length')?.value) || 0,
        width: parseFloat(document.getElementById('edit-width')?.value) || 0,
        thickness: parseFloat(document.getElementById('edit-thickness')?.value) || 0,
        quantity: parseInt(document.getElementById('edit-quantity')?.value) || 1,
        finishingType: finishingTypeBtn?.dataset.finishingType || 'Surowe',
        finishingVariant: finishingVariantBtn?.dataset.finishingVariant || null,
        finishingColor: finishingColorBtn?.dataset.finishingColor || null,
        finishingGloss: finishingGlossBtn?.dataset.finishingGloss || null
    };

    // ✅ NOWE: Oblicz objętość na podstawie aktualnych wymiarów z formularza
    const currentVolume = (formElements.length / 100) * (formElements.width / 100) * (formElements.thickness / 100);
    log('sync', `📏 Obliczono objętość z wymiarów ${formElements.length}x${formElements.width}x${formElements.thickness}: ${currentVolume.toFixed(6)} m³`);

    const selectedVariant = document.querySelector('input[name="edit-variantOption"]:checked');

    // Aktualizuj podstawowe dane produktu (bez zmiany show_on_client_page)
    currentEditingQuoteData.items
        .filter(item => item.product_index === activeProductIndex)
        .forEach(item => {
            item.length_cm = formElements.length;
            item.width_cm = formElements.width;
            item.thickness_cm = formElements.thickness;
            // ✅ NOWE: Aktualizuj objętość na podstawie nowych wymiarów
            item.volume_m3 = currentVolume;
            item.calculated_volume_m3 = currentVolume;
            // ❌ USUŃ - ilość nie należy do tabeli quote_items
            // item.quantity = formElements.quantity;
            // ❌ USUŃ - wykończenie należy do tabeli quote_items_details, nie quote_items
            // Dane wykończenia są zapisywane do details poniżej (linie 3554-3557)
            // item.finishing_type = formElements.finishingType;
            // item.finishing_variant = formElements.finishingVariant;
            // item.finishing_color = formElements.finishingColor;
            // item.finishing_gloss = formElements.finishingGloss;
        });

    // ✅ POPRAWKA: Zapisz ilość do quote_details (gdzie powinna być)
    if (!currentEditingQuoteData.details) {
        currentEditingQuoteData.details = [];
    }

    let detailsItem = currentEditingQuoteData.details.find(d => d.product_index === activeProductIndex);
    if (!detailsItem) {
        // Utwórz nowy rekord details jeśli nie istnieje
        detailsItem = {
            product_index: activeProductIndex,
            quantity: 1,
            finishing_type: 'Surowe',
            finishing_variant: null,
            finishing_color: null,
            finishing_gloss_level: null,
            finishing_price_netto: 0,
            finishing_price_brutto: 0
        };
        currentEditingQuoteData.details.push(detailsItem);
    }

    // Aktualizuj ilość w details
    detailsItem.quantity = parseInt(formElements.quantity) || 1;
    log('sync', `✅ Zaktualizowano ilość w details: ${detailsItem.quantity}`);

    // ✅ NOWA POPRAWKA: Zapisz ceny z kalkulatora do currentEditingQuoteData.items
    // Pobierz ceny z UI edytora dla każdego wariantu
    const editorVariants = document.querySelectorAll('.variant-option');
    editorVariants.forEach(variantEl => {
        const radio = variantEl.querySelector('input[type="radio"]');
        if (!radio) return;

        const variantCode = radio.value;
        const item = currentEditingQuoteData.items.find(
            i => i.product_index === activeProductIndex && i.variant_code === variantCode
        );

        if (!item) return;

        // Pobierz ceny z UI (skopiowane z kalkulatora przez copyCalculationResults)
        const unitBruttoEl = variantEl.querySelector('.unit-brutto');
        const unitNettoEl = variantEl.querySelector('.unit-netto');
        const totalBruttoEl = variantEl.querySelector('.total-brutto');
        const totalNettoEl = variantEl.querySelector('.total-netto');

        // Zapisz ceny jako calculated_price_* (używane w collectUpdatedQuoteData)
        if (unitBruttoEl?.textContent) {
            const price = parseFloat(unitBruttoEl.textContent.replace(/[^\d,.]/g, '').replace(',', '.'));
            if (!isNaN(price)) {
                item.calculated_price_brutto = price;
                item.unit_price_brutto = price;
                item.final_price_brutto = price;
            }
        }

        if (unitNettoEl?.textContent) {
            const price = parseFloat(unitNettoEl.textContent.replace(/[^\d,.]/g, '').replace(',', '.'));
            if (!isNaN(price)) {
                item.calculated_price_netto = price;
                item.unit_price_netto = price;
                item.final_price_netto = price;
            }
        }

        // ✅ NOWE: Zapisz price_per_m3 z dataset
        if (radio.dataset.pricePerM3) {
            item.price_per_m3 = parseFloat(radio.dataset.pricePerM3);
        }

        // Zapisz również objętość jeśli dostępna
        if (radio.dataset.volumeM3) {
            item.calculated_volume_m3 = parseFloat(radio.dataset.volumeM3);
            item.volume_m3 = parseFloat(radio.dataset.volumeM3);
        }

        // ✅ DEBUG: Szczegółowy log cen (wyłączony - zbyt dużo logów)
        if (DEBUG_LOGS.debug) {
            console.log(`[SAVE PRICES] Wariant ${variantCode}:`, {
                price_per_m3: item.price_per_m3,
                volume_m3: item.volume_m3,
                calculated_volume_m3: item.calculated_volume_m3,
                unit_price_brutto: item.unit_price_brutto,
                calculated_price_brutto: item.calculated_price_brutto,
                final_price_brutto: item.final_price_brutto
            });
        }
    });

    // ✅ POPRAWKA: Zapisz koszty wykończenia dla aktywnego produktu
    if (window.activeQuoteForm?.dataset) {
        const finishingBrutto = parseFloat(window.activeQuoteForm.dataset.finishingBrutto) || 0;
        const finishingNetto = parseFloat(window.activeQuoteForm.dataset.finishingNetto) || 0;

        // DEBUG: Log przed zapisaniem (wyłączony - zbyt dużo logów)
        if (DEBUG_LOGS.debug) {
            console.log(`[SAVE FINISHING] Produkt ${activeProductIndex}:`, {
                formElements_finishingType: formElements.finishingType,
                formElements_finishingVariant: formElements.finishingVariant,
                formElements_finishingColor: formElements.finishingColor,
                formElements_finishingGloss: formElements.finishingGloss,
                finishingBrutto,
                finishingNetto
            });
        }

        // Aktualizuj wykończenie w details
        detailsItem.finishing_price_brutto = finishingBrutto;
        detailsItem.finishing_price_netto = finishingNetto;
        detailsItem.finishing_type = formElements.finishingType || 'Surowe';
        detailsItem.finishing_variant = formElements.finishingVariant || null;
        detailsItem.finishing_color = formElements.finishingColor || null;
        detailsItem.finishing_gloss_level = formElements.finishingGloss || null;

        if (DEBUG_LOGS.debug) {
            console.log(`[SAVE FINISHING] Po zapisaniu do detailsItem:`, {
                finishing_type: detailsItem.finishing_type,
                finishing_variant: detailsItem.finishing_variant,
                finishing_color: detailsItem.finishing_color,
                finishing_gloss_level: detailsItem.finishing_gloss_level
            });
        }

        log('sync', `✅ Zapisano wykończenie w details: ${finishingBrutto} PLN brutto`);
    }

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
    log('editor', `Aktywacja produktu: ${productIndex}`);

    // ✅ KROK 1: Zapisz stan zaznaczonych wariantów WSZYSTKICH produktów (wzorowane na calculator.js)
    const savedVariants = {};
    if (currentEditingQuoteData?.items) {
        const uniqueProductIndexes = [...new Set(currentEditingQuoteData.items.map(item => item.product_index))];

        uniqueProductIndexes.forEach(pIndex => {
            const selectedItem = currentEditingQuoteData.items.find(
                item => item.product_index === pIndex && item.is_selected === true
            );
            if (selectedItem) {
                savedVariants[pIndex] = {
                    variant_code: selectedItem.variant_code,
                    id: selectedItem.id
                };
                log('editor', `💾 Zapisano wariant produktu ${pIndex}: ${selectedItem.variant_code}`);
            }
        });
    }

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

    const productItem = currentEditingQuoteData.items.find(item => item.product_index === productIndex && item.is_selected === true);
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

    // ✅ KROK 2: Przywróć zaznaczenia wariantów WSZYSTKICH produktów (wzorowane na calculator.js)
    Object.entries(savedVariants).forEach(([pIndex, variantData]) => {
        const pIndexInt = parseInt(pIndex);

        // Dla każdego produktu przywróć jego wybrany wariant w danych
        currentEditingQuoteData.items.forEach(item => {
            if (item.product_index === pIndexInt) {
                // Zaznacz tylko ten który był zapisany
                if (item.variant_code === variantData.variant_code) {
                    item.is_selected = true;
                } else {
                    item.is_selected = false;
                }
            }
        });

        log('editor', `🔄 Przywrócono wariant produktu ${pIndexInt}: ${variantData.variant_code}`);
    });

    // ✅ KROK 3: Ustaw odpowiedni wariant w UI dla aktywnego produktu
    if (savedVariants[productIndex]) {
        selectVariantByCode(savedVariants[productIndex].variant_code);
    } else {
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
    const closeButton = document.getElementById('close-quote-editor');
    const cancelButton = document.getElementById('cancel-quote-edit'); // ✅ NOWE: Przycisk Anuluj

    if (!modal || !closeButton) {
        console.error('[QUOTE EDITOR] Nie znaleziono przycisku zamykania');
        return;
    }

    // Handler zamykania
    const closeHandler = () => {
        log('editor', 'Zamykanie edytora wyceny...');

        // ✅ NOWE: Przywróć funkcje calculator.js przed zamknięciem
        restoreCalculatorFunctions();

        // ✅ NOWE: Pełne czyszczenie danych przy zamknięciu
        clearEditorData();

        // Zamknij modal
        modal.style.display = 'none';

        // Opcjonalnie: odśwież listę wycen
        if (typeof loadQuotes === 'function') {
            loadQuotes();
        }

        log('editor', '✅ Edytor zamknięty');
    };

    // Usuń stare event listenery i dodaj nowe
    closeButton.replaceWith(closeButton.cloneNode(true));
    const newCloseButton = document.getElementById('close-quote-editor');

    newCloseButton.addEventListener('click', closeHandler);

    // ✅ NOWE: Dodaj listener dla przycisku Anuluj
    if (cancelButton) {
        cancelButton.replaceWith(cancelButton.cloneNode(true));
        const newCancelButton = document.getElementById('cancel-quote-edit');
        newCancelButton.addEventListener('click', closeHandler);
        log('editor', '✅ Przycisk Anuluj skonfigurowany');
    } else {
        log('editor', '⚠️ Nie znaleziono przycisku Anuluj (#cancel-quote-edit)');
    }

    // Zamknij przez ESC
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal.style.display === 'flex') {
            closeHandler();
        }
    });

    log('editor', '✅ Handlery zamykania skonfigurowane (kliknięcie w tło wyłączone)');
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

    // Wyczyść dane wyceny
    currentEditingQuoteData = null;
    activeProductIndex = null;

    // Wyczyść cache
    window.currentActiveProductData = {};

    // ✅ NOWE: Reset flagi przeliczania
    isRecalculating = false;

    // ✅ NOWE: Wyczyść oryginalną kopię danych
    window.originalQuoteData = null;

    // Reset kalkulatora
    resetCalculatorAfterEditor();

    // Wyczyść formularz UI
    clearEditorForm();

    log('editor', '✅ Dane edytora wyczyszczone');
}

/**
 * ✅ NOWA FUNKCJA - Czyszczenie formularza UI
 */
function clearEditorForm() {
    // Wyczyść pola formularza
    const fieldsToReset = [
        'edit-length',
        'edit-width',
        'edit-thickness',
        'edit-quantity',
        'edit-clientType'
    ];

    fieldsToReset.forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (field) {
            if (fieldId === 'edit-clientType') {
                field.selectedIndex = 0; // Reset select do pierwszej opcji
            } else if (fieldId === 'edit-quantity') {
                field.value = '1'; // Ilość na 1
            } else {
                field.value = ''; // Wyczyść inne pola
            }
        }
    });

    // Wyczyść listę produktów
    const productsList = document.getElementById('edit-products-list');
    if (productsList) {
        productsList.innerHTML = '';
    }

    // Wyczyść podsumowanie
    const summaryElements = document.querySelectorAll(
        '.edit-order-brutto, .edit-order-netto, ' +
        '.edit-finishing-brutto, .edit-finishing-netto, ' +
        '.edit-product-total-brutto, .edit-product-total-netto'
    );
    summaryElements.forEach(el => {
        if (el) el.textContent = '0.00';
    });

    // Reset wykończenia do "Surowe"
    const finishingButtons = document.querySelectorAll('#quote-editor-modal .finishing-btn');
    finishingButtons.forEach(btn => btn.classList.remove('active'));

    const surowiBtn = document.querySelector('#quote-editor-modal [data-finishing-type="Surowe"]');
    if (surowiBtn) surowiBtn.classList.add('active');

    // Wyczyść warianty
    const variantOptions = document.querySelectorAll('#quote-editor-modal .variant-option');
    variantOptions.forEach(variant => {
        // Odznacz radio buttony
        const radio = variant.querySelector('input[type="radio"]');
        if (radio) radio.checked = false;

        // Usuń klasę selected
        variant.classList.remove('selected');

        // Resetuj checkboxy dostępności
        const checkbox = variant.querySelector('.variant-availability-checkbox');
        if (checkbox) checkbox.checked = false;
    });

    // Ukryj sekcje wykończenia
    const finishingVariantWrapper = document.getElementById('edit-finishing-variant-wrapper');
    const finishingColorWrapper = document.getElementById('edit-finishing-color-wrapper');
    const finishingGlossWrapper = document.getElementById('edit-finishing-gloss-wrapper');

    if (finishingVariantWrapper) finishingVariantWrapper.style.display = 'none';
    if (finishingColorWrapper) finishingColorWrapper.style.display = 'none';
    if (finishingGlossWrapper) finishingGlossWrapper.style.display = 'none';

    log('editor', '✅ Formularz UI wyczyszczony');
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
async function saveQuoteChanges() {
    log('editor', 'Zapisywanie zmian w wycenie...');

    // Zachowaj bieżące dane produktu przed zapisem
    saveActiveProductFormData();

    if (!currentEditingQuoteData) {
        showToast('Błąd: Brak danych wyceny do zapisu', 'error');
        return;
    }

    if (!validateFormBeforeSave()) return;

    const updatedData = collectUpdatedQuoteData();
    if (!updatedData) {
        showToast('Błąd: Nie udało się zebrać danych z formularza', 'error');
        return;
    }

    // ✅ DEBUG: Szczegółowy log payloadu - WARIANTY I CENY
    console.log('═══════════════════════════════════════════════════');
    console.log('[PAYLOAD TO BACKEND] Liczba produktów:', updatedData.products.length);
    updatedData.products.forEach((product, index) => {
        console.log(`\n[PRODUCT ${index + 1}] Product Index: ${product.product_index}`);
        console.log(`  Wymiary: ${product.length_cm} x ${product.width_cm} x ${product.thickness_cm} cm`);
        console.log(`  Ilość: ${product.quantity}`);
        console.log(`  Wybrany wariant: ${product.selected_variant.variant_code}`);
        console.log(`  Liczba wariantów: ${product.variants.length}`);

        product.variants.forEach((variant, vIdx) => {
            console.log(`    [Wariant ${vIdx + 1}] ${variant.variant_code}:`, {
                item_id: variant.item_id,
                is_selected: variant.is_selected,
                price_per_m3: variant.price_per_m3,
                volume_m3: variant.volume_m3,
                unit_price_brutto: variant.unit_price_brutto,
                unit_price_netto: variant.unit_price_netto
            });
        });
    });
    console.log('═══════════════════════════════════════════════════\n');

    // Pokaż stan ładowania
    setSaveButtonLoading(true);

    try {
        const response = await fetch(`/quotes/api/quotes/${currentEditingQuoteData.id}/save`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(updatedData)
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || result.details || 'Błąd podczas zapisywania');
        }

        log('editor', '✅ Wycena zapisana pomyślnie:', result);

        // Pokaż sukces
        showToast('Wycena została zaktualizowana', 'success');

        // ✅ POPRAWKA: refreshQuoteModal w quotes.js oczekuje ID (liczby), nie obiektu
        if (result.quote && result.quote.id) {
            await refreshQuoteModal(result.quote.id);
        }

        // ✅ Zamknij edytor po pomyślnym zapisie
        if (window.QuoteEditor && typeof window.QuoteEditor.close === 'function') {
            window.QuoteEditor.close();
        }

    } catch (error) {
        console.error('[QUOTE EDITOR] Błąd zapisu:', error);
        showToast(error.message || 'Wystąpił błąd podczas zapisywania wyceny', 'error');
    } finally {
        // Ukryj stan ładowania
        setSaveButtonLoading(false);
    }
}

function setSaveButtonLoading(isLoading) {
    const saveButton = document.getElementById('save-quote-changes');
    if (!saveButton) return;

    if (isLoading) {
        saveButton.dataset.originalText = saveButton.innerHTML;
        saveButton.disabled = true;
        saveButton.innerHTML = `
            <span class="btn-loading-dots">
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="dot"></span>
            </span>
            Zapisywanie...
        `;
    } else {
        saveButton.disabled = false;
        saveButton.innerHTML = saveButton.dataset.originalText || 'Zapisz zmiany';
    }
}

// ❌ USUNIĘTO: refreshQuoteModal - używamy funkcji z quotes.js
// która pobiera świeże dane z serwera i odświeża modal szczegółów wyceny

function showToast(message, type = 'info') {
    if (typeof window.showToast === 'function') {
        window.showToast(message, type);
        return;
    }

    const icons = {
        'success': '✅',
        'error': '❌',
        'warning': '⚠️',
        'info': 'ℹ️'
    };

    const icon = icons[type] || icons['info'];
    alert(`${icon} ${message}`);
}

/**
 * ✅ POPRAWIONA FUNKCJA - Zbieranie WSZYSTKICH danych do zapisu w bazie
 */
function collectUpdatedQuoteData() {
    try {
        if (!currentEditingQuoteData || !currentEditingQuoteData.items) {
            console.error('[QUOTE EDITOR] Brak danych wyceny');
            return null;
        }

        // Pobierz grupę cenową i mnożnik
        const clientTypeSelect = document.getElementById('edit-clientType');
        const clientType = clientTypeSelect?.value || currentEditingQuoteData.quote_client_type;
        const multiplier = getMultiplierValue(clientType);

        // ===== DANE GŁÓWNE WYCENY (tabela quotes) =====
        const quoteData = {
            quote_id: currentEditingQuoteData.id,
            quote_number: currentEditingQuoteData.quote_number,
            quote_client_type: clientType,
            quote_multiplier: multiplier,
            quote_type: currentEditingQuoteData.quote_type || 'brutto',
            notes: currentEditingQuoteData.notes || null,
            // Dane kuriera - używamy ?? zamiast || żeby zachować wartość 0 jeśli została jawnie ustawiona
            courier_name: currentEditingQuoteData.courier_name ?? null,
            shipping_cost_netto: currentEditingQuoteData.shipping_cost_netto ?? null,
            shipping_cost_brutto: currentEditingQuoteData.shipping_cost_brutto ?? null
        };

        // ===== DANE WSZYSTKICH PRODUKTÓW (tabela quote_items + quote_items_details) =====
        const products = [];

        // Zbierz wszystkie produkty z currentEditingQuoteData.items
        const productIndexes = [...new Set(currentEditingQuoteData.items.map(item => item.product_index))];

        productIndexes.forEach(productIndex => {
            // Znajdź wszystkie warianty dla tego produktu
            const productItems = currentEditingQuoteData.items.filter(item => item.product_index === productIndex);

            if (productItems.length === 0) return;

            // Znajdź wybrany wariant dla tego produktu
            const selectedItem = productItems.find(item => item.is_selected);

            if (!selectedItem) return;

            // Zbierz dane szczegółowe (z tabeli quote_items_details)
            const productDetails = currentEditingQuoteData.details?.find(d => d.product_index === productIndex);

            // ✅ POPRAWKA: Dla aktywnego produktu pobierz świeżą ilość z UI
            let quantity = productDetails?.quantity || 1;
            if (parseInt(productIndex) === activeProductIndex) {
                const quantityInput = document.getElementById('edit-quantity');
                if (quantityInput && quantityInput.value) {
                    quantity = parseInt(quantityInput.value) || 1;
                }
            }

            // Zbierz dane wykończenia
            const finishingData = collectFinishingData(productIndex);

            // Buduj obiekt produktu
            const product = {
                product_index: productIndex,

                // Dane wymiarów i ilości
                length_cm: selectedItem.length_cm,
                width_cm: selectedItem.width_cm,
                thickness_cm: selectedItem.thickness_cm,
                quantity: quantity,

                // Wybrany wariant
                selected_variant: {
                    variant_code: selectedItem.variant_code,
                    item_id: selectedItem.id,
                    // ✅ POPRAWKA: Użyj świeżych obliczeń jeśli dostępne, inaczej wartości z bazy
                    volume_m3: selectedItem.calculated_volume_m3 || selectedItem.volume_m3,
                    price_per_m3: selectedItem.price_per_m3,
                    multiplier: multiplier,
                    unit_price_netto: selectedItem.calculated_price_netto || selectedItem.unit_price_netto || selectedItem.final_price_netto,
                    unit_price_brutto: selectedItem.calculated_price_brutto || selectedItem.unit_price_brutto || selectedItem.final_price_brutto,
                    total_price_netto: selectedItem.calculated_price_netto || selectedItem.final_price_netto,
                    total_price_brutto: selectedItem.calculated_price_brutto || selectedItem.final_price_brutto
                },

                // Wszystkie warianty (dostępność, zaznaczenie i CENY)
                variants: productItems.map(item => {
                    // ✅ POPRAWKA: ZAWSZE przelicz price_per_m3 przez multiplier
                    let freshPricePerM3 = null;

                    // Dla aktywnego produktu - najpierw spróbuj pobrać z UI (jeśli użytkownik zmienił wymiary)
                    if (parseInt(productIndex) === activeProductIndex) {
                        const radio = document.querySelector(`input[name="edit-variantOption"][value="${item.variant_code}"]`);
                        if (radio?.dataset.pricePerM3) {
                            freshPricePerM3 = parseFloat(radio.dataset.pricePerM3);
                        }
                    }

                    // Jeśli nie ma w UI (dla aktywnego) lub to nieaktywny produkt - przelicz bazową cenę
                    if (freshPricePerM3 === null) {
                        const config = window.variantMapping?.[item.variant_code];
                        if (config && window.priceIndex) {
                            const match = getEditorPrice(
                                config.species,
                                config.technology,
                                config.wood_class,
                                item.thickness_cm,
                                item.length_cm
                            );
                            if (match) {
                                // Bazowa cena * multiplier = cena dla grupy cenowej
                                freshPricePerM3 = match.price_per_m3 * multiplier;
                            }
                        }
                    }

                    return {
                        item_id: item.id,
                        variant_code: item.variant_code,
                        is_selected: item.is_selected,
                        show_on_client_page: item.show_on_client_page,
                        length_cm: item.length_cm,
                        width_cm: item.width_cm,
                        thickness_cm: item.thickness_cm,
                        // ✅ POPRAWKA: Użyj przeliczonej ceny per m3
                        price_per_m3: freshPricePerM3 ?? 0,
                        volume_m3: item.calculated_volume_m3 ?? item.volume_m3 ?? 0,
                        unit_price_netto: item.calculated_price_netto ?? item.unit_price_netto ?? item.final_price_netto ?? 0,
                        unit_price_brutto: item.calculated_price_brutto ?? item.unit_price_brutto ?? item.final_price_brutto ?? 0,
                        final_price_netto: item.calculated_price_netto ?? item.final_price_netto ?? 0,
                        final_price_brutto: item.calculated_price_brutto ?? item.final_price_brutto ?? 0
                    };
                }),

                // Wykończenie
                finishing: finishingData
            };

            products.push(product);
        });

        // ===== ZWRÓĆ KOMPLETNE DANE =====
        return {
            quote: quoteData,
            products: products,
            total_products: products.length
        };

    } catch (error) {
        console.error('[QUOTE EDITOR] Błąd zbierania danych:', error);
        console.error('[QUOTE EDITOR] Stack trace:', error.stack);
        return null;
    }
}

/**
 * ✅ NOWA FUNKCJA - Zbieranie danych wykończenia dla produktu
 */
function collectFinishingData(productIndex) {
    try {
        // ✅ POPRAWKA: Sprawdź czy to aktywny produkt - jeśli tak, pobierz dane z UI
        const isActiveProduct = parseInt(productIndex) === activeProductIndex;

        if (isActiveProduct) {
            // Dla aktywnego produktu - pobierz dane z UI i świeże obliczenia
            const uiData = collectFinishingFromUI();

            // ✅ POPRAWKA: Pobierz ceny wykończenia z activeQuoteForm.dataset (zapisane przez saveActiveProductFormData)
            let finishingNetto = 0;
            let finishingBrutto = 0;

            // Sprawdź najpierw w details (zapisane przez saveActiveProductFormData)
            const detailsItem = currentEditingQuoteData.details?.find(d => d.product_index === productIndex);
            if (detailsItem) {
                finishingNetto = detailsItem.finishing_price_netto || 0;
                finishingBrutto = detailsItem.finishing_price_brutto || 0;
            }

            // Jeśli nie ma w details, spróbuj pobrać z activeQuoteForm.dataset
            if (finishingNetto === 0 && finishingBrutto === 0 && window.activeQuoteForm?.dataset) {
                finishingNetto = parseFloat(window.activeQuoteForm.dataset.finishingNetto) || 0;
                finishingBrutto = parseFloat(window.activeQuoteForm.dataset.finishingBrutto) || 0;
            }

            // DEBUG: Log dla aktywnego produktu
            console.log(`[COLLECT FINISHING] Produkt ${productIndex} (AKTYWNY), dane z UI:`, {
                finishing_type: uiData.finishing_type,
                finishing_variant: uiData.finishing_variant,
                finishing_color: uiData.finishing_color,
                finishing_gloss_level: uiData.finishing_gloss_level,
                finishingNetto,
                finishingBrutto
            });

            const result = {
                finishing_type: uiData.finishing_type,
                finishing_variant: uiData.finishing_variant,
                finishing_color: uiData.finishing_color,
                finishing_gloss_level: uiData.finishing_gloss_level,
                finishing_price_netto: finishingNetto,
                finishing_price_brutto: finishingBrutto
            };

            console.log(`[COLLECT FINISHING] Produkt ${productIndex} (AKTYWNY), zwracam:`, result);
            return result;
        }

        // Dla nieaktywnych produktów - użyj zapisanych danych
        const detailsItem = currentEditingQuoteData.details?.find(d => d.product_index === productIndex);

        if (!detailsItem) {
            // Brak zapisanych danych
            console.log(`[COLLECT FINISHING] Produkt ${productIndex} (nieaktywny): Brak detailsItem, zwracam Surowe`);
            return {
                finishing_type: 'Surowe',
                finishing_variant: null,
                finishing_color: null,
                finishing_gloss_level: null,
                finishing_price_netto: 0,
                finishing_price_brutto: 0
            };
        }

        // DEBUG: Log danych z details
        console.log(`[COLLECT FINISHING] Produkt ${productIndex} (nieaktywny), dane z details:`, {
            finishing_type: detailsItem.finishing_type,
            finishing_variant: detailsItem.finishing_variant,
            finishing_color: detailsItem.finishing_color,
            finishing_gloss_level: detailsItem.finishing_gloss_level
        });

        // Zwróć zapisane dane
        const result = {
            finishing_type: detailsItem.finishing_type || 'Surowe',
            finishing_variant: detailsItem.finishing_variant || null,
            finishing_color: detailsItem.finishing_color || null,
            finishing_gloss_level: detailsItem.finishing_gloss_level || null,
            finishing_price_netto: detailsItem.finishing_price_netto || 0,
            finishing_price_brutto: detailsItem.finishing_price_brutto || 0
        };

        console.log(`[COLLECT FINISHING] Produkt ${productIndex} (nieaktywny), zwracam:`, result);
        return result;
    } catch (error) {
        console.error('[QUOTE EDITOR] Błąd zbierania danych wykończenia:', error);
        return {
            finishing_type: 'Surowe',
            finishing_variant: null,
            finishing_color: null,
            finishing_gloss_level: null,
            finishing_price_netto: 0,
            finishing_price_brutto: 0
        };
    }
}

/**
 * ✅ NOWA FUNKCJA - Zbieranie danych wykończenia z UI edytora
 */
function collectFinishingFromUI() {
    const finishingTypeBtn = document.querySelector('#quote-editor-modal .finishing-btn[data-finishing-type].active');
    const finishingVariantBtn = document.querySelector('#quote-editor-modal .finishing-btn[data-finishing-variant].active');
    const finishingColorBtn = document.querySelector('#quote-editor-modal .color-btn.active');
    const finishingGlossBtn = document.querySelector('#quote-editor-modal .finishing-btn[data-finishing-gloss].active');

    return {
        finishing_type: finishingTypeBtn?.dataset.finishingType || 'Surowe',
        finishing_variant: finishingVariantBtn?.dataset.finishingVariant || null,
        finishing_color: finishingColorBtn?.dataset.finishingColor || null,
        finishing_gloss_level: finishingGlossBtn?.dataset.finishingGloss || null,
        finishing_price_netto: 0, // Backend będzie obliczał na podstawie typu
        finishing_price_brutto: 0
    };
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
                        if (finishingColor) {
                            finishing += ` ${finishingColor}`;
                        }
                    }
                }
            }
        }
    } else {
        // Dla nieaktywnych - pobierz wykończenie z danych wyceny
        const finishingData = currentEditingQuoteData?.finishing?.find(f => f.product_index === item.product_index);
        if (finishingData && finishingData.finishing_type) {
            finishing = ` | ${finishingData.finishing_type}`;

            if (finishingData.finishing_type !== 'Surowe' && finishingData.finishing_variant) {
                finishing += ` ${finishingData.finishing_variant}`;

                if (finishingData.finishing_variant === 'Barwne' && finishingData.finishing_color) {
                    finishing += ` ${finishingData.finishing_color}`;
                }
            }
        }
    }

    // Main info: wariant + wymiary + wykończenie + ilość
    const main = `${translatedVariant} • ${dimensions}${finishing} • ${quantity} szt.`;

    // Oblicz objętość i wagę
    const volume = (length * width * thickness * quantity) / 1000000; // cm³ -> m³
    const weight = volume * 800; // kg (gęstość drewna)
    const volumeText = typeof formatVolumeDisplay === 'function' ?
        formatVolumeDisplay(volume) : `${volume.toFixed(3)} m³`;
    const weightText = typeof formatWeightDisplay === 'function' ?
        formatWeightDisplay(weight) : `${weight.toFixed(1)} kg`;

    // Pobierz ceny (wartość całkowita, nie jednostkowa)
    let valueNetto = 0;
    let valueBrutto = 0;

    if (isActiveProduct) {
        // Dla aktywnego produktu - pobierz z activeProductCosts i activeFinishingCosts
        const productCosts = calculateActiveProductCosts();
        const finishingCosts = calculateActiveProductFinishingCosts();

        valueNetto = (productCosts.netto || 0) + (finishingCosts.netto || 0);
        valueBrutto = (productCosts.brutto || 0) + (finishingCosts.brutto || 0);

        console.log('[generateProductDescriptionForQuote] Aktywny produkt - ceny z obliczeń:', {
            productCosts, finishingCosts, valueNetto, valueBrutto
        });
    } else {
        // Dla nieaktywnych - użyj zapisanych wartości
        valueNetto = parseFloat(item.final_price_netto || item.calculated_price_netto || 0);
        valueBrutto = parseFloat(item.final_price_brutto || item.calculated_price_brutto || 0);

        // Dodaj koszt wykończenia jeśli istnieje
        const finishingData = currentEditingQuoteData?.finishing?.find(f => f.product_index === item.product_index);
        if (finishingData) {
            valueNetto += parseFloat(finishingData.finishing_price_netto || 0);
            valueBrutto += parseFloat(finishingData.finishing_price_brutto || 0);
        }

        console.log('[generateProductDescriptionForQuote] Nieaktywny produkt - ceny z danych:', {
            item_netto: item.final_price_netto,
            item_brutto: item.final_price_brutto,
            finishing_netto: finishingData?.finishing_price_netto,
            finishing_brutto: finishingData?.finishing_price_brutto,
            valueNetto, valueBrutto
        });
    }

    // ✅ NOWE: Formatuj ceny (podobnie jak w calculator)
    const priceNettoText = valueNetto > 0 ? `${valueNetto.toFixed(2)} PLN netto` : '0.00 PLN netto';
    const priceBruttoText = valueBrutto > 0 ? `${valueBrutto.toFixed(2)} PLN brutto` : '0.00 PLN brutto';

    // ✅ NOWE: Sub info zawiera teraz: objętość | waga | wartość netto | wartość brutto
    const sub = `${volumeText}  |  ${weightText}  |  ${priceBruttoText}  |  ${priceNettoText}`;

    console.log('[generateProductDescriptionForQuote] Wygenerowany opis z cenami:', {
        main, sub, isActiveProduct, length, width, thickness, quantity, variantCode, finishing,
        valueNetto, valueBrutto
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

    // ✅ DEBUG: Szczegółowy log walidacji (wyłączony - zbyt dużo logów)
    if (DEBUG_LOGS.debug) {
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

    // Znajdź główną sekcję produktów, nie kontener scroll
    const mainSection = document.querySelector('.edit-products-summary-main');
    if (!mainSection) {
        console.error('Nie znaleziono głównej sekcji produktów');
        return;
    }

    // ✅ KLUCZOWA POPRAWKA: Znajdź lub utwórz element podsumowania
    let summaryElement = mainSection.querySelector('.products-total-summary');

    if (totalVolume > 0 || totalWeight > 0) {
        // Jeśli nie ma elementu, utwórz go
        if (!summaryElement) {
            summaryElement = document.createElement('div');
            summaryElement.className = 'products-total-summary';
            summaryElement.innerHTML = `
                <div class="products-total-title">Łączne podsumowanie:</div>
                <div class="products-total-details">
                    <span class="products-total-volume"></span>
                    <span class="products-total-weight"></span>
                </div>
            `;
            // Dodaj na końcu głównej sekcji
            mainSection.appendChild(summaryElement);

            log('editor', '✅ Utworzono nowy element podsumowania');
        }

        // ✅ KLUCZOWA POPRAWKA: Aktualizuj tylko zawartość spanów, nie cały innerHTML
        const volumeSpan = summaryElement.querySelector('.products-total-volume');
        const weightSpan = summaryElement.querySelector('.products-total-weight');

        if (volumeSpan && weightSpan) {
            // Sprawdź czy wartości się zmieniły przed aktualizacją (optymalizacja)
            const newVolumeText = formatVolumeDisplay(totalVolume);
            const newWeightText = formatWeightDisplay(totalWeight);

            if (volumeSpan.textContent !== newVolumeText) {
                volumeSpan.textContent = newVolumeText;
            }

            if (weightSpan.textContent !== newWeightText) {
                weightSpan.textContent = newWeightText;
            }

            log('editor', `✅ Zaktualizowano zawartość podsumowania: ${newVolumeText} | ${newWeightText}`);
        }
    } else {
        // Jeśli brak danych, usuń element jeśli istnieje
        if (summaryElement) {
            summaryElement.remove();
            log('editor', '✅ Usunięto podsumowanie (brak danych)');
        }
    }
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
        if (DEBUG_LOGS.debug) {
            console.log('[checkProductCompletenessForQuote] Brak item');
        }
        return false;
    }

    // ✅ DEBUG: Szczegółowy log walidacji (wyłączony - zbyt dużo logów)
    if (DEBUG_LOGS.debug) {
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
    }

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
        if (!isValid && DEBUG_LOGS.debug) {
            console.log('[checkProductCompletenessForQuote] Brakuje pola:', field);
        }
        return isValid;
    });

    if (DEBUG_LOGS.debug) {
        console.log('[checkProductCompletenessForQuote] Produkt jest kompletny:', isComplete);
    }
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
        { client_type: 'Bazowy', multiplier: 1.0 },
        { client_type: 'Hurt', multiplier: 1.1 },
        { client_type: 'Detal', multiplier: 1.3 },
        { client_type: 'Detal+', multiplier: 1.5 },
        { client_type: 'Czernecki netto', multiplier: 0.935 },
        { client_type: 'Czernecki FV', multiplier: 1.015 }
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

    // ✅ KRYTYCZNA POPRAWKA: Używaj ORYGINALNYCH danych, nie zmodyfikowanych
    // Jeśli mamy zapisaną oryginalną kopię, użyj jej zamiast zmodyfikowanych danych
    const dataSource = window.originalQuoteData || quoteData;
    log('sync', `Używam ${window.originalQuoteData ? 'ORYGINALNYCH' : 'bieżących'} danych do synchronizacji checkboxów`);

    // Znajdź pozycje dla tego produktu
    const productItems = dataSource.items.filter(item => item.product_index === productIndex);

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

    // ✅ USUNIĘTO: Synchronizację wizualnych elementów (.selected)
    // Klasa .selected jest zarządzana przez updateSelectedVariant() podczas kliknięcia w radio button
    // NIE synchronizujemy jej tutaj, bo to powoduje konflikty

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

    // ✅ POPRAWKA: Konwertuj na number od razu
    const multiplierValue = parseFloat(selectedOption.dataset.multiplierValue);
    const clientType = selectedOption.value;

    log('sync', `Zmiana grupy cenowej: ${clientType} (mnożnik: ${multiplierValue})`);

    // ✅ KLUCZOWA POPRAWKA: Aktualizuj zmienne globalne BEZPOŚREDNIO (bez sprawdzania typeof)
    window.currentClientType = clientType;
    window.currentMultiplier = multiplierValue;
    log('sync', `✅ Zaktualizowano window.currentClientType = ${clientType}`);
    log('sync', `✅ Zaktualizowano window.currentMultiplier = ${multiplierValue}`);

    // ✅ Aktualizuj multiplierMapping
    if (window.multiplierMapping) {
        window.multiplierMapping[clientType] = multiplierValue;
        log('sync', `✅ Zaktualizowano multiplierMapping[${clientType}] = ${multiplierValue}`);
    }

    // ✅ Synchronizuj grupę cenową w danych wyceny
    syncClientTypeAcrossAllProducts(clientType, multiplierValue);

    // ✅ POPRAWKA: Wywołaj onFormDataChange() aby przeliczyć ceny i zaktualizować podsumowanie
    setTimeout(() => {
        log('sync', 'Wywołuję onFormDataChange() po zmianie grupy cenowej...');
        onFormDataChange();

        log('sync', '✅ Zakończono aktualizację po zmianie grupy cenowej');
    }, 100);
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
            // ✅ POPRAWKA: Domyślnie wszystkie warianty widoczne (checkboxy włączone)
            // Ukryj tylko jesion-micro-ab i buk-micro-ab
            show_on_client_page: (code === 'buk-micro-ab' || code === 'jes-micro-ab') ? 0 : 1,
            final_price_brutto: 0,
            final_price_netto: 0,
            calculated_price_brutto: 0,
            calculated_price_netto: 0,
            calculated_finishing_brutto: 0,
            calculated_finishing_netto: 0,
            // ✅ WAŻNE: Brak id - oznacza nowy produkt do dodania w bazie
            id: null,
            is_new: true  // Flaga dla backendu
        });
    });

    // ✅ POPRAWKA: Dodaj details dla nowego produktu (ilość, wykończenie)
    currentEditingQuoteData.details = currentEditingQuoteData.details || [];
    currentEditingQuoteData.details.push({
        product_index: newIndex,
        quantity: 1,
        finishing_type: 'Surowe',
        finishing_variant: null,
        finishing_color: null,
        finishing_gloss_level: null,
        finishing_price_brutto: 0,
        finishing_price_netto: 0
    });

    // Ensure finishing array has placeholder for this product (dla kompatybilności wstecznej)
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

    if (!currentEditingQuoteData || !currentEditingQuoteData.items) {
        log('editor', '❌ Brak danych wyceny');
        return;
    }

    // Sprawdź ile produktów jest w wycenie
    const uniqueProducts = getUniqueProductsCount(currentEditingQuoteData.items.filter(item => item.is_selected));

    if (uniqueProducts <= 1) {
        showToast('Nie możesz usunąć ostatniego produktu z wyceny', 'error');
        return;
    }

    if (!confirm('Czy na pewno chcesz usunąć ten produkt?')) return;

    // Usuń wszystkie itemy (warianty) tego produktu
    const itemsToRemove = currentEditingQuoteData.items.filter(
        item => item.product_index === productIndex
    );

    log('editor', `Usuwanie ${itemsToRemove.length} wariantów produktu ${productIndex}`);

    // Usuń itemy z tablicy
    currentEditingQuoteData.items = currentEditingQuoteData.items.filter(
        item => item.product_index !== productIndex
    );

    // Usuń wykończenie jeśli istnieje
    if (currentEditingQuoteData.finishing) {
        currentEditingQuoteData.finishing = currentEditingQuoteData.finishing.filter(
            f => f.product_index !== productIndex
        );
        log('editor', '✅ Usunięto wykończenie produktu');
    }

    log('editor', `✅ Usunięto produkt ${productIndex}`);

    // Znajdź następny produkt do aktywowania
    const remainingProducts = [...new Set(currentEditingQuoteData.items.map(item => item.product_index))];
    const nextProductIndex = remainingProducts.length > 0 ? remainingProducts[0] : null;

    // Odśwież listę produktów
    loadProductsToEditor(currentEditingQuoteData);

    // Aktywuj pierwszy dostępny produkt
    if (nextProductIndex !== null) {
        setTimeout(() => {
            activateProductInEditor(nextProductIndex);
        }, 100);
    }

    // Zaktualizuj podsumowanie
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

        // ✅ POPRAWKA: Pełne czyszczenie danych przy zamykaniu modala
        const modal = document.getElementById('quote-editor-modal');
        if (modal) modal.style.display = 'none';

        // Wyczyść wszystkie dane edytora
        clearEditorData();

        // Reset stanu UI
        resetEditorState();

        log('editor', '✅ Modal zamknięty i dane wyczyszczone');
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