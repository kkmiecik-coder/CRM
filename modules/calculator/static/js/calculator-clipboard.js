// calculator-clipboard.js
// Moduł schowka - kopiowanie wyceny do schowka
// ============================================
// COPY TO CLIPBOARD - Kopiowanie wyceny
// ============================================

/**
 * Formatuje pojedynczy produkt do plain text
 * @param {HTMLElement} form - Formularz produktu
 * @param {number} productIndex - Numer produktu (1-based)
 * @param {boolean} showOnlySelected - Czy pokazywać tylko wybrane warianty (dla długich wycen)
 * @returns {string} Sformatowany tekst produktu
 */
function formatProductToText(form, productIndex, showOnlySelected = false) {
    const priceMode = getCurrentPriceMode();
    const showBrutto = priceMode === 'brutto';

    // Pobierz wymiary
    const length = form.querySelector('[data-field="length"]')?.value || '0';
    const width = form.querySelector('[data-field="width"]')?.value || '0';
    const thickness = form.querySelector('[data-field="thickness"]')?.value || '0';
    const quantity = form.querySelector('[data-field="quantity"]')?.value || '1';

    // Pobierz wybrany wariant
    const selectedVariant = form.querySelector('.variants input[type="radio"]:checked');
    const selectedVariantCode = selectedVariant?.value || '';

    let text = '';
    text += '─────────────────────────────────────────────────────────────\n';
    text += `𝗣𝗥𝗢𝗗𝗨𝗞𝗧 ${productIndex}\n`;
    text += '─────────────────────────────────────────────────────────────\n';
    text += `𝗪𝘆𝗺𝗶𝗮𝗿𝘆: ${length} x ${width} x ${thickness} cm\n`;
    text += `𝗜𝗹𝗼𝘀́𝗰: ${quantity} szt.\n\n`;

    // Warianty - nagłówek zależny od trybu
    if (showOnlySelected) {
        text += '𝗪𝘆𝗯𝗿𝗮𝗻𝘆 𝘄𝗮𝗿𝗶𝗮𝗻𝘁:\n\n';
    } else {
        text += '𝗗𝗼𝘀𝘁𝗲̨𝗽𝗻𝗲 𝘄𝗮𝗿𝗶𝗮𝗻𝘁𝘆:\n\n';
    }

    const variantOptions = form.querySelectorAll('.variant-option');

    variantOptions.forEach(option => {
        const radio = option.querySelector('input[type="radio"]');
        const variantCode = radio?.value || '';
        const variant = variantMapping[variantCode];

        if (!variant) return;

        const isSelected = variantCode === selectedVariantCode;
        const isAvailable = radio && !radio.disabled;

        // Jeśli pokazujemy tylko wybrane - pomiń niewybrane
        if (showOnlySelected && !isSelected) return;

        // Pomijamy niedostępne warianty, chyba że są wybrane
        if (!isAvailable && !isSelected) return;

        const speciesLabel = `${variant.species} ${variant.technology} ${variant.wood_class}`;
        const nettoPrice = option.querySelector('.unit-netto')?.textContent || '0.00 PLN';
        const bruttoPrice = option.querySelector('.unit-brutto')?.textContent || '0.00 PLN';

        const selectedMark = isSelected ? '  ⭐ WYBRANO' : '';

        // Nazwa wariantu
        text += `  ${speciesLabel}${selectedMark}\n`;

        // Ceny w nowej linii z wcięciem
        if (showBrutto) {
            text += `     → Netto: ${nettoPrice} | Brutto: ${bruttoPrice}\n\n`;
        } else {
            text += `     → Netto: ${nettoPrice}\n\n`;
        }
    });

    // Wykończenie (usunięte dodatkowe \n bo już jest w pętli)
    const finishingType = form.querySelector('.finishing-buttons .finishing-btn.active')?.dataset.type || 'surowe';
    let finishingText = 'Surowe';

    if (finishingType === 'lakierowanie') {
        const variant = form.querySelector('.lacquer-variant-buttons .lacquer-variant-btn.active')?.dataset.variant;
        finishingText = variant === 'barwne' ? 'Lakierowanie barwne' : 'Lakierowanie bezbarwne';

        if (variant === 'barwne') {
            const color = form.querySelector('.color-buttons .color-btn.active')?.dataset.color;
            if (color) {
                const colorNames = {
                    'buk': 'Buk',
                    'orzech': 'Orzech',
                    'dab': 'Dąb',
                    'palisander': 'Palisander',
                    'wenge': 'Wenge',
                    'czarny': 'Czarny',
                    'bialy': 'Biały',
                    'szary': 'Szary',
                    'niebieski': 'Niebieski'
                };
                finishingText += ` (${colorNames[color] || color})`;
            }
        }
    } else if (finishingType === 'olejowanie') {
        finishingText = 'Olejowanie';
    }

    text += `𝗪𝘆𝗸𝗼𝗻́𝗰𝘇𝗲𝗻𝗶𝗲: ${finishingText}\n`;

    // Koszt wykończenia
    const finishingNettoEl = form.querySelector('.finishing-cost-netto');
    const finishingBruttoEl = form.querySelector('.finishing-cost-brutto');

    if (finishingNettoEl && finishingBruttoEl) {
        const finishingNetto = finishingNettoEl.textContent;
        const finishingBrutto = finishingBruttoEl.textContent;

        if (showBrutto) {
            text += `𝗞𝗼𝘀𝘇𝘁 𝘄𝘆𝗸𝗼𝗻́𝗰𝘇𝗲𝗻𝗶𝗮: ${finishingNetto} netto / ${finishingBrutto} brutto\n`;
        } else {
            text += `𝗞𝗼𝘀𝘇𝘁 𝘄𝘆𝗸𝗼𝗻́𝗰𝘇𝗲𝗻𝗶𝗮: ${finishingNetto} netto\n`;
        }
    }

    // Suma za produkt
    const totalNettoEl = form.querySelector('.final-netto');
    const totalBruttoEl = form.querySelector('.final-brutto');

    if (totalNettoEl && totalBruttoEl) {
        const totalNetto = totalNettoEl.textContent;
        const totalBrutto = totalBruttoEl.textContent;

        text += '\n';
        if (showBrutto) {
            text += `𝗦𝘂𝗺𝗮 𝘇𝗮 𝗽𝗿𝗼𝗱𝘂𝗸𝘁: ${totalNetto} netto / ${totalBrutto} brutto\n`;
        } else {
            text += `𝗦𝘂𝗺𝗮 𝘇𝗮 𝗽𝗿𝗼𝗱𝘂𝗸𝘁: ${totalNetto} netto\n`;
        }
    }

    return text;
}

/**
 * Formatuje całą wycenę (wszystkie produkty + podsumowanie) do plain text
 * @returns {string} Sformatowany tekst wyceny
 */
function formatQuoteToText() {
    const priceMode = getCurrentPriceMode();
    const showBrutto = priceMode === 'brutto';

    let text = '';

    // Wszystkie produkty
    const forms = document.querySelectorAll('.quote-form');
    const productCount = forms.length;

    // Jeśli więcej niż 7 produktów, pokazuj tylko wybrane warianty
    const showOnlySelected = productCount > 7;

    forms.forEach((form, index) => {
        text += formatProductToText(form, index + 1, showOnlySelected);
        text += '\n';
    });

    // Podsumowanie
    text += '═══════════════════════════════════════════════════════════════\n';
    text += '𝗣𝗢𝗗𝗦𝗨𝗠𝗢𝗪𝗔𝗡𝗜𝗘\n';
    text += '═══════════════════════════════════════════════════════════════\n';

    // Pobierz wartości z podsumowania
    const summaryNettoProducts = document.querySelector('.order-summary .order-netto')?.textContent || '0.00 PLN';
    const summaryBruttoProducts = document.querySelector('.order-summary .order-brutto')?.textContent || '0.00 PLN';

    const summaryNettoFinishing = document.querySelector('.finishing-summary .finishing-netto')?.textContent || '0.00 PLN';
    const summaryBruttoFinishing = document.querySelector('.finishing-summary .finishing-brutto')?.textContent || '0.00 PLN';

    if (showBrutto) {
        text += `𝗣𝗿𝗼𝗱𝘂𝗸𝘁𝘆 (𝘀𝘂𝗿𝗼𝘄𝗲):       ${summaryNettoProducts.padEnd(15)} netto / ${summaryBruttoProducts} brutto\n`;
        text += `𝗪𝘆𝗸𝗼𝗻́𝗰𝘇𝗲𝗻𝗶𝗲:             ${summaryNettoFinishing.padEnd(15)} netto / ${summaryBruttoFinishing} brutto\n`;
    } else {
        text += `𝗣𝗿𝗼𝗱𝘂𝗸𝘁𝘆 (𝘀𝘂𝗿𝗼𝘄𝗲):       ${summaryNettoProducts} netto\n`;
        text += `𝗪𝘆𝗸𝗼𝗻́𝗰𝘇𝗲𝗻𝗶𝗲:             ${summaryNettoFinishing} netto\n`;
    }

    // Dostawa (jeśli obliczona)
    const summaryNettoDelivery = document.querySelector('.delivery-summary .delivery-netto')?.textContent;
    const summaryBruttoDelivery = document.querySelector('.delivery-summary .delivery-brutto')?.textContent;
    const courierName = document.querySelector('.delivery-summary .courier')?.textContent;

    if (summaryNettoDelivery && summaryBruttoDelivery && courierName && courierName.trim() !== '') {
        if (showBrutto) {
            text += `𝗪𝘆𝘀𝘆ł𝗸𝗮 (${courierName}):${' '.repeat(Math.max(0, 12 - courierName.length))}${summaryNettoDelivery.padEnd(15)} netto / ${summaryBruttoDelivery} brutto\n`;
        } else {
            text += `𝗪𝘆𝘀𝘆ł𝗸𝗮 (${courierName}):${' '.repeat(Math.max(0, 12 - courierName.length))}${summaryNettoDelivery} netto\n`;
        }
    }

    // Suma końcowa
    const totalNetto = document.querySelector('.final-summary .final-netto')?.textContent || '0.00 PLN';
    const totalBrutto = document.querySelector('.final-summary .final-brutto')?.textContent || '0.00 PLN';

    text += '───────────────────────────────────────────────────────────────\n';
    if (showBrutto) {
        text += `𝗥𝗔𝗭𝗘𝗠:                   ${totalNetto.padEnd(15)} netto / ${totalBrutto} brutto\n`;
    } else {
        text += `𝗥𝗔𝗭𝗘𝗠:                   ${totalNetto} netto\n`;
    }
    text += '═══════════════════════════════════════════════════════════════\n';

    return text;
}

/**
 * Kopiuje tekst do schowka
 * @param {string} text - Tekst do skopiowania
 * @returns {Promise<boolean>} True jeśli sukces
 */
async function copyToClipboard(text) {
    try {
        // Nowoczesne API
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            return true;
        }

        // Fallback dla starszych przeglądarek
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        textArea.style.top = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();

        const successful = document.execCommand('copy');
        document.body.removeChild(textArea);

        return successful;
    } catch (err) {
        console.error('[copyToClipboard] Błąd:', err);
        return false;
    }
}

/**
 * Pokazuje feedback wizualny po skopiowaniu
 * @param {HTMLElement} button - Przycisk który został kliknięty
 */
function showCopyFeedback(button) {
    const textSpan = button.querySelector('.copy-btn-text');
    const originalText = textSpan.textContent;

    // Zmień tekst i styl
    button.classList.add('copied');
    textSpan.textContent = '✓ Skopiowano';

    // Ukryj tooltip podczas feedbacku
    const tooltip = button.parentElement.querySelector('.copy-tooltip');
    if (tooltip) {
        tooltip.classList.add('hide-tooltip');
    }

    // Przywróć po 2 sekundach
    setTimeout(() => {
        button.classList.remove('copied');
        textSpan.textContent = originalText;
        if (tooltip) {
            tooltip.classList.remove('hide-tooltip');
        }
    }, 2000);
}

/**
 * Waliduje czy można skopiować wycenę
 * @returns {boolean} True jeśli walidacja przeszła
 */
function validateCopyAction() {
    const forms = document.querySelectorAll('.quote-form');

    // Sprawdź czy wszystkie produkty mają wybrane warianty
    for (let form of forms) {
        const selectedRadio = form.querySelector('.variants input[type="radio"]:checked');
        if (!selectedRadio) {
            return false;
        }
    }

    // Sprawdź dostępność wariantów
    if (window.variantAvailability && !window.variantAvailability.validate()) {
        return false;
    }

    return true;
}

/**
 * Inicjalizuje funkcjonalność kopiowania do schowka
 */
function initCopyToClipboard() {
    // Obsługa kliknięć na opcje w tooltipie
    document.addEventListener('click', async (e) => {
        const option = e.target.closest('.copy-tooltip-option');
        if (!option) return;

        const copyType = option.dataset.copyType;
        const button = option.closest('.copy-to-clipboard-container').querySelector('.copy-to-clipboard');

        // Walidacja
        if (!validateCopyAction()) {
            alert('Wybierz wariant dla wszystkich produktów przed skopiowaniem.');
            return;
        }

        let textToCopy = '';

        if (copyType === 'product') {
            // Kopiuj tylko aktywny produkt - używamy globalnej zmiennej activeQuoteForm
            if (!activeQuoteForm) {
                return;
            }

            const forms = Array.from(document.querySelectorAll('.quote-form'));
            const productIndex = forms.indexOf(activeQuoteForm) + 1;

            textToCopy = formatProductToText(activeQuoteForm, productIndex);
        } else if (copyType === 'quote') {
            // Kopiuj całą wycenę
            textToCopy = formatQuoteToText();
        }

        // Kopiuj do schowka
        const success = await copyToClipboard(textToCopy);

        if (success) {
            showCopyFeedback(button);
        } else {
            console.error('[Copy] Nie udało się skopiować');
            alert('Nie udało się skopiować do schowka. Spróbuj ponownie.');
        }
    });

    // Aktualizuj stan przycisków kopiowania po zmianach
    document.addEventListener('change', () => {
        updateCopyButtonStates();
    });

    // Inicjalna aktualizacja stanów
    updateCopyButtonStates();
}

/**
 * Aktualizuje stan przycisków kopiowania (enabled/disabled)
 */
function updateCopyButtonStates() {
    const buttons = document.querySelectorAll('.copy-to-clipboard');
    const isValid = validateCopyAction();

    buttons.forEach(button => {
        button.disabled = !isValid;
    });
}

// Inicjalizacja po załadowaniu DOM
document.addEventListener('DOMContentLoaded', () => {
    initCopyToClipboard();
});

// Eksport funkcji do globalnego obiektu
window.CalculatorClipboard = {
    formatProductToText,
    formatQuoteToText,
    copyToClipboard,
    showCopyFeedback,
    validateCopyAction,
    initCopyToClipboard,
    updateCopyButtonStates
};
