/**
 * Moduł zarządzania produktami i dostępnością wariantów
 * Wyodrębniony z calculator.js - funkcje zarządzania produktami,
 * kartami produktów, duplikacją, usuwaniem oraz dostępnością wariantów.
 */


// ============ FUNKCJE ZARZĄDZANIA PRODUKTAMI ============

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


    // Usuń sklonowany przełącznik brutto/netto (jeśli istnieje)
    const clonedPriceToggle = form.querySelector('.price-mode-toggle');
    if (clonedPriceToggle) {
        clonedPriceToggle.remove();
    }

    // KROK 1: Zachowaj aktualną grupę cenową PRZED resetowaniem
    const currentClientType = form.querySelector('select[data-field="clientType"]')?.value;

    // KROK 2: POPRAWKA - Unikalne ID i name dla radio buttons wariantów
    form.querySelectorAll('.variants input[type="radio"]').forEach((radio, radioIndex) => {
        const baseId = radio.value || `variant-${radioIndex}`;

        // ✅ POPRAWKA: Ustaw poprawne ID i name
        const newId = `${baseId}-product-${index}`;
        const newName = `variant-product-${index}`;  // ✅ Konsistentna nazwa
        const oldId = radio.id;


        // Ustaw nowe ID i name
        radio.id = newId;
        radio.name = newName;
        radio.checked = false; // Reset zaznaczenia

        // ✅ POPRAWKA: Aktualizuj powiązany label
        const label = form.querySelector(`label[for="${oldId}"]`);
        if (label) {
            label.setAttribute('for', newId);
        }
    });

    // KROK 3: Resetuj wszystkie inputy wymiarów (pomiń radio buttony kształtu)
    form.querySelectorAll('input[data-field]').forEach(input => {
        if (input.type === 'radio') return; // Nie resetuj radio (kształt obsługiwany osobno)
        input.value = input.dataset.field === 'quantity' ? '1' : '';
    });

    // KROK 4: Resetuj selecty ale ZACHOWAJ grupę cenową
    form.querySelectorAll('select[data-field]').forEach(select => {
        if (select.dataset.field === 'clientType') {
            if (currentClientType) {
                // Przywróć istniejącą grupę cenową
                select.value = currentClientType;
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

    // ✅ Resetuj wszystkie dane wykończenia (każdy produkt ma indywidualne wykończenie)
    form.dataset.finishingType = 'Surowe';
    form.dataset.finishingVariant = '';
    form.dataset.finishingColor = '';
    form.dataset.finishingFullPath = 'Surowe';
    form.dataset.finishingOptionId = '';
    form.dataset.finishingBrutto = '';
    form.dataset.finishingNetto = '';

    // ✅ Resetuj dane obróbki krawędzi (każdy produkt ma indywidualną obróbkę)
    delete form.dataset.edgesData;
    delete form.dataset.edgesNetto;
    delete form.dataset.edgesBrutto;
    delete form.dataset.edgesCount;
    delete form.dataset.edgesType;
    delete form.dataset.edgesRValue;
    delete form.dataset.edgesSvg;

    // ✅ Resetuj wizualnie podsumowanie wykończenia
    const finishingOptionsSummary = form.querySelector('.finishing-options-summary');
    if (finishingOptionsSummary) {
        finishingOptionsSummary.style.display = 'none';
        const finishingRow = finishingOptionsSummary.querySelector('.finishing-row');
        if (finishingRow) {
            finishingRow.style.display = 'none';
        }
    }

    // ✅ Resetuj wizualnie podsumowanie krawędzi
    const edgesOptionsSummary = form.querySelector('.edges-options-summary');
    if (edgesOptionsSummary) {
        edgesOptionsSummary.style.display = 'none';
        const edgesRow = edgesOptionsSummary.querySelector('.edges-row');
        if (edgesRow) {
            edgesRow.style.display = 'none';
            const textEl = edgesRow.querySelector('.edges-summary-text');
            const priceEl = edgesRow.querySelector('.edges-summary-price');
            if (textEl) textEl.textContent = '';
            if (priceEl) priceEl.textContent = '';
        }
    }

    // ✅ Przywróć oryginalny tekst przycisku obróbki krawędzi i ustaw disabled
    const edgesBtn = form.querySelector('.open-edges-modal-btn');
    if (edgesBtn) {
        edgesBtn.textContent = '+ Dodaj';
        edgesBtn.disabled = true;
        edgesBtn.classList.add('disabled');
        edgesBtn.title = 'Uzupełnij wszystkie wymiary (długość, szerokość, grubość)';
    }

    // ✅ Resetuj kolory wariantów
    form.querySelectorAll('.variant-option').forEach(option => {
        option.style.backgroundColor = '';
        option.querySelectorAll('*').forEach(el => {
            el.style.color = '';
        });
    });

    // ✅ Resetuj kształt produktu na prostokątny
    form.dataset.productShape = 'rectangular';
    delete form.dataset.shapeListenersAttached; // Pozwól initShapeToggle dodać nowe listenery
    const shapeRadios = form.querySelectorAll('input[data-field="shapeRect"], input[data-field="shapeRound"]');
    shapeRadios.forEach(radio => {
        radio.name = `productShape-${index}`;
        radio.checked = (radio.value === 'rectangular');
    });
    initShapeToggle(form);

    // ✅ Usuń oznaczenie o dodanych event listenerach
    delete form.dataset.listenersAttached;

}

/**
 * Sprawdza czy produkt jest kompletny
 */
function checkProductCompleteness(form) {
    if (!form) return false;

    const length = form.querySelector('[data-field="length"]')?.value;
    const width = form.querySelector('[data-field="width"]')?.value;
    const thickness = form.querySelector('[data-field="thickness"]')?.value;
    const quantity = form.querySelector('[data-field="quantity"]')?.value;

    // Sprawdź zaznaczony wariant (tylko w sekcji .variants)
    const variant = form.querySelector('.variants input[type="radio"]:checked');

    if (!(length && width && thickness && quantity && variant)) return false;

    // Walidacja wykończenia - wybór musi być kompletny
    if (!checkFinishingCompleteness(form)) return false;

    return true;
}

function checkFinishingCompleteness(form) {
    // Sprawdź czy ostatni wybrany przycisk w drzewku ma nierozwinięte dzieci
    const container = form.querySelector('.finishing-tree-container');
    if (!container) return true;

    // Znajdź ostatni aktywny przycisk (najgłębszy poziom)
    const allActiveBtns = container.querySelectorAll('.finishing-option-btn.active');
    if (allActiveBtns.length === 0) return true;

    const lastActiveBtn = allActiveBtns[allActiveBtns.length - 1];
    const optionId = lastActiveBtn.dataset.optionId;
    const options = window.finishingOptionsFlat || [];

    // Jeśli ten przycisk ma dzieci w drzewie opcji — wybór jest niekompletny
    const hasChildren = options.some(opt => String(opt.parent_id) === String(optionId));
    if (hasChildren) return false;

    // Jeśli sekcja połysku jest widoczna — musi być wybrany stopień połysku
    const glossLevel = container.querySelector('.finishing-level-gloss');
    if (glossLevel && glossLevel.style.display !== 'none') {
        const glossSelected = glossLevel.querySelector('.finishing-gloss-btn.active');
        if (!glossSelected) return false;
    }

    return true;
}

/**
 * Duplikuje produkt na podstawie indeksu źródłowego
 */

function duplicateProduct(sourceIndex) {

    const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
    const sourceForm = forms[sourceIndex];

    if (!sourceForm) {
        console.error(`[duplicateProduct] Nie znaleziono formularza o indeksie ${sourceIndex}`);
        return;
    }

    // KROK 1: Zapisz stan wszystkich formularzy (tylko warianty, nie kształt)
    const selectedStates = forms.map((form, index) => {
        const selectedRadio = form.querySelector('.variants input[type="radio"]:checked');
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
        finishingGloss: null,

        // Obróbka krawędzi
        edgesData: sourceForm.dataset.edgesData || null,
        edgesNetto: sourceForm.dataset.edgesNetto || null,
        edgesBrutto: sourceForm.dataset.edgesBrutto || null,
        edgesCount: sourceForm.dataset.edgesCount || null,
        edgesType: sourceForm.dataset.edgesType || null,
        edgesRValue: sourceForm.dataset.edgesRValue || null,
        edgesSvg: sourceForm.dataset.edgesSvg || null
    };

    // Pobierz zaznaczony wariant z formularza źródłowego (pomiń radio kształtu)
    const sourceSelectedRadio = sourceForm.querySelector('.variants input[type="radio"]:checked');
    if (sourceSelectedRadio) {
        sourceData.selectedVariant = {
            value: sourceSelectedRadio.value,
            orderBrutto: sourceForm.dataset.orderBrutto,
            orderNetto: sourceForm.dataset.orderNetto
        };
    }

    // Pobierz dane wykończeń z dataset formularza (nowy system hierarchiczny)
    sourceData.finishingType = sourceForm.dataset.finishingType || null;
    sourceData.finishingVariant = sourceForm.dataset.finishingVariant || null;
    sourceData.finishingColor = sourceForm.dataset.finishingColor || null;
    sourceData.finishingFullPath = sourceForm.dataset.finishingFullPath || null;
    sourceData.finishingOptionId = sourceForm.dataset.finishingOptionId || null;
    sourceData.finishingBrutto = sourceForm.dataset.finishingBrutto || null;
    sourceData.finishingNetto = sourceForm.dataset.finishingNetto || null;

    // Fallback: spróbuj też ze starych selektorów dla kompatybilności wstecznej
    if (!sourceData.finishingType) {
        const finishingTypeBtn = sourceForm.querySelector('.finishing-btn[data-finishing-type].active');
        if (finishingTypeBtn) {
            sourceData.finishingType = finishingTypeBtn.dataset.finishingType;
        }
    }

    // Pobierz dane połysku
    sourceData.finishingGloss = sourceForm.dataset.finishingGloss || null;
    if (!sourceData.finishingGloss) {
        const finishingGlossBtn = sourceForm.querySelector('.finishing-gloss-btn.active');
        if (finishingGlossBtn) {
            sourceData.finishingGloss = finishingGlossBtn.dataset.glossValue;
        }
    }


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


        // Wypełnij wymiary (z dispatchEvent żeby listenery zareagowały)
        if (sourceData.length) {
            const lengthInput = newForm.querySelector('[data-field="length"]');
            if (lengthInput) {
                lengthInput.value = sourceData.length;
                lengthInput.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }

        if (sourceData.width) {
            const widthInput = newForm.querySelector('[data-field="width"]');
            if (widthInput) {
                widthInput.value = sourceData.width;
                widthInput.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }

        if (sourceData.thickness) {
            const thicknessInput = newForm.querySelector('[data-field="thickness"]');
            if (thicknessInput) {
                thicknessInput.value = sourceData.thickness;
                thicknessInput.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }

        if (sourceData.quantity) {
            const quantityInput = newForm.querySelector('[data-field="quantity"]');
            if (quantityInput) {
                quantityInput.value = sourceData.quantity;
                quantityInput.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }

        if (sourceData.clientType) {
            const clientTypeSelect = newForm.querySelector('[data-field="clientType"]');
            if (clientTypeSelect) {
                clientTypeSelect.value = sourceData.clientType;
            }
        } else {
            // Jeśli kopiowany produkt nie miał grupy cenowej, ustaw domyślną
            setDefaultClientType(newForm, false);
        }

        // ✅ POPRAWKA: Aktualizuj stan przycisku obróbki krawędzi po wypełnieniu wymiarów
        // (ustawienie .value programowo nie wywołuje eventu 'input', więc trzeba ręcznie)
        if (typeof EdgesModule !== 'undefined' && EdgesModule.updateButtonState) {
            EdgesModule.updateButtonState(newForm);
        }

        // Aktywuj wykończenia jeśli były wybrane (nowy system hierarchiczny)
        if (sourceData.finishingType) {
            // Próba 1: Nowy system - kliknij przyciski w drzewku hierarchicznym
            const finishingTreeContainer = newForm.querySelector('.finishing-tree-container');

            if (finishingTreeContainer) {
                // Kliknij przycisk typu wykończenia (poziom 0)
                const typeBtn = finishingTreeContainer.querySelector(
                    `.finishing-option-btn[data-option-name="${sourceData.finishingType}"]`
                );

                if (typeBtn) {
                    typeBtn.click();

                    // Po kliknięciu typu, ustaw wariant i kolor z opóźnieniem
                    setTimeout(() => {
                        // Wariant (poziom 1) - np. "Bezbarwne", "Barwne"
                        if (sourceData.finishingVariant) {
                            const variantBtn = finishingTreeContainer.querySelector(
                                `.finishing-option-btn[data-option-name="${sourceData.finishingVariant}"]`
                            );
                            if (variantBtn) {
                                variantBtn.click();

                                // Kolor (poziom 2)
                                setTimeout(() => {
                                    if (sourceData.finishingColor) {
                                        const colorBtn = finishingTreeContainer.querySelector(
                                            `.finishing-option-btn[data-option-name="${sourceData.finishingColor}"]`
                                        );
                                        if (colorBtn) {
                                            colorBtn.click();
                                        }
                                    }

                                    // Połysk (po kolorze)
                                    if (sourceData.finishingGloss) {
                                        setTimeout(() => {
                                            const glossBtn = finishingTreeContainer.querySelector(
                                                `.finishing-gloss-btn[data-gloss-value="${sourceData.finishingGloss}"]`
                                            );
                                            if (glossBtn) {
                                                glossBtn.click();
                                            }
                                        }, 50);
                                    }
                                }, 50);
                            }
                        }
                    }, 50);
                } else {
                    // Fallback: stary system - próbuj stare selektory
                    const oldFinishingBtn = newForm.querySelector(`[data-finishing-type="${sourceData.finishingType}"]`);
                    if (oldFinishingBtn) {
                        oldFinishingBtn.click();

                        setTimeout(() => {
                            if (sourceData.finishingColor) {
                                const colorBtn = newForm.querySelector(`[data-finishing-color="${sourceData.finishingColor}"]`);
                                if (colorBtn) colorBtn.click();
                            }
                            if (sourceData.finishingGloss) {
                                const glossBtn = newForm.querySelector(`.finishing-gloss-btn[data-gloss-value="${sourceData.finishingGloss}"]`);
                                if (glossBtn) glossBtn.click();
                            }
                        }, 100);
                    }
                }
            }
        }

        // ✅ Kopiuj dane obróbki krawędzi
        if (sourceData.edgesData) {
            newForm.dataset.edgesData = sourceData.edgesData;
            newForm.dataset.edgesNetto = sourceData.edgesNetto;
            newForm.dataset.edgesBrutto = sourceData.edgesBrutto;
            newForm.dataset.edgesCount = sourceData.edgesCount;
            newForm.dataset.edgesType = sourceData.edgesType;
            newForm.dataset.edgesRValue = sourceData.edgesRValue;
            newForm.dataset.edgesSvg = sourceData.edgesSvg;

            // Aktualizuj wizualnie przycisk i podsumowanie krawędzi
            const edgesBtn = newForm.querySelector('.open-edges-modal-btn');
            if (edgesBtn) {
                edgesBtn.textContent = 'Zmień obróbkę krawędzi';
                edgesBtn.disabled = false;
                edgesBtn.classList.remove('disabled');
                edgesBtn.title = '';
            }

            // Aktualizuj wiersz podsumowania krawędzi
            const edgesOptionsSummary = newForm.querySelector('.edges-options-summary');
            if (edgesOptionsSummary) {
                const edgesRow = edgesOptionsSummary.querySelector('.edges-row');
                if (edgesRow) {
                    // Zbuduj tekst podsumowania
                    try {
                        const edgesArray = JSON.parse(sourceData.edgesData);
                        const edgeLetters = edgesArray.map(e => e.letter).sort().join(', ');
                        const typeLabel = sourceData.edgesType === 'chamfer' ? 'Fazowanie' : 'Zaokrąglenie';
                        const priceBruttoText = parseFloat(sourceData.edgesBrutto).toLocaleString('pl-PL', {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2
                        }) + ' zł brutto';
                        const priceNettoText = parseFloat(sourceData.edgesNetto).toLocaleString('pl-PL', {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2
                        }) + ' zł netto';

                        const textEl = edgesRow.querySelector('.edges-summary-text');
                        const priceEl = edgesRow.querySelector('.edges-summary-price');
                        let priceNettoEl = edgesRow.querySelector('.edges-summary-price-netto');

                        // Jeśli element netto nie istnieje, utwórz go dynamicznie
                        if (!priceNettoEl) {
                            const content = edgesRow.querySelector('.options-summary-content');
                            if (content) {
                                priceNettoEl = document.createElement('span');
                                priceNettoEl.className = 'options-summary-price-netto edges-summary-price-netto';
                                content.appendChild(priceNettoEl);
                            }
                        }

                        if (textEl) textEl.textContent = `${typeLabel} R${sourceData.edgesRValue}: ${edgeLetters}`;
                        if (priceEl) priceEl.textContent = priceBruttoText;
                        if (priceNettoEl) priceNettoEl.textContent = priceNettoText;

                        edgesRow.style.display = 'flex';
                        edgesOptionsSummary.style.display = 'flex';
                    } catch (e) {
                        console.error('[duplicateProduct] Błąd parsowania danych krawędzi:', e);
                    }
                }
            }

        }

        // Przeliczy ceny jeśli mamy wszystkie wymiary
        const hasClientType = sourceData.clientType || (typeof isPartner !== 'undefined' && isPartner);
        if (sourceData.length && sourceData.width && sourceData.thickness && hasClientType) {
            setTimeout(() => {
                updatePrices();

                // Zaznacz ten sam wariant co w źródle
                if (sourceData.selectedVariant) {
                    const radioToSelect = newForm.querySelector(`input[type="radio"][value="${sourceData.selectedVariant.value}"]`);
                    if (radioToSelect) {
                        radioToSelect.checked = true;
                        radioToSelect.dispatchEvent(new Event('change', { bubbles: true }));
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


    }, 100);
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
            removeProduct(index);
            return;
        }

        // Obsługa przycisku duplikowania
        const duplicateBtn = e.target.closest('.duplicate-product-btn');
        if (duplicateBtn) {
            e.stopPropagation();
            const index = parseInt(duplicateBtn.dataset.index);
            duplicateProduct(index);
            return;
        }
    });

    // Oznacz że listenery zostały dodane
    productSummaryContainer._listenersAttached = true;
}

function removeProduct(index) {
    const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));

    if (forms.length <= 1) {
        return;
    }

    const formToRemove = forms[index];
    if (!formToRemove) return;

    // Przenieś .quote-summary jeśli jest w usuwanym formularzu
    const summaryInForm = formToRemove.querySelector('.quote-summary');
    if (summaryInForm) {
        quoteFormsContainer.appendChild(summaryInForm);
    }

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

    // Powiadom detekcje zmian (tryb edycji wyceny)
    document.dispatchEvent(new CustomEvent('products-changed'));
}

/**
 * Aktywuje kartę produktu
 */
function activateProductCard(index) {

    const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));

    if (index < 0 || index >= forms.length) {
        console.error(`[activateProductCard] Nieprawidłowy index: ${index}`);
        return;
    }

    // KROK 1: Zapisz stan zaznaczonych wariantów we WSZYSTKICH formularzach (pomiń radio kształtu)
    const selectedVariants = {};
    forms.forEach((form, formIndex) => {
        const selectedRadio = form.querySelector('.variants input[type="radio"]:checked');
        if (selectedRadio) {
            selectedVariants[formIndex] = {
                id: selectedRadio.id,
                value: selectedRadio.value,
                checked: true
            };
        }
    });

    // KROK 2: Ukryj wszystkie formularze
    forms.forEach((form, i) => {
        form.classList.toggle('hidden', i !== index);
    });

    // KROK 2.5: Przenieś globalne .quote-summary do aktywnego formularza
    const quoteSummary = quoteFormsContainer.querySelector('.quote-summary');
    if (quoteSummary) {
        const targetRow = forms[index].querySelector('.workspace-row-2');
        if (targetRow) {
            targetRow.appendChild(quoteSummary);
        }
    }

    // KROK 3: Ustaw aktywny formularz
    const previousActiveForm = activeQuoteForm;
    activeQuoteForm = forms[index];

    if (!activeQuoteForm) {
        console.error(`[activateProductCard] Nie można znaleźć formularza o index ${index}`);
        return;
    }


    // KROK 4: Odśwież event listeners TYLKO dla aktywnego formularza
    if (activeQuoteForm) {
        attachFormListeners(activeQuoteForm);

        // ✅ POPRAWKA: Wywołaj updatePrices TYLKO jeśli formularz ma wypełnione wymiary
        const hasValidDimensions = checkFormHasValidDimensions(activeQuoteForm);
        if (hasValidDimensions) {
            updatePrices();
        }
    }

    // KROK 5: Przywróć zaznaczenia we WSZYSTKICH formularzach
    Object.entries(selectedVariants).forEach(([formIndex, variant]) => {
        const form = forms[parseInt(formIndex)];
        if (form && variant.id) {
            const radio = form.querySelector(`#${variant.id}`);
            if (radio && !radio.checked) {
                radio.checked = true;

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

    const firstForm = quoteFormsContainer.querySelector('.quote-form');
    if (!firstForm) {
        console.error("[addNewProduct] Nie znaleziono pierwszego formularza!");
        return;
    }

    // KROK 1: Zapisz stan zaznaczonych wariantów przed klonowaniem (pomiń radio kształtu)
    const allForms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
    const selectedStates = allForms.map((form, index) => {
        const selectedRadio = form.querySelector('.variants input[type="radio"]:checked');
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


    // KROK 2: Pobierz aktualną grupę cenową
    const currentClientType = activeQuoteForm?.querySelector('select[data-field="clientType"]')?.value ||
        firstForm?.querySelector('select[data-field="clientType"]')?.value || null;

    const newIndex = allForms.length;

    // KROK 3: Sklonuj i przygotuj nowy formularz
    const newForm = firstForm.cloneNode(true);
    newForm.classList.add('hidden');

    // Usuń .quote-summary z klona - podsumowanie jest globalne, nie per-produkt
    const clonedSummary = newForm.querySelector('.quote-summary');
    if (clonedSummary) clonedSummary.remove();

    // ✅ POPRAWKA: Odznacz radio kształtu w klonie PRZED dodaniem do DOM
    // (zapobiega konfliktowi grup radio - klon i oryginał mają tę samą nazwę "productShape-N",
    // a ponieważ .quote-form to <div> nie <form>, przeglądarka traktuje je jako jedną grupę)
    newForm.querySelectorAll('input[data-field="shapeRect"], input[data-field="shapeRound"]').forEach(r => {
        r.checked = false;
    });

    quoteFormsContainer.appendChild(newForm);

    prepareNewProductForm(newForm, newIndex);

    // KROK 4: Przywróć grupę cenową
    if (currentClientType) {
        const select = newForm.querySelector('select[data-field="clientType"]');
        if (select) {
            select.value = currentClientType;
        }
    }

    // KROK 4.1: Przywróć grupę cenową TAKŻE w aktywnym formularzu
    if (currentClientType) {
        const select = newForm.querySelector('select[data-field="clientType"]');
        if (select) {
            select.value = currentClientType;
        }
    } else {
        // Jeśli nie ma aktualnej grupy cenowej, ustaw domyślną
        setDefaultClientType(newForm, false);
    }

    // KROK 5: Dodaj event listenery do nowego formularza
    attachFormListeners(newForm);

    // KROK 5.1: ✅ POPRAWKA - Przebuduj drzewko wykończeń dla nowego formularza
    // Klonowanie kopiuje stare event listenery, więc trzeba przebudować drzewko
    if (typeof renderFinishingTree === 'function') {
        renderFinishingTree(newForm);
    }

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

        // Powiadom detekcje zmian (tryb edycji wyceny)
        document.dispatchEvent(new CustomEvent('products-changed'));
    }, 150);

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

    });

}

function scrollToLatestProduct() {
    const container = document.getElementById('products-summary-container');
    if (container) {
        // Scroll do dołu kontenera po dodaniu nowego produktu
        container.scrollTop = container.scrollHeight;
    }
}

// ============ DOSTĘPNOŚĆ WARIANTÓW ============

// Warianty niedostępne — ustawiane przez kod, nie przez użytkownika.
// Stan niedostępności definiowany jest w HTML (class="unavailable", disabled na radio).
const unavailableVariants = ['jes-micro-ab'];

/**
 * Inicjalizuje niedostępność wariantów na podstawie konfiguracji.
 * Ustawia class="unavailable" i disabled na radio dla niedostępnych wariantów.
 */
function initializeVariantAvailability() {
    const allForms = document.querySelectorAll('.quote-form');
    allForms.forEach(form => {
        unavailableVariants.forEach(variantCode => {
            const radio = form.querySelector(`input[type="radio"][value="${variantCode}"]`);
            if (radio) {
                radio.disabled = true;
                const option = radio.closest('.variant-option');
                if (option) option.classList.add('unavailable');
            }
        });
    });
}

/**
 * Pobiera dostępne warianty z formularza (te, które nie mają disabled radio)
 */
function getAvailableVariants(form) {
    const radios = form.querySelectorAll('.variants input[type="radio"]:not(:disabled)');
    return Array.from(radios).map(r => r.value);
}

/**
 * Walidacja przed zapisem — sprawdza czy zaznaczony wariant jest dostępny
 */
function validateAvailableVariants() {
    const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));

    for (let i = 0; i < forms.length; i++) {
        const form = forms[i];
        const selectedRadio = form.querySelector('.variants input[type="radio"]:checked');

        if (selectedRadio && selectedRadio.disabled) {
            alert(`Produkt ${i + 1} ma zaznaczony niedostępny wariant. Wybierz dostępny wariant.`);
            return false;
        }
    }

    return true;
}

/**
 * Filtruje warianty tylko do dostępnych przed wysłaniem do backend
 */
function filterAvailableVariantsForSave(form, variants) {
    const availableVariants = getAvailableVariants(form);
    return variants.filter(v => availableVariants.includes(v.variant_code));
}

// ============ EVENT LISTENERS ============

/**
 * Dodaj obsługę dostępności do event listenerów formularza
 */
function attachVariantSelectionListeners(form) {
    // Tylko radio wariantów (pomiń radio kształtu)
    const radioButtons = form.querySelectorAll('.variants input[type="radio"]');

    radioButtons.forEach(radio => {
        // Usuń poprzednie event listenery
        radio.removeEventListener('change', handleVariantSelection);

        // Dodaj nowy event listener
        radio.addEventListener('change', handleVariantSelection);
    });

    // Kliknięcie w cały wiersz wariantu zaznacza radio button
    const variantRows = form.querySelectorAll('.variant-option');
    variantRows.forEach(row => {
        if (row._variantRowClickHandler) {
            row.removeEventListener('click', row._variantRowClickHandler);
        }
        row._variantRowClickHandler = function (e) {
            // Jeśli kliknięto w sam radio button, nie rób nic (obsłuży się naturalnie)
            if (e.target.type === 'radio') return;

            const radio = this.querySelector('input[type="radio"]');
            if (radio && !radio.disabled) {
                radio.checked = true;
                radio.dispatchEvent(new Event('change', { bubbles: true }));
            }
        };
        row.addEventListener('click', row._variantRowClickHandler);
    });
}

function checkRadioButtonIntegrity() {

    const allForms = quoteFormsContainer.querySelectorAll('.quote-form');
    let hasIssues = false;

    allForms.forEach((form, formIndex) => {
        // Sprawdzaj tylko radio wariantów (pomiń radio kształtu)
        const radioButtons = form.querySelectorAll('.variants input[type="radio"]');
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
                    radio.checked = false;
                });
            }
        });
    });

    if (!hasIssues) {
    }

    return !hasIssues;
}

function fixSelectedClasses() {

    const allForms = quoteFormsContainer.querySelectorAll('.quote-form');

    allForms.forEach((form, formIndex) => {
        // Znajdź zaznaczony radio button wariantu (pomiń radio kształtu)
        const checkedRadio = form.querySelector('.variants input[type="radio"]:checked');

        // Usuń wszystkie klasy 'selected' z tego formularza
        form.querySelectorAll('.variant-option').forEach(option => {
            option.classList.remove('selected');
        });

        // Dodaj 'selected' tylko do właściwego wariantu
        if (checkedRadio) {
            const selectedOption = checkedRadio.closest('.variant-option');
            if (selectedOption) {
                selectedOption.classList.add('selected');
            }
        }
    });
}

function handleVariantSelection(e) {
    const radio = e.target;
    const form = radio.closest('.quote-form');

    if (!form) return;


    // ✅ KLUCZOWA POPRAWKA: Usuń 'selected' TYLKO z tego formularza
    form.querySelectorAll('.variant-option').forEach(option => {
        option.classList.remove('selected');
    });

    // Dodaj 'selected' do wybranego wariantu
    const selectedOption = radio.closest('.variant-option');
    if (selectedOption && radio.checked) {
        selectedOption.classList.add('selected');
    }

    // Wywołaj aktualizację cen
    updatePrices();
}

// ============ EXPORT FUNCTIONS ============

window.variantAvailability = {
    initialize: initializeVariantAvailability,
    validate: validateAvailableVariants,
    filter: filterAvailableVariantsForSave,
    getAvailable: getAvailableVariants
};

window.CalculatorProducts = {
    areAllProductsComplete,
    prepareNewProductForm,
    checkProductCompleteness,
    duplicateProduct,
    attachProductCardListeners,
    removeProduct,
    activateProductCard,
    checkFormHasValidDimensions,
    addNewProduct,
    fixAllRadioButtonNames,
    scrollToLatestProduct,
    initializeVariantAvailability,
    getAvailableVariants,
    validateAvailableVariants,
    filterAvailableVariantsForSave,
    attachVariantSelectionListeners,
    checkRadioButtonIntegrity,
    fixSelectedClasses,
    handleVariantSelection
};

// Kluczowe funkcje dostępne bezpośrednio na window
window.areAllProductsComplete = areAllProductsComplete;
window.checkProductCompleteness = checkProductCompleteness;
window.activateProductCard = activateProductCard;
window.attachProductCardListeners = attachProductCardListeners;
window.addNewProduct = addNewProduct;
window.removeProduct = removeProduct;
window.duplicateProduct = duplicateProduct;
window.prepareNewProductForm = prepareNewProductForm;
window.scrollToLatestProduct = scrollToLatestProduct;
