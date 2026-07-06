// calculator-events.js
// Moduł eventów - listenery formularzy, walidacja, modal pobierania, edge3D

/**
 * Znajdź nazwę grupy cenowej na podstawie ID z bazy danych
 */
function getDefaultClientTypeForId(targetId) {
    const multipliersDataEl = document.getElementById('multipliers-data');
    if (multipliersDataEl) {
        try {
            const multipliersFromDB = JSON.parse(multipliersDataEl.textContent);
            const defaultGroup = multipliersFromDB.find(m => m.id === targetId);
            if (defaultGroup) {
                return defaultGroup.label;
            }
        } catch (e) {
            // ignoruj błąd parsowania
        }
    }
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
        return;
    }

    // ✅ ZMIENIONE: Różnicuj standardowych i flexible partnerów
    const isFlexiblePartner = document.body.dataset.flexiblePartner === 'true';

    // Standardowi partnerzy nie używają selecta (mają fixed multiplier)
    if (isPartner && !isFlexiblePartner) {
        return;
    }

    // ✅ NOWE: Różny domyślny mnożnik dla flexible partners
    const FLEXIBLE_PARTNER_DEFAULT_MULTIPLIER_ID = 11;  // Domyślny mnożnik dla flexible partners — Czernecki (1.05)

    let defaultMultiplierId;
    if (isFlexiblePartner) {
        defaultMultiplierId = FLEXIBLE_PARTNER_DEFAULT_MULTIPLIER_ID;
    } else {
        defaultMultiplierId = DEFAULT_MULTIPLIER_ID;
    }

    const defaultClientType = getDefaultClientTypeForId(defaultMultiplierId);

    if (defaultClientType && multiplierMapping[defaultClientType]) {
        clientTypeSelect.value = defaultClientType;
    }
}

/**
 * Dodaje listenery do formularza wyceny
 */
function attachFormListeners(form) {
    if (!form) return;

    // ✅ NOWA POPRAWKA: Zachowaj aktualną grupę cenową przed dodaniem listeners
    const currentClientType = form.querySelector('select[data-field="clientType"]')?.value;

    // POPRAWNE ROZWIĄZANIE - bez klonowania
    const inputs = form.querySelectorAll('input[data-field], select[data-field]');
    inputs.forEach(input => {
        // Usuń poprzednie listenery bezpośrednio
        input.removeEventListener('input', updatePrices);
        input.removeEventListener('change', updatePrices);

        // Oznacz pole jako "touched" po opuszczeniu — potrzebne do walidacji
        if (!input._blurTouchedAttached) {
            input.addEventListener('blur', function () {
                this.dataset.touched = 'true';
            });
            input._blurTouchedAttached = true;
        }

        // Dodaj nowe listenery
        if (input.matches('input[data-field]')) {
            input.addEventListener('input', updatePrices);
        } else if (input.matches('select[data-field]')) {
            input.addEventListener('change', updatePrices);
        }
    });

    // ✅ POPRAWKA: Dodaj listenery dla radio buttons z obsługą klasy 'selected'
    attachVariantSelectionListeners(form);

    // ✅ NOWE: Dodaj walidację długości i szerokości dla tego formularza
    attachLengthValidation(form);
    attachWidthValidation(form);
    attachThicknessValidation(form);
    attachQuantityValidation(form);

    // Oznacz formularz jako mający event listenery
    form.dataset.listenersAttached = "true";

    // Dodaj obsługę wykończenia
    attachFinishingUIListeners(form);

    // Na końcu funkcji, PRZYWRÓĆ grupę cenową jeśli została przypadkowo zresetowana
    if (currentClientType && !isPartner) {
        const clientTypeSelect = form.querySelector('select[data-field="clientType"]');
        if (clientTypeSelect && clientTypeSelect.value !== currentClientType) {
            clientTypeSelect.value = currentClientType;
        }
    }
}

/**
 * Synchronizuje grupę cenową na wszystkich produktach
 */
function syncClientTypeAcrossProducts(selectedType, sourceForm) {

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
        }
    });

    // Przelicz ceny z zachowaniem aktywnego formularza
    const originalActiveForm = activeQuoteForm;

    allForms.forEach(form => {
        activeQuoteForm = form;
    });

    activeQuoteForm = originalActiveForm;

    // Backend liczy wszystkie produkty w jednym request — jedno wywołanie
    // po pętli wystarczy (zamiast N wywołań, po jednym na formularz).
    updatePricesNow();

    // ✅ PRZYWRÓĆ stany po przeliczeniu - POPRAWIONE
    preservedStates.forEach(state => {
        state.checkedRadios.forEach(radioData => {
            const radio = state.form.querySelector(`input[value="${radioData.value}"]`);
            if (radio) {
                radio.checked = true;

                // ✅ POPRAWKA: Użyj NOWYCH cen z radio.dataset (przeliczonych przez updatePrices)
                // zamiast starych wartości z preservedStates
                if (radio.dataset.totalBrutto && radio.dataset.totalNetto) {
                    state.form.dataset.orderBrutto = radio.dataset.totalBrutto;
                    state.form.dataset.orderNetto = radio.dataset.totalNetto;
                }

                // Przywróć kolor
                const selectedVariant = radio.closest('div');
                if (selectedVariant) {
                    selectedVariant.querySelectorAll('*').forEach(el => el.style.color = "#ED6B24");
                }
            }
        });
    });

    // ✅ POPRAWKA: Przelicz podsumowanie po przywróceniu stanów
    updateGlobalSummary();

    // ✅ POPRAWKA: Napraw klasy 'selected' po synchronizacji
    setTimeout(() => {
        fixSelectedClasses();
    }, 100);

}

/**
 * Obsługa zmiany grupy cenowej
 */
function handleClientTypeChange(event) {
    const selectedType = event.target.value;
    const sourceForm = event.target.closest('.quote-form');


    // Synchronizuj z innymi produktami
    syncClientTypeAcrossProducts(selectedType, sourceForm);
}

/**
 * Przełącza widoczność kolumny kąta w tabeli edge3d
 */
function toggleAngleColumn(show) {
    const table = document.getElementById('edge3d-table');
    if (!table) return;
    const headerCell = table.querySelector('.edge3d-header .edge3d-cell:nth-child(4)');
    if (headerCell) headerCell.style.visibility = show ? 'visible' : 'hidden';
}

/**
 * Delegacja: podświetlenie krawędzi w 3D i aktualizacja edgeSettings przy zmianie inputa
 */
function onEdgeInputChange(e) {
    const input = e.target;
    const row = input.closest('.edge3d-row');
    if (!row) return;
    const key = row.querySelector('.edge3d-cell').textContent.trim();

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
 * Delegacja: ustaw typ obróbki krawędzi i renderuj ponownie
 */
function onTypeButtonClick(e) {
    const btn = e.currentTarget;
    const key = btn.dataset.edgeKey;
    const type = btn.dataset.type;

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

// Zmienne do śledzenia ostatnich wymiarów i ustawień (cache 3D)
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
 * UWAGA: Stary kod - edges module używa teraz .open-edges-modal-btn z event delegation w edges.js
 */
function initEdge3D() {
    // Noop - obsługa przeniesiona do EdgesModule w edges.js
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
 * Walidacja wymiaru — dynamiczne limity z cennika.
 * @param {HTMLElement} form
 * @param {string} fieldName - np. "length", "width", "thickness"
 * @param {string} errorClass - np. "error-message-length"
 * @param {string} label - np. "Długość", "Szerokość", "Grubość"
 * @param {string} limitMinKey - klucz w getPricingLimits(), np. "length_min"
 * @param {string} limitMaxKey - klucz w getPricingLimits(), np. "length_max"
 */
function attachDimensionValidation(form, fieldName, errorClass, label, limitMinKey, limitMaxKey) {
    if (!form) return;

    const input = form.querySelector(`input[data-field="${fieldName}"]`);
    if (!input) return;

    input.removeEventListener('input', input._validationHandler);

    input._validationHandler = function () {
        const val = parseFloat(this.value);
        let errorSpan = this.parentNode.querySelector('.' + errorClass);
        const limits = window.CalculatorCore.getPricingLimits();

        if (!limits) {
            if (errorSpan) errorSpan.remove();
            return;
        }

        var currentForm = this.closest('.quote-form');
        var shape = currentForm ? (currentForm.dataset.productShape || 'rectangular') : 'rectangular';

        var min = limits[limitMinKey];
        var max = limits[limitMaxKey];
        var displayLabel = label;

        // Koło: średnica musi mieścić się w obu zakresach
        if (shape === 'circle' && fieldName === 'length') {
            max = Math.min(limits.length_max, limits.width_max);
            min = Math.max(limits.length_min, limits.width_min);
            displayLabel = 'Średnica';
        }

        // Koło: pomijaj walidację width (obsługiwana przez length)
        if (shape === 'circle' && fieldName === 'width') {
            if (errorSpan) errorSpan.remove();
            this.classList.remove('error-outline');
            return;
        }

        if (!isNaN(val) && (val < min || val > max)) {
            if (!errorSpan) {
                errorSpan = document.createElement('span');
                errorSpan.classList.add(errorClass);
                errorSpan.style.color = 'red';
                errorSpan.style.fontSize = '12px';
                errorSpan.style.display = 'block';
                errorSpan.style.marginTop = '4px';
                this.parentNode.appendChild(errorSpan);
            }
            errorSpan.textContent = `${displayLabel} poza zakresem ${min}-${max} cm.`;
            this.classList.add('error-outline');
        } else {
            if (errorSpan) errorSpan.remove();
            this.classList.remove('error-outline');
        }
    };

    input.addEventListener('input', input._validationHandler);
}

function attachLengthValidation(form) {
    attachDimensionValidation(form, 'length', 'error-message-length', 'Długość', 'length_min', 'length_max');
}

function attachWidthValidation(form) {
    attachDimensionValidation(form, 'width', 'error-message-width', 'Szerokość', 'width_min', 'width_max');
}

function attachThicknessValidation(form) {
    attachDimensionValidation(form, 'thickness', 'error-message-thickness', 'Grubość', 'thickness_min', 'thickness_max');
}

/**
 * Walidacja ilości — minimum 1 szt, ale pozwalamy na puste pole i 0
 * (wygoda na telefonie — mozna skasowac i wpisac nowa wartosc)
 */
function attachQuantityValidation(form) {
    if (!form) return;

    const input = form.querySelector('input[data-field="quantity"]');
    if (!input) return;

    // Kontener .quantity (nie .quantity-stepper) dla error message
    const quantityWrapper = input.closest('.quantity');

    input.removeEventListener('input', input._quantityValidationHandler);

    input._quantityValidationHandler = function () {
        const val = parseInt(this.value);
        let errorSpan = quantityWrapper ? quantityWrapper.querySelector('.error-message-quantity') : null;

        if (this.value === '' || (!isNaN(val) && val < 1)) {
            if (!errorSpan && quantityWrapper) {
                errorSpan = document.createElement('span');
                errorSpan.classList.add('error-message-quantity');
                errorSpan.style.color = 'red';
                errorSpan.style.fontSize = '12px';
                errorSpan.style.display = 'block';
                errorSpan.style.marginTop = '4px';
                quantityWrapper.appendChild(errorSpan);
            }
            if (errorSpan) errorSpan.textContent = 'Ilość musi wynosić minimum 1 szt.';
            this.classList.add('error-outline');
        } else {
            if (errorSpan) errorSpan.remove();
            this.classList.remove('error-outline');
        }
    };

    input.addEventListener('input', input._quantityValidationHandler);

    // Przyciski +/− steppera
    const minusBtn = form.querySelector('.qty-minus');
    const plusBtn = form.querySelector('.qty-plus');

    if (minusBtn && !minusBtn._qtyHandler) {
        minusBtn._qtyHandler = function () {
            const cur = parseInt(input.value) || 1;
            if (cur > 1) {
                input.value = cur - 1;
                input.dispatchEvent(new Event('input', { bubbles: true }));
            }
        };
        minusBtn.addEventListener('click', minusBtn._qtyHandler);
    }

    if (plusBtn && !plusBtn._qtyHandler) {
        plusBtn._qtyHandler = function () {
            const cur = parseInt(input.value) || 0;
            input.value = cur + 1;
            input.dispatchEvent(new Event('input', { bubbles: true }));
        };
        plusBtn.addEventListener('click', plusBtn._qtyHandler);
    }
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
 * Bezpieczne dodawanie listenerów z zachowaniem wartości formularza
 */
function safeAttachFormListeners(form) {
    if (!form) return;

    // Sprawdź czy listenery już zostały dodane
    if (form.dataset.listenersAttached === "true") {
        return;
    }


    // ✅ KLUCZOWA POPRAWKA: Zachowaj wszystkie wartości formularza przed manipulacją
    const formValues = {};

    // Zapisz wartości input i select (pomiń select kształtu - zarządzane przez initShapeToggle)
    form.querySelectorAll('input[data-field], select[data-field]').forEach(input => {
        if (input.dataset.field === 'shapeSelect') return;
        const key = input.id || input.name || input.dataset.field;
        if (input.type === 'checkbox' || input.type === 'radio') {
            formValues[key] = input.checked;
        } else {
            formValues[key] = input.value;
        }
    });

    // Zapisz wartości radio buttons (pomiń select kształtu)
    form.querySelectorAll('input[type="radio"]').forEach(radio => {
        if (radio.dataset.field === 'shapeSelect') return;
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


    // ✅ NOWA POPRAWKA: Dodaj listenery dla inputów BEZ klonowania
    const inputs = form.querySelectorAll('input[data-field], select[data-field]');
    inputs.forEach(input => {
        // Pomiń radio buttony kształtu (obsługiwane przez initShapeToggle)
        if (input.type === 'radio') return;

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

    // Dodaj listenery dla radio buttons wariantów BEZ klonowania
    // (kształt obsługiwany przez ShapeEditor)
    const radios = form.querySelectorAll('.variants input[type="radio"]');
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
                // oraz kaskadowo resetuj niższe poziomy
                if (this.dataset.finishingType) {
                    // Poziom 1: Rodzaj wykończenia - resetuj też wariant i kolor
                    const sameTypeButtons = parentForm.querySelectorAll(`[data-finishing-type]`);
                    sameTypeButtons.forEach(b => b.classList.remove('active'));

                    // Kaskadowe resetowanie: odznacz wariant wykończenia
                    const variantButtons = parentForm.querySelectorAll(`[data-finishing-variant]`);
                    variantButtons.forEach(b => b.classList.remove('active'));

                    // Kaskadowe resetowanie: odznacz kolor
                    const colorButtons = parentForm.querySelectorAll('.color-btn');
                    colorButtons.forEach(b => b.classList.remove('active'));

                } else if (this.dataset.finishingVariant) {
                    // Poziom 2: Podrodzaj wykończenia - resetuj też kolor
                    const sameTypeButtons = parentForm.querySelectorAll(`[data-finishing-variant]`);
                    sameTypeButtons.forEach(b => b.classList.remove('active'));

                    // Kaskadowe resetowanie: odznacz kolor
                    const colorButtons = parentForm.querySelectorAll('.color-btn');
                    colorButtons.forEach(b => b.classList.remove('active'));

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

    // Przywróć wartości input i select (pomiń select kształtu)
    form.querySelectorAll('input[data-field], select[data-field]').forEach(input => {
        if (input.dataset.field === 'shapeSelect') return;
        const key = input.id || input.name || input.dataset.field;
        const savedValue = formValues[key];

        if (savedValue !== undefined) {
            if (input.type === 'checkbox' || input.type === 'radio') {
                input.checked = savedValue;
            } else {
                input.value = savedValue;
            }
        }
    });

    // Przywróć stany radio buttons (pomiń select kształtu)
    form.querySelectorAll('input[type="radio"]').forEach(radio => {
        if (radio.dataset.field === 'shapeSelect') return;
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

}

/**
 * Inicjalizacja modala pobierania wyceny (PDF/PNG)
 */
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

    if (!modal) {
        return;
    }

    if (!iframe) {
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

            if (!quoteToken) {
                return;
            }

            // Ustaw nowy quote token
            currentQuoteToken = quoteToken;
            isLoadingPdf = true;

            // ZMIANA: Przygotuj URL PDF z tokenem
            const pdfUrl = `/quotes/api/quotes/${quoteToken}/pdf.pdf`;

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

            // DODAJ obserwatora zmian iframe.src
            const srcObserver = setInterval(() => {
                if (isLoadingPdf && currentQuoteToken) {
                    const currentSrc = iframe.src;
                    if (currentSrc && !currentSrc.includes('/pdf.pdf') && !currentSrc.includes('about:blank')) {
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
        });
    }

    // ZMIANA: Pobieranie PDF z tokenem
    if (downloadPDF) {
        downloadPDF.addEventListener("click", (e) => {
            e.preventDefault();
            const quoteToken = downloadPDF.dataset.token || currentQuoteToken;
            if (quoteToken) {
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
        }
    });

    // POPRAWIONA detekcja ładowania - z ochroną przed resetowaniem
    iframe.addEventListener('load', function handleIframeLoad() {

        // Sprawdź czy to nasze PDF i czy aktualnie ładujemy
        if (isLoadingPdf && iframe.src.includes('/pdf.pdf') && currentQuoteToken) {
            iframe.style.background = "none";
            iframe.style.animation = "none";
            isLoadingPdf = false;

            if (loadingTimeout) {
                clearTimeout(loadingTimeout);
                loadingTimeout = null;
            }
        } else if (isLoadingPdf && (iframe.src === window.location.href || iframe.src.includes('/calculator/'))) {
            // Jeśli iframe zostało zresetowane, przywróć PDF URL
            const pdfUrl = `/quotes/api/quotes/${currentQuoteToken}/pdf.pdf`;

            // Dodaj krótkie opóźnienie aby uniknąć natychmiastowego ponownego resetu
            setTimeout(() => {
                if (isLoadingPdf && currentQuoteToken) {
                    iframe.src = pdfUrl;
                }
            }, 100);
        }
    });

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

            showIframeFallback(iframe, pdfUrl);
        }
    } catch (e) {
        // W przypadku CORS nie możemy sprawdzić zawartości, więc zakładamy że działa
    }
}

/**
 * Funkcja pomocnicza - pokazuje fallback gdy iframe nie działa
 */
function showIframeFallback(iframe, pdfUrl) {

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

/**
 * Przekierowuje do modułu quotes i otwiera modal szczegółów wyceny
 * @param {number} quoteId - ID wyceny
 */
function redirectToQuoteDetails(quoteId) {

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

    redirectToQuoteDetailsByNumber(quoteNumber);
}

/**
 * Reinicjalizuje event listenery we wszystkich formularzach
 */
function reinitializeAllEventListeners() {

    const allForms = quoteFormsContainer.querySelectorAll('.quote-form');
    allForms.forEach((form, index) => {

        // Usuń oznaczenie o event listenerach
        delete form.dataset.listenersAttached;

        // Dodaj event listenery
        safeAttachFormListeners(form);
    });

}

/**
 * Zatrzymuje system backup przed opuszczeniem strony
 */
function cleanupBeforeUnload() {
    if (window.quoteDraftBackup) {
        window.quoteDraftBackup.stopAutoSave();
    }
}

// Event listener dla czyszczenia przed opuszczeniem strony
window.addEventListener('beforeunload', cleanupBeforeUnload);

// Eksport funkcji jako globalny obiekt
window.CalculatorEvents = {
    getDefaultClientTypeForId,
    setDefaultClientType,
    attachFormListeners,
    syncClientTypeAcrossProducts,
    handleClientTypeChange,
    toggleAngleColumn,
    onEdgeInputChange,
    onTypeButtonClick,
    maybeRender3D,
    renderEdgeInputs,
    initEdge3D,
    attachDownloadModalClose,
    attachDownloadFormatButtons,
    attachLengthValidation,
    attachWidthValidation,
    attachThicknessValidation,
    attachGlobalValidationListeners,
    safeAttachFormListeners,
    initCalculatorDownloadModal,
    checkIframeLoading,
    showIframeFallback,
    redirectToQuoteDetails,
    redirectToQuoteDetailsByNumber,
    handleGoToQuoteFromModal,
    reinitializeAllEventListeners,
    cleanupBeforeUnload
};
