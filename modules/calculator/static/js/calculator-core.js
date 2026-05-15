// calculator-core.js
// Moduł podstawowy kalkulatora - stan globalny, obliczenia cenowe, formatowanie
// Zawiera: zmienne stanu, stałe, przełącznik brutto/netto, indeks cenowy,
// aktualizację cen, podsumowanie globalne, obliczenia objętości i wagi
// ------------------------------
// STAN GLOBALNY I STAŁE
// ------------------------------

const DEBUG = false;  // Wyłączone - zmniejsza ilość logów w konsoli
function dbg(...args) { if (DEBUG) console.log(...args); }

// Komunikaty wysyłki wyświetlane podczas wyceny
const shippingMessages = [
    { text: "Wyceniam wysyłkę, proszę czekać...", delay: 0 },
    { text: "Sprawdzam dostępnych kurierów...", delay: 3000 },
    { text: "Negocjuję najlepszą cenę...", delay: 6000 },
    { text: "Wycena mniejszych produktów trwa zwykle dłużej...", delay: 9000 },
    { text: "Jeszcze chwilka...", delay: 12000 },
    { text: "Już widzę kuriera! 🚚", delay: 15000 },
    { text: "Prawie gotowe...", delay: 18000 }
];

let messageTimeouts = [];
let currentClientType = '';
let currentMultiplier = 1.0;
let mainContainer = null;
let currentPriceMode = 'brutto'; // Domyślny tryb: brutto

// Domyślna grupa cenowa - ID z tabeli multipliers
const DEFAULT_MULTIPLIER_ID = 2;

// ------------------------------
// PRZEŁĄCZNIK BRUTTO/NETTO
// ------------------------------

/**
 * Inicjalizuje przełącznik trybu cen (brutto/netto)
 */
function initPriceModeToggle() {
    const bruttoRadio = document.getElementById('priceModeBrutto');
    const nettoRadio = document.getElementById('priceModeNetto');

    if (!bruttoRadio || !nettoRadio) {
        console.error('[initPriceModeToggle] ❌ Nie znaleziono radio buttonów brutto/netto');
        return;
    }

    // Funkcja przełączania trybu
    function switchPriceMode(mode) {
        currentPriceMode = mode;

        const quoteContainer = document.querySelector('.quote-container');
        const quoteSummary = document.querySelector('.quote-summary');
        const quoteForms = document.querySelector('.quote-forms');
        const containers = [quoteContainer, quoteSummary, quoteForms, document.body].filter(Boolean);

        containers.forEach(container => {
            if (mode === 'brutto') {
                // Tryb BRUTTO = wyróżnij brutto, przyciemnij netto
                container.classList.remove('hide-brutto');
                container.classList.add('hide-netto');
            } else {
                // Tryb NETTO = wyróżnij netto, przyciemnij brutto
                container.classList.remove('hide-netto');
                container.classList.add('hide-brutto');
            }
        });

        updateToggleButtonColors();

        try {
            localStorage.setItem('woodpower_price_mode', mode);
        } catch (e) {
            // Ignore localStorage errors (e.g., private browsing)
        }
    }

    // Funkcja aktualizacji kolorów przycisków
    function updateToggleButtonColors() {
        const bruttoLabel = document.querySelector('label[for="priceModeBrutto"]');
        const nettoLabel = document.querySelector('label[for="priceModeNetto"]');

        if (currentPriceMode === 'brutto') {
            bruttoLabel?.classList.add('toggle-option-active');
            nettoLabel?.classList.remove('toggle-option-active');
        } else {
            bruttoLabel?.classList.remove('toggle-option-active');
            nettoLabel?.classList.add('toggle-option-active');
        }
    }

    // Event listenery
    bruttoRadio.addEventListener('change', function () {
        if (this.checked) {
            switchPriceMode('brutto');
        }
    });

    nettoRadio.addEventListener('change', function () {
        if (this.checked) {
            switchPriceMode('netto');
        }
    });

    // Domyślnie zawsze brutto przy nowej wycenie.
    // Tryb netto jest przywracany tylko przy edycji wyceny lub wczytywaniu draftu.
    bruttoRadio.checked = true;
    switchPriceMode('brutto');

}

/**
 * Pobiera aktualny tryb cen (brutto/netto)
 */
function getCurrentPriceMode() {
    // Zawsze czytaj bezpośrednio z radio buttons jako źródło prawdy
    const nettoRadio = document.getElementById('priceModeNetto');
    const bruttoRadio = document.getElementById('priceModeBrutto');

    if (nettoRadio && nettoRadio.checked) {
        return 'netto';
    } else if (bruttoRadio && bruttoRadio.checked) {
        return 'brutto';
    }

    // Fallback
    return 'brutto';
}

// Eksportuj funkcję globalnie
window.getCurrentPriceMode = getCurrentPriceMode;

// ========================================
// USTAWIENIA KALKULATORA (kształt okrągły)
// ========================================

window._roundShapeSurchargeNetto = 0;

async function loadCalculatorSettings() {
    try {
        const response = await fetch('/calculator/api/calculator-settings');
        if (response.ok) {
            const data = await response.json();
            window._roundShapeSurchargeNetto = data.round_shape_surcharge_netto || 0;
        }
    } catch (e) {
        // Ignore fetch errors for calculator settings
    }
}

// ------------------------------
// MAPOWANIE WARIANTÓW I KRAWĘDZI
// ------------------------------

const variantMapping = {
    'dab-lity-ab': { species: 'Dąb', technology: 'Lity', wood_class: 'A/B' },
    'dab-lity-bb': { species: 'Dąb', technology: 'Lity', wood_class: 'B/B' },
    'dab-micro-ab': { species: 'Dąb', technology: 'Mikrowczep', wood_class: 'A/B' },
    'dab-micro-bb': { species: 'Dąb', technology: 'Mikrowczep', wood_class: 'B/B' },
    'jes-lity-ab': { species: 'Jesion', technology: 'Lity', wood_class: 'A/B' },
    'jes-micro-ab': { species: 'Jesion', technology: 'Mikrowczep', wood_class: 'A/B' },
    'buk-lity-ab': { species: 'Buk', technology: 'Lity', wood_class: 'A/B' },
    'buk-micro-ab': { species: 'Buk', technology: 'Mikrowczep', wood_class: 'A/B' }
};

const edgesList = [
    "top-front", "top-back", "top-left", "top-right",
    "bottom-front", "bottom-back", "bottom-left", "bottom-right",
    "left-front", "left-back", "right-front", "right-back"
];

// ------------------------------
// ZMIENNE STANU
// ------------------------------

let isPartner = false;
let userMultiplier = 1.0;
let multiplierMapping = {};
let pricesFromDatabase = [];
let priceIndex = {};

let quoteFormsContainer = null;
let productSummaryContainer = null;
let activeQuoteForm = null;

let edge3dRoot = null;

let orderSummaryEls = {};
let deliverySummaryEls = {};
let finalSummaryEls = {};
let finishingSummaryEls = {};
let edgesSummaryEls = {};

const shippingPackingMultiplier = 1.3;

// ------------------------------
// FUNKCJE OBLICZENIOWE I FORMATUJĄCE
// ------------------------------

/**
 * Oblicza objętość pojedynczego produktu w m³
 */
function calculateSingleVolume(length, width, thickness) {
    return (length / 100) * (width / 100) * (thickness / 100);
}

/**
 * Zaokrągla wartość do groszy (2 miejsc po przecinku) eliminując błędy float
 */
function roundToGrosze(value) {
    return Math.round((value + Number.EPSILON) * 100) / 100;
}

/**
 * Formatuje liczbę do formatu PLN (z poprawnym zaokrągleniem)
 */
function formatPLN(value) {
    return roundToGrosze(value).toFixed(2) + ' PLN';
}

/**
 * Wylicza globalne limity wymiarów na podstawie cennika.
 * Zwraca obiekt z min/max dla length, width, thickness.
 */
function getPricingLimits() {
    if (!pricesFromDatabase || pricesFromDatabase.length === 0) {
        return null;
    }
    const limits = {
        length_min: Infinity, length_max: -Infinity,
        width_min: Infinity, width_max: -Infinity,
        thickness_min: Infinity, thickness_max: -Infinity
    };
    pricesFromDatabase.forEach(entry => {
        if (entry.length_min < limits.length_min) limits.length_min = entry.length_min;
        if (entry.length_max > limits.length_max) limits.length_max = entry.length_max;
        if (entry.width_min < limits.width_min) limits.width_min = entry.width_min;
        if (entry.width_max > limits.width_max) limits.width_max = entry.width_max;
        if (entry.thickness_min < limits.thickness_min) limits.thickness_min = entry.thickness_min;
        if (entry.thickness_max > limits.thickness_max) limits.thickness_max = entry.thickness_max;
    });
    return limits;
}

/**
 * Wylicza limity wymiarów dla konkretnego wariantu (species + technology + wood_class).
 * Zwraca null jeśli brak danych dla tego wariantu.
 */
function getPricingLimitsForVariant(variantId) {
    var config = variantMapping[variantId];
    if (!config) return null;
    var key = config.species + '::' + config.technology + '::' + config.wood_class;
    var arr = priceIndex[key] || [];
    if (arr.length === 0) return null;
    var limits = {
        length_min: Infinity, length_max: -Infinity,
        width_min: Infinity, width_max: -Infinity,
        thickness_min: Infinity, thickness_max: -Infinity
    };
    arr.forEach(function(entry) {
        if (entry.length_min < limits.length_min) limits.length_min = entry.length_min;
        if (entry.length_max > limits.length_max) limits.length_max = entry.length_max;
        if (entry.width_min < limits.width_min) limits.width_min = entry.width_min;
        if (entry.width_max > limits.width_max) limits.width_max = entry.width_max;
        if (entry.thickness_min < limits.thickness_min) limits.thickness_min = entry.thickness_min;
        if (entry.thickness_max > limits.thickness_max) limits.thickness_max = entry.thickness_max;
    });
    return limits;
}

/**
 * Buduje indeks cenowy (priceIndex) na podstawie pricesFromDatabase
 */
function buildPriceIndex() {
    priceIndex = {};
    pricesFromDatabase.forEach(entry => {
        const key = `${entry.species}::${entry.technology}::${entry.wood_class}`;
        if (!priceIndex[key]) priceIndex[key] = [];
        priceIndex[key].push(entry);
    });
}

/**
 * Pobiera cenę z priceIndex zamiast liniowego .find na całej tablicy
 */
function getPrice(species, technology, wood_class, thickness, length, width) {
    const roundedThickness = Math.ceil(thickness);
    const key = `${species}::${technology}::${wood_class}`;
    const arr = priceIndex[key] || [];
    return arr.find(entry =>
        roundedThickness >= entry.thickness_min &&
        roundedThickness <= entry.thickness_max &&
        length >= entry.length_min &&
        length <= entry.length_max &&
        width >= entry.width_min &&
        width <= entry.width_max
    );
}

// ------------------------------
// PODSUMOWANIE GLOBALNE
// ------------------------------

/**
 * Aktualizuje globalne podsumowanie - suma wszystkich produktów
 */
function updateGlobalSummary() {
    if (!quoteFormsContainer) return;

    // ===================================================================
    // KROK 1: Oblicz sumy ze WSZYSTKICH formularzy
    // ===================================================================
    let sumOrderBrutto = 0;
    let sumOrderNetto = 0;
    let sumFinishingBrutto = 0;
    let sumFinishingNetto = 0;
    let sumEdgesBrutto = 0;
    let sumEdgesNetto = 0;

    const forms = quoteFormsContainer.querySelectorAll('.quote-form');
    forms.forEach(form => {
        const oBr = parseFloat(form.dataset.orderBrutto) || 0;
        const oNt = parseFloat(form.dataset.orderNetto) || 0;
        const fBr = parseFloat(form.dataset.finishingBrutto) || 0;
        const fNt = parseFloat(form.dataset.finishingNetto) || 0;
        const eBr = parseFloat(form.dataset.edgesBrutto) || 0;
        const eNt = parseFloat(form.dataset.edgesNetto) || 0;

        sumOrderBrutto += oBr;
        sumOrderNetto += oNt;
        sumFinishingBrutto += fBr;
        sumFinishingNetto += fNt;
        sumEdgesBrutto += eBr;
        sumEdgesNetto += eNt;
    });

    // ===================================================================
    // KROK 2: Wyświetl SUMĘ produktów surowych w "Koszt surowego"
    // ===================================================================
    orderSummaryEls.brutto.textContent = sumOrderBrutto > 0 ? formatPLN(sumOrderBrutto) : "0.00 PLN";
    orderSummaryEls.netto.textContent = sumOrderNetto > 0 ? formatPLN(sumOrderNetto) : "0.00 PLN";

    // ===================================================================
    // KROK 3: Wyświetl SUMĘ wykończeń w "Koszty wykończenia" (wliczając obróbkę krawędzi!)
    // ===================================================================
    const totalFinishingBrutto = sumFinishingBrutto + sumEdgesBrutto;
    const totalFinishingNetto = sumFinishingNetto + sumEdgesNetto;
    finishingSummaryEls.brutto.textContent = totalFinishingBrutto > 0 ? formatPLN(totalFinishingBrutto) : "0.00 PLN";
    finishingSummaryEls.netto.textContent = totalFinishingNetto > 0 ? formatPLN(totalFinishingNetto) : "0.00 PLN";

    // ===================================================================
    // KROK 4: Odczytaj koszt wysyłki (ustawiony wcześniej przez showDeliveryModal)
    // ===================================================================
    let deliveryBruttoVal = 0;
    let deliveryNettoVal = 0;
    const deliveryBruttoText = deliverySummaryEls.brutto.textContent;
    const deliveryNettoText = deliverySummaryEls.netto.textContent;

    if (deliveryBruttoText.endsWith('PLN')) {
        deliveryBruttoVal = parseFloat(deliveryBruttoText.replace(" PLN", "")) || 0;
    }
    if (deliveryNettoText.endsWith('PLN')) {
        deliveryNettoVal = parseFloat(deliveryNettoText.replace(" PLN", "")) || 0;
    }

    // ===================================================================
    // KROK 5: Oblicz i wyświetl SUMĘ KOŃCOWĄ (z krawędziami!)
    // ===================================================================
    const totalBrutto = sumOrderBrutto + sumFinishingBrutto + sumEdgesBrutto + deliveryBruttoVal;
    const totalNetto = sumOrderNetto + sumFinishingNetto + sumEdgesNetto + deliveryNettoVal;

    finalSummaryEls.brutto.textContent = totalBrutto > 0 ? formatPLN(totalBrutto) : "0.00 PLN";
    finalSummaryEls.netto.textContent = totalNetto > 0 ? formatPLN(totalNetto) : "0.00 PLN";

    // ===================================================================
    // KROK 6: Aktualizuj inne elementy UI
    // ===================================================================
    updateCalculateDeliveryButtonState();
    generateProductsSummary();
}

// ------------------------------
// AKTUALIZACJA CEN
// ------------------------------

/**
 * Aktualizuje ceny jednostkowe i sumaryczne dla aktywnego formularza
 */
function updatePrices() {
    if (!activeQuoteForm) {
        return;
    }

    // DEBUG: Sprawdź który formularz jest aktywny
    const allForms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
    const activeFormIndex = allForms.indexOf(activeQuoteForm);

    const lengthEl = activeQuoteForm.querySelector('input[data-field="length"]');
    const widthEl = activeQuoteForm.querySelector('input[data-field="width"]');
    const thicknessEl = activeQuoteForm.querySelector('input[data-field="thickness"]');
    const quantityEl = activeQuoteForm.querySelector('input[data-field="quantity"]');
    const clientTypeEl = activeQuoteForm.querySelector('select[data-field="clientType"]');
    const variantContainer = activeQuoteForm.querySelector('.variants');

    if (!lengthEl || !widthEl || !thicknessEl || !quantityEl || !variantContainer) {
        return;
    }

    const length = parseFloat(lengthEl.value);
    const width = parseFloat(widthEl.value);
    const thickness = parseFloat(thicknessEl.value);
    let quantity = parseInt(quantityEl.value);

    // Walidacja quantity — pozwalamy na puste pole i 0 (wygoda na telefonie),
    // ale traktujemy jako blad i nie liczymy cen
    if (isNaN(quantity) || quantity < 1) {
        // Nie nadpisujemy wartosci w inpucie — uzytkownik moze kasowac i wpisywac nowa
    }

    const clientType = clientTypeEl ? clientTypeEl.value : "";

    // Walidacja grupy cenowej — tylko jeśli pole było dotknięte
    if (clientTypeEl) {
        if (!clientType && clientTypeEl.dataset.touched === 'true') clientTypeEl.classList.add('error-outline');
        else if (clientType) clientTypeEl.classList.remove('error-outline');
    }

    if (!isPartner && !clientType) {
        showErrorForAllVariants("Brak grupy", variantContainer);
        activeQuoteForm.dataset.orderBrutto = "";
        activeQuoteForm.dataset.orderNetto = "";
        var selectedRadioNoGroup = activeQuoteForm.querySelector('.variants input[type="radio"]:checked');
        _updateCanvasColorForVariant(activeQuoteForm, selectedRadioNoGroup, length, width, thickness);
        updateGlobalSummary();
        return;
    }

    // Szczegółowe komunikaty błędów
    let errorMsg = "";
    const limits = getPricingLimits();
    if (isNaN(length)) errorMsg = "Brak dług.";
    else if (isNaN(width)) errorMsg = "Brak szer.";
    else if (isNaN(thickness)) errorMsg = "Brak grub.";
    else if (isNaN(quantity) || quantity < 1) errorMsg = "Brak ilości";
    else if (limits) {
        var shape = activeQuoteForm.dataset.productShape || 'rectangular';
        if (shape === 'circle') {
            // Koło: średnica musi mieścić się w obu zakresach (length i width)
            var diameterMax = Math.min(limits.length_max, limits.width_max);
            var diameterMin = Math.max(limits.length_min, limits.width_min);
            if (length > diameterMax) errorMsg = "Śr. poza zakr.";
            else if (length < diameterMin) errorMsg = "Śr. poza zakr.";
            else if (thickness < limits.thickness_min || thickness > limits.thickness_max) errorMsg = "Grub. poza zakr.";
        } else {
            if (length < limits.length_min || length > limits.length_max) errorMsg = "Dług. poza zakr.";
            else if (width < limits.width_min || width > limits.width_max) errorMsg = "Szer. poza zakr.";
            else if (thickness < limits.thickness_min || thickness > limits.thickness_max) errorMsg = "Grub. poza zakr.";
        }
    }

    // Podświetlaj puste pola na czerwono TYLKO jeśli były dotknięte przez użytkownika.
    // Nie usuwaj error-outline jeśli wartość przekracza zakres (walidacja z calculator-events).
    const touched = (el) => el && el.dataset.touched === 'true';
    const outOfRange = (el) => el && el.parentNode && el.parentNode.querySelector('.error-message-length, .error-message-width, .error-message-thickness');

    if (lengthEl) {
        if (isNaN(length) && touched(lengthEl)) lengthEl.classList.add('error-outline');
        else if (!isNaN(length) && !outOfRange(lengthEl)) lengthEl.classList.remove('error-outline');
    }
    if (widthEl) {
        if (isNaN(width) && touched(widthEl)) widthEl.classList.add('error-outline');
        else if (!isNaN(width) && !outOfRange(widthEl)) widthEl.classList.remove('error-outline');
    }
    if (thicknessEl) {
        if (isNaN(thickness) && touched(thicknessEl)) thicknessEl.classList.add('error-outline');
        else if (!isNaN(thickness) && !outOfRange(thicknessEl)) thicknessEl.classList.remove('error-outline');
    }
    if (quantityEl) {
        if ((isNaN(quantity) || quantity < 1) && touched(quantityEl)) quantityEl.classList.add('error-outline');
        else if (!isNaN(quantity) && quantity >= 1) quantityEl.classList.remove('error-outline');
    }

    if (errorMsg) {
        showErrorForAllVariants(errorMsg, variantContainer);
        activeQuoteForm.dataset.orderBrutto = "";
        activeQuoteForm.dataset.orderNetto = "";
        activeQuoteForm.dataset.outOfRange = "true";
        activeQuoteForm.dataset.errorMessage = errorMsg;
        // Canvas: sprawdź kolory na podstawie wybranego wariantu
        var selectedRadioEarly = activeQuoteForm.querySelector('.variants input[type="radio"]:checked');
        _updateCanvasColorForVariant(activeQuoteForm, selectedRadioEarly, length, width, thickness);
        updateGlobalSummary();
        return;
    }
    // Wyczyść błąd gdy wymiary poprawne
    delete activeQuoteForm.dataset.errorMessage;

    const singleVolume = calculateSingleVolume(length, width, Math.ceil(thickness));
    // Flexible partner używa selecta, standardowy partner używa userMultiplier
    const isFlexiblePartner = document.body.dataset.flexiblePartner === 'true';

    let multiplier;
    if (isPartner && !isFlexiblePartner) {
        // Standardowy partner - fixed multiplier
        multiplier = userMultiplier;
    } else {
        // Admin/User/Flexible Partner - multiplier z selecta
        multiplier = multiplierMapping[clientType] || 1.0;
    }

    const variantItems = Array.from(variantContainer.children)
        .filter(child => child.querySelector('input[type="radio"]'));

    const tabIndex = Array.from(quoteFormsContainer.querySelectorAll('.quote-form')).indexOf(activeQuoteForm);

    if (tabIndex === -1) {
        console.error("updatePrices: activeQuoteForm nie jest w tablicy formularzy");
        return;
    }

    // Reset kolorów wariantów
    variantItems.forEach(variant => {
        variant.querySelectorAll('*').forEach(el => el.style.color = "");
    });

    // Oblicz ceny dla wszystkich wariantów
    variantItems.forEach(variant => {
        const radio = variant.querySelector('input[type="radio"]');
        if (!radio) return;

        const id = radio.value;
        const config = variantMapping[id];
        if (!config) return;

        const match = getPrice(config.species, config.technology, config.wood_class, thickness, length, width);
        const unitBruttoSpan = variant.querySelector('.unit-brutto');
        const unitNettoSpan = variant.querySelector('.unit-netto');
        const totalBruttoSpan = variant.querySelector('.total-brutto');
        const totalNettoSpan = variant.querySelector('.total-netto');

        if (match && unitBruttoSpan && unitNettoSpan && totalBruttoSpan && totalNettoSpan) {
            const basePrice = match.price_per_m3;
            let effectiveMultiplier = multiplier;
            let unitNetto = singleVolume * basePrice * effectiveMultiplier;

            // Dopłata za kształt okrągły/koło (per sztuka) - po mnożniku
            const productShape = activeQuoteForm.dataset.productShape || 'rectangular';
            if ((productShape === 'round' || productShape === 'circle') && window._roundShapeSurchargeNetto) {
                unitNetto += window._roundShapeSurchargeNetto;
            }

            // Wycięcia — flat koszt per dziura
            const holesCount = parseInt(activeQuoteForm.dataset.shapeHolesCount || '0', 10);
            const cutoutPrice = parseFloat(window.cutoutPriceNetto || '0');
            if (holesCount > 0 && cutoutPrice > 0) {
                unitNetto += holesCount * cutoutPrice;
            }

            variant.style.backgroundColor = "";

            const unitBrutto = roundToGrosze(unitNetto * 1.23);
            const totalNetto = roundToGrosze(unitNetto * quantity);
            const totalBrutto = roundToGrosze(unitBrutto * quantity);

            radio.dataset.totalNetto = totalNetto;
            radio.dataset.totalBrutto = totalBrutto;
            radio.dataset.volumeM3 = singleVolume;
            radio.dataset.pricePerM3 = basePrice;
            radio.dataset.multiplier = effectiveMultiplier;
            radio.dataset.finalPrice = unitNetto;

            unitBruttoSpan.textContent = formatPLN(unitBrutto);
            unitNettoSpan.textContent = formatPLN(unitNetto);
            totalBruttoSpan.textContent = formatPLN(totalBrutto);
            totalNettoSpan.textContent = formatPLN(totalNetto);
        } else {
            // Szczegółowe komunikaty błędów dla brakujących cen
            if (unitBruttoSpan) unitBruttoSpan.textContent = 'Brak ceny';
            if (unitNettoSpan) unitNettoSpan.textContent = 'Brak ceny';
            if (totalBruttoSpan) totalBruttoSpan.textContent = 'Brak ceny';
            if (totalNettoSpan) totalNettoSpan.textContent = 'Brak ceny';

            // Wyczyść dataset żeby stare wartości nie były używane
            delete radio.dataset.totalNetto;
            delete radio.dataset.totalBrutto;
            delete radio.dataset.pricePerM3;
            delete radio.dataset.volumeM3;
            delete radio.dataset.multiplier;
            delete radio.dataset.finalPrice;
        }
    });

    // Znajdź zaznaczony radio button wariantu (pomiń radio kształtu)
    const selectedRadio = activeQuoteForm.querySelector('.variants input[type="radio"]:checked');

    if (selectedRadio && selectedRadio.dataset.totalBrutto && selectedRadio.dataset.totalNetto) {
        activeQuoteForm.dataset.orderBrutto = selectedRadio.dataset.totalBrutto;
        activeQuoteForm.dataset.orderNetto = selectedRadio.dataset.totalNetto;
        delete activeQuoteForm.dataset.outOfRange;

        // Pokoloruj wybrany wariant
        const selectedVariant = selectedRadio.closest('div');
        if (selectedVariant) {
            selectedVariant.querySelectorAll('*').forEach(el => el.style.color = "#ED6B24");
        }

    } else {
        activeQuoteForm.dataset.orderBrutto = "";
        activeQuoteForm.dataset.orderNetto = "";
        // Sprawdź czy jakikolwiek wariant ma cenę
        var anyVariantHasPrice = false;
        activeQuoteForm.querySelectorAll('.variants input[type="radio"]').forEach(function(r) {
            if (r.dataset.totalBrutto && parseFloat(r.dataset.totalBrutto) > 0) anyVariantHasPrice = true;
        });

        if (selectedRadio && !anyVariantHasPrice) {
            // Żaden wariant nie ma ceny — pełny błąd
            activeQuoteForm.dataset.outOfRange = "true";
            activeQuoteForm.dataset.errorMessage = "Wszystkie warianty poza zakresem";
        } else if (selectedRadio) {
            // Wybrany wariant poza zakresem, ale inne mają cenę
            activeQuoteForm.dataset.outOfRange = "true";
            activeQuoteForm.dataset.errorMessage = "Wybrany wariant poza zakresem";
        } else {
            delete activeQuoteForm.dataset.outOfRange;
            delete activeQuoteForm.dataset.errorMessage;
        }
    }

    // Aktualizuj wykończenie i krawędzie
    calculateFinishingCost(activeQuoteForm);

    // Przelicz krawędzie jeśli są zapisane
    if (window.EdgesModule && typeof window.EdgesModule.recalculateEdgesForForm === 'function') {
        window.EdgesModule.recalculateEdgesForForm(activeQuoteForm);
    }

    // Zaktualizuj podgląd SVG krawędzi
    if (window.EdgesModule && typeof window.EdgesModule.updateEdgesPreview === 'function') {
        window.EdgesModule.updateEdgesPreview(activeQuoteForm);
    }

    // ======= Aktualizacja kolorów canvasa na podstawie wybranego wariantu =======
    _updateCanvasColorForVariant(activeQuoteForm, selectedRadio, length, width, thickness);

    updateGlobalSummary();
    updateCalculateDeliveryButtonState();
    generateProductsSummary();

    // Przelicz inne produkty tylko przy zmianie wymiarów
    if (lengthEl.matches(':focus') || widthEl.matches(':focus') || thicknessEl.matches(':focus') || quantityEl.matches(':focus')) {
        updatePricesInOtherProducts();
    }

}

/**
 * Aktualizuje kolor kształtu na canvasie:
 * - czerwony gdy wybrany wariant nie ma ceny (wymiary poza zakresem)
 * - pomarańczowy gdy cena jest ok lub brak wybranego wariantu
 * Dodatkowo koloruje konkretne labele wymiarów bbox na czerwono.
 */
function _updateCanvasColorForVariant(form, selectedRadio, length, width, thickness) {
    var editor = form._shapeEditor;
    if (!editor) return;

    // Brak wybranego wariantu — canvas normalny
    if (!selectedRadio) {
        editor.setColorTheme('normal');
        editor.setOutOfRangeDims({ length: false, width: false });
        return;
    }

    var variantId = selectedRadio.value;
    var variantLimits = getPricingLimitsForVariant(variantId);

    // Brak danych cennikowych — canvas normalny
    if (!variantLimits || isNaN(length) || isNaN(width) || isNaN(thickness)) {
        editor.setColorTheme('normal');
        editor.setOutOfRangeDims({ length: false, width: false });
        return;
    }

    var shape = form.dataset.productShape || 'rectangular';

    // Sprawdź które wymiary są poza zakresem dla wybranego wariantu
    var lengthOut = false;
    var widthOut = false;

    if (shape === 'circle') {
        var diamMax = Math.min(variantLimits.length_max, variantLimits.width_max);
        var diamMin = Math.max(variantLimits.length_min, variantLimits.width_min);
        if (length < diamMin || length > diamMax) {
            lengthOut = true;
            widthOut = true;
        }
    } else {
        if (length < variantLimits.length_min || length > variantLimits.length_max) lengthOut = true;
        if (width < variantLimits.width_min || width > variantLimits.width_max) widthOut = true;
    }

    var thicknessOut = thickness < variantLimits.thickness_min || thickness > variantLimits.thickness_max;

    // Kształt na czerwono jeśli KTÓRYKOLWIEK wymiar poza zakresem
    var anyOutOfRange = lengthOut || widthOut || thicknessOut;
    editor.setColorTheme(anyOutOfRange ? 'error' : 'normal');
    editor.setOutOfRangeDims({ length: lengthOut, width: widthOut });
}

// ========== FUNKCJA TESTOWA ==========

window.testRadioNames = function() {
    const allForms = document.querySelectorAll('.quote-form');
    allForms.forEach((form, formIndex) => {
        const radios = form.querySelectorAll('input[type="radio"]');

        const nameGroups = {};
        radios.forEach(radio => {
            if (!nameGroups[radio.name]) {
                nameGroups[radio.name] = [];
            }
            nameGroups[radio.name].push({
                id: radio.id,
                checked: radio.checked,
                value: radio.value
            });
        });

        Object.entries(nameGroups).forEach(([name, radios]) => {
            const checkedCount = radios.filter(r => r.checked).length;

            if (checkedCount > 1) {
                console.error(`BŁĄD: Więcej niż 1 zaznaczony radio button w grupie ${name}`);
            }
        });
    });
};

// ------------------------------
// OBSŁUGA BŁĘDÓW WARIANTÓW
// ------------------------------

/**
 * Pokazuje komunikat błędu we wszystkich wariantach
 */
function showErrorForAllVariants(errorMsg, variantContainer) {
    const variantItems = Array.from(variantContainer.children)
        .filter(child => child.querySelector('input[type="radio"]'));
    variantItems.forEach(variant => {
        ['.unit-brutto', '.unit-netto', '.total-brutto', '.total-netto'].forEach(sel => {
            const span = variant.querySelector(sel);
            if (span) span.textContent = errorMsg;
        });
    });
}

/**
 * Przelicza ceny we wszystkich produktach oprócz aktywnego
 */
function updatePricesInOtherProducts() {
    if (!quoteFormsContainer) return;

    const allForms = quoteFormsContainer.querySelectorAll('.quote-form');
    const originalActiveForm = activeQuoteForm;
    const originalActiveFormIndex = Array.from(allForms).indexOf(originalActiveForm);

    allForms.forEach((form, formIndex) => {
        if (form === originalActiveForm) return; // Pomiń aktywny formularz

        // Sprawdź czy produkt ma wypełnione wymiary
        const length = form.querySelector('[data-field="length"]')?.value;
        const width = form.querySelector('[data-field="width"]')?.value;
        const thickness = form.querySelector('[data-field="thickness"]')?.value;

        if (length && width && thickness) {
            // Tymczasowo ustaw jako aktywny dla obliczeń
            activeQuoteForm = form;

            // Wywołaj główną część updatePrices dla tego formularza
            const lengthEl = form.querySelector('input[data-field="length"]');
            const widthEl = form.querySelector('input[data-field="width"]');
            const thicknessEl = form.querySelector('input[data-field="thickness"]');
            const quantityEl = form.querySelector('input[data-field="quantity"]');
            const clientTypeEl = form.querySelector('select[data-field="clientType"]');
            const variantContainer = form.querySelector('.variants');

            if (lengthEl && widthEl && thicknessEl && quantityEl && variantContainer) {
                const length = parseFloat(lengthEl.value);
                const width = parseFloat(widthEl.value);
                const thickness = parseFloat(thicknessEl.value);
                let quantity = parseInt(quantityEl.value) || 1;
                const clientType = clientTypeEl ? clientTypeEl.value : "";

                if (!isNaN(length) && !isNaN(width) && !isNaN(thickness) && (isPartner || clientType)) {
                    const singleVolume = calculateSingleVolume(length, width, Math.ceil(thickness));
                    let multiplier = isPartner ? userMultiplier : (multiplierMapping[clientType] || 1.0);

                    const variantItems = Array.from(variantContainer.children)
                        .filter(child => child.querySelector('input[type="radio"]'));

                    // Używaj variantMapping zamiast split
                    variantItems.forEach(variant => {
                        const radio = variant.querySelector('input[type="radio"]');
                        if (!radio) return;

                        const id = radio.value;
                        const config = variantMapping[id]; // Używaj mapowania!
                        if (!config) return;

                        const match = getPrice(config.species, config.technology, config.wood_class, thickness, length, width);

                        if (match) {
                            const basePrice = match.price_per_m3;

                            // Użyj mnożnika z wybranej grupy cenowej (bez automatycznej zmiany na Detal+)
                            const effectiveMultiplier = multiplier;
                            let unitNetto = singleVolume * basePrice * effectiveMultiplier;

                            // Dopłata za kształt okrągły/koło
                            const otherProductShape = form.dataset.productShape || 'rectangular';
                            if ((otherProductShape === 'round' || otherProductShape === 'circle') && window._roundShapeSurchargeNetto) {
                                unitNetto += window._roundShapeSurchargeNetto;
                            }

                            // Wycięcia — flat koszt per dziura
                            const holesCount2 = parseInt(form.dataset.shapeHolesCount || '0', 10);
                            const cutoutPrice2 = parseFloat(window.cutoutPriceNetto || '0');
                            if (holesCount2 > 0 && cutoutPrice2 > 0) {
                                unitNetto += holesCount2 * cutoutPrice2;
                            }

                            // Wyczyść kolor tła (usunięto starą regułę Detal+)
                            variant.style.backgroundColor = "";

                            const unitBrutto = roundToGrosze(unitNetto * 1.23);
                            const totalNetto = roundToGrosze(unitNetto * quantity);
                            const totalBrutto = roundToGrosze(unitBrutto * quantity);

                            radio.dataset.totalNetto = totalNetto;
                            radio.dataset.totalBrutto = totalBrutto;
                            radio.dataset.volumeM3 = singleVolume;
                            radio.dataset.pricePerM3 = basePrice;

                            const unitBruttoSpan = variant.querySelector('.unit-brutto');
                            const unitNettoSpan = variant.querySelector('.unit-netto');
                            const totalBruttoSpan = variant.querySelector('.total-brutto');
                            const totalNettoSpan = variant.querySelector('.total-netto');

                            if (unitBruttoSpan) unitBruttoSpan.textContent = formatPLN(unitBrutto);
                            if (unitNettoSpan) unitNettoSpan.textContent = formatPLN(unitNetto);
                            if (totalBruttoSpan) totalBruttoSpan.textContent = formatPLN(totalBrutto);
                            if (totalNettoSpan) totalNettoSpan.textContent = formatPLN(totalNetto);
                        } else {
                            // Brak ceny - wyczyść dataset i pokaż błąd
                            const unitBruttoSpan = variant.querySelector('.unit-brutto');
                            const unitNettoSpan = variant.querySelector('.unit-netto');
                            const totalBruttoSpan = variant.querySelector('.total-brutto');
                            const totalNettoSpan = variant.querySelector('.total-netto');

                            if (unitBruttoSpan) unitBruttoSpan.textContent = 'Brak ceny';
                            if (unitNettoSpan) unitNettoSpan.textContent = 'Brak ceny';
                            if (totalBruttoSpan) totalBruttoSpan.textContent = 'Brak ceny';
                            if (totalNettoSpan) totalNettoSpan.textContent = 'Brak ceny';

                            delete radio.dataset.totalNetto;
                            delete radio.dataset.totalBrutto;
                            delete radio.dataset.pricePerM3;
                            delete radio.dataset.volumeM3;
                        }
                    });

                    // Zaktualizuj dataset jeśli jest wybrana opcja
                    const tabIndex = Array.from(quoteFormsContainer.querySelectorAll('.quote-form')).indexOf(form);
                    const selectedRadio = form.querySelector(`input[name="variant-product-${tabIndex}-selected"]:checked`);
                    if (selectedRadio && selectedRadio.dataset.totalBrutto && selectedRadio.dataset.totalNetto) {
                        form.dataset.orderBrutto = selectedRadio.dataset.totalBrutto;
                        form.dataset.orderNetto = selectedRadio.dataset.totalNetto;
                        delete form.dataset.outOfRange;
                    } else if (selectedRadio) {
                        form.dataset.orderBrutto = "";
                        form.dataset.orderNetto = "";
                        form.dataset.outOfRange = "true";
                    }
                }
            }
        }
    });

    // Przywróć oryginalny aktywny formularz
    activeQuoteForm = originalActiveForm;

}

// ------------------------------
// RESET CEN WARIANTÓW
// ------------------------------

/**
 * Resetuje ceny wariantów w formularzu (przy błędach walidacji)
 */
function resetVariantPrices(form, missingField = 'długości') {
    if (!form) return;

    const displayMessage = `Brak ${missingField}`;

    form.querySelectorAll('.variant-option').forEach(option => {
        const unitBrutto = option.querySelector('.unit-brutto');
        const unitNetto = option.querySelector('.unit-netto');
        const totalBrutto = option.querySelector('.total-brutto');
        const totalNetto = option.querySelector('.total-netto');

        if (unitBrutto) unitBrutto.textContent = displayMessage;
        if (unitNetto) unitNetto.textContent = displayMessage;
        if (totalBrutto) totalBrutto.textContent = displayMessage;
        if (totalNetto) totalNetto.textContent = displayMessage;
    });

    // Resetuj dataset
    form.dataset.orderBrutto = '';
    form.dataset.orderNetto = '';
}

// ------------------------------
// DANE ZAGREGOWANE DLA WYSYŁKI
// ------------------------------

/**
 * Oblicza zagregowane dane do wyceny wysyłki
 */
function computeAggregatedData() {
    const forms = quoteFormsContainer.querySelectorAll('.quote-form');
    if (forms.length === 0) {
        console.error("Brak formularzy .quote-form");
        return null;
    }

    let maxLength = 0;
    let maxWidth = 0;
    let totalThickness = 0;
    let totalWeight = 0;

    forms.forEach(form => {
        const lengthVal = parseFloat(form.querySelector('input[data-field="length"]').value) || 0;
        const widthVal = parseFloat(form.querySelector('input[data-field="width"]').value) || 0;
        const thicknessVal = parseFloat(form.querySelector('input[data-field="thickness"]').value) || 0;
        const quantityVal = parseInt(form.querySelector('input[data-field="quantity"]').value) || 1;

        if (lengthVal > maxLength) maxLength = lengthVal;
        if (widthVal > maxWidth) maxWidth = widthVal;

        totalThickness += thicknessVal * quantityVal;
        // Realna objętość i waga (przez calculateProductVolume/Weight)
        totalWeight += calculateProductWeight(form);
    });

    const aggregatedLength = maxLength + 5;
    const aggregatedWidth = maxWidth + 5;
    const aggregatedThickness = totalThickness + 5;

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

// ------------------------------
// OBLICZENIA OBJĘTOŚCI I WAGI
// ------------------------------

/**
 * Oblicza realną objętość produktu (uwzględnia kształt)
 * Dla nie-prostokątnych kształtów używa realnego pola z ShapeEditor
 */
function calculateProductVolume(form) {
    const length = parseFloat(form.querySelector('[data-field="length"]')?.value) || 0;
    const width = parseFloat(form.querySelector('[data-field="width"]')?.value) || 0;
    const thickness = parseFloat(form.querySelector('[data-field="thickness"]')?.value) || 0;
    const quantity = parseInt(form.querySelector('[data-field="quantity"]')?.value) || 1;

    if (thickness <= 0) return 0;

    const productShape = form.dataset.productShape || 'rectangular';

    // Nie-prostokątne kształty: pole NETTO (po odjęciu wycięć) — waga/objętość odzwierciedlają fizyczny produkt
    if (productShape !== 'rectangular') {
        const netAreaCm2 = parseFloat(form.dataset.shapeNetAreaCm2);
        const realAreaCm2 = parseFloat(form.dataset.shapeRealAreaCm2);
        const effectiveCm2 = !isNaN(netAreaCm2) && netAreaCm2 > 0 ? netAreaCm2 : realAreaCm2;
        if (!isNaN(effectiveCm2) && effectiveCm2 > 0) {
            return (effectiveCm2 / 10000) * (thickness / 100) * quantity;
        }
    }

    // Rectangular: jeśli są dziury — użyj net z dataset
    const netRect = parseFloat(form.dataset.shapeNetAreaCm2);
    if (!isNaN(netRect) && netRect > 0 && parseInt(form.dataset.shapeHolesCount || '0', 10) > 0) {
        return (netRect / 10000) * (thickness / 100) * quantity;
    }
    if (length <= 0 || width <= 0) return 0;
    return calculateSingleVolume(length, width, thickness) * quantity;
}

/**
 * Oblicza wagę produktu (gęstość drewna: 800 kg/m³)
 * Używa realnej objętości (nie bbox)
 */
function calculateProductWeight(form) {
    const volume = calculateProductVolume(form);
    return volume * 800;
}

/**
 * Formatuje objętość do czytelnego formatu
 */
function formatVolume(volume) {
    if (volume === 0) return "0.000 m³";
    return volume.toFixed(3) + " m³";
}

/**
 * Formatuje wagę do czytelnego formatu (kg lub tony)
 */
function formatWeight(weight) {
    if (weight === 0) return "0.0 kg";
    if (weight >= 1000) {
        return (weight / 1000).toFixed(2) + " t";
    }
    return weight.toFixed(1) + " kg";
}

/**
 * Oblicza łączną objętość i wagę wszystkich produktów
 */
function calculateTotalVolumeAndWeight() {
    const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
    let totalVolume = 0;
    let totalWeight = 0;

    forms.forEach(form => {
        const isComplete = checkProductCompleteness(form);
        if (isComplete) {
            totalVolume += calculateProductVolume(form);
            totalWeight += calculateProductWeight(form);
        }
    });

    return { totalVolume, totalWeight };
}

// ==============================
// EKSPORT MODUŁU
// ==============================

window.CalculatorCore = {
    // Zmienne stanu (gettery/settery dla współdzielonego stanu)
    get DEBUG() { return DEBUG; },
    get isPartner() { return isPartner; },
    set isPartner(val) { isPartner = val; },
    get userMultiplier() { return userMultiplier; },
    set userMultiplier(val) { userMultiplier = val; },
    get multiplierMapping() { return multiplierMapping; },
    set multiplierMapping(val) { multiplierMapping = val; },
    get pricesFromDatabase() { return pricesFromDatabase; },
    set pricesFromDatabase(val) { pricesFromDatabase = val; },
    get priceIndex() { return priceIndex; },
    get quoteFormsContainer() { return quoteFormsContainer; },
    set quoteFormsContainer(val) { quoteFormsContainer = val; },
    get productSummaryContainer() { return productSummaryContainer; },
    set productSummaryContainer(val) { productSummaryContainer = val; },
    get activeQuoteForm() { return activeQuoteForm; },
    set activeQuoteForm(val) { activeQuoteForm = val; },
    get edge3dRoot() { return edge3dRoot; },
    set edge3dRoot(val) { edge3dRoot = val; },
    get currentClientType() { return currentClientType; },
    set currentClientType(val) { currentClientType = val; },
    get currentMultiplier() { return currentMultiplier; },
    set currentMultiplier(val) { currentMultiplier = val; },
    get mainContainer() { return mainContainer; },
    set mainContainer(val) { mainContainer = val; },
    get currentPriceMode() { return currentPriceMode; },
    orderSummaryEls,
    deliverySummaryEls,
    finalSummaryEls,
    finishingSummaryEls,
    edgesSummaryEls,
    shippingPackingMultiplier,
    variantMapping,
    edgesList,
    DEFAULT_MULTIPLIER_ID,
    dbg,
    initPriceModeToggle,
    getCurrentPriceMode,
    loadCalculatorSettings,
    calculateSingleVolume,
    roundToGrosze,
    formatPLN,
    buildPriceIndex,
    getPricingLimits,
    getPrice,
    updateGlobalSummary,
    updatePrices,
    showErrorForAllVariants,
    updatePricesInOtherProducts,
    resetVariantPrices,
    computeAggregatedData,
    calculateProductVolume,
    calculateProductWeight,
    formatVolume,
    formatWeight,
    calculateTotalVolumeAndWeight
};
