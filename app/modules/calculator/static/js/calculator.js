// calculator.js
console.log("calculator.js załadowany!");

// ------------------------------
// GLOBAL STATE & CACHING SETUP
// ------------------------------

const DEBUG = true;
function dbg(...args) { if (DEBUG) console.log(...args); }

// Dodaj na początku pliku
const shippingMessages = [
    { text: "Wyceniam wysyłkę, proszę czekać...", delay: 0 },
    { text: "Sprawdzam dostępnych kurierów...", delay: 3000 },
    { text: "Wycena mniejszych produktów trwa zwykle dłużej...", delay: 6000 },
    { text: "Jeszcze chwilka...", delay: 9000 },
    { text: "Już widzę kuriera! 🚚", delay: 12000 },
    { text: "Negocjuję najlepszą cenę...", delay: 15000 },
    { text: "Prawie gotowe...", delay: 18000 }
];

let messageTimeouts = [];
let currentClientType = '';
let currentMultiplier = 1.0;
let mainContainer = null;

// Domyślna grupa cenowa - ID z tabeli multipliers
const DEFAULT_MULTIPLIER_ID = 2;

// Pobieranie cen wykończeń z bazy danych
async function loadFinishingPrices() {
    try {
        console.log('[CALCULATOR] Ładowanie cen wykończenia z bazy danych...');

        const response = await fetch('/calculator/api/finishing-prices');
        if (response.ok) {
            const prices = await response.json();
            window.finishingPrices = {};

            prices.forEach(price => {
                window.finishingPrices[price.name] = parseFloat(price.price_netto);
            });

            console.log('[CALCULATOR] ✅ Załadowano ceny wykończeń z bazy danych:', window.finishingPrices);
        } else {
            throw new Error(`HTTP ${response.status}`);
        }
    } catch (error) {
        console.error('[CALCULATOR] ❌ Błąd pobierania cen wykończeń z bazy, używam domyślnych:', error);

        // Fallback - domyślne ceny
        window.finishingPrices = {
            'Surowe': 0,
            'Lakierowane bezbarwne': 200,
            'Lakierowane barwne': 250,
            'Olejowanie': 250
        };

        console.log('[CALCULATOR] Używam domyślnych cen wykończeń:', window.finishingPrices);
    }
}
function toggleTheme() {
    document.documentElement.toggleAttribute('data-theme', 'dark');
}

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

// Zmodyfikowana funkcja calculateDelivery
async function calculateDelivery() {
    dbg("Przycisk 'Oblicz wysyłkę' kliknięty");
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

    try {
        const response = await fetch('/calculator/shipping_quote', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(shippingParams)
        });

        if (response.ok) {
            const quotesData = await response.json();
            const quotesList = Array.isArray(quotesData) ? quotesData : [quotesData];
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

            dbg("Otrzymane wyceny wysyłki:", quotes);

            if (quotes.length === 0) {
                showDeliveryErrorModal("Brak dostępnych metod dostawy.");
            } else {
                // ✅ DODAJ packingInfo:
                const packingInfo = {
                    multiplier: shippingPackingMultiplier,
                    message: `Do cen wysyłki została doliczona kwota ${Math.round((shippingPackingMultiplier - 1) * 100)}% na pakowanie.`
                };
                showDeliveryModal(quotes, packingInfo);
            }
        } else {
            console.error("Błąd w żądaniu wyceny wysyłki:", response.status);
            showDeliveryErrorModal("Błąd serwera przy wycenie wysyłki.");
        }
    } catch (error) {
        console.error("Wyjątek przy wycenie wysyłki:", error);
        showDeliveryErrorModal("Błąd sieci przy wycenie wysyłki.");
    } finally {
        stopRotatingMessages();
        if (overlay) {
            overlay.style.display = 'none';
        }
    }
}

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

const shippingPackingMultiplier = 1.3;

/**
 * Oblicza objętość pojedynczego produktu w m³
 */
function calculateSingleVolume(length, width, thickness) {
    return (length / 100) * (width / 100) * (thickness / 100);
}

/**
 * Formatuje liczbę do formatu PLN
 */
function formatPLN(value) {
    return value.toFixed(2) + ' PLN';
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
function getPrice(species, technology, wood_class, thickness, length) {
    const roundedThickness = Math.ceil(thickness);
    const key = `${species}::${technology}::${wood_class}`;
    const arr = priceIndex[key] || [];
    return arr.find(entry =>
        roundedThickness >= entry.thickness_min &&
        roundedThickness <= entry.thickness_max &&
        length >= entry.length_min &&
        length <= entry.length_max
    );
}

/**
 * Aktualizuje globalne podsumowanie oraz pojedynczy koszt aktywnego formularza
 */
function updateGlobalSummary() {

    if (!quoteFormsContainer) return;

    // 1) Pokaż w "Koszt surowego" i "Koszty wykończenia" dane tylko dla activeQuoteForm
    if (activeQuoteForm) {
        // Surowy z activeQuoteForm
        const orderBruttoVal = parseFloat(activeQuoteForm.dataset.orderBrutto) || 0;
        const orderNettoVal = parseFloat(activeQuoteForm.dataset.orderNetto) || 0;
        orderSummaryEls.brutto.textContent = orderBruttoVal ? formatPLN(orderBruttoVal) : "0.00 PLN";
        orderSummaryEls.netto.textContent = orderNettoVal ? formatPLN(orderNettoVal) : "0.00 PLN";

        // Wykończenie dla activeQuoteForm
        const finBruttoVal = parseFloat(activeQuoteForm.dataset.finishingBrutto) || 0;
        const finNettoVal = parseFloat(activeQuoteForm.dataset.finishingNetto) || 0;
        finishingSummaryEls.brutto.textContent = finBruttoVal ? formatPLN(finBruttoVal) : "0.00 PLN";
        finishingSummaryEls.netto.textContent = finNettoVal ? formatPLN(finNettoVal) : "0.00 PLN";
    } else {
        // Jeśli nie ma aktywnego, pokaż puste / domyślne
        orderSummaryEls.brutto.textContent = "0.00 PLN";
        orderSummaryEls.netto.textContent = "0.00 PLN";
        finishingSummaryEls.brutto.textContent = "0.00 PLN";
        finishingSummaryEls.netto.textContent = "0.00 PLN";
    }

    // 2) Oblicz sumę globalną: surowy + wykończenie ze wszystkich formularzy
    let sumOrderBrutto = 0;
    let sumOrderNetto = 0;
    let sumFinishingBrutto = 0;
    let sumFinishingNetto = 0;

    const forms = quoteFormsContainer.querySelectorAll('.quote-form');
    forms.forEach(form => {
        const oBr = parseFloat(form.dataset.orderBrutto) || 0;
        const oNt = parseFloat(form.dataset.orderNetto) || 0;
        const fBr = parseFloat(form.dataset.finishingBrutto) || 0;
        const fNt = parseFloat(form.dataset.finishingNetto) || 0;
        sumOrderBrutto += oBr;
        sumOrderNetto += oNt;
        sumFinishingBrutto += fBr;
        sumFinishingNetto += fNt;
    });

    // 3) Teraz odczytaj koszt kuriera (delivery) – zakładamy, że został ustawiony w DOM przez showDeliveryModal
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

    // 4) Wstaw do sekcji "Koszt wysyłki" nazwę i wartości brutto/netto (jeżeli nie wyliczone, zostaw poprzedni tekst)
    //    (zakładamy, że deliverySummaryEls.courier, .brutto i .netto już wcześniej wypełniono przez showDeliveryModal / showDeliveryErrorModal)

    // 5) W sekcji „Suma” zsumuj:
    //    SUMA_BRUTTO = sumOrderBrutto + sumFinishingBrutto + deliveryBruttoVal
    //    SUMA_NETTO  = sumOrderNetto  + sumFinishingNetto  + deliveryNettoVal
    const totalBrutto = sumOrderBrutto + sumFinishingBrutto + deliveryBruttoVal;
    const totalNetto = sumOrderNetto + sumFinishingNetto + deliveryNettoVal;
    finalSummaryEls.brutto.textContent = (totalBrutto > 0) ? formatPLN(totalBrutto) : "0.00 PLN";
    finalSummaryEls.netto.textContent = (totalNetto > 0) ? formatPLN(totalNetto) : "0.00 PLN";

    updateCalculateDeliveryButtonState();
    generateProductsSummary();
}


/**
 * Znajdź nazwę grupy cenowej na podstawie ID z bazy danych
 */
function getDefaultClientTypeForId(targetId) {
    console.log(`[getDefaultClientTypeForId] Szukam grupy cenowej dla ID: ${targetId}`);

    // KROK 1: Sprawdź czy mamy dostęp do danych multipliers z DOM
    const multipliersDataEl = document.getElementById('multipliers-data');
    if (multipliersDataEl) {
        try {
            const multipliersFromDB = JSON.parse(multipliersDataEl.textContent);
            const defaultGroup = multipliersFromDB.find(m => m.id === targetId);

            if (defaultGroup) {
                console.log(`[getDefaultClientTypeForId] ✅ Znaleziono grupę: ${defaultGroup.label} (ID: ${defaultGroup.id})`);
                return defaultGroup.label;
            } else {
                console.warn(`[getDefaultClientTypeForId] ❌ Nie znaleziono grupy o ID ${targetId} w danych z DOM`);
            }
        } catch (e) {
            console.warn(`[getDefaultClientTypeForId] Błąd parsowania danych multipliers:`, e);
        }
    } else {
        console.warn(`[getDefaultClientTypeForId] Brak elementu #multipliers-data w DOM`);
    }

    // KROK 2: Fallback - sprawdź w globalnym multiplierMapping
    // ❌ PROBLEM: multiplierMapping nie zawiera ID, więc nie możemy dopasować po ID
    // Zamiast tego zwracamy null, żeby nie ustawiać błędnej grupy
    console.warn(`[getDefaultClientTypeForId] ❌ Brak dostępu do ID grup w multiplierMapping - zwracam null`);
    return null;
}

/**
 * Ustaw domyślną grupę cenową w formularzu
 */
function setDefaultClientType(form, skipIfAlreadySet = true) {
    if (!form) return;

    const clientTypeSelect = form.querySelector('select[data-field="clientType"]');
    if (!clientTypeSelect) return;

    // Jeśli grupa już jest ustawiona i skipIfAlreadySet=true, nie zmieniaj
    if (skipIfAlreadySet && clientTypeSelect.value) {
        console.log(`[setDefaultClientType] Grupa już ustawiona: ${clientTypeSelect.value}, pomijam`);
        return;
    }

    // ✅ ZMIENIONE: Różnicuj standardowych i flexible partnerów
    const isFlexiblePartner = document.body.dataset.flexiblePartner === 'true';

    // Standardowi partnerzy nie używają selecta (mają fixed multiplier)
    if (isPartner && !isFlexiblePartner) {
        console.log(`[setDefaultClientType] Standardowy Partner - pomijam ustawienie domyślnej grupy`);
        return;
    }

    // ✅ NOWE: Różny domyślny mnożnik dla flexible partners
    const FLEXIBLE_PARTNER_DEFAULT_MULTIPLIER_ID = 5;  // Domyślny mnożnik dla flexible partners

    let defaultMultiplierId;
    if (isFlexiblePartner) {
        defaultMultiplierId = FLEXIBLE_PARTNER_DEFAULT_MULTIPLIER_ID;
        console.log(`[setDefaultClientType] Flexible Partner - używam mnożnika ID: ${defaultMultiplierId}`);
    } else {
        defaultMultiplierId = DEFAULT_MULTIPLIER_ID;
        console.log(`[setDefaultClientType] Admin/User - używam mnożnika ID: ${defaultMultiplierId}`);
    }

    const defaultClientType = getDefaultClientTypeForId(defaultMultiplierId);

    if (defaultClientType && multiplierMapping[defaultClientType]) {
        clientTypeSelect.value = defaultClientType;
        console.log(`[setDefaultClientType] Ustawiono domyślną grupę cenową: ${defaultClientType}`);
    } else {
        console.warn(`[setDefaultClientType] Nie można ustawić domyślnej grupy cenowej dla ID: ${defaultMultiplierId}`);
    }
}


/**
 * Aktualizuje ceny jednostkowe i sumaryczne dla aktywnego formularza
 */
function updatePrices() {
    dbg("updatePrices: start");

    if (!activeQuoteForm) {
        console.warn("updatePrices: Brak aktywnego formularza");
        return;
    }

    const lengthEl = activeQuoteForm.querySelector('input[data-field="length"]');
    const widthEl = activeQuoteForm.querySelector('input[data-field="width"]');
    const thicknessEl = activeQuoteForm.querySelector('input[data-field="thickness"]');
    const quantityEl = activeQuoteForm.querySelector('input[data-field="quantity"]');
    const clientTypeEl = activeQuoteForm.querySelector('select[data-field="clientType"]');
    const variantContainer = activeQuoteForm.querySelector('.variants');

    if (!lengthEl || !widthEl || !thicknessEl || !quantityEl || !variantContainer) {
        console.warn("updatePrices: Brak wymaganych elementów w formularzu");
        return;
    }

    const length = parseFloat(lengthEl.value);
    const width = parseFloat(widthEl.value);
    const thickness = parseFloat(thicknessEl.value);
    let quantity = parseInt(quantityEl.value);

    // ✅ ZACHOWAJ: Walidacja quantity
    if (isNaN(quantity) || quantity < 1) {
        quantity = 1;
        quantityEl.value = 1;
    }

    const clientType = clientTypeEl ? clientTypeEl.value : "";

    // ✅ ZACHOWAJ: Walidacja grupy cenowej z error-outline
    if (clientTypeEl) {
        if (!clientType) clientTypeEl.classList.add('error-outline');
        else clientTypeEl.classList.remove('error-outline');
    }

    if (!isPartner && !clientType) {
        showErrorForAllVariants("Brak grupy", variantContainer);
        activeQuoteForm.dataset.orderBrutto = "";
        activeQuoteForm.dataset.orderNetto = "";
        updateGlobalSummary();
        return;
    }

    // ✅ ZACHOWAJ: Szczegółowe komunikaty błędów
    let errorMsg = "";
    if (isNaN(length)) errorMsg = "Brak dług.";
    else if (isNaN(width)) errorMsg = "Brak szer.";
    else if (isNaN(thickness)) errorMsg = "Brak grub.";

    // ✅ ZACHOWAJ: Dodawanie error-outline do poszczególnych pól
    if (lengthEl) {
        if (isNaN(length)) lengthEl.classList.add('error-outline');
        else lengthEl.classList.remove('error-outline');
    }
    if (widthEl) {
        if (isNaN(width)) widthEl.classList.add('error-outline');
        else widthEl.classList.remove('error-outline');
    }
    if (thicknessEl) {
        if (isNaN(thickness)) thicknessEl.classList.add('error-outline');
        else thicknessEl.classList.remove('error-outline');
    }
    if (quantityEl) {
        if (isNaN(quantity)) quantityEl.classList.add('error-outline');
        else quantityEl.classList.remove('error-outline');
    }

    if (errorMsg) {
        showErrorForAllVariants(errorMsg, variantContainer);
        activeQuoteForm.dataset.orderBrutto = "";
        activeQuoteForm.dataset.orderNetto = "";
        updateGlobalSummary();
        return;
    }

    const singleVolume = calculateSingleVolume(length, width, Math.ceil(thickness));
    // ✅ POPRAWIONE: Flexible partner używa selecta, standardowy partner używa userMultiplier
    const isFlexiblePartner = document.body.dataset.flexiblePartner === 'true';

    let multiplier;
    if (isPartner && !isFlexiblePartner) {
        // Standardowy partner - fixed multiplier
        multiplier = userMultiplier;
    } else {
        // Admin/User/Flexible Partner - multiplier z selecta
        multiplier = multiplierMapping[clientType] || 1.0;
    }

    dbg("updatePrices: dimensions and multiplier", {
        length, width, thickness, quantity, singleVolume, multiplier, clientType
    });

    const variantItems = Array.from(variantContainer.children)
        .filter(child => child.querySelector('input[type="radio"]'));

    const tabIndex = Array.from(quoteFormsContainer.querySelectorAll('.quote-form')).indexOf(activeQuoteForm);
    dbg("updatePrices: tabIndex", tabIndex);

    if (tabIndex === -1) {
        console.error("updatePrices: activeQuoteForm nie jest w tablicy formularzy");
        return;
    }

    // ✅ ZACHOWAJ: Reset kolorów wariantów
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

        dbg("Processing variant:", id, config);

        const match = getPrice(config.species, config.technology, config.wood_class, thickness, length);
        const unitBruttoSpan = variant.querySelector('.unit-brutto');
        const unitNettoSpan = variant.querySelector('.unit-netto');
        const totalBruttoSpan = variant.querySelector('.total-brutto');
        const totalNettoSpan = variant.querySelector('.total-netto');

        if (match && unitBruttoSpan && unitNettoSpan && totalBruttoSpan && totalNettoSpan) {
            const basePrice = match.price_per_m3;
            dbg("→ obliczenia:", { basePrice, singleVolume, multiplier });

            let effectiveMultiplier = multiplier;
            let unitNetto = singleVolume * basePrice * effectiveMultiplier;

            variant.style.backgroundColor = "";

            const unitBrutto = unitNetto * 1.23;
            const totalNetto = unitNetto * quantity;
            const totalBrutto = unitBrutto * quantity;

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
            // ✅ ZACHOWAJ: Szczegółowe komunikaty błędów dla brakujących cen
            if (unitBruttoSpan) unitBruttoSpan.textContent = 'Brak ceny';
            if (unitNettoSpan) unitNettoSpan.textContent = 'Brak ceny';
            if (totalBruttoSpan) totalBruttoSpan.textContent = 'Brak ceny';
            if (totalNettoSpan) totalNettoSpan.textContent = 'Brak ceny';
        }
    });

    // ✅ POPRAWKA: Znajdź zaznaczony radio button BEZ zmiany nazw
    // Używamy prostego selektora :checked zamiast manipulacji nazwami
    const selectedRadio = activeQuoteForm.querySelector('input[type="radio"]:checked');

    if (selectedRadio && selectedRadio.dataset.totalBrutto && selectedRadio.dataset.totalNetto) {
        activeQuoteForm.dataset.orderBrutto = selectedRadio.dataset.totalBrutto;
        activeQuoteForm.dataset.orderNetto = selectedRadio.dataset.totalNetto;

        // Pokoloruj wybrany wariant
        const selectedVariant = selectedRadio.closest('div');
        if (selectedVariant) {
            selectedVariant.querySelectorAll('*').forEach(el => el.style.color = "#ED6B24");
        }

        console.log(`[updatePrices] Zaznaczony wariant w produkcie ${tabIndex + 1}: ${selectedRadio.value}`);
    } else {
        activeQuoteForm.dataset.orderBrutto = "";
        activeQuoteForm.dataset.orderNetto = "";
        console.log(`[updatePrices] Brak zaznaczonego wariantu w produkcie ${tabIndex + 1}`);
    }

    // Aktualizuj wykończenie i podsumowania
    calculateFinishingCost(activeQuoteForm);
    updateGlobalSummary();
    updateCalculateDeliveryButtonState();
    generateProductsSummary();

    // ✅ ZACHOWAJ: Przelicz inne produkty tylko przy zmianie wymiarów
    if (lengthEl.matches(':focus') || widthEl.matches(':focus') || thicknessEl.matches(':focus') || quantityEl.matches(':focus')) {
        updatePricesInOtherProducts();
    }

    dbg("← updatePrices end");
}

// ========== FUNKCJA TESTOWA ==========

window.testRadioNames = function() {
    console.log("\n🧪 TEST NAZW RADIO BUTTONS PO updatePrices:");
    
    const allForms = document.querySelectorAll('.quote-form');
    allForms.forEach((form, formIndex) => {
        console.log(`\n--- FORMULARZ ${formIndex + 1} ---`);
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
            console.log(`Name: ${name} - ${radios.length} radio buttons, ${checkedCount} zaznaczone`);
            
            if (checkedCount > 1) {
                console.error(`❌ BŁĄD: Więcej niż 1 zaznaczony radio button w grupie ${name}`);
            }
        });
    });
};

console.log("✅ Poprawiona funkcja updatePrices została załadowana!");
console.log("Dostępne funkcje testowe:");
console.log("- testRadioNames() - sprawdza nazwy radio buttons po updatePrices");

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

function updatePricesInOtherProducts() {
    if (!quoteFormsContainer) return;
    
    const allForms = quoteFormsContainer.querySelectorAll('.quote-form');
    const originalActiveForm = activeQuoteForm;
    
    allForms.forEach(form => {
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

                    // ✅ POPRAWKA: Używaj variantMapping zamiast split
                    variantItems.forEach(variant => {
                        const radio = variant.querySelector('input[type="radio"]');
                        if (!radio) return;

                        const id = radio.value;
                        const config = variantMapping[id]; // ✅ UŻYWAJ mapowania!
                        if (!config) return;

                        const match = getPrice(config.species, config.technology, config.wood_class, thickness, length);
                        
                        if (match) {
                            const basePrice = match.price_per_m3; // ✅ UŻYWAJ price_per_m3
                            let effectiveMultiplier = multiplier;
                            let unitNetto = singleVolume * basePrice * effectiveMultiplier;

                            if (!isPartner && clientType === "Detal" && unitNetto < 1000) {
                                effectiveMultiplier = 1.5;
                                unitNetto = singleVolume * basePrice * effectiveMultiplier;
                                variant.style.backgroundColor = "#FFECEC";
                            } else {
                                variant.style.backgroundColor = "";
                            }

                            const unitBrutto = unitNetto * 1.23;
                            const totalNetto = unitNetto * quantity;
                            const totalBrutto = unitBrutto * quantity;

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
                        }
                    });

                    // Zaktualizuj dataset jeśli jest wybrana opcja
                    const tabIndex = Array.from(quoteFormsContainer.querySelectorAll('.quote-form')).indexOf(form);
                    const selectedRadio = form.querySelector(`input[name="variant-product-${tabIndex}-selected"]:checked`);
                    if (selectedRadio && selectedRadio.dataset.totalBrutto && selectedRadio.dataset.totalNetto) {
                        form.dataset.orderBrutto = selectedRadio.dataset.totalBrutto;
                        form.dataset.orderNetto = selectedRadio.dataset.totalNetto;
                    }
                }
            }
        }
    });
    
    // Przywróć oryginalny aktywny formularz
    activeQuoteForm = originalActiveForm;
    
    console.log('✅ Przeliczono ceny we wszystkich produktach');
}

// POPRAWKA 2: Napraw attachFinishingUIListeners - unikalne ID dla każdego produktu
function attachFinishingUIListeners(form) {
    if (!form) return;
    
    const formIndex = Array.from(quoteFormsContainer.children).indexOf(form);
    
    const typeButtons = form.querySelectorAll('.finishing-btn[data-finishing-type]');
    const variantButtons = form.querySelectorAll('.finishing-btn[data-finishing-variant]');
    const glossButtons = form.querySelectorAll('.finishing-btn[data-finishing-gloss]');
    const colorButtons = form.querySelectorAll('.color-btn[data-finishing-color]');
    
    const variantWrapper = form.querySelector(`#finishing-variant-wrapper-${formIndex}`) || 
                          form.querySelector('#finishing-variant-wrapper');
    const glossWrapper = form.querySelector(`#finishing-gloss-wrapper-${formIndex}`) || 
                        form.querySelector('#finishing-gloss-wrapper');
    const colorWrapper = form.querySelector(`#finishing-color-wrapper-${formIndex}`) || 
                        form.querySelector('#finishing-color-wrapper');

    // ❌ PROBLEM: Te zmienne są ustawiane tylko raz na początku
    // let currentType = form.querySelector('.finishing-btn[data-finishing-type].active')?.dataset.finishingType || 'Surowe';
    // let currentVariant = form.querySelector('.finishing-btn[data-finishing-variant].active')?.dataset.finishingVariant || 'Surowe';

    const resetButtons = buttons => buttons.forEach(btn => btn.classList.remove('active'));
    const show = el => { if (el) el.style.display = 'flex'; };
    const hide = el => { if (el) el.style.display = 'none'; };

    function updateVisibility() {
        const currentType = form.querySelector('.finishing-btn[data-finishing-type].active')?.dataset.finishingType || 'Surowe';
        const currentVariant = form.querySelector('.finishing-btn[data-finishing-variant].active')?.dataset.finishingVariant || 'Surowe';

        console.log('[updateVisibility] currentType:', currentType, 'currentVariant:', currentVariant);

        if (currentType === 'Surowe') {
            hide(variantWrapper);
            hide(colorWrapper);
            return;
        }

        if (currentType === 'Olejowanie') {
            hide(variantWrapper);
            hide(colorWrapper);
            return;
        }

        if (currentType === 'Lakierowanie') {
            show(variantWrapper);

            if (currentVariant === 'Barwne') {
                show(colorWrapper);
            } else {
                hide(colorWrapper);
            }
        }
    }

    typeButtons.forEach(btn => {
        // Usuń poprzednie listenery specyficzne dla tego formularza
        btn.removeEventListener('click', btn._formSpecificHandler);
        
        btn._formSpecificHandler = () => {
            console.log('[typeButton clicked]', btn.dataset.finishingType);
            resetButtons(typeButtons);
            btn.classList.add('active');
            // ❌ USUNIĘTE: currentType = btn.dataset.finishingType;
            updateVisibility(); // ✅ POPRAWKA: updateVisibility pobierze aktualną wartość
            calculateFinishingCost(form);
            generateProductsSummary();
        };
        
        btn.addEventListener('click', btn._formSpecificHandler);
    });

    variantButtons.forEach(btn => {
        btn.removeEventListener('click', btn._formSpecificHandler);
        
        btn._formSpecificHandler = () => {
            console.log('[variantButton clicked]', btn.dataset.finishingVariant);
            resetButtons(variantButtons);
            btn.classList.add('active');
            // ❌ USUNIĘTE: currentVariant = btn.dataset.finishingVariant;
            updateVisibility(); // ✅ POPRAWKA: updateVisibility pobierze aktualną wartość
            calculateFinishingCost(form);
            generateProductsSummary();
        };
        
        btn.addEventListener('click', btn._formSpecificHandler);
    });

    glossButtons.forEach(btn => {
        btn.removeEventListener('click', btn._formSpecificHandler);
        
        btn._formSpecificHandler = () => {
            console.log('[glossButton clicked]', btn.dataset.finishingGloss);
            resetButtons(glossButtons);
            btn.classList.add('active');
            generateProductsSummary();
        };
        
        btn.addEventListener('click', btn._formSpecificHandler);
    });

    colorButtons.forEach(btn => {
        btn.removeEventListener('click', btn._formSpecificHandler);
        
        btn._formSpecificHandler = () => {
            console.log('[colorButton clicked]', btn.dataset.finishingColor);
            resetButtons(colorButtons);
            btn.classList.add('active');
            generateProductsSummary();
        };
        
        btn.addEventListener('click', btn._formSpecificHandler);
    });

    // Wywołaj updateVisibility na początku, żeby ustawić prawidłowy stan
    updateVisibility();
}

// POPRAWKA 5: Napraw calculateFinishingCost - usuń globalne ID
function calculateFinishingCost(form) {
    dbg("🧪 calculateFinishingCost start:", form?.id || 'brak ID');

    if (!form) return { netto: null, brutto: null };

    // Pobierz wybrane wykończenie
    const finishingTypeBtn = form.querySelector('.finishing-btn.active[data-finishing-type]');
    const finishingVariantBtn = form.querySelector('.finishing-btn.active[data-finishing-variant]');

    const finishingType = finishingTypeBtn ? finishingTypeBtn.dataset.finishingType : 'Surowe';
    const finishingVariant = finishingVariantBtn ? finishingVariantBtn.dataset.finishingVariant : null;

    // Pobierz elementy input
    const lengthInput = form.querySelector('input[data-field="length"]');
    const widthInput = form.querySelector('input[data-field="width"]');
    const thicknessInput = form.querySelector('input[data-field="thickness"]');
    const quantityInput = form.querySelector('input[data-field="quantity"]');

    // Znajdź elementy do wyświetlania kosztów
    let finishingBruttoEl = form.querySelector('.finishing-brutto') || document.getElementById('finishing-brutto');
    let finishingNettoEl = form.querySelector('.finishing-netto') || document.getElementById('finishing-netto');

    // Jeśli surowe - zwróć 0
    if (finishingType === 'Surowe') {
        form.dataset.finishingBrutto = 0;
        form.dataset.finishingNetto = 0;
        if (finishingBruttoEl) finishingBruttoEl.textContent = '0.00 PLN';
        if (finishingNettoEl) finishingNettoEl.textContent = '0.00 PLN';
        updateGlobalSummary();
        dbg("🧪 calculateFinishingCost end: surowe");
        return { netto: 0, brutto: 0 };
    }

    // Walidacja wymiarów
    if (!lengthInput?.value || !widthInput?.value || !thicknessInput?.value) {
        dbg("🧪 calculateFinishingCost end: brak wymiarów");
        return { netto: null, brutto: null };
    }

    const lengthVal = parseFloat(lengthInput.value);
    const widthVal = parseFloat(widthInput.value);
    const thicknessVal = parseFloat(thicknessInput.value);
    const quantityVal = parseInt(quantityInput.value) || 1;

    // POPRAWIONE OBLICZENIE POWIERZCHNI:
    // Wymiary są już w cm, konwertujemy na metry
    const lengthM = lengthVal / 100;     // cm → m
    const widthM = widthVal / 100;       // cm → m
    const thicknessM = thicknessVal / 100; // cm → m

    // Powierzchnia wszystkich ścian sześcianu w m²
    const surfaceAreaPerPieceM2 = 2 * (lengthM * widthM + lengthM * thicknessM + widthM * thicknessM);
    const totalSurfaceAreaM2 = surfaceAreaPerPieceM2 * quantityVal;

    dbg("🧪 Obliczenia powierzchni:", {
        "Wymiary [cm]": `${lengthVal}×${widthVal}×${thicknessVal}`,
        "Wymiary [m]": `${lengthM.toFixed(3)}×${widthM.toFixed(3)}×${thicknessM.toFixed(3)}`,
        "Powierzchnia 1 szt [m²]": surfaceAreaPerPieceM2.toFixed(4),
        "Ilość": quantityVal,
        "Całkowita powierzchnia [m²]": totalSurfaceAreaM2.toFixed(4)
    });

    // Pobierz cenę z bazy danych (używa window.finishingPrices załadowanego przez loadFinishingPrices())
    let pricePerM2 = 0;

    if (finishingType === 'Lakierowanie' && finishingVariant === 'Bezbarwne') {
        pricePerM2 = window.finishingPrices?.['Lakierowane bezbarwne'] || 200;
    } else if (finishingType === 'Lakierowanie' && finishingVariant === 'Barwne') {
        pricePerM2 = window.finishingPrices?.['Lakierowane barwne'] || 250;
    } else if (finishingType === 'Olejowanie') {
        pricePerM2 = window.finishingPrices?.['Olejowanie'] || 250;
    }

    dbg("🧪 Cena wykończenia:", {
        "Typ": finishingType,
        "Wariant": finishingVariant,
        "Cena za m² [PLN netto]": pricePerM2
    });

    // Oblicz końcowe koszty
    const finishingPriceNetto = Math.round(totalSurfaceAreaM2 * pricePerM2 * 100) / 100;
    const finishingPriceBrutto = Math.round(finishingPriceNetto * 1.23 * 100) / 100;

    // Zapisz w dataset formularza
    form.dataset.finishingBrutto = finishingPriceBrutto;
    form.dataset.finishingNetto = finishingPriceNetto;

    // Aktualizuj wyświetlanie
    if (finishingBruttoEl) finishingBruttoEl.textContent = finishingPriceBrutto.toFixed(2) + ' PLN';
    if (finishingNettoEl) finishingNettoEl.textContent = finishingPriceNetto.toFixed(2) + ' PLN';

    // Odśwież globalne podsumowanie
    updateGlobalSummary();
    generateProductsSummary();

    dbg("🧪 calculateFinishingCost end:", {
        finishingPriceNetto,
        finishingPriceBrutto,
        "powierzchnia_m2": totalSurfaceAreaM2.toFixed(4),
        "cena_za_m2": pricePerM2
    });

    return { netto: finishingPriceNetto, brutto: finishingPriceBrutto };
}

/**
 * Aktualizuje stan przycisków "Oblicz wysyłkę" i "Zapisz wycenę"
 */
function updateCalculateDeliveryButtonState() {
    const allComplete = areAllProductsComplete();
    
    const calcDeliveryBtn = document.querySelector('.calculate-delivery');
    const saveQuoteBtn = document.querySelector('.save-quote');

    [calcDeliveryBtn, saveQuoteBtn].forEach(btn => {
        if (!btn) return;
        if (!allComplete) {
            btn.classList.add('btn-disabled');
            btn.disabled = true;
        } else {
            btn.classList.remove('btn-disabled');
            btn.disabled = false;
        }
    });
}

/**
 * Dodaje listener dla wykończenia (inputy + kliknięcia)
 */
function attachFinishingListenersToForm(form) {
    if (!form) return;
    const inputs = form.querySelectorAll(
        'input[data-field="length"], input[data-field="width"], input[data-field="thickness"], input[data-field="quantity"]'
    );
    inputs.forEach(input => {
        input.addEventListener('input', () => calculateFinishingCost(form));
    });

    form.querySelectorAll('.finishing-btn').forEach(btn => {
        btn.addEventListener('click', () => calculateFinishingCost(form));
    });
}

function attachFormListeners(form) {
    if (!form) return;

    console.log(`[attachFormListeners] Dodaję listenery dla formularza`);

    // ✅ NOWA POPRAWKA: Zachowaj aktualną grupę cenową przed dodaniem listeners
    const currentClientType = form.querySelector('select[data-field="clientType"]')?.value;

    // POPRAWNE ROZWIĄZANIE - bez klonowania
    const inputs = form.querySelectorAll('input[data-field], select[data-field]');
    inputs.forEach(input => {
        // Usuń poprzednie listenery bezpośrednio
        input.removeEventListener('input', updatePrices);
        input.removeEventListener('change', updatePrices);

        // Dodaj nowe listenery
        if (input.matches('input[data-field]')) {
            input.addEventListener('input', updatePrices);
        } else if (input.matches('select[data-field]')) {
            input.addEventListener('change', updatePrices);
        }

        // DEBUG: Sprawdź wartość grupy cenowej
        if (input.matches('select[data-field="clientType"]')) {
            console.log(`[attachFormListeners] Grupa cenowa w formularzu: ${input.value}`);
        }
    });

    // ✅ POPRAWKA: Dodaj listenery dla radio buttons z obsługą klasy 'selected'
    attachVariantSelectionListeners(form);

    // Oznacz formularz jako mający event listenery
    form.dataset.listenersAttached = "true";

    // Dodaj obsługę wykończenia
    attachFinishingUIListeners(form);

    // Na końcu funkcji, PRZYWRÓĆ grupę cenową jeśli została przypadkowo zresetowana
    if (currentClientType && !isPartner) {
        const clientTypeSelect = form.querySelector('select[data-field="clientType"]');
        if (clientTypeSelect && clientTypeSelect.value !== currentClientType) {
            clientTypeSelect.value = currentClientType;
            console.log(`[attachFormListeners] Przywrócono grupę cenową: ${currentClientType}`);
        }
    }
}
function syncClientTypeAcrossProducts(selectedType, sourceForm) {
    console.log(`[syncClientType] Synchronizuję grupę ${selectedType} na wszystkich produktach`);

    // Zaktualizuj zmienne globalne
    currentClientType = selectedType;
    currentMultiplier = multiplierMapping[selectedType] || 1.0;

    // ✅ ZACHOWAJ stany przed synchronizacją
    const allForms = quoteFormsContainer.querySelectorAll('.quote-form');
    const preservedStates = [];

    allForms.forEach((form, index) => {
        const checkedRadios = [];
        form.querySelectorAll('.variants input[type="radio"]:checked').forEach(radio => {
            checkedRadios.push({
                value: radio.value,
                totalBrutto: radio.dataset.totalBrutto,
                totalNetto: radio.dataset.totalNetto
            });
        });

        preservedStates.push({
            form: form,
            index: index,
            checkedRadios: checkedRadios
        });
    });

    allForms.forEach(form => {
        if (form === sourceForm) return; // Pomiń formularz źródłowy

        const select = form.querySelector('select[data-field="clientType"]');
        if (select && select.value !== selectedType) {
            select.value = selectedType;
            console.log(`[syncClientType] Zaktualizowano select w formularzu:`, form);
        }
    });

    // Przelicz ceny z zachowaniem aktywnego formularza
    const originalActiveForm = activeQuoteForm;

    allForms.forEach(form => {
        activeQuoteForm = form;
        updatePrices();
    });

    activeQuoteForm = originalActiveForm;

    // ✅ PRZYWRÓĆ stany po przeliczeniu - POPRAWIONE
    preservedStates.forEach(state => {
        state.checkedRadios.forEach(radioData => {
            const radio = state.form.querySelector(`input[value="${radioData.value}"]`);
            if (radio) {
                // ✅ POPRAWKA: NIE zmieniaj name - zostaw oryginalną wartość
                radio.checked = true;

                // Przywróć dataset jeśli się zgadza
                if (radioData.totalBrutto && radioData.totalNetto) {
                    state.form.dataset.orderBrutto = radioData.totalBrutto;
                    state.form.dataset.orderNetto = radioData.totalNetto;
                }

                // Przywróć kolor
                const selectedVariant = radio.closest('div');
                if (selectedVariant) {
                    selectedVariant.querySelectorAll('*').forEach(el => el.style.color = "#ED6B24");
                }
            }
        });
    });

    // ✅ POPRAWKA: Napraw klasy 'selected' po synchronizacji
    setTimeout(() => {
        fixSelectedClasses();
    }, 100);

    console.log('✅ Zsynchronizowano grupę cenową z zachowaniem selekcji');
}

function handleClientTypeChange(event) {
    const selectedType = event.target.value;
    const sourceForm = event.target.closest('.quote-form');
    
    console.log(`🔄 Zmieniono grupę cenową na: ${selectedType}`);
    
    // Synchronizuj z innymi produktami
    syncClientTypeAcrossProducts(selectedType, sourceForm);
}

function areAllProductsComplete() {
    const allForms = quoteFormsContainer.querySelectorAll('.quote-form');
    
    for (let form of allForms) {
        if (!checkProductCompleteness(form)) {
            return false;
        }
    }
    
    return allForms.length > 0; // Musi być przynajmniej jeden produkt
}

/**
 * Przygotowuje klonowany formularz (ustawia ID, name, resetuje wartości)
 */
function prepareNewProductForm(form, index) {
    if (!form) return;

    console.log(`[prepareNewProductForm] Przygotowuję formularz dla produktu ${index + 1}`);

    // KROK 1: Zachowaj aktualną grupę cenową PRZED resetowaniem
    const currentClientType = form.querySelector('select[data-field="clientType"]')?.value;
    console.log(`[prepareNewProductForm] Zachowuję grupę cenową: ${currentClientType}`);

    // KROK 2: POPRAWKA - Unikalne ID i name dla radio buttons wariantów
    form.querySelectorAll('.variants input[type="radio"]').forEach((radio, radioIndex) => {
        const baseId = radio.value || `variant-${radioIndex}`;

        // ✅ POPRAWKA: Ustaw poprawne ID i name
        const newId = `${baseId}-product-${index}`;
        const newName = `variant-product-${index}`;  // ✅ Konsistentna nazwa
        const oldId = radio.id;

        console.log(`[prepareNewProductForm] Radio ${radioIndex + 1}: ${oldId} → ${newId}, name: ${radio.name} → ${newName}`);

        // Ustaw nowe ID i name
        radio.id = newId;
        radio.name = newName;
        radio.checked = false; // Reset zaznaczenia

        // ✅ POPRAWKA: Aktualizuj powiązany label
        const label = form.querySelector(`label[for="${oldId}"]`);
        if (label) {
            label.setAttribute('for', newId);
            console.log(`[prepareNewProductForm] Zaktualizowano label: ${oldId} → ${newId}`);
        }
    });

    // KROK 3: Resetuj wszystkie inputy wymiarów
    form.querySelectorAll('input[data-field]').forEach(input => {
        // Ustaw wartość 1 dla ilości, pozostawiając pozostałe pola puste
        input.value = input.dataset.field === 'quantity' ? '1' : '';
    });

    // KROK 4: Resetuj selecty ale ZACHOWAJ grupę cenową
    form.querySelectorAll('select[data-field]').forEach(select => {
        if (select.dataset.field === 'clientType') {
            if (currentClientType) {
                // Przywróć istniejącą grupę cenową
                select.value = currentClientType;
                console.log(`[prepareNewProductForm] Przywrócono grupę cenową: ${currentClientType}`);
            } else {
                // Ustaw domyślną grupę cenową dla nowych produktów
                setDefaultClientType(form, false); // false = ustaw nawet jeśli puste
            }
        } else {
            select.selectedIndex = 0;
        }
    });

    // KROK 5: Resetuj stan wykończenia
    form.querySelectorAll('.finishing-btn.active').forEach(btn => {
        btn.classList.remove('active');
    });

    // Ustaw domyślne wykończenie "Surowe"
    const defaultFinishing = form.querySelector('.finishing-btn[data-finishing-type="Surowe"]');
    if (defaultFinishing) {
        defaultFinishing.classList.add('active');
        console.log(`[prepareNewProductForm] Ustawiono domyślne wykończenie: Surowe`);
    }

    // KROK 6: Ukryj sekcje wykończenia
    const finishingWrapper = form.querySelector('.finishing-wrapper');
    if (finishingWrapper) {
        finishingWrapper.style.display = 'none';
    }

    // Ukryj sekcje kolorów i połysków
    const colorSection = form.querySelector('.color-section');
    const glossSection = form.querySelector('.gloss-section');
    if (colorSection) colorSection.style.display = 'none';
    if (glossSection) glossSection.style.display = 'none';

    // ✅ KLUCZOWA POPRAWKA: Resetuj klasy 'selected' z wariantów w nowym formularzu
    form.querySelectorAll('.variant-option').forEach(option => {
        option.classList.remove('selected');
    });
    console.log(`[prepareNewProductForm] ✅ Zresetowano klasy 'selected' w nowym formularzu`);

    // ✅ NOWA POPRAWKA: Resetuj wyświetlane ceny w wariantach
    form.querySelectorAll('.variant-option').forEach(option => {
        // Resetuj ceny jednostkowe
        const unitBrutto = option.querySelector('.unit-brutto');
        const unitNetto = option.querySelector('.unit-netto');
        const totalBrutto = option.querySelector('.total-brutto');
        const totalNetto = option.querySelector('.total-netto');

        if (unitBrutto) unitBrutto.textContent = 'Brak dług.';
        if (unitNetto) unitNetto.textContent = 'Brak dług.';
        if (totalBrutto) totalBrutto.textContent = 'Brak dług.';
        if (totalNetto) totalNetto.textContent = 'Brak dług.';
    });

    // ✅ Resetuj dataset formularza (ceny, dane)
    form.dataset.orderBrutto = '';
    form.dataset.orderNetto = '';
    form.dataset.finishingType = 'Surowe';
    form.dataset.finishingBrutto = '';
    form.dataset.finishingNetto = '';

    // ✅ Resetuj kolory wariantów
    form.querySelectorAll('.variant-option').forEach(option => {
        option.style.backgroundColor = '';
        option.querySelectorAll('*').forEach(el => {
            el.style.color = '';
        });
    });

    // ✅ Usuń oznaczenie o dodanych event listenerach
    delete form.dataset.listenersAttached;

    console.log(`[prepareNewProductForm] ✅ Formularz produktu ${index + 1} został przygotowany i zresetowany`);
}

// DODAJ także nową funkcję resetującą ceny (do użycia przy błędach walidacji)
function resetVariantPrices(form, missingField = 'długości') {
    if (!form) return;

    console.log(`[resetVariantPrices] Resetuję ceny w formularzu - brak: ${missingField}`);

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


/**
 * Toggles visibility of the angle column in the edge3d table
 */
function toggleAngleColumn(show) {
    const table = document.getElementById('edge3d-table');
    if (!table) return;
    const headerCell = table.querySelector('.edge3d-header .edge3d-cell:nth-child(4)');
    if (headerCell) headerCell.style.visibility = show ? 'visible' : 'hidden';
}

/**
 * Delegation: highlight edge in 3D and update edgeSettings on input change
 */
function onEdgeInputChange(e) {
    const input = e.target;
    const row = input.closest('.edge3d-row');
    if (!row) return;
    const key = row.querySelector('.edge3d-cell').textContent.trim();
    console.log(`→ onEdgeInputChange — key="${key}", value="${input.value}"`);

    if (typeof window.highlightEdge === 'function') {
        window.highlightEdge(key, '#ED6B24', 2);
    }

    window.edgeSettings[key] = window.edgeSettings[key] || {};
    window.edgeSettings[key].value = parseFloat(input.value) || 0;

    const dims = {
        length: parseFloat(document.querySelector('input[data-field="length"]').value) || 0,
        width: parseFloat(document.querySelector('input[data-field="width"]').value) || 0,
        height: parseFloat(document.querySelector('input[data-field="thickness"]').value) || 0
    };

    maybeRender3D(dims, window.edgeSettings);
}

/**
 * Delegation: ustaw typ obróbki krawędzi i renderuj ponownie
 */
function onTypeButtonClick(e) {
    const btn = e.currentTarget;
    const key = btn.dataset.edgeKey;
    const type = btn.dataset.type;
    console.log(`→ onTypeButtonClick — key="${key}", type="${type}"`);

    window.edgeSettings[key] = window.edgeSettings[key] || {};
    if (window.edgeSettings[key].type === type) return;
    window.edgeSettings[key].type = type;

    toggleAngleColumn(type === 'fazowana');

    const dims = {
        length: parseFloat(document.querySelector('input[data-field="length"]').value) || 0,
        width: parseFloat(document.querySelector('input[data-field="width"]').value) || 0,
        height: parseFloat(document.querySelector('input[data-field="thickness"]').value) || 0
    };

    maybeRender3D(dims, window.edgeSettings);
}

let lastDims = { length: 0, width: 0, height: 0 };
let lastSettingsJSON = JSON.stringify({});

/**
 * Renderuje 3D tylko wtedy, gdy wymiary lub settings się zmieniły
 */
function maybeRender3D(dims, settings) {
    const dimsChanged = dims.length !== lastDims.length ||
        dims.width !== lastDims.width ||
        dims.height !== lastDims.height;
    const settingsJSON = JSON.stringify(settings);
    const settingsChanged = settingsJSON !== lastSettingsJSON;

    if (!dimsChanged && !settingsChanged) return;

    lastDims = { ...dims };
    lastSettingsJSON = settingsJSON;

    if (edge3dRoot) {
        edge3dRoot.render(
            React.createElement(Edge3DViewer, { dimensions: dims, edgeSettings: settings })
        );
    }
}

/**
 * Renderuje tabelę edge3d przy pomocy DocumentFragment
 */
function renderEdgeInputs() {
    const table = document.getElementById('edge3d-table');
    if (!table) return console.error("Brak #edge3d-table w DOM");

    const frag = document.createDocumentFragment();

    const header = document.createElement('div');
    header.className = 'edge3d-row edge3d-header';
    header.innerHTML = `
        <div class="edge3d-cell" style="width:120px;">Krawędź</div>
        <div class="edge3d-cell" style="width:172px;">Typ</div>
        <div class="edge3d-cell" style="width:140px;">Wartość [mm]</div>
        <div class="edge3d-cell" style="width:200px; visibility:hidden;">Kąt [°]</div>
    `;
    frag.appendChild(header);

    const basePath = '/calculator/static/images/edges';
    const iconMap = { frezowana: 'frezowanie.svg', fazowana: 'fazowanie.svg' };

    edgesList.forEach(key => {
        const row = document.createElement('div');
        row.className = 'edge3d-row';
        row.style.display = 'flex';
        row.style.gap = '12px';
        row.style.alignItems = 'center';
        row.style.padding = '0 12px';

        row.addEventListener('mouseenter', () => {
            row.classList.add('edge-row-hover');
            if (typeof window.highlightEdge === 'function') {
                window.highlightEdge(key, '#ED6B24', 2);
            }
        });
        row.addEventListener('mouseleave', () => {
            row.classList.remove('edge-row-hover');
            if (typeof window.resetEdge === 'function') {
                window.resetEdge(key);
            }
        });

        const nameCell = document.createElement('div');
        nameCell.className = 'edge3d-cell';
        nameCell.style.width = '120px';
        nameCell.textContent = key;
        row.appendChild(nameCell);

        const typeCell = document.createElement('div');
        typeCell.className = 'edge3d-cell';
        typeCell.style.display = 'flex';
        typeCell.style.gap = '8px';
        typeCell.style.width = '160px';
        Object.keys(iconMap).forEach(type => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'edge-type-btn';
            btn.dataset.edgeKey = key;
            btn.dataset.type = type;
            const img = document.createElement('img');
            img.src = `${basePath}/${iconMap[type]}`;
            img.alt = type;
            btn.appendChild(img);
            btn.addEventListener('click', onTypeButtonClick);
            typeCell.appendChild(btn);
        });
        row.appendChild(typeCell);

        const valueCell = document.createElement('div');
        valueCell.className = 'edge3d-cell';
        valueCell.style.width = '140px';
        const input = document.createElement('input');
        input.type = 'number';
        input.id = `edge-value-${key}`;
        input.className = 'input-small';
        input.style.width = '100%';
        input.min = 0;
        input.addEventListener('input', onEdgeInputChange);
        valueCell.appendChild(input);
        row.appendChild(valueCell);

        const angleCell = document.createElement('div');
        angleCell.className = 'edge3d-cell';
        angleCell.style.width = '200px';
        angleCell.style.visibility = 'hidden';
        angleCell.style.display = 'flex';
        angleCell.style.alignItems = 'center';
        const range = document.createElement('input');
        range.type = 'range';
        range.id = `edge-angle-${key}`;
        range.className = 'input-range';
        range.min = 0;
        range.max = 90;
        range.step = 1;
        range.oninput = function () {
            angleDisplay.textContent = this.value + '°';
        };
        const angleDisplay = document.createElement('span');
        angleDisplay.id = `angle-display-${key}`;
        angleDisplay.style.marginLeft = '8px';
        angleDisplay.style.width = '40px';
        angleDisplay.textContent = '45°';
        angleCell.appendChild(range);
        angleCell.appendChild(angleDisplay);
        row.appendChild(angleCell);

        frag.appendChild(row);
    });

    table.innerHTML = '';
    table.appendChild(frag);
}

/**
 * Inicjalizuje edge3d przy kliknięciu przycisku
 */
function initEdge3D() {
    const openEdgesBtn = document.getElementById('openEdgesModal');
    if (!openEdgesBtn) return console.warn("Nie znaleziono przycisku #openEdgesModal");
    openEdgesBtn.addEventListener('click', () => {
        renderEdgeInputs();
        document.querySelector('.modal-3d-overlay').style.display = 'flex';
        toggleAngleColumn(false);
        const dims = {
            length: parseFloat(document.querySelector('input[data-field="length"]').value) || 0,
            width: parseFloat(document.querySelector('input[data-field="width"]').value) || 0,
            height: parseFloat(document.querySelector('input[data-field="thickness"]').value) || 0
        };
        const container = document.getElementById('edge3d-root');
        if (!edge3dRoot) {
            edge3dRoot = ReactDOM.createRoot(container);
        }
        edge3dRoot.render(
            React.createElement(Edge3DViewer, { dimensions: dims, edgeSettings: window.edgeSettings })
        );
    });
}

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
        const volume = (lengthVal / 100) * (widthVal / 100) * (thicknessVal / 100);
        const productWeight = volume * 800 * quantityVal;
        totalWeight += productWeight;
    });

    const aggregatedLength = maxLength + 5;
    const aggregatedWidth = maxWidth + 5;
    const aggregatedThickness = totalThickness + 5;

    dbg("Aggregated dims for shipping:", { aggregatedLength, aggregatedWidth, aggregatedThickness, totalWeight });

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

function updateDeliverySelection(selection) {
    console.log('Wybrano dostawę:', selection);
    
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
}

/**
 * Ładuje najnowsze wyceny i wyświetla w #latestQuotesList
 */
function loadLatestQuotes() {
    console.info("[loadLatestQuotes] Startuję ładowanie ostatnich wycen...");
    const container = document.getElementById('latestQuotesList');
    if (!container) {
        console.warn("[loadLatestQuotes] Brak kontenera #latestQuotesList – przerywam");
        return;
    }

    fetch('/calculator/latest_quotes')
        .then(res => res.json())
        .then(data => {
            console.info(`[loadLatestQuotes] Otrzymano ${data.length} wycen`);
            if (!data.length) {
                container.innerHTML = '<p>Brak wycen do wyświetlenia.</p>';
                return;
            }

            const html = data.map(q => `
                <div class="quote-row">
                    <div class="quote-cell">${q.quote_number}</div>
                    <div class="quote-cell">${q.created_at}</div>
                    <div class="quote-cell">${q.client_name}</div>
                    <div class="quote-cell">${q.quote_source}</div>
                    <div class="quote-cell">
                        <span class="quote-status" style="background-color: ${q.status_color};">${q.status}</span>
                    </div>
                    <div class="quote-actions">
                        <button class="go-ahead" data-id="${q.id}">Przejdź</button>
                        <button class="quotes-btn-download" data-token="${q.public_token}">
                            Pobierz
                        </button>
                    </div>
                </div>
            `).join('');

            container.innerHTML = html;
            console.log("[loadLatestQuotes] Wyrenderowano HTML z ostatnimi wycenami");

            // TYLKO obsługa przycisku "Przejdź" - pobieranie jest obsługiwane przez initCalculatorDownloadModal()
            container.querySelectorAll('.go-ahead').forEach(btn => {
                btn.addEventListener('click', () => {
                    const id = btn.dataset.id;
                    console.log(`[go-ahead] Klik na przycisk przejdź – ID: ${id}`);

                    // BACKUP: Zapisz ID do sessionStorage
                    sessionStorage.setItem('openQuoteId', id);
                    console.log(`[go-ahead] Zapisano do sessionStorage: openQuoteId=${id}`);

                    // Przekieruj do quotes z parametrem aby otworzyć modal
                    const targetUrl = `/quotes?open_quote=${id}`;
                    console.log(`[go-ahead] Przekierowanie do:`, targetUrl);
                    window.location.href = targetUrl;
                });
            });
        })
        .catch(err => {
            console.error("[loadLatestQuotes] Błąd podczas ładowania wycen:", err);
        });
}

/**
 * Dodaje listener zamykania modala "download-modal" po kliknięciu w "x" lub poza modal
 */
function attachDownloadModalClose() {
    const modal = document.getElementById("download-modal");
    if (!modal) return;
    const closeBtn = modal.querySelector('.close-btn');
    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            modal.style.display = 'none';
            const iframe = document.getElementById("quotePreview");
            if (iframe) iframe.src = "";
        });
    }
    document.addEventListener('click', e => {
        if (modal.style.display === 'flex' && !modal.contains(e.target)) {
            modal.style.display = 'none';
            const iframe = document.getElementById("quotePreview");
            if (iframe) iframe.src = "";
        }
    });
}

/**
 * Dodaje funkcjonalność przyciskom PDF i PNG w modalu "download-modal"
 */
function attachDownloadFormatButtons() {
    const pdfBtn = document.getElementById('pdf-btn');
    const pngBtn = document.getElementById('png-btn');
    const iframe = document.getElementById("quotePreview");
    if (pdfBtn && iframe) {
        pdfBtn.addEventListener('click', () => {
            const src = iframe.src;
            if (src) {
                const a = document.createElement('a');
                a.href = src;
                a.download = 'quote.pdf';
                a.click();
            }
        });
    }
    if (pngBtn && iframe) {
        pngBtn.addEventListener('click', () => {
            // Zakładamy, że iframe wyświetla PDF; konwersja do PNG wymaga backendu lub biblioteki na stronie.
            // Tutaj wykonamy prosty fallback: otworzymy PDF w nowej karcie, by użytkownik mógł zapisać jako obraz.
            const src = iframe.src;
            if (src) {
                window.open(src, '_blank');
            }
        });
    }
}

/**
 * Walidacja długości (max 450 cm)
 */
function attachLengthValidation() {
    const lengthInput = document.querySelector('input[data-field="length"]');
    if (!lengthInput) return;
    lengthInput.addEventListener('input', function () {
        const val = parseFloat(this.value);
        let errorSpan = this.parentNode.querySelector('.error-message-length');
        if (!errorSpan) {
            errorSpan = document.createElement('span');
            errorSpan.classList.add('error-message-length');
            errorSpan.style.color = 'red';
            errorSpan.style.fontSize = '12px';
            this.parentNode.appendChild(errorSpan);
        }
        if (!isNaN(val) && val > 450) {
            errorSpan.textContent = "Długość poza odpowiednim zakresem 0-450 cm.";
        } else {
            errorSpan.textContent = "";
        }
    });
}

/**
 * Walidacja szerokości (max 120 cm)
 */
function attachWidthValidation() {
    const widthInput = document.querySelector('input[data-field="width"]');
    if (!widthInput) return;
    widthInput.addEventListener('input', function () {
        const val = parseFloat(this.value);
        let errorSpan = this.parentNode.querySelector('.error-message-width');
        if (!errorSpan) {
            errorSpan = document.createElement('span');
            errorSpan.classList.add('error-message-width');
            errorSpan.style.color = 'red';
            errorSpan.style.fontSize = '12px';
            this.parentNode.appendChild(errorSpan);
        }
        if (!isNaN(val) && val > 120) {
            errorSpan.textContent = "Szerokość poza odpowiednim zakresem 0-120 cm.";
        } else {
            errorSpan.textContent = "";
        }
    });
}

/**
 * Walidacja i kolorowanie pól (klasa .error-outline)
 */
function attachGlobalValidationListeners() {
    const inputs = document.querySelectorAll('.quote-form input[data-field], .quote-form select[data-field]');
    inputs.forEach(input => {
        input.addEventListener('input', updateGlobalSummary);
        input.addEventListener('change', updateGlobalSummary);
    });
}

/**
 * Main init on DOMContentLoaded
 */
function init() {
    console.log("DOMContentLoaded – inicjalizacja calculator.js");
    function initMainContainer() {
        mainContainer = document.querySelector('.products-summary-main');
        if (!mainContainer) {
            console.warn('[initMainContainer] Nie znaleziono .products-summary-main');
        } else {
            console.log('[initMainContainer] mainContainer zainicjalizowany');
        }
    }

    // Załaduj ceny wykończeń z bazy danych
    loadFinishingPrices();

    const overlay = document.getElementById('loadingOverlay');
    if (overlay) overlay.style.display = 'none';

    const pricesDataEl = document.getElementById('prices-data');
    if (!pricesDataEl) {
        console.error("Brak elementu #prices-data");
        return;
    }
    try {
        pricesFromDatabase = JSON.parse(pricesDataEl.textContent);
        buildPriceIndex();
    } catch (e) {
        console.error("Niepoprawny JSON w #prices-data", e);
    }

    const userRole = document.body.dataset.role;
    userMultiplier = parseFloat(document.body.dataset.multiplier || "1.0");
    isPartner = userRole === "partner";
    dbg("Rola użytkownika:", userRole, "Mnożnik:", userMultiplier);

    multiplierMapping = {};
    const multipliersDataEl = document.getElementById('multipliers-data');
    if (multipliersDataEl) {
        try {
            const multipliersFromDB = JSON.parse(multipliersDataEl.textContent);
            multipliersFromDB.forEach(m => {
                multiplierMapping[m.label] = m.value;
            });
            dbg("Pobrane mnożniki:", multiplierMapping);
        } catch (e) {
            console.warn("Niepoprawny JSON w #multipliers-data", e);
        }
    } else {
        console.warn("Brak #multipliers-data – nie załadowano mnożników.");
    }

    // ✅ ZMIENIONE: Różnicuj standardowych i flexible partnerów
    const isFlexiblePartner = document.body.dataset.flexiblePartner === 'true';

    if (isPartner && !isFlexiblePartner) {
        // Standardowy partner - używa tylko swojego mnożnika (fixed)
        currentClientType = document.body.dataset.clientType || null;
        currentMultiplier = userMultiplier;
        dbg("Standardowy Partner - grupa cenowa:", currentClientType, "Mnożnik:", currentMultiplier);
    } else if (isPartner && isFlexiblePartner) {
        // ✅ NOWE: Flexible partner - ustaw domyślny mnożnik ID=5
        const FLEXIBLE_PARTNER_DEFAULT_MULTIPLIER_ID = 5;
        const defaultClientType = getDefaultClientTypeForId(FLEXIBLE_PARTNER_DEFAULT_MULTIPLIER_ID);

        if (defaultClientType && multiplierMapping[defaultClientType]) {
            currentClientType = defaultClientType;
            currentMultiplier = multiplierMapping[defaultClientType];
            dbg("Flexible Partner - domyślna grupa cenowa:", currentClientType, "Mnożnik:", currentMultiplier);
        } else {
            dbg("⚠️ Flexible Partner - nie znaleziono domyślnej grupy o ID:", FLEXIBLE_PARTNER_DEFAULT_MULTIPLIER_ID);
        }
    }

    orderSummaryEls.brutto = document.querySelector('.quote-summary .order-summary .order-brutto');
    orderSummaryEls.netto = document.querySelector('.quote-summary .order-summary .order-netto');
    deliverySummaryEls.courier = document.querySelector('.quote-summary .delivery-summary .courier');
    deliverySummaryEls.brutto = document.querySelector('.quote-summary .delivery-summary .delivery-brutto');
    deliverySummaryEls.netto = document.querySelector('.quote-summary .delivery-summary .delivery-netto');
    finalSummaryEls.brutto = document.querySelector('.quote-summary .final-summary .final-brutto');
    finalSummaryEls.netto = document.querySelector('.quote-summary .final-summary .final-netto');
    finishingSummaryEls.brutto = document.querySelector('.quote-summary .finishing-brutto');
    finishingSummaryEls.netto = document.querySelector('.quote-summary .finishing-netto');

    const populateMultiplierSelects = () => {
        console.log("[populateMultiplierSelects] Wypełniam opcje grup cenowych");
        
        document.querySelectorAll('select[data-field="clientType"]').forEach(select => {
            const currentValue = select.value; // Zachowaj aktualną wartość
            
            // Stwórz opcje bez resetowania selected
            select.innerHTML = '';
            
            // Dodaj placeholder opcję
            const placeholderOption = document.createElement('option');
            placeholderOption.value = '';
            placeholderOption.disabled = true;
            placeholderOption.hidden = true;
            placeholderOption.textContent = 'Wybierz grupę';
            // NIE ustawiaj selected na placeholder
            select.appendChild(placeholderOption);
            
            // Dodaj opcje grup cenowych
            Object.entries(multiplierMapping).forEach(([label, value]) => {
                const option = document.createElement('option');
                option.value = label;
                option.textContent = `${label} (${value})`;
                select.appendChild(option);
            });
            
            // Przywróć wartość jeśli była ustawiona
            if (currentValue) {
                select.value = currentValue;
                console.log(`[populateMultiplierSelects] Przywrócono wartość: ${currentValue}`);
            }
            
            // Ustaw domyślną wartość dla partnerów
            if (currentValue) {
                select.value = currentValue;
                console.log(`[populateMultiplierSelects] Przywrócono wartość: ${currentValue}`);
            } else {
                // Ustaw domyślną grupę cenową dla nie-partnerów
                if (!isPartner) {
                    const defaultClientType = getDefaultClientTypeForId(DEFAULT_MULTIPLIER_ID);
                    if (defaultClientType && multiplierMapping[defaultClientType]) {
                        select.value = defaultClientType;
                        console.log(`[populateMultiplierSelects] Ustawiono domyślną grupę: ${defaultClientType}`);
                    }
                }

                // Ustaw domyślną wartość dla partnerów (istniejący kod)
                if (isPartner && currentClientType && !currentValue) {
                    select.value = currentClientType;
                    console.log(`[populateMultiplierSelects] Ustawiono domyślną dla partnera: ${currentClientType}`);
                }
            }
        });
    };
    populateMultiplierSelects();

    if (isPartner && !isFlexiblePartner) {
        // Tylko standardowi partnerzy mają ukryty select
        document.querySelectorAll('select[data-field="clientType"]').forEach(el => {
            const wrapper = el.closest('.client-type');
            if (wrapper) wrapper.remove();
        });
    }

    productSummaryContainer = document.getElementById('products-summary-container');
    quoteFormsContainer = document.querySelector('.quote-forms');
    if (!quoteFormsContainer) {
        quoteFormsContainer = document.createElement('div');
        quoteFormsContainer.className = 'quote-forms';
        const calcMain = document.querySelector('.calculator-main');
        calcMain.insertBefore(quoteFormsContainer, calcMain.firstElementChild);
        const initialQuoteForm = document.querySelector('.quote-form');
        if (initialQuoteForm) quoteFormsContainer.appendChild(initialQuoteForm);
    }

    function updateActiveQuoteForm(index) {
        const forms = quoteFormsContainer.querySelectorAll('.quote-form');
        forms.forEach((form, i) => {
            form.style.display = (i === index) ? 'flex' : 'none';
        });
    }

    document.addEventListener('click', e => {
        const removeBtn = e.target.closest('.remove-product');
        if (removeBtn) {
            if (!activeQuoteForm) {
                console.log("Brak aktywnego formularza.");
                return;
            }
            const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
            const index = forms.indexOf(activeQuoteForm);
            if (index === -1) {
                console.log("activeQuoteForm nie jest w tablicy formularzy.");
                return;
            }

            // Usuń aktywny formularz
            activeQuoteForm.remove();

            // Pobierz pozostałe formularze po usunięciu
            const remainingForms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
            
            // Wybierz nowy aktywny formularz
            let newIndex = index > 0 ? index - 1 : 0;
            if (remainingForms.length > 0 && remainingForms[newIndex]) {
                activateProductCard(newIndex);
            } else if (remainingForms.length > 0) {
                // Fallback - aktywuj pierwszy dostępny
                activateProductCard(0);
            }

            // Odśwież panel produktów
            generateProductsSummary();
        }
    });

    updateActiveQuoteForm(0);

    const modalCloseBtn = document.getElementById('modalCloseBtn');
    if (modalCloseBtn) {
        modalCloseBtn.addEventListener('click', () => {
            const modal = document.getElementById('deliveryModal');
            if (modal) modal.style.display = 'none';
            const overlay = document.getElementById('loadingOverlay');
            if (overlay) overlay.style.display = 'none';
        });
    }

    document.addEventListener('click', e => {
        const modal = document.getElementById('deliveryModal');
        if (modal && modal.style.display === 'block' && !modal.contains(e.target)) {
            modal.style.display = 'none';
            const overlay = document.getElementById('loadingOverlay');
            if (overlay) overlay.style.display = 'none';
        }
    });

    initEdge3D();
    attachCalculateDeliveryListener();
    loadLatestQuotes();
    initCalculatorDownloadModal();
    attachDownloadModalClose();
    attachDownloadFormatButtons();
    attachLengthValidation();
    attachWidthValidation();
    attachGlobalValidationListeners();
    attachGoToQuoteListeners();
    initMainContainer();

    quoteFormsContainer.querySelectorAll('.quote-form').forEach((form, index) => {
        prepareNewProductForm(form, index);
        safeAttachFormListeners(form);
        calculateFinishingCost(form);
    });

    // NOWA FUNKCJA: Dodaj event listener do synchronizacji grup cenowych
    document.addEventListener('change', e => {
        if (e.target.matches('select[data-field="clientType"]')) {
            const selectedType = e.target.value;
            const sourceForm = e.target.closest('.quote-form');

            // ✅ POPRAWKA: Synchronizuj TYLKO jeśli zmiana pochodzi od użytkownika
            // NIE synchronizuj jeśli zmiana jest programowa (np. podczas addNewProduct)
            if (selectedType && sourceForm && e.isTrusted) {
                console.log(`[Event] Użytkownik zmienił grupę na ${selectedType} - synchronizuję`);
                syncClientTypeAcrossProducts(selectedType, sourceForm);
            } else if (!e.isTrusted) {
                console.log(`[Event] Programowa zmiana grupy na ${selectedType} - pomijam synchronizację`);
            }
        }
    });

    window.multiplierMapping = multiplierMapping;
    window.isPartner = isPartner;
    window.userMultiplier = userMultiplier;
    
    console.log("[init] Udostępniono globalne zmienne:", {
        multiplierMapping: window.multiplierMapping,
        isPartner: window.isPartner,
        userMultiplier: window.userMultiplier
    });
    generateProductsSummary();
    // Aktywuj pierwszy produkt
    if (quoteFormsContainer.querySelector('.quote-form')) {
        activateProductCard(0);
    }

    // Inicjalizacja systemu backup wycen
    if (typeof QuoteDraftBackup !== 'undefined') {
        const userId = document.body.dataset.userId;
        if (userId) {
            quoteDraftBackup = new QuoteDraftBackup();
            quoteDraftBackup.init(parseInt(userId));
            console.log('[Calculator] System backup wycen zainicjalizowany dla użytkownika:', userId);
        } else {
            console.warn('[Calculator] Brak user_id - system backup nie został uruchomiony');
        }
    } else {
        console.warn('[Calculator] QuoteDraftBackup nie jest dostępny - sprawdź czy skrypt został załadowany');
    }

    setTimeout(() => {
        const firstForm = quoteFormsContainer.querySelector('.quote-form');
        if (firstForm) {
            const clientTypeSelect = firstForm.querySelector('select[data-field="clientType"]');
            if (clientTypeSelect && !clientTypeSelect.value && !isPartner) {
                setDefaultClientType(firstForm, false);
                console.log(`[init] Ustawiono domyślną grupę cenową w pierwszym produkcie: ${clientTypeSelect.value}`);
            }
        }
    }, 100);

    console.log("Inicjalizacja calculator.js zakończona");

}

function safeAttachFormListeners(form) {
    if (!form) return;

    // Sprawdź czy listenery już zostały dodane
    if (form.dataset.listenersAttached === "true") {
        console.log(`[safeAttachFormListeners] Pomijam - listenery już dodane`);
        return;
    }

    console.log(`[safeAttachFormListeners] Dodaję listenery dla formularza`);

    // ✅ KLUCZOWA POPRAWKA: Zachowaj wszystkie wartości formularza przed manipulacją
    const formValues = {};

    // Zapisz wartości input i select
    form.querySelectorAll('input[data-field], select[data-field]').forEach(input => {
        const key = input.id || input.name || input.dataset.field;
        if (input.type === 'checkbox' || input.type === 'radio') {
            formValues[key] = input.checked;
        } else {
            formValues[key] = input.value;
        }
    });

    // Zapisz wartości radio buttons
    form.querySelectorAll('input[type="radio"]').forEach(radio => {
        const key = radio.id || radio.name;
        formValues[key + '_checked'] = radio.checked;
        formValues[key + '_value'] = radio.value;
    });

    // Zapisz stany przycisków wykończenia
    form.querySelectorAll('.finishing-btn').forEach(btn => {
        const key = btn.dataset.finishingType || btn.dataset.finishingVariant || btn.dataset.finishingGloss;
        if (key) {
            formValues['finishing_' + key] = btn.classList.contains('active');
        }
    });

    // Zapisz stany przycisków kolorów
    form.querySelectorAll('.color-btn').forEach(btn => {
        const key = btn.dataset.finishingColor;
        if (key) {
            formValues['color_' + key] = btn.classList.contains('active');
        }
    });

    console.log(`[safeAttachFormListeners] Zapisano wartości formularza:`, formValues);

    // ✅ NOWA POPRAWKA: Dodaj listenery dla inputów BEZ klonowania
    const inputs = form.querySelectorAll('input[data-field], select[data-field]');
    inputs.forEach(input => {
        // Usuń poprzednie listenery bezpośrednio
        input.removeEventListener('input', updatePrices);
        input.removeEventListener('change', updatePrices);

        // Dodaj nowe listenery
        if (input.matches('input[data-field]')) {
            input.addEventListener('input', updatePrices);
        } else if (input.matches('select[data-field]')) {
            input.addEventListener('change', updatePrices);
        }
    });

    // Dodaj listenery dla radio buttons BEZ klonowania
    const radios = form.querySelectorAll('input[type="radio"]');
    radios.forEach(radio => {
        // Usuń poprzednie listenery
        radio.removeEventListener('change', updatePrices);
        radio.removeEventListener('change', handleRadioButtonChange);

        // Dodaj nowy listener
        radio.addEventListener('change', handleRadioButtonChange);
    });

    /**
     * Ulepszona obsługa zmiany radio buttonów
     */
    function handleRadioButtonChange(event) {
        const radio = event.target;
        const form = radio.closest('.quote-form');

        if (!form) return;

        // Upewnij się, że tylko ten radio jest zaznaczony w swojej grupie
        const groupName = radio.name;
        const otherRadios = form.querySelectorAll(`input[name="${groupName}"]`);

        otherRadios.forEach(otherRadio => {
            if (otherRadio !== radio && otherRadio.checked) {
                console.log(`🔧 Odznaczam konfliktowy radio: ${otherRadio.value}`);
                otherRadio.checked = false;
            }
        });

        // Zaktualizuj klasy CSS
        form.querySelectorAll('.variant-option').forEach(option => {
            option.classList.remove('selected');
        });

        if (radio.checked) {
            const selectedOption = radio.closest('.variant-option');
            if (selectedOption) {
                selectedOption.classList.add('selected');
            }
        }

        // Wywołaj oryginalną funkcję updatePrices
        updatePrices();

        // Sprawdź integralność po zmianie
        setTimeout(() => {
            checkRadioButtonIntegrity();
        }, 50);
    }

    // ✅ POPRAWKA: Dodaj listenery dla przycisków wykończenia BEZ klonowania
    const finishingBtns = form.querySelectorAll('.finishing-btn');
    finishingBtns.forEach(btn => {
        // Usuń poprzednie listenery bezpośrednio
        btn.removeEventListener('click', btn._finishingClickHandler);

        // Utwórz nowy handler i zapisz referencję
        btn._finishingClickHandler = function () {
            const parentForm = this.closest('.quote-form');
            if (parentForm) {
                // Znajdź typ przycisku i usuń active z innych tego samego typu
                if (this.dataset.finishingType) {
                    const sameTypeButtons = parentForm.querySelectorAll(`[data-finishing-type]`);
                    sameTypeButtons.forEach(b => b.classList.remove('active'));
                } else if (this.dataset.finishingVariant) {
                    const sameTypeButtons = parentForm.querySelectorAll(`[data-finishing-variant]`);
                    sameTypeButtons.forEach(b => b.classList.remove('active'));
                } else if (this.dataset.finishingGloss) {
                    const sameTypeButtons = parentForm.querySelectorAll(`[data-finishing-gloss]`);
                    sameTypeButtons.forEach(b => b.classList.remove('active'));
                }

                // Dodaj active do klikniętego
                this.classList.add('active');

                // Aktualizuj
                updatePrices();
                generateProductsSummary();
            }
        };

        // Dodaj nowy listener
        btn.addEventListener('click', btn._finishingClickHandler);
    });

    // ✅ POPRAWKA: Dodaj listenery dla przycisków kolorów BEZ klonowania
    const colorBtns = form.querySelectorAll('.color-btn');
    colorBtns.forEach(btn => {
        // Usuń poprzednie listenery bezpośrednio
        btn.removeEventListener('click', btn._colorClickHandler);

        // Utwórz nowy handler i zapisz referencję
        btn._colorClickHandler = function () {
            const parentForm = this.closest('.quote-form');
            if (parentForm) {
                const colorButtons = parentForm.querySelectorAll('.color-btn');
                colorButtons.forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                generateProductsSummary();
            }
        };

        // Dodaj nowy listener
        btn.addEventListener('click', btn._colorClickHandler);
    });

    // ✅ KLUCZOWA POPRAWKA: Przywróć wszystkie wartości po dodaniu listenerów
    console.log(`[safeAttachFormListeners] Przywracam wartości formularza...`);

    // Przywróć wartości input i select
    form.querySelectorAll('input[data-field], select[data-field]').forEach(input => {
        const key = input.id || input.name || input.dataset.field;
        const savedValue = formValues[key];

        if (savedValue !== undefined) {
            if (input.type === 'checkbox' || input.type === 'radio') {
                input.checked = savedValue;
            } else {
                input.value = savedValue;
                // Specjalne logowanie dla grup cenowych
                if (input.matches('select[data-field="clientType"]') && savedValue) {
                    console.log(`[safeAttachFormListeners] ✅ Przywrócono grupę cenową: ${savedValue}`);
                }
            }
        }
    });

    // Przywróć stany radio buttons
    form.querySelectorAll('input[type="radio"]').forEach(radio => {
        const key = radio.id || radio.name;
        const savedChecked = formValues[key + '_checked'];
        if (savedChecked !== undefined) {
            radio.checked = savedChecked;
        }
    });

    // Przywróć stany przycisków wykończenia
    form.querySelectorAll('.finishing-btn').forEach(btn => {
        const key = btn.dataset.finishingType || btn.dataset.finishingVariant || btn.dataset.finishingGloss;
        if (key) {
            const savedActive = formValues['finishing_' + key];
            if (savedActive) {
                btn.classList.add('active');
            }
        }
    });

    // Przywróć stany przycisków kolorów
    form.querySelectorAll('.color-btn').forEach(btn => {
        const key = btn.dataset.finishingColor;
        if (key) {
            const savedActive = formValues['color_' + key];
            if (savedActive) {
                btn.classList.add('active');
            }
        }
    });

    // Oznacz że listenery zostały dodane
    form.dataset.listenersAttached = "true";

    // Dodaj listenery UI wykończeń
    attachFinishingUIListeners(form);

    console.log(`[safeAttachFormListeners] ✅ Zakończono dodawanie listenerów z zachowaniem wartości`);
}

function initCalculatorDownloadModal() {
    // Spróbuj znaleźć modal z różnymi możliwymi ID
    const modal = document.getElementById("download-modal") ||
        document.getElementById("downloadModal") ||
        document.querySelector(".download-modal");

    // Spróbuj znaleźć różne możliwe elementy
    const closeBtn = document.getElementById("closeDownloadModal") ||
        document.getElementById("close-download-modal") ||
        document.querySelector(".close-download-modal") ||
        modal?.querySelector(".close-modal");

    const iframe = document.getElementById("quotePreview") ||
        document.getElementById("quote-preview") ||
        modal?.querySelector("iframe");

    const downloadPDF = document.getElementById("downloadPDF") ||
        document.getElementById("pdf-btn") ||
        modal?.querySelector(".download-pdf");

    const downloadPNG = document.getElementById("downloadPNG") ||
        document.getElementById("png-btn") ||
        modal?.querySelector(".download-png");

    console.log("[initCalculatorDownloadModal] Znalezione elementy:", {
        modal: !!modal,
        closeBtn: !!closeBtn,
        iframe: !!iframe,
        downloadPDF: !!downloadPDF,
        downloadPNG: !!downloadPNG
    });

    if (!modal) {
        console.warn("[initCalculatorDownloadModal] Nie znaleziono modala pobierania");
        return;
    }

    if (!iframe) {
        console.warn("[initCalculatorDownloadModal] Nie znaleziono iframe w modalu");
        return;
    }

    // NOWA WERSJA - bez nieskończonej pętli
    let currentQuoteToken = null; // ZMIANA: przechowujemy token zamiast ID
    let loadingTimeout = null;
    let isLoadingPdf = false;

    // Event listener dla przycisków pobierz w ostatnich wycenach
    document.addEventListener("click", (e) => {
        const downloadBtn = e.target.closest(".quotes-btn-download");
        if (downloadBtn) {
            e.preventDefault();
            // ZMIANA: Pobieramy token zamiast ID
            const quoteToken = downloadBtn.dataset.token;
            console.log(`[Calculator DownloadModal] Klik dla TOKEN: ${quoteToken}`);

            if (!quoteToken) {
                console.warn("❗️Brak quoteToken – dataset.token undefined!");
                return;
            }

            // Ustaw nowy quote token
            currentQuoteToken = quoteToken;
            isLoadingPdf = true;

            // ZMIANA: Przygotuj URL PDF z tokenem
            const pdfUrl = `/quotes/api/quotes/${quoteToken}/pdf.pdf`;
            console.log(`[Calculator DownloadModal] Ustawianie URL PDF: ${pdfUrl}`);

            // DEBUGOWANIE iframe
            console.log(`[Calculator DownloadModal] iframe attributes:`, {
                id: iframe.id,
                src: iframe.src,
                width: iframe.width,
                height: iframe.height,
                sandbox: iframe.sandbox.toString(),
                loading: iframe.loading,
                name: iframe.name
            });

            // Wyczyść poprzednie timeouty
            if (loadingTimeout) {
                clearTimeout(loadingTimeout);
            }

            // Dodaj loading indicator
            iframe.style.background = "linear-gradient(45deg, #f0f0f0 25%, transparent 25%), linear-gradient(-45deg, #f0f0f0 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #f0f0f0 75%), linear-gradient(-45deg, transparent 75%, #f0f0f0 75%)";
            iframe.style.backgroundSize = "20px 20px";
            iframe.style.backgroundPosition = "0 0, 0 10px, 10px -10px, -10px 0px";
            iframe.style.animation = "loading 1s linear infinite";

            // Ustaw URL PDF w iframe
            iframe.src = pdfUrl;
            console.log(`[Calculator DownloadModal] iframe.src ustawiony na: ${iframe.src}`);

            // DODAJ obserwatora zmian iframe.src
            const srcObserver = setInterval(() => {
                if (isLoadingPdf && currentQuoteToken) {
                    const currentSrc = iframe.src;
                    if (currentSrc && !currentSrc.includes('/pdf.pdf') && !currentSrc.includes('about:blank')) {
                        console.log(`[Calculator DownloadModal] WYKRYTO RESET iframe.src z ${currentSrc} - przywracam PDF`);
                        iframe.src = pdfUrl;
                    }
                } else {
                    clearInterval(srcObserver);
                }
            }, 500);

            // Wyczyść obserwatora po 15 sekundach
            setTimeout(() => {
                clearInterval(srcObserver);
            }, 15000);

            // Backup timeout na ukrycie loadingu (jeśli load event nie zadziała)
            loadingTimeout = setTimeout(() => {
                console.log(`[Calculator DownloadModal] Backup timeout - ukrywam loading po 10 sekundach`);
                iframe.style.background = "none";
                iframe.style.animation = "none";
                isLoadingPdf = false;
            }, 10000); // Zwiększono do 10 sekund

            // ZMIANA: Ustaw token dla przycisków pobierania
            if (downloadPDF) downloadPDF.dataset.token = quoteToken;
            if (downloadPNG) downloadPNG.dataset.token = quoteToken;

            // Pokaż modal
            modal.style.display = "flex";
            modal.classList.add("active");

            console.log(`[Calculator DownloadModal] Modal powinien być widoczny - display: ${modal.style.display}`);
        }
    });

    // Funkcja czyszczenia modala
    function cleanupModal() {
        if (loadingTimeout) {
            clearTimeout(loadingTimeout);
            loadingTimeout = null;
        }
        iframe.src = "";
        iframe.style.background = "none";
        iframe.style.animation = "none";
        currentQuoteToken = null; // ZMIANA: czyszczenie tokenu
        isLoadingPdf = false;

        // Usuń fallback jeśli istnieje
        const fallback = modal.querySelector('.iframe-fallback');
        if (fallback) {
            fallback.remove();
        }
    }

    // Zamykanie modala
    if (closeBtn) {
        closeBtn.addEventListener("click", (e) => {
            e.preventDefault();
            modal.style.display = "none";
            modal.classList.remove("active");
            cleanupModal();
            console.log(`[Calculator DownloadModal] Modal zamknięty`);
        });
    }

    // ZMIANA: Pobieranie PDF z tokenem
    if (downloadPDF) {
        downloadPDF.addEventListener("click", (e) => {
            e.preventDefault();
            const quoteToken = downloadPDF.dataset.token || currentQuoteToken;
            if (quoteToken) {
                console.log(`[Calculator DownloadModal] Pobieranie PDF dla TOKEN: ${quoteToken}`);
                const pdfUrl = `/quotes/api/quotes/${quoteToken}/pdf.pdf`;
                window.open(pdfUrl, "_blank");
            }
        });
    }

    // ZMIANA: Pobieranie PNG z tokenem
    if (downloadPNG) {
        downloadPNG.addEventListener("click", (e) => {
            e.preventDefault();
            const quoteToken = downloadPNG.dataset.token || currentQuoteToken;
            if (quoteToken) {
                console.log(`[Calculator DownloadModal] Pobieranie PNG dla TOKEN: ${quoteToken}`);
                const pngUrl = `/quotes/api/quotes/${quoteToken}/pdf.png`;
                window.open(pngUrl, "_blank");
            }
        });
    }

    // Zamykanie przez kliknięcie tła
    modal.addEventListener("click", (e) => {
        if (e.target === modal) {
            modal.style.display = "none";
            modal.classList.remove("active");
            cleanupModal();
            console.log(`[Calculator DownloadModal] Modal zamknięty przez kliknięcie tła`);
        }
    });

    // POPRAWIONA detekcja ładowania - z ochroną przed resetowaniem
    iframe.addEventListener('load', function handleIframeLoad() {
        console.log(`[Calculator DownloadModal] iframe load event triggered`);
        console.log(`[Calculator DownloadModal] iframe.src: ${iframe.src}`);
        console.log(`[Calculator DownloadModal] isLoadingPdf: ${isLoadingPdf}`);

        // Sprawdź czy to nasze PDF i czy aktualnie ładujemy
        if (isLoadingPdf && iframe.src.includes('/pdf.pdf') && currentQuoteToken) {
            console.log(`[Calculator DownloadModal] PDF załadowany pomyślnie dla TOKEN: ${currentQuoteToken}`);
            iframe.style.background = "none";
            iframe.style.animation = "none";
            isLoadingPdf = false;

            if (loadingTimeout) {
                clearTimeout(loadingTimeout);
                loadingTimeout = null;
            }
        } else if (isLoadingPdf && (iframe.src === window.location.href || iframe.src.includes('/calculator/'))) {
            // Jeśli iframe zostało zresetowane, przywróć PDF URL
            console.log(`[Calculator DownloadModal] iframe zostało zresetowane, przywracam PDF URL`);
            const pdfUrl = `/quotes/api/quotes/${currentQuoteToken}/pdf.pdf`;
            console.log(`[Calculator DownloadModal] Przywracam URL: ${pdfUrl}`);

            // Dodaj krótkie opóźnienie aby uniknąć natychmiastowego ponownego resetu
            setTimeout(() => {
                if (isLoadingPdf && currentQuoteToken) {
                    iframe.src = pdfUrl;
                    console.log(`[Calculator DownloadModal] URL przywrócony: ${iframe.src}`);
                }
            }, 100);
        }
    });

    console.log("[initCalculatorDownloadModal] Modal pobierania zainicjalizowany z obsługą tokenów");
}

/**
 * Funkcja pomocnicza - sprawdza czy iframe się załadował
 */
function checkIframeLoading(iframe, pdfUrl) {
    try {
        // Sprawdź czy iframe wydaje się pusty
        const iframeDoc = iframe.contentDocument || iframe.contentWindow?.document;

        if (!iframeDoc || iframeDoc.body.children.length === 0 ||
            iframeDoc.body.innerHTML.trim() === '' ||
            iframeDoc.documentElement.innerHTML.includes('error') ||
            iframeDoc.documentElement.innerHTML.includes('404')) {

            console.log(`[Calculator DownloadModal] iframe wydaje się pusty lub z błędem, pokazuję fallback`);
            showIframeFallback(iframe, pdfUrl);
        } else {
            console.log(`[Calculator DownloadModal] iframe wydaje się załadowany poprawnie`);
        }
    } catch (e) {
        console.log(`[Calculator DownloadModal] Nie można sprawdzić zawartości iframe (CORS), assumuje że działa:`, e);
        // W przypadku CORS nie możemy sprawdzić zawartości, więc zakładamy że działa
    }
}

/**
 * Funkcja pomocnicza - pokazuje fallback gdy iframe nie działa
 */
function showIframeFallback(iframe, pdfUrl) {
    console.log(`[Calculator DownloadModal] Pokazuję fallback dla PDF`);

    // Usuń poprzedni fallback jeśli istnieje
    const existingFallback = iframe.parentNode.querySelector('.iframe-fallback');
    if (existingFallback) {
        existingFallback.remove();
    }

    // Ukryj iframe
    iframe.style.display = 'none';

    // Utwórz fallback
    const fallbackDiv = document.createElement('div');
    fallbackDiv.className = 'iframe-fallback';
    fallbackDiv.style.cssText = `
        text-align: center; 
        padding: 50px; 
        background: #f9f9f9; 
        border: 2px dashed #ccc; 
        border-radius: 8px;
        height: 700px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
    `;

    fallbackDiv.innerHTML = `
        <div style="max-width: 400px;">
            <svg style="width: 64px; height: 64px; margin-bottom: 20px; fill: #ED6B24;" viewBox="0 0 24 24">
                <path d="M14,2H6A2,2 0 0,0 4,4V20A2,2 0 0,0 6,22H18A2,2 0 0,0 20,20V8L14,2M18,20H6V4H13V9H18V20Z"/>
            </svg>
            <h3 style="color: #333; margin-bottom: 15px;">Podgląd wyceny PDF</h3>
            <p style="color: #666; margin-bottom: 25px; line-height: 1.4;">
                Nie można wyświetlić podglądu PDF w przeglądarce.<br>
                Kliknij poniżej aby otworzyć plik w nowej karcie.
            </p>
            <a href="${pdfUrl}" target="_blank" style="
                background: #ED6B24; 
                color: white; 
                padding: 12px 24px; 
                text-decoration: none; 
                border-radius: 6px;
                display: inline-flex;
                align-items: center;
                gap: 8px;
                font-weight: 500;
                transition: background 0.2s;
            " onmouseover="this.style.background='#d85d20'" onmouseout="this.style.background='#ED6B24'">
                <svg style="width: 16px; height: 16px; fill: currentColor;" viewBox="0 0 24 24">
                    <path d="M14,3V5H17.59L7.76,14.83L9.17,16.24L19,6.41V10H21V3M19,19H5V5H12V3H5C3.89,3 3,3.9 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V12H19V19Z"/>
                </svg>
                Otwórz PDF w nowej karcie
            </a>
        </div>
    `;

    // Wstaw fallback po iframe
    iframe.parentNode.insertBefore(fallbackDiv, iframe.nextSibling);
}

document.addEventListener('DOMContentLoaded', init);

window.calculateFinishingCost = calculateFinishingCost;

/**
 * Przekierowuje do modułu quotes i otwiera modal szczegółów wyceny
 * @param {number} quoteId - ID wyceny
 */
function redirectToQuoteDetails(quoteId) {
    console.log(`[redirectToQuoteDetails] Przekierowanie do wyceny ID: ${quoteId}`);
    
    if (!quoteId) {
        console.error("[redirectToQuoteDetails] Brak ID wyceny");
        return;
    }
    
    // Zapisz ID wyceny w sessionStorage, aby móc ją otworzyć po załadowaniu strony
    sessionStorage.setItem('openQuoteModal', quoteId);
    
    // Przekieruj do modułu quotes
    window.location.href = '/quotes/';
}

/**
 * Przekierowuje do modułu quotes na podstawie numeru wyceny
 * @param {string} quoteNumber - Numer wyceny (np. "01/12/24/W")
 */
function redirectToQuoteDetailsByNumber(quoteNumber) {
    console.log(`[redirectToQuoteDetailsByNumber] Przekierowanie do wyceny: ${quoteNumber}`);
    
    if (!quoteNumber) {
        console.error("[redirectToQuoteDetailsByNumber] Brak numeru wyceny");
        return;
    }
    
    // Zapisz numer wyceny w sessionStorage
    sessionStorage.setItem('openQuoteModalByNumber', quoteNumber);
    
    // Przekieruj do modułu quotes
    window.location.href = '/quotes/';
}

/**
 * Funkcja do obsługi przycisku "Przejdź" w modalu sukcesu zapisu wyceny
 */
function handleGoToQuoteFromModal() {
    const quoteNumberDisplay = document.querySelector('.quote-number-display');
    
    if (!quoteNumberDisplay || !quoteNumberDisplay.textContent) {
        console.error("[handleGoToQuoteFromModal] Brak numeru wyceny w modalu");
        alert("Błąd: nie znaleziono numeru wyceny");
        return;
    }
    
    const quoteNumber = quoteNumberDisplay.textContent.trim();
    console.log(`[handleGoToQuoteFromModal] Przechodzę do wyceny: ${quoteNumber}`);
    
    redirectToQuoteDetailsByNumber(quoteNumber);
}

/**
 * Dodaj obsługę przycisków "Przejdź" w ostatnich wycenach
 */
function attachGoToQuoteListeners() {
    // Delegacja eventów dla przycisków "Przejdź" w ostatnich wycenach
    const latestQuotesList = document.getElementById('latestQuotesList');
    
    if (latestQuotesList) {
        latestQuotesList.addEventListener('click', (e) => {
            if (e.target.classList.contains('go-ahead')) {
                e.preventDefault();
                const quoteId = e.target.dataset.id;
                
                if (quoteId) {
                    console.log(`[latestQuotes] Przechodzę do wyceny ID: ${quoteId}`);
                    redirectToQuoteDetails(parseInt(quoteId));
                } else {
                    console.error("[latestQuotes] Brak ID wyceny w data-id");
                }
            }
        });
    }
}

/**
 * Modernizowany modal opcji dostawy
 * Obsługuje paginację, własnych kurierów i lepsze UX
 */

class DeliveryModal {
    constructor() {
        this.modal = null;
        this.quotes = [];
        this.currentPage = 1;
        this.itemsPerPage = 8;
        this.selectedOption = null;
        this.customCarrier = null;
        this.isCustomMode = false;
        this.VAT_RATE = 0.23;
        this.MARGIN_RATE = 0.30;
        
        this.init();
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

    show(quotes, packingInfo = null) {
        this.quotes = quotes || [];
        this.currentPage = 1;
        this.selectedOption = null;
        this.customCarrier = null;

        // Sortuj opcje po cenie
        this.quotes.sort((a, b) => (a.grossPrice || 0) - (b.grossPrice || 0));

        this.showMainView();
        this.renderOptions();
        this.updatePackingInfo(packingInfo);
        this.updateConfirmButton();

        // Pokaż modal z animacją
        this.modal.style.display = 'flex';
        requestAnimationFrame(() => {
            this.modal.classList.add('active');
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
            
            <div class="delivery-modal-price">
                <div class="delivery-modal-price-brutto">${(quote.grossPrice || 0).toFixed(2)} PLN</div>
                <div class="delivery-modal-price-netto">${(quote.netPrice || 0).toFixed(2)} PLN netto</div>
            </div>
            
            <div class="delivery-modal-price">
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
        console.log('Wybrano opcję dostawy:', selection);
        
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

/**
 * Sprawdza czy produkt jest kompletny
 */
function checkProductCompleteness(form) {
    if (!form) return false;
    
    const length = form.querySelector('[data-field="length"]')?.value;
    const width = form.querySelector('[data-field="width"]')?.value;
    const thickness = form.querySelector('[data-field="thickness"]')?.value;
    const quantity = form.querySelector('[data-field="quantity"]')?.value;
    const variant = form.querySelector('input[type="radio"]:checked');
    
    return !!(length && width && thickness && quantity && variant);
}

/**
 * Pobiera opis wariantu z formularza
 */
function getVariantDescription(form) {
    if (!form) return null;
    
    const variant = form.querySelector('input[type="radio"]:checked');
    if (!variant) return null;
    
    // Znajdź label dla tego radio button
    const label = form.querySelector(`label[for="${variant.id}"]`);
    if (label) {
        // Usuń tag "BRAK" jeśli istnieje i pobierz czysty tekst
        return label.textContent.replace(/BRAK/g, '').trim();
    }
    
    // Fallback - tłumacz kod na czytelną nazwę
    const variantNames = {
        'dab-lity-ab': 'Dąb lity A/B',
        'dab-lity-bb': 'Dąb lity B/B',
        'dab-micro-ab': 'Dąb mikrowczep A/B',
        'dab-micro-bb': 'Dąb mikrowczep B/B',
        'jes-lity-ab': 'Jesion lity A/B',
        'jes-micro-ab': 'Jesion mikrowczep A/B',
        'buk-lity-ab': 'Buk lity A/B',
        'buk-micro-ab': 'Buk mikrowczep A/B'
    };
    
    return variantNames[variant.value] || variant.value;
}

/**
 * Pobiera opis wykończenia z formularza
 */
function getFinishingDescription(form) {
    if (!form) return null;
    
    const finishingTypeBtn = form.querySelector('.finishing-btn[data-finishing-type].active');
    const finishingVariantBtn = form.querySelector('.finishing-btn[data-finishing-variant].active');
    
    if (!finishingTypeBtn || finishingTypeBtn.dataset.finishingType === 'Surowe') {
        return null;
    }
    
    let description = finishingTypeBtn.dataset.finishingType;
    
    if (finishingVariantBtn) {
        description += ` ${finishingVariantBtn.dataset.finishingVariant}`;
        
        // Dodaj kolor jeśli jest wybrany i wariant jest barwny
        if (finishingVariantBtn.dataset.finishingVariant === 'Barwne') {
            const colorBtn = form.querySelector('.color-btn.active');
            if (colorBtn) {
                const color = colorBtn.dataset.finishingColor;
                if (color) {
                    description += ` (${color})`;
                }
            }
        }
    }
    
    return description;
}

function getFinishingDescriptionWithGloss(form) {
    if (!form) return null;
    
    const finishingTypeBtn = form.querySelector('.finishing-btn[data-finishing-type].active');
    const finishingVariantBtn = form.querySelector('.finishing-btn[data-finishing-variant].active');
    
    if (!finishingTypeBtn || finishingTypeBtn.dataset.finishingType === 'Surowe') {
        return null;
    }
    
    let description = finishingTypeBtn.dataset.finishingType;
    
    if (finishingVariantBtn) {
        description += ` ${finishingVariantBtn.dataset.finishingVariant}`;
        
        // Dodaj kolor jeśli jest wybrany
        if (finishingVariantBtn.dataset.finishingVariant === 'Barwne') {
            const colorBtn = form.querySelector('.color-btn.active');
            if (colorBtn) {
                const color = colorBtn.dataset.finishingColor;
                if (color) {
                    description += ` (${color})`;
                }
            }
        }
    }
    
    // ✅ POPRAWKA: Dodaj stopień połysku
    if (finishingTypeBtn.dataset.finishingType === 'Lakierowanie') {
        const glossBtn = form.querySelector('.finishing-btn[data-finishing-gloss].active');
        if (glossBtn) {
            const gloss = glossBtn.dataset.finishingGloss;
            if (gloss) {
                description += ` ${gloss}`;
            }
        }
    }
    
    return description;
}

/**
 * Generuje opis produktu
 */
function generateProductDescription(form, index) {
    if (!form) return { main: `Błąd formularza`, sub: "" };

    const isComplete = checkProductCompleteness(form);

    if (!isComplete) {
        return { main: `Dokończ wycenę produktu`, sub: "" };
    }

    const length = form.querySelector('[data-field="length"]')?.value;
    const width = form.querySelector('[data-field="width"]')?.value;
    const thickness = form.querySelector('[data-field="thickness"]')?.value;
    const quantity = form.querySelector('[data-field="quantity"]')?.value;

    const variantRadio = form.querySelector('input[type="radio"]:checked');
    const variantLabel = variantRadio ? form.querySelector(`label[for="${variantRadio.id}"]`) : null;
    const variantName = variantLabel ? variantLabel.textContent.replace(/BRAK/g, '').trim() : 'Nieznany wariant';

    // Dodaj wykończenie z stopniem połysku
    const finishingDescription = getFinishingDescriptionWithGloss(form);

    let mainDescription = `${variantName} ${length}×${width}×${thickness} cm | ${quantity} szt.`;

    if (finishingDescription) {
        mainDescription += ` | ${finishingDescription}`;
    }

    // NOWE: Oblicz objętość i wagę dla informacji dodatkowych
    const volume = calculateProductVolume(form);
    const weight = calculateProductWeight(form);
    const subDescription = volume > 0 ? `${formatVolume(volume)} | ${formatWeight(weight)}` : "";

    return { main: mainDescription, sub: subDescription };
}

/**
 * Duplikuje produkt na podstawie indeksu źródłowego
 */

function duplicateProduct(sourceIndex) {
    console.log(`[duplicateProduct] Rozpoczynam duplikowanie produktu ${sourceIndex + 1}...`);

    const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
    const sourceForm = forms[sourceIndex];

    if (!sourceForm) {
        console.error(`[duplicateProduct] Nie znaleziono formularza o indeksie ${sourceIndex}`);
        return;
    }

    // KROK 1: Zapisz stan wszystkich formularzy
    const selectedStates = forms.map((form, index) => {
        const selectedRadio = form.querySelector('input[type="radio"]:checked');
        return {
            formIndex: index,
            selectedVariant: selectedRadio ? {
                id: selectedRadio.id,
                value: selectedRadio.value,
                checked: true,
                orderBrutto: form.dataset.orderBrutto,
                orderNetto: form.dataset.orderNetto
            } : null
        };
    });

    // KROK 2: Pobierz wszystkie dane z formularza źródłowego
    const sourceData = {
        // Wymiary
        length: sourceForm.querySelector('[data-field="length"]')?.value || '',
        width: sourceForm.querySelector('[data-field="width"]')?.value || '',
        thickness: sourceForm.querySelector('[data-field="thickness"]')?.value || '',
        quantity: sourceForm.querySelector('[data-field="quantity"]')?.value || '',
        clientType: sourceForm.querySelector('[data-field="clientType"]')?.value || '',

        // Zaznaczony wariant
        selectedVariant: null,

        // Wykończenia
        finishingType: null,
        finishingColor: null,
        finishingGloss: null
    };

    // Pobierz zaznaczony wariant z formularza źródłowego
    const sourceSelectedRadio = sourceForm.querySelector('input[type="radio"]:checked');
    if (sourceSelectedRadio) {
        sourceData.selectedVariant = {
            value: sourceSelectedRadio.value,
            orderBrutto: sourceForm.dataset.orderBrutto,
            orderNetto: sourceForm.dataset.orderNetto
        };
    }

    // Pobierz dane wykończeń
    const finishingTypeBtn = sourceForm.querySelector('.finishing-btn[data-finishing-type].active');
    if (finishingTypeBtn) {
        sourceData.finishingType = finishingTypeBtn.dataset.finishingType;
    }

    const finishingColorBtn = sourceForm.querySelector('.color-btn.active');
    if (finishingColorBtn) {
        sourceData.finishingColor = finishingColorBtn.dataset.finishingColor;
    }

    const finishingGlossBtn = sourceForm.querySelector('.finishing-btn[data-finishing-gloss].active');
    if (finishingGlossBtn) {
        sourceData.finishingGloss = finishingGlossBtn.dataset.finishingGloss;
    }

    console.log(`[duplicateProduct] Dane do skopiowania:`, sourceData);

    // KROK 3: Utwórz nowy formularz używając addNewProduct
    const newIndex = forms.length;
    addNewProduct();

    // KROK 4: Poczekaj na utworzenie nowego formularza i wypełnij go danymi
    setTimeout(() => {
        const newForms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
        const newForm = newForms[newIndex];

        if (!newForm) {
            console.error(`[duplicateProduct] Nie znaleziono nowego formularza`);
            return;
        }

        console.log(`[duplicateProduct] Wypełniam nowy formularz danymi...`);

        // Wypełnij wymiary
        if (sourceData.length) {
            const lengthInput = newForm.querySelector('[data-field="length"]');
            if (lengthInput) lengthInput.value = sourceData.length;
        }

        if (sourceData.width) {
            const widthInput = newForm.querySelector('[data-field="width"]');
            if (widthInput) widthInput.value = sourceData.width;
        }

        if (sourceData.thickness) {
            const thicknessInput = newForm.querySelector('[data-field="thickness"]');
            if (thicknessInput) thicknessInput.value = sourceData.thickness;
        }

        if (sourceData.quantity) {
            const quantityInput = newForm.querySelector('[data-field="quantity"]');
            if (quantityInput) quantityInput.value = sourceData.quantity;
        }

        if (sourceData.clientType) {
            const clientTypeSelect = newForm.querySelector('[data-field="clientType"]');
            if (clientTypeSelect) {
                clientTypeSelect.value = sourceData.clientType;
                console.log(`[duplicateProduct] Przywrócono grupę cenową: ${sourceData.clientType}`);
            }
        } else {
            // Jeśli kopiowany produkt nie miał grupy cenowej, ustaw domyślną
            setDefaultClientType(newForm, false);
        }

        // Aktywuj wykończenia jeśli były wybrane
        if (sourceData.finishingType) {
            const finishingBtn = newForm.querySelector(`[data-finishing-type="${sourceData.finishingType}"]`);
            if (finishingBtn) {
                finishingBtn.click();

                // Po aktywacji wykończenia, ustaw kolor i połysk
                setTimeout(() => {
                    if (sourceData.finishingColor) {
                        const colorBtn = newForm.querySelector(`[data-finishing-color="${sourceData.finishingColor}"]`);
                        if (colorBtn) colorBtn.click();
                    }

                    if (sourceData.finishingGloss) {
                        const glossBtn = newForm.querySelector(`[data-finishing-gloss="${sourceData.finishingGloss}"]`);
                        if (glossBtn) glossBtn.click();
                    }
                }, 100);
            }
        }

        // Przeliczy ceny jeśli mamy wszystkie wymiary
        if (sourceData.length && sourceData.width && sourceData.thickness && sourceData.clientType) {
            setTimeout(() => {
                updatePrices();

                // Zaznacz ten sam wariant co w źródle
                if (sourceData.selectedVariant) {
                    const radioToSelect = newForm.querySelector(`input[type="radio"][value="${sourceData.selectedVariant.value}"]`);
                    if (radioToSelect) {
                        radioToSelect.click();
                        console.log(`[duplicateProduct] Zaznaczono wariant: ${sourceData.selectedVariant.value}`);
                    }
                }

                // Przywróć zaznaczenia w starych formularzach
                selectedStates.forEach(state => {
                    if (state.selectedVariant && state.formIndex < newIndex) {
                        const form = newForms[state.formIndex];
                        if (form) {
                            const radio = form.querySelector(`input[type="radio"][value="${state.selectedVariant.value}"]`);
                            if (radio && !radio.checked) {
                                radio.checked = true;
                                form.dataset.orderBrutto = state.selectedVariant.orderBrutto || '';
                                form.dataset.orderNetto = state.selectedVariant.orderNetto || '';
                            }
                        }
                    }
                });

                updateGlobalSummary();
                generateProductsSummary();
            }, 200);
        }

        console.log(`[duplicateProduct] ✅ Pomyślnie zduplikowano produkt ${sourceIndex + 1} jako produkt ${newIndex + 1}`);

    }, 100);
}

/**
 * Generuje panel produktów
 */
function generateProductsSummary() {
    if (!productSummaryContainer) return;

    const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
    productSummaryContainer.innerHTML = '';

    // POPRAWKA: Znajdź główny kontener bezpiecznie
    const summaryMainContainer = productSummaryContainer.parentElement ||
        document.querySelector('.products-summary-main');

    // Usuń istniejące podsumowanie jeśli istnieje
    if (summaryMainContainer) {
        const existingSummary = summaryMainContainer.querySelector('.products-total-summary');
        if (existingSummary) {
            existingSummary.remove();
        }
    }

    if (forms.length === 0) {
        productSummaryContainer.innerHTML = '<div class="no-products">Brak produktów</div>';
        return;
    }

    forms.forEach((form, index) => {
        const descriptionData = generateProductDescription(form, index);
        const isComplete = checkProductCompleteness(form);
        const isActive = form === activeQuoteForm;

        const productCard = document.createElement('div');
        productCard.className = `product-card ${isActive ? 'active' : ''} ${!isComplete ? 'error' : ''}`;
        productCard.dataset.index = index;

        // Przycisk usuwania gdy jest więcej niż 1 produkt
        const removeButton = forms.length > 1 ? `
            <button class="remove-product-btn" data-index="${index}" title="Usuń produkt">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
            </button>
        ` : '';

        productCard.innerHTML = `
            <div class="product-card-content">
                <div class="product-card-number">${index + 1}</div>
                <div class="product-card-details">
                    <div class="product-card-main-info">${descriptionData.main}</div>
                    ${descriptionData.sub ? `<div class="product-card-sub-info">${descriptionData.sub}</div>` : ''}
                </div>
                <button class="duplicate-product-btn" data-index="${index}" title="Duplikuj produkt">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                </button>
            </div>
            ${removeButton}
        `;

        // POPRAWKA: Dodaj listener NATYCHMIAST po utworzeniu elementu
        productCard.addEventListener('click', (e) => {
            // Nie przełączaj jeśli kliknięto przycisk usuwania lub duplikowania
            if (e.target.closest('.remove-product-btn') || e.target.closest('.duplicate-product-btn')) return;
            activateProductCard(index);
        });

        productSummaryContainer.appendChild(productCard);
    });

    // NOWE: Dodaj podsumowanie objętości i wagi NA DOLE GŁÓWNEGO KONTENERA
    const { totalVolume, totalWeight } = calculateTotalVolumeAndWeight();

    if (forms.length > 0 && (totalVolume > 0 || totalWeight > 0) && summaryMainContainer) {
        const summaryCard = document.createElement('div');
        summaryCard.className = 'products-total-summary';
        summaryCard.innerHTML = `
            <div class="products-total-title">Łączne podsumowanie:</div>
            <div class="products-total-details">
                <span class="products-total-volume">${formatVolume(totalVolume)}</span>
                <span class="products-total-weight">${formatWeight(totalWeight)}</span>
            </div>
        `;
        // POPRAWKA: Dodaj do summaryMainContainer zamiast mainContainer
        summaryMainContainer.appendChild(summaryCard);
    }

    // POPRAWKA: Dodaj event listeners FUNKCJĄ DELEGUJĄCĄ aby uniknąć problemów
    attachProductCardListeners();

    // Aktualizuj stan przycisków
    updateCalculateDeliveryButtonState();
}

function attachProductCardListeners() {
    // Usuń poprzednie listenery jeśli istnieją
    if (productSummaryContainer._listenersAttached) {
        return;
    }

    // Użyj delegacji eventów dla przycisków usuwania i duplikowania
    productSummaryContainer.addEventListener('click', (e) => {
        // Obsługa przycisku usuwania
        const removeBtn = e.target.closest('.remove-product-btn');
        if (removeBtn) {
            e.stopPropagation();
            const index = parseInt(removeBtn.dataset.index);
            console.log(`[removeProduct] Usuwam produkt ${index + 1}`);
            removeProduct(index);
            return;
        }

        // Obsługa przycisku duplikowania
        const duplicateBtn = e.target.closest('.duplicate-product-btn');
        if (duplicateBtn) {
            e.stopPropagation();
            const index = parseInt(duplicateBtn.dataset.index);
            console.log(`[duplicateProduct] Duplikuję produkt ${index + 1}`);
            duplicateProduct(index);
            return;
        }
    });

    // Oznacz że listenery zostały dodane
    productSummaryContainer._listenersAttached = true;
    console.log('[attachProductCardListeners] Event listenery dla kart produktów zostały dodane');
}

function removeProduct(index) {
    const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
    
    if (forms.length <= 1) {
        console.log("Nie można usunąć ostatniego produktu");
        return;
    }
    
    const formToRemove = forms[index];
    if (!formToRemove) return;
    
    // Usuń formularz
    formToRemove.remove();
    
    // Zaktualizuj aktywny formularz
    const remainingForms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
    
    if (remainingForms.length > 0) {
        // Jeśli usunięty był aktywny, aktywuj poprzedni lub pierwszy
        const newIndex = index > 0 ? index - 1 : 0;
        activateProductCard(Math.min(newIndex, remainingForms.length - 1));
    }
    
    // Odśwież podsumowanie
    generateProductsSummary();
    updateGlobalSummary();
}

/**
 * Aktywuje kartę produktu
 */
function activateProductCard(index) {
    console.log(`[activateProductCard] Aktywuję produkt ${index + 1}`);
    
    const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
    
    if (index < 0 || index >= forms.length) {
        console.error(`[activateProductCard] Nieprawidłowy index: ${index}`);
        return;
    }
    
    // KROK 1: Zapisz stan zaznaczonych wariantów we WSZYSTKICH formularzach
    const selectedVariants = {};
    forms.forEach((form, formIndex) => {
        const selectedRadio = form.querySelector('input[type="radio"]:checked');
        if (selectedRadio) {
            selectedVariants[formIndex] = {
                id: selectedRadio.id,
                value: selectedRadio.value,
                checked: true
            };
            console.log(`[activateProductCard] Zapisano stan formularza ${formIndex + 1}: ${selectedRadio.value}`);
        }
    });
    
    // KROK 2: Ukryj wszystkie formularze
    forms.forEach((form, i) => {
        form.style.display = (i === index) ? 'flex' : 'none';
    });
    
    // KROK 3: Ustaw aktywny formularz
    const previousActiveForm = activeQuoteForm;
    activeQuoteForm = forms[index];
    
    if (!activeQuoteForm) {
        console.error(`[activateProductCard] Nie można znaleźć formularza o index ${index}`);
        return;
    }
    
    console.log(`[activateProductCard] Podpinam listenery dla produktu ${index + 1}`);
    
    // KROK 4: Odśwież event listeners TYLKO dla aktywnego formularza
    if (activeQuoteForm) {
        attachFormListeners(activeQuoteForm);
        
        // ✅ POPRAWKA: Wywołaj updatePrices TYLKO jeśli formularz ma wypełnione wymiary
        const hasValidDimensions = checkFormHasValidDimensions(activeQuoteForm);
        if (hasValidDimensions) {
            console.log(`[activateProductCard] Aktualizuję ceny dla produktu ${index + 1}`);
            updatePrices();
        } else {
            console.log(`[activateProductCard] Pomijam updatePrices - brak wymiarów w produkcie ${index + 1}`);
        }
    }
    
    // KROK 5: Przywróć zaznaczenia we WSZYSTKICH formularzach
    Object.entries(selectedVariants).forEach(([formIndex, variant]) => {
        const form = forms[parseInt(formIndex)];
        if (form) {
            const radio = form.querySelector(`#${variant.id}`);
            if (radio && !radio.checked) {
                radio.checked = true;
                console.log(`[activateProductCard] Przywrócono zaznaczenie w formularzu ${parseInt(formIndex) + 1}: ${variant.value}`);
                
                // Ustaw kolory dla przywróconego zaznaczenia
                const selectedVariant = radio.closest('div');
                if (selectedVariant) {
                    selectedVariant.querySelectorAll('*').forEach(el => el.style.color = "#ED6B24");
                }
                
                // Aktualizuj dataset formularza
                if (radio.dataset.totalBrutto && radio.dataset.totalNetto) {
                    form.dataset.orderBrutto = radio.dataset.totalBrutto;
                    form.dataset.orderNetto = radio.dataset.totalNetto;
                }
            }
        }
    });
    
    // KROK 6: Odśwież panel produktów
    generateProductsSummary();
    
    console.log(`[activateProductCard] ✅ Aktywowano produkt ${index + 1}`);
}

function checkFormHasValidDimensions(form) {
    if (!form) return false;
    
    const length = parseFloat(form.querySelector('[data-field="length"]')?.value || 0);
    const width = parseFloat(form.querySelector('[data-field="width"]')?.value || 0);
    const thickness = parseFloat(form.querySelector('[data-field="thickness"]')?.value || 0);
    const clientType = form.querySelector('[data-field="clientType"]')?.value;
    
    const hasValidDimensions = !isNaN(length) && length > 0 && 
                               !isNaN(width) && width > 0 && 
                               !isNaN(thickness) && thickness > 0;
                               
    const hasClientType = isPartner || clientType;
    
    return hasValidDimensions && hasClientType;
}

/**
 * Dodaje nowy produkt
 */
function addNewProduct() {
    console.log("[addNewProduct] Rozpoczynam dodawanie nowego produktu...");

    const firstForm = quoteFormsContainer.querySelector('.quote-form');
    if (!firstForm) {
        console.error("[addNewProduct] Nie znaleziono pierwszego formularza!");
        return;
    }

    // KROK 1: Zapisz stan zaznaczonych wariantów przed klonowaniem
    const allForms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
    const selectedStates = allForms.map((form, index) => {
        const selectedRadio = form.querySelector('input[type="radio"]:checked');
        return {
            formIndex: index,
            selectedVariant: selectedRadio ? {
                id: selectedRadio.id,
                value: selectedRadio.value,
                checked: true,
                orderBrutto: form.dataset.orderBrutto,
                orderNetto: form.dataset.orderNetto
            } : null
        };
    });

    console.log("[addNewProduct] Zapisane stany zaznaczonych wariantów:", selectedStates);

    // KROK 2: Pobierz aktualną grupę cenową
    const currentClientType = activeQuoteForm?.querySelector('select[data-field="clientType"]')?.value ||
        firstForm?.querySelector('select[data-field="clientType"]')?.value || null;
    console.log(`[addNewProduct] Aktualna grupa cenowa z aktywnego formularza: ${currentClientType}`);

    const newIndex = allForms.length;

    // KROK 3: Sklonuj i przygotuj nowy formularz
    const newForm = firstForm.cloneNode(true);
    newForm.style.display = 'none';
    quoteFormsContainer.appendChild(newForm);

    prepareNewProductForm(newForm, newIndex);

    // KROK 4: Przywróć grupę cenową
    if (currentClientType) {
        const select = newForm.querySelector('select[data-field="clientType"]');
        if (select) {
            select.value = currentClientType;
            console.log(`[addNewProduct] Przywrócono grupę cenową: ${currentClientType}`);
        }
    }

    // KROK 4.1: Przywróć grupę cenową TAKŻE w aktywnym formularzu
    if (currentClientType) {
        const select = newForm.querySelector('select[data-field="clientType"]');
        if (select) {
            select.value = currentClientType;
            console.log(`[addNewProduct] Przywrócono grupę cenową: ${currentClientType}`);
        }
    } else {
        // Jeśli nie ma aktualnej grupy cenowej, ustaw domyślną
        setDefaultClientType(newForm, false);
    }

    // KROK 5: Dodaj event listenery do nowego formularza
    attachFormListeners(newForm);

    // KROK 6: Przywróć zaznaczenia w STARYCH formularzach
    selectedStates.forEach(state => {
        if (state.selectedVariant) {
            const form = allForms[state.formIndex];
            if (form) {
                // Znajdź radio button po value zamiast po ID (ID się zmieniło)
                const radio = form.querySelector(`input[type="radio"][value="${state.selectedVariant.value}"]:checked`);
                if (!radio) {
                    // Jeśli nie jest zaznaczony, zaznacz go
                    const radioToCheck = form.querySelector(`input[type="radio"][value="${state.selectedVariant.value}"]`);
                    if (radioToCheck) {
                        radioToCheck.checked = true;
                        form.dataset.orderBrutto = state.selectedVariant.orderBrutto || '';
                        form.dataset.orderNetto = state.selectedVariant.orderNetto || '';
                        console.log(`[addNewProduct] Przywrócono zaznaczenie w formularzu ${state.formIndex + 1}: ${state.selectedVariant.value}`);
                    }
                }
            }
        }
    });

    // KROK 7: Aktywuj nowy formularz (bez resetowania starych)
    activateProductCard(newIndex);

    // KROK 8: Wymuś odświeżenie z opóźnieniem
    setTimeout(() => {
        updateGlobalSummary();
        generateProductsSummary();
        scrollToLatestProduct();

        // ✅ POPRAWKA: Upewnij się, że klasy 'selected' są prawidłowe we wszystkich formularzach
        fixSelectedClasses();
    }, 150);

    console.log(`[addNewProduct] ✅ Pomyślnie dodano produkt ${newIndex + 1}`);
}

function reinitializeAllEventListeners() {
    console.log("[reinitializeAllEventListeners] Reinicjalizuję wszystkie event listenery...");
    
    const allForms = quoteFormsContainer.querySelectorAll('.quote-form');
    allForms.forEach((form, index) => {
        console.log(`[reinitializeAllEventListeners] Reinicjalizuję formularz ${index + 1}`);
        
        // Usuń oznaczenie o event listenerach
        delete form.dataset.listenersAttached;
        
        // Dodaj event listenery
        safeAttachFormListeners(form);
    });
    
    console.log("[reinitializeAllEventListeners] ✅ Zakończono reinicjalizację");
}

function fixAllRadioButtonNames() {
    const allForms = quoteFormsContainer.querySelectorAll('.quote-form');
    
    allForms.forEach((form, formIndex) => {
        // ✅ NAJPIERW zachowaj informację o zaznaczonych radio
        const checkedRadios = [];
        form.querySelectorAll('.variants input[type="radio"]:checked').forEach(radio => {
            checkedRadios.push(radio.value); // Zachowaj value zaznaczonego radio
        });
        
        // Teraz zaktualizuj nazwy i ID
        form.querySelectorAll('.variants input[type="radio"]').forEach(radio => {
            const baseValue = radio.value;
            const wasChecked = radio.checked; // Zachowaj stan zaznaczenia
            
            radio.id = `${baseValue}-product-${formIndex}`;
            radio.name = `variant-product-${formIndex}`;
            
            // ✅ PRZYWRÓĆ zaznaczenie jeśli było zaznaczone
            if (wasChecked || checkedRadios.includes(baseValue)) {
                radio.checked = true;
                // Dodatkowo zaktualizuj nazwę dla zaznaczonego
                radio.name = `variant-product-${formIndex}-selected`;
            }
            
            // Aktualizuj label
            const label = form.querySelector(`label[for*="${baseValue}"]`);
            if (label) {
                label.setAttribute('for', radio.id);
            }
        });
        
        console.log(`✅ Naprawiono radio buttons dla produktu ${formIndex + 1}, zachowano ${checkedRadios.length} zaznaczonych`);
    });
    
    console.log('✅ Naprawiono nazwy radio buttonów we wszystkich formularzach BEZ resetowania selekcji');
}

function calculateProductVolume(form) {
    const length = parseFloat(form.querySelector('[data-field="length"]')?.value) || 0;
    const width = parseFloat(form.querySelector('[data-field="width"]')?.value) || 0;
    const thickness = parseFloat(form.querySelector('[data-field="thickness"]')?.value) || 0;
    const quantity = parseInt(form.querySelector('[data-field="quantity"]')?.value) || 1;

    if (length <= 0 || width <= 0 || thickness <= 0) return 0;

    const singleVolume = calculateSingleVolume(length, width, thickness);
    return singleVolume * quantity;
}

function calculateProductWeight(form) {
    const volume = calculateProductVolume(form);
    // Gęstość drewna: 800 kg/m³
    return volume * 800;
}

function formatVolume(volume) {
    if (volume === 0) return "0.000 m³";
    return volume.toFixed(3) + " m³";
}

function formatWeight(weight) {
    if (weight === 0) return "0.0 kg";
    if (weight >= 1000) {
        return (weight / 1000).toFixed(2) + " t";
    }
    return weight.toFixed(1) + " kg";
}

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

// JavaScript dla obsługi dostępności wariantów

// Mapowanie domyślnych stanów dostępności
const defaultVariantAvailability = {
    'dab-lity-ab': true,
    'dab-lity-bb': true,
    'dab-micro-ab': true,
    'dab-micro-bb': true,
    'jes-lity-ab': true,
    'jes-micro-ab': false,  // Domyślnie niedostępny (był "BRAK")
    'buk-lity-ab': true,
    'buk-micro-ab': false   // Domyślnie niedostępny (był "BRAK")
};

/**
 * Inicjalizuje dostępność wariantów dla wszystkich formularzy
 */
function initializeVariantAvailability() {
    console.log("[initializeVariantAvailability] Inicjalizuję dostępność wariantów...");

    const allForms = document.querySelectorAll('.quote-form');
    allForms.forEach((form, formIndex) => {
        console.log(`[initializeVariantAvailability] Inicjalizuję formularz ${formIndex + 1}`);

        // Ustaw domyślne stany checkbox
        Object.entries(defaultVariantAvailability).forEach(([variantCode, isAvailable]) => {
            const checkbox = form.querySelector(`[data-variant="${variantCode}"]`);
            if (checkbox) {
                checkbox.checked = isAvailable;
                updateVariantAvailability(form, variantCode, isAvailable);
            }
        });

        // Dodaj event listenery dla checkbox
        attachVariantAvailabilityListeners(form);
    });

    console.log("[initializeVariantAvailability] ✅ Zakończono inicjalizację");
}

/**
 * Dodaje event listenery dla checkbox dostępności w danym formularzu
 */
function attachVariantAvailabilityListeners(form) {
    const checkboxes = form.querySelectorAll('.variant-availability-checkbox');

    checkboxes.forEach(checkbox => {
        checkbox.addEventListener('change', (e) => {
            const variantCode = e.target.dataset.variant;
            const isAvailable = e.target.checked;

            console.log(`[availabilityChange] Wariant ${variantCode}: ${isAvailable ? 'dostępny' : 'niedostępny'}`);

            // Walidacja - zawsze musi być przynajmniej jeden dostępny wariant
            if (!isAvailable && !checkAtLeastOneAvailable(form, variantCode)) {
                e.preventDefault();
                e.target.checked = true;
                alert('Przynajmniej jeden wariant musi być dostępny!');
                return;
            }

            updateVariantAvailability(form, variantCode, isAvailable);

            // Jeśli wariant został wyłączony a był zaznaczony, odznacz go
            if (!isAvailable) {
                const radio = form.querySelector(`input[type="radio"][value="${variantCode}"]`);
                if (radio && radio.checked) {
                    radio.checked = false;
                    // Wyczyść dane o cenie produktu
                    form.dataset.orderBrutto = "";
                    form.dataset.orderNetto = "";
                    updateGlobalSummary();
                    generateProductsSummary();
                }
            }
        });
    });
}

/**
 * Aktualizuje wizualny stan dostępności wariantu
 */
function updateVariantAvailability(form, variantCode, isAvailable) {
    const variantElement = form.querySelector(`[data-variant="${variantCode}"]`).closest('.variant-option');
    const radio = form.querySelector(`input[type="radio"][value="${variantCode}"]`);

    if (isAvailable) {
        // Wariant dostępny
        variantElement.classList.remove('unavailable');
        radio.disabled = false;
        radio.style.pointerEvents = 'auto';
    } else {
        // Wariant niedostępny
        variantElement.classList.add('unavailable');
        radio.disabled = true;
        radio.style.pointerEvents = 'none';

        // Odznacz jeśli był zaznaczony
        if (radio.checked) {
            radio.checked = false;
        }
    }
}

/**
 * Sprawdza czy przynajmniej jeden wariant będzie dostępny (poza wykluczanym)
 */
function checkAtLeastOneAvailable(form, excludeVariant = null) {
    const checkboxes = form.querySelectorAll('.variant-availability-checkbox');
    let availableCount = 0;

    checkboxes.forEach(checkbox => {
        if (checkbox.dataset.variant !== excludeVariant && checkbox.checked) {
            availableCount++;
        }
    });

    return availableCount > 0;
}

/**
 * Pobiera dostępne warianty z formularza
 */
function getAvailableVariants(form) {
    const availableVariants = [];
    const checkboxes = form.querySelectorAll('.variant-availability-checkbox:checked');

    checkboxes.forEach(checkbox => {
        availableVariants.push(checkbox.dataset.variant);
    });

    return availableVariants;
}

/**
 * Ustala dostępność wariantów przy tworzeniu nowego produktu
 */
function setDefaultVariantAvailability(form) {
    console.log("[setDefaultVariantAvailability] Ustawiam domyślną dostępność...");

    Object.entries(defaultVariantAvailability).forEach(([variantCode, isAvailable]) => {
        const checkbox = form.querySelector(`[data-variant="${variantCode}"]`);
        if (checkbox) {
            checkbox.checked = isAvailable;
            updateVariantAvailability(form, variantCode, isAvailable);
        }
    });

    // Dodaj event listenery
    attachVariantAvailabilityListeners(form);
}

/**
 * Kopiuje stany dostępności z jednego formularza do drugiego
 */
function copyVariantAvailability(sourceForm, targetForm) {
    console.log("[copyVariantAvailability] Kopiuję stany dostępności...");

    const sourceCheckboxes = sourceForm.querySelectorAll('.variant-availability-checkbox');

    sourceCheckboxes.forEach(sourceCheckbox => {
        const variantCode = sourceCheckbox.dataset.variant;
        const isAvailable = sourceCheckbox.checked;

        const targetCheckbox = targetForm.querySelector(`[data-variant="${variantCode}"]`);
        if (targetCheckbox) {
            targetCheckbox.checked = isAvailable;
            updateVariantAvailability(targetForm, variantCode, isAvailable);
        }
    });

    // Dodaj event listenery do nowego formularza
    attachVariantAvailabilityListeners(targetForm);
}

/**
 * Aktualizacja funkcji attachFormListeners - dodaj obsługę dostępności
 */
function attachFormListenersWithAvailability(form) {
    // Wywołaj istniejącą funkcję
    safeAttachFormListeners(form);

    // Dodaj obsługę dostępności jeśli jeszcze nie została dodana
    if (!form.dataset.availabilityAttached) {
        attachVariantAvailabilityListeners(form);
        form.dataset.availabilityAttached = 'true';
    }
}

// Aktualizacja funkcji prepareNewProductForm
function prepareNewProductFormWithAvailability(form, index) {
    console.log(`[prepareNewProductFormWithAvailability] Przygotowuję formularz ${index + 1}`);

    // Wywołaj istniejącą funkcję
    prepareNewProductForm(form, index);

    // Ustaw domyślną dostępność wariantów
    setDefaultVariantAvailability(form);
}

// Aktualizacja funkcji duplicateProduct - skopiuj stany dostępności
function duplicateProductWithAvailability(sourceIndex) {
    console.log(`[duplicateProductWithAvailability] Duplikuję produkt ${sourceIndex + 1} z dostępnością...`);

    const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
    const sourceForm = forms[sourceIndex];

    if (!sourceForm) {
        console.error(`Nie znaleziono formularza o indeksie ${sourceIndex}`);
        return;
    }

    // Zapisz stany dostępności z formularza źródłowego
    const availabilityStates = {};
    const sourceCheckboxes = sourceForm.querySelectorAll('.variant-availability-checkbox');
    sourceCheckboxes.forEach(checkbox => {
        availabilityStates[checkbox.dataset.variant] = checkbox.checked;
    });

    // Wywołaj oryginalną funkcję duplikowania
    duplicateProduct(sourceIndex);

    // Po utworzeniu nowego produktu, skopiuj stany dostępności
    setTimeout(() => {
        const newForms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
        const newForm = newForms[newForms.length - 1]; // Ostatni dodany formularz

        if (newForm) {
            // Skopiuj stany dostępności
            Object.entries(availabilityStates).forEach(([variantCode, isAvailable]) => {
                const checkbox = newForm.querySelector(`[data-variant="${variantCode}"]`);
                if (checkbox) {
                    checkbox.checked = isAvailable;
                    updateVariantAvailability(newForm, variantCode, isAvailable);
                }
            });

            console.log(`[duplicateProductWithAvailability] ✅ Skopiowano stany dostępności do nowego produktu`);
        }
    }, 150);
}

// ============ AKTUALIZACJA ISTNIEJĄCYCH FUNKCJI ============

/**
 * Aktualizacja funkcji init() - dodaj inicjalizację dostępności
 */
function initWithAvailability() {
    // Wywołaj istniejącą funkcję init
    // (tu będzie wywołanie oryginalnej funkcji init)

    // Dodaj inicjalizację dostępności wariantów
    setTimeout(() => {
        initializeVariantAvailability();
    }, 100);
}

/**
 * Aktualizacja addNewProduct - ustaw domyślną dostępność
 */
function addNewProductWithAvailability() {
    console.log("[addNewProductWithAvailability] Dodaję nowy produkt z dostępnością...");

    // Wywołaj oryginalną funkcję
    addNewProduct();

    // Po dodaniu produktu ustaw domyślną dostępność
    setTimeout(() => {
        const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
        const newForm = forms[forms.length - 1];

        if (newForm) {
            setDefaultVariantAvailability(newForm);
            console.log("[addNewProductWithAvailability] ✅ Ustawiono domyślną dostępność dla nowego produktu");
        }
    }, 100);
}

/**
 * Walidacja przed zapisem wyceny - sprawdź czy są dostępne warianty
 */
function validateAvailableVariants() {
    const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));

    for (let i = 0; i < forms.length; i++) {
        const form = forms[i];
        const availableVariants = getAvailableVariants(form);

        if (availableVariants.length === 0) {
            alert(`Produkt ${i + 1} nie ma żadnych dostępnych wariantów. Dodaj przynajmniej jeden dostępny wariant.`);
            return false;
        }

        // Sprawdź czy zaznaczony wariant jest dostępny
        const selectedRadio = form.querySelector('input[type="radio"]:checked');
        if (selectedRadio) {
            const selectedVariant = selectedRadio.value;
            if (!availableVariants.includes(selectedVariant)) {
                alert(`Produkt ${i + 1} ma zaznaczony niedostępny wariant. Wybierz dostępny wariant.`);
                return false;
            }
        }
    }

    return true;
}

/**
 * Filtruje warianty tylko do dostępnych przed wysłaniem do backend
 */
function filterAvailableVariantsForSave(form, variants) {
    const availableVariants = getAvailableVariants(form);

    return variants.filter(variant => {
        return availableVariants.includes(variant.variant_code);
    });
}

// ============ EVENT LISTENERS ============

/**
 * Dodaj obsługę dostępności do event listenerów formularza
 */
function attachVariantSelectionListeners(form) {
    const radioButtons = form.querySelectorAll('input[type="radio"]');

    radioButtons.forEach(radio => {
        // Usuń poprzednie event listenery
        radio.removeEventListener('change', handleVariantSelection);

        // Dodaj nowy event listener
        radio.addEventListener('change', handleVariantSelection);
    });
}

function checkRadioButtonIntegrity() {
    console.log("🔍 Sprawdzam integralność radio buttonów...");

    const allForms = quoteFormsContainer.querySelectorAll('.quote-form');
    let hasIssues = false;

    allForms.forEach((form, formIndex) => {
        const radioButtons = form.querySelectorAll('input[type="radio"]');
        const radioGroups = {};

        // Grupuj radio buttony według name
        radioButtons.forEach(radio => {
            if (!radioGroups[radio.name]) {
                radioGroups[radio.name] = [];
            }
            radioGroups[radio.name].push(radio);
        });

        // Sprawdź każdą grupę
        Object.entries(radioGroups).forEach(([groupName, radios]) => {
            const checkedRadios = radios.filter(r => r.checked);

            if (checkedRadios.length > 1) {
                console.error(`❌ PROBLEM w formularzu ${formIndex + 1}, grupa "${groupName}": ${checkedRadios.length} zaznaczonych radio buttonów`);
                hasIssues = true;

                // Automatycznie napraw - zostaw tylko pierwszy zaznaczony
                checkedRadios.slice(1).forEach(radio => {
                    console.log(`🔧 Odznaczam radio: ${radio.value}`);
                    radio.checked = false;
                });
            }
        });
    });

    if (!hasIssues) {
        console.log("✅ Radio buttony są w porządku");
    }

    return !hasIssues;
}

function fixSelectedClasses() {
    console.log("[fixSelectedClasses] Naprawiam klasy 'selected'...");

    const allForms = quoteFormsContainer.querySelectorAll('.quote-form');

    allForms.forEach((form, formIndex) => {
        // Znajdź zaznaczony radio button w tym formularzu
        const checkedRadio = form.querySelector('input[type="radio"]:checked');

        // Usuń wszystkie klasy 'selected' z tego formularza
        form.querySelectorAll('.variant-option').forEach(option => {
            option.classList.remove('selected');
        });

        // Dodaj 'selected' tylko do właściwego wariantu
        if (checkedRadio) {
            const selectedOption = checkedRadio.closest('.variant-option');
            if (selectedOption) {
                selectedOption.classList.add('selected');
                console.log(`[fixSelectedClasses] ✅ Formularz ${formIndex + 1}: Dodano 'selected' do ${checkedRadio.value}`);
            }
        }
    });
}

function handleVariantSelection(e) {
    const radio = e.target;
    const form = radio.closest('.quote-form');

    if (!form) return;

    console.log(`[handleVariantSelection] Zmieniono wariant na: ${radio.value} w formularzu`, form);

    // ✅ KLUCZOWA POPRAWKA: Usuń 'selected' TYLKO z tego formularza
    form.querySelectorAll('.variant-option').forEach(option => {
        option.classList.remove('selected');
    });

    // Dodaj 'selected' do wybranego wariantu
    const selectedOption = radio.closest('.variant-option');
    if (selectedOption && radio.checked) {
        selectedOption.classList.add('selected');
        console.log(`[handleVariantSelection] ✅ Dodano klasę 'selected' do wariantu: ${radio.value}`);
    }

    // Wywołaj aktualizację cen
    updatePrices();
}

/**
 * Inicjalizacja po załadowaniu DOM
 */
document.addEventListener('DOMContentLoaded', function () {
    // Poczekaj na załadowanie kalkulatora
    setTimeout(() => {
        if (typeof quoteFormsContainer !== 'undefined' && quoteFormsContainer) {
            initializeVariantAvailability();
            console.log("[DOMContentLoaded] ✅ Zainicjalizowano dostępność wariantów");
        }
    }, 500);
});

// ============ EXPORT FUNCTIONS ============

// Eksportuj funkcje do użycia w innych plikach
window.variantAvailability = {
    initialize: initializeVariantAvailability,
    setDefault: setDefaultVariantAvailability,
    copy: copyVariantAvailability,
    validate: validateAvailableVariants,
    filter: filterAvailableVariantsForSave,
    getAvailable: getAvailableVariants
};
function scrollToLatestProduct() {
    const container = document.getElementById('products-summary-container');
    if (container) {
        // Scroll do dołu kontenera po dodaniu nowego produktu
        container.scrollTop = container.scrollHeight;
    }
}

document.addEventListener('DOMContentLoaded', function() {
    console.log("🔧 Inicjalizuję poprawki resetowania wariantów...");
    function initializeAddProductButton() {
        const addProductBtn = document.getElementById('add-product-btn');
        if (addProductBtn) {
            addProductBtn.addEventListener('click', addNewProduct);
            console.log('[initializeAddProductButton] Przycisk dodawania produktu został zainicjalizowany');
        } else {
            console.warn('[initializeAddProductButton] Nie znaleziono przycisku #add-product-btn');
        }
    }

    // Wymuś reinicjalizację event listenerów po krótkim opóźnieniu
    setTimeout(() => {
        reinitializeAllEventListeners();
        
        // Dodatkowe odświeżenie
        if (typeof updateCalculateDeliveryButtonState === 'function') {
            updateCalculateDeliveryButtonState();
        }
        if (typeof generateProductsSummary === 'function') {
            generateProductsSummary();
        }
        if (typeof updatePrices === 'function') {
            updatePrices();
        }
    }, 500);

    initializeAddProductButton();

    // Okresowe sprawdzanie radio buttonów
    setInterval(() => {
        checkRadioButtonIntegrity();
    }, 100000); // Co 100 sekund

    setInterval(() => {
        // Sprawdź czy są problemy z klasami selected
        const allForms = quoteFormsContainer.querySelectorAll('.quote-form');
        let hasIssues = false;

        allForms.forEach(form => {
            const selectedCount = form.querySelectorAll('.variant-option.selected').length;
            const checkedCount = form.querySelectorAll('input[type="radio"]:checked').length;

            if (selectedCount !== checkedCount) {
                hasIssues = true;
            }
        });

        if (hasIssues) {
            console.log("🔧 Wykryto problemy z klasami 'selected' - naprawiam...");
            fixSelectedClasses();
        }
    }, 5000); // Co 5 sekund

    // Dodaj globalną funkcję do debugowania
    window.debugRadioButtons = checkRadioButtonIntegrity;

    console.log("✅ Poprawki resetowania wariantów zostały zainicjalizowane!");
});

// ========== KONIEC POPRAWEK ==========

console.log("✅ Poprawki resetowania wariantów zostały załadowane!");

/**
* Zatrzymuje system backup przed opuszczeniem strony
*/
function cleanupBeforeUnload() {
    if (quoteDraftBackup) {
        quoteDraftBackup.stopAutoSave();
        console.log('[Calculator] System backup zatrzymany przed opuszczeniem strony');
    }
}

// Event listener dla czyszczenia przed opuszczeniem strony
window.addEventListener('beforeunload', cleanupBeforeUnload);