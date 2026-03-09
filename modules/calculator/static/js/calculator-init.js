// calculator-init.js
// Moduł inicjalizacyjny - orkiestruje uruchomienie kalkulatora
/**
 * Main init on DOMContentLoaded
 */
function init() {
    function initMainContainer() {
        mainContainer = document.querySelector('.products-summary-main');
    }

    // Załaduj ceny wykończeń z bazy danych i ustawienia kalkulatora
    loadFinishingPrices();
    loadCalculatorSettings();

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
    multiplierMapping = {};
    const multipliersDataEl = document.getElementById('multipliers-data');
    if (multipliersDataEl) {
        try {
            const multipliersFromDB = JSON.parse(multipliersDataEl.textContent);
            multipliersFromDB.forEach(m => {
                multiplierMapping[m.label] = m.value;
            });
        } catch (e) {
            // Ignore JSON parse errors for multipliers data
        }
    }

    // ✅ ZMIENIONE: Różnicuj standardowych i flexible partnerów
    const isFlexiblePartner = document.body.dataset.flexiblePartner === 'true';

    if (isPartner && !isFlexiblePartner) {
        // Standardowy partner - używa tylko swojego mnożnika (fixed)
        currentClientType = document.body.dataset.clientType || null;
        currentMultiplier = userMultiplier;
    } else if (isPartner && isFlexiblePartner) {
        // ✅ NOWE: Flexible partner - ustaw domyślny mnożnik ID=5
        const FLEXIBLE_PARTNER_DEFAULT_MULTIPLIER_ID = 5;
        const defaultClientType = getDefaultClientTypeForId(FLEXIBLE_PARTNER_DEFAULT_MULTIPLIER_ID);

        if (defaultClientType && multiplierMapping[defaultClientType]) {
            currentClientType = defaultClientType;
            currentMultiplier = multiplierMapping[defaultClientType];
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
    edgesSummaryEls.brutto = document.querySelector('.quote-summary .edges-brutto');
    edgesSummaryEls.netto = document.querySelector('.quote-summary .edges-netto');

    const populateMultiplierSelects = () => {
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
            }

            // Ustaw domyślną wartość dla partnerów
            if (currentValue) {
                select.value = currentValue;
            } else {
                // Ustaw domyślną grupę cenową dla nie-partnerów
                if (!isPartner) {
                    const defaultClientType = getDefaultClientTypeForId(DEFAULT_MULTIPLIER_ID);
                    if (defaultClientType && multiplierMapping[defaultClientType]) {
                        select.value = defaultClientType;
                    }
                }

                // Ustaw domyślną wartość dla partnerów (istniejący kod)
                if (isPartner && currentClientType && !currentValue) {
                    select.value = currentClientType;
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
            form.classList.toggle('hidden', i !== index);
        });
    }

    document.addEventListener('click', e => {
        const removeBtn = e.target.closest('.remove-product');
        if (removeBtn) {
            if (!activeQuoteForm) {
                return;
            }
            const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
            const index = forms.indexOf(activeQuoteForm);
            if (index === -1) {
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
    initCalculatorDownloadModal();
    attachDownloadModalClose();
    attachDownloadFormatButtons();
    attachGlobalValidationListeners();
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
                syncClientTypeAcrossProducts(selectedType, sourceForm);
            }
        }
    });

    window.multiplierMapping = multiplierMapping;
    window.isPartner = isPartner;
    window.userMultiplier = userMultiplier;

    generateProductsSummary();
    // Aktywuj pierwszy produkt
    if (quoteFormsContainer.querySelector('.quote-form')) {
        activateProductCard(0);
    }

    // Inicjalizacja systemu backup wycen (wylaczony w trybie edycji wyceny)
    const _editModeParams = new URLSearchParams(window.location.search);
    const _isQuoteEditMode = _editModeParams.has('edit_quote');

    if (_isQuoteEditMode) {
        // Pokaz informacje w badge
        const _badge = document.getElementById('draftStatusBadge');
        const _text = document.getElementById('draftStatusText');
        const _textWrap = document.getElementById('draftStatusTextWrap');
        const _saveBtn = document.getElementById('draftSaveBtn');
        const _separator = _badge?.querySelector('.draft-status-separator');
        const _time = document.getElementById('draftStatusTime');
        if (_badge) _badge.classList.add('unsaved');
        if (_text) _text.innerHTML = 'Edycja wyceny — <strong>kopia zapasowa nieaktywna</strong>';
        if (_textWrap) _textWrap.style.width = _text.scrollWidth + 'px';
        if (_saveBtn) _saveBtn.style.display = 'none';
        if (_separator) _separator.style.display = 'none';
        if (_time) _time.style.display = 'none';
    } else if (typeof QuoteDraftBackup !== 'undefined') {
        const userId = document.body.dataset.userId;
        if (userId) {
            quoteDraftBackup = new QuoteDraftBackup();
            quoteDraftBackup.init(parseInt(userId));
        }
    }

    setTimeout(() => {
        const firstForm = quoteFormsContainer.querySelector('.quote-form');
        if (firstForm) {
            const clientTypeSelect = firstForm.querySelector('select[data-field="clientType"]');
            if (clientTypeSelect && !clientTypeSelect.value && !isPartner) {
                setDefaultClientType(firstForm, false);
            }
        }
    }, 100);

    // Inicjalizuj przełącznik brutto/netto
    initPriceModeToggle();

    // Inicjalizuj toggle kształtu dla pierwszego formularza
    const initialForm = quoteFormsContainer?.querySelector('.quote-form');
    if (initialForm) {
        initShapeToggle(initialForm);
    }

    // Inicjalizacja trybu edycji wyceny
    if (typeof QuoteEditLoader !== 'undefined') {
        const quoteEditLoader = new QuoteEditLoader();
        quoteEditLoader.init();
    }

}

// Główny listener uruchamiający inicjalizację po załadowaniu DOM
document.addEventListener('DOMContentLoaded', init);

// Wyliczanie wysokości sidebara na podstawie elementów nad nim
document.addEventListener('DOMContentLoaded', function () {
    const sidebar = document.querySelector('.calculator-sidebar');
    const headerRow = document.querySelector('.calculator-header-row');
    const calculatorrr = document.querySelector('.calculatorrr');
    if (!sidebar || !headerRow || !calculatorrr) return;

    function calcSidebarHeight() {
        if (window.innerWidth <= 768) {
            sidebar.style.maxHeight = '';
            return;
        }
        const gap = parseFloat(getComputedStyle(calculatorrr).gap) || 15;
        const headerH = headerRow.offsetHeight;
        // main-content padding-top
        const mainContent = document.querySelector('.main-content');
        const paddingTop = mainContent ? parseFloat(getComputedStyle(mainContent).paddingTop) || 0 : 0;
        const offset = paddingTop + headerH + gap * 2;
        sidebar.style.maxHeight = 'calc(100dvh - ' + offset + 'px)';
    }

    calcSidebarHeight();
    window.addEventListener('resize', calcSidebarHeight);
});

// Inicjalizacja dostępności wariantów po załadowaniu DOM
document.addEventListener('DOMContentLoaded', function () {
    // Poczekaj na załadowanie kalkulatora
    setTimeout(() => {
        if (typeof quoteFormsContainer !== 'undefined' && quoteFormsContainer) {
            initializeVariantAvailability();
        }
    }, 500);
});

// Inicjalizacja poprawek resetowania wariantów i dodatkowych listenerów
document.addEventListener('DOMContentLoaded', function() {
    function initializeAddProductButton() {
        const addProductBtn = document.getElementById('add-product-btn');
        if (addProductBtn) {
            addProductBtn.addEventListener('click', addNewProduct);
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
        // Uruchom updatePrices tylko jeśli formularz ma wypełnione wymiary
        // (unikamy czerwonych obwódek na pustym formularzu przy starcie)
        if (typeof updatePrices === 'function') {
            const firstForm = document.querySelector('.quote-form');
            const hasLength = firstForm && firstForm.querySelector('input[data-field="length"]')?.value;
            if (hasLength) {
                updatePrices();
            }
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
            const checkedCount = form.querySelectorAll('.variants input[type="radio"]:checked').length;

            if (selectedCount !== checkedCount) {
                hasIssues = true;
            }
        });

        if (hasIssues) {
            fixSelectedClasses();
        }
    }, 5000); // Co 5 sekund

    // Dodaj globalną funkcję do debugowania
    window.debugRadioButtons = checkRadioButtonIntegrity;

});
