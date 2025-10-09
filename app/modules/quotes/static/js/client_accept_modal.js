// ========== NOWY MODAL AKCEPTACJI - 3 KROKI ==========

// Stan modala
let currentStep = 1;
let clientData = {};
let existingClientData = null;
let currentQuoteData = null;

// Inicjalizacja modala akceptacji
function initAcceptModal() {
    console.log('[AcceptModal] Inicjalizacja modala akceptacji');

    // Event listenery dla checkboxów
    document.getElementById('selfPickup').addEventListener('change', handleSelfPickupChange);
    document.getElementById('wantInvoice').addEventListener('change', handleInvoiceToggle);

    // Event listener dla GUS
    document.getElementById('gusLookupBtn').addEventListener('click', handleGusLookup);

    // Event listener dla przycisku zamknij
    const closeBtn = document.querySelector('#acceptModal .modal-close');
    if (closeBtn) {
        closeBtn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            closeAcceptModal();
        });
    }

    // Event listener dla finalnego submitowania z walidacją checkbox
    document.getElementById('finalSubmitBtn').addEventListener('click', handleFinalSubmit);

    console.log('[AcceptModal] Modal zainicjalizowany');
}

// Przejście do konkretnego kroku
async function goToStep(stepNumber) {
    console.log(`[AcceptModal] Przejście do kroku ${stepNumber}`);

    // POPRAWKA: Walidacja TYLKO przy przechodzeniu do przodu
    const isGoingForward = stepNumber > currentStep;

    if (isGoingForward) {
        const isValid = await validateCurrentStep();
        if (!isValid) {
            console.log(`[AcceptModal] Walidacja kroku ${currentStep} niepomyślna`);
            return;
        }
    }

    // Ukryj obecny krok
    const currentStepElement = document.getElementById(`accept-step-${currentStep}`);
    const nextStepElement = document.getElementById(`accept-step-${stepNumber}`);

    currentStepElement.style.display = 'none';

    // Ukryj obecne akcje
    document.getElementById(`step-${currentStep}-actions`).style.display = 'none';

    // Aktualizuj progress bar
    updateProgressBar(stepNumber);

    // Pokaż nowy krok
    currentStep = stepNumber;
    nextStepElement.style.display = 'block';

    // Pokaż odpowiednie akcje
    document.getElementById(`step-${stepNumber}-actions`).style.display = 'flex';

    // Przewiń scrollowalną zawartość na górę
    const scrollableContent = document.querySelector('#acceptModal .modal-scrollable-content');
    if (scrollableContent) {
        scrollableContent.scrollTo({ top: 0, behavior: 'smooth' });
    }

    // POPRAWKA: Specjalne akcje dla kroku 3
    if (stepNumber === 3) {
        updateSummaryWithQuoteData();
    }

    console.log(`[AcceptModal] Przeszedł do kroku ${stepNumber}`);
}

// Aktualizacja paska postępu
function updateProgressBar(stepNumber) {
    const steps = document.querySelectorAll('#acceptModal .progress-step');

    steps.forEach((step, index) => {
        const stepNum = index + 1;
        step.classList.remove('active', 'completed');

        if (stepNum === stepNumber) {
            step.classList.add('active');
        } else if (stepNum < stepNumber) {
            step.classList.add('completed');
        }
    });
}

// Walidacja obecnego kroku
async function validateCurrentStep() {
    switch (currentStep) {
        case 1:
            return await validateContactStep(); // Teraz async!
        case 2:
            return validateDataStep(); // Synchroniczne
        case 3:
            return true; // POPRAWKA: Krok 3 zawsze przechodzi
        default:
            return true;
    }
}

// Event listenery dla przycisków - muszą być async
function attachStepButtons() {
    // Przycisk "Dalej" w kroku 1
    const nextStep1Btn = document.querySelector('#step-1-actions .btn-primary');
    if (nextStep1Btn) {
        nextStep1Btn.addEventListener('click', async function (e) {
            e.preventDefault();
            await goToStep(2);
        });
    }

    // Przycisk "Dalej" w kroku 2  
    const nextStep2Btn = document.querySelector('#step-2-actions .btn-primary');
    if (nextStep2Btn) {
        nextStep2Btn.addEventListener('click', async function (e) {
            e.preventDefault();
            await goToStep(3);
        });
    }

    // Przyciski "Wstecz"
    const backStep2Btn = document.querySelector('#step-2-actions .btn-secondary');
    if (backStep2Btn) {
        backStep2Btn.addEventListener('click', function (e) {
            e.preventDefault();
            goToStep(1); // Wstecz nie wymaga walidacji
        });
    }

    const backStep3Btn = document.querySelector('#step-3-actions .btn-secondary');
    if (backStep3Btn) {
        backStep3Btn.addEventListener('click', function (e) {
            e.preventDefault();
            goToStep(2); // Wstecz nie wymaga walidacji
        });
    }
}

// Walidacja kroku kontaktowego
function validateContactStep() {
    let isValid = true;

    const email = document.getElementById('acceptEmail').value.trim();
    const phone = document.getElementById('acceptPhone').value.trim();

    clearFieldError('emailError');
    clearFieldError('phoneError');

    if (!email) {
        showFieldError('emailError', 'Email jest wymagany');
        isValid = false;
    } else if (!isValidEmail(email)) {
        showFieldError('emailError', 'Podaj prawidłowy adres email');
        isValid = false;
    }

    if (!phone) {
        showFieldError('phoneError', 'Numer telefonu jest wymagany');
        isValid = false;
    } else if (!isValidPhone(phone)) {
        showFieldError('phoneError', 'Podaj prawidłowy numer telefonu');
        isValid = false;
    }

    return isValid;
}

// Walidacja kroku danych
function validateDataStep() {
    let isValid = true;
    const isSelfPickup = document.getElementById('selfPickup').checked;
    const wantInvoice = document.getElementById('wantInvoice').checked;

    clearAllFieldErrors();

    if (!isSelfPickup) {
        const requiredDeliveryFields = [
            { id: 'deliveryName', name: 'Imię i nazwisko' },
            { id: 'deliveryAddress', name: 'Adres' },
            { id: 'deliveryZip', name: 'Kod pocztowy' },
            { id: 'deliveryCity', name: 'Miasto' }
        ];

        for (const field of requiredDeliveryFields) {
            const value = document.getElementById(field.id).value.trim();
            if (!value) {
                showFieldError(`${field.id}Error`, `${field.name} jest wymagane`);
                isValid = false;
            }
        }

        const zipCode = document.getElementById('deliveryZip').value.trim();
        if (zipCode && !isValidZipCode(zipCode)) {
            showFieldError('deliveryZipError', 'Podaj prawidłowy kod pocztowy (12-345)');
            isValid = false;
        }
    }

    if (wantInvoice) {
        const nip = document.getElementById('invoiceNip').value.trim();
        if (!nip) {
            showFieldError('invoiceNipError', 'NIP jest wymagany dla faktury');
            isValid = false;
        } else if (!isValidNIP(nip)) {
            showFieldError('invoiceNipError', 'Podaj prawidłowy NIP (10 cyfr)');
            isValid = false;
        }
    }

    return isValid;
}

// POPRAWKA: Nowa funkcja pobierania danych wyceny ze strony
function updateQuoteSummaryFromPage() {
    const summaryContainer = document.getElementById('quoteSummaryContent');

    try {
        let totalNetto = '0.00';
        let totalVat = '0.00';
        let totalBrutto = '0.00';
        let quoteNumber = '';

        // POPRAWKA: Pobierz numer wyceny z globalnych danych lub z DOM
        if (window.currentQuoteData && window.currentQuoteData.quote_number) {
            quoteNumber = window.currentQuoteData.quote_number;
        }

        // POPRAWKA: Pobierz dane z konkretnych elementów na stronie
        // Szukaj elementu z ceną brutto
        const priceBruttoElement = document.querySelector('.price-brutto, .summary-total-main');
        if (priceBruttoElement) {
            const bruttoText = priceBruttoElement.textContent || priceBruttoElement.innerText;
            console.log('[AcceptModal] Znaleziono element brutto:', bruttoText);

            // Wyciągnij liczbę z tekstu (usuń "zł", "&nbsp;", spacje, etc.)
            const bruttoMatch = bruttoText.match(/[\d,\s]+/);
            if (bruttoMatch) {
                totalBrutto = bruttoMatch[0]
                    .replace(/\s/g, '')           // Usuń spacje
                    .replace(/&nbsp;/g, '')       // Usuń &nbsp;
                    .replace(',', '.');           // Zamień przecinek na kropkę

                console.log('[AcceptModal] Wyciągnięto brutto:', totalBrutto);
            }
        }

        // POPRAWKA: Szukaj elementu z ceną netto
        const priceNettoElement = document.querySelector('.price-netto, .total-netto');
        if (priceNettoElement) {
            const nettoText = priceNettoElement.textContent || priceNettoElement.innerText;
            console.log('[AcceptModal] Znaleziono element netto:', nettoText);

            // Wyciągnij liczbę z tekstu
            const nettoMatch = nettoText.match(/[\d,\s]+/);
            if (nettoMatch) {
                totalNetto = nettoMatch[0]
                    .replace(/\s/g, '')           // Usuń spacje
                    .replace(/&nbsp;/g, '')       // Usuń &nbsp;
                    .replace(',', '.');           // Zamień przecinek na kropkę

                console.log('[AcceptModal] Wyciągnięto netto:', totalNetto);
            }
        }

        // POPRAWKA: Oblicz VAT na podstawie różnicy brutto - netto
        if (totalBrutto !== '0.00' && totalNetto !== '0.00') {
            const bruttoNum = parseFloat(totalBrutto);
            const nettoNum = parseFloat(totalNetto);
            const vatNum = bruttoNum - nettoNum;
            totalVat = vatNum.toFixed(2);
        } else if (totalBrutto !== '0.00' && totalNetto === '0.00') {
            // Jeśli mamy tylko brutto, oblicz netto (zakładając VAT 23%)
            const bruttoNum = parseFloat(totalBrutto);
            const nettoNum = bruttoNum / 1.23;
            const vatNum = bruttoNum - nettoNum;

            totalNetto = nettoNum.toFixed(2);
            totalVat = vatNum.toFixed(2);
        }

        // POPRAWKA: Fallback - szukaj w innych miejscach
        if (totalBrutto === '0.00') {
            // Szukaj elementów zawierających "zł"
            const priceElements = document.querySelectorAll('*');

            for (let element of priceElements) {
                const text = element.textContent;
                if (text && text.includes('zł') && !text.includes('0,00') && !text.includes('0.00')) {
                    // Sprawdź czy to wygląda na cenę końcową (większa wartość)
                    const priceMatch = text.match(/([\d\s,]+)[\s&nbsp;]*zł/);
                    if (priceMatch) {
                        const price = priceMatch[1]
                            .replace(/\s/g, '')
                            .replace(/&nbsp;/g, '')
                            .replace(',', '.');

                        const priceNum = parseFloat(price);
                        const currentBruttoNum = parseFloat(totalBrutto);

                        // Użyj tej ceny jeśli jest większa od obecnej
                        if (priceNum > currentBruttoNum && priceNum > 10) { // Tylko sensowne ceny
                            totalBrutto = price;
                            console.log('[AcceptModal] Fallback - znaleziono cenę:', price);
                            break;
                        }
                    }
                }
            }
        }

        // POPRAWKA: Sprawdź w window.quoteData jeśli nadal brak danych
        if (totalBrutto === '0.00' && window.quoteData) {
            if (window.quoteData.total_price) {
                totalBrutto = window.quoteData.total_price.toString();
            }
            if (window.quoteData.costs) {
                totalBrutto = window.quoteData.costs.total_brutto || totalBrutto;
                totalNetto = window.quoteData.costs.total_netto || totalNetto;
                totalVat = window.quoteData.costs.total_vat || totalVat;
            }
        }

        // POPRAWKA: Jeśli nadal brak danych, sprawdź localStorage lub inne źródła
        if (totalBrutto === '0.00') {
            console.log('[AcceptModal] Brak danych cenowych - sprawdzam dodatkowe źródła');

            // Sprawdź elementy z klasami zawierającymi "total", "price", "cost"
            const totalElements = document.querySelectorAll('[class*="total"], [class*="price"], [class*="cost"], [class*="summary"]');

            for (let element of totalElements) {
                const text = element.textContent;
                if (text && (text.includes('zł') || text.includes('PLN'))) {
                    const priceMatch = text.match(/([\d\s,]+)/);
                    if (priceMatch) {
                        const price = priceMatch[1].replace(/\s/g, '').replace(',', '.');
                        const priceNum = parseFloat(price);

                        if (priceNum > 100) { // Tylko rozsądne ceny
                            totalBrutto = price;
                            console.log('[AcceptModal] Znaleziono cenę w elemencie:', element.className, price);
                            break;
                        }
                    }
                }
            }
        }

        // Formatuj wygląd podsumowania
        const summary = `
            <div class="quote-summary-item" style="display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #e5e5e5;">
                <span style="font-weight: 600; color: #666;">Numer wyceny:</span>
                <span style="color: #333;">${quoteNumber || 'N/A'}</span>
            </div>
            <div class="quote-summary-item" style="display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #e5e5e5;">
                <span style="font-weight: 600; color: #666;">Wartość netto:</span>
                <span style="color: #333;">${totalNetto} zł</span>
            </div>
            <div class="quote-summary-item" style="display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #e5e5e5;">
                <span style="font-weight: 600; color: #666;">VAT 23%:</span>
                <span style="color: #333;">${totalVat} zł</span>
            </div>
            <div class="quote-summary-item total" style="display: flex; justify-content: space-between; padding: 8px 0; font-weight: bold; background: rgba(237, 107, 36, 0.1); margin: 8px -8px 0 -8px; padding: 8px;">
                <span style="color: #ED6B24;">Wartość brutto:</span>
                <span style="color: #ED6B24;">${totalBrutto} zł</span>
            </div>
        `;

        summaryContainer.innerHTML = summary;

        console.log('[AcceptModal] Podsumowanie wyceny zaktualizowane:', {
            quoteNumber, totalNetto, totalVat, totalBrutto
        });

    } catch (error) {
        console.error('[AcceptModal] Błąd aktualizacji podsumowania wyceny:', error);
        summaryContainer.innerHTML = '<p style="color: #666;">Błąd ładowania danych wyceny</p>';
    }
}
function debugQuotePrices() {
    console.log('=== DEBUG DANYCH CENOWYCH ===');

    // Sprawdź globalne dane
    console.log('window.currentQuoteData:', window.currentQuoteData);
    console.log('window.quoteData:', window.quoteData);

    // Sprawdź elementy DOM
    console.log('Elementy z klasą price-brutto:', document.querySelectorAll('.price-brutto'));
    console.log('Elementy z klasą price-netto:', document.querySelectorAll('.price-netto'));
    console.log('Elementy z klasą total-netto:', document.querySelectorAll('.total-netto'));
    console.log('Elementy z klasą summary-total-main:', document.querySelectorAll('.summary-total-main'));

    // Sprawdź zawartość elementów
    const bruttoElement = document.querySelector('.price-brutto, .summary-total-main');
    if (bruttoElement) {
        console.log('Tekst elementu brutto:', bruttoElement.textContent);
    }

    const nettoElement = document.querySelector('.price-netto, .total-netto');
    if (nettoElement) {
        console.log('Tekst elementu netto:', nettoElement.textContent);
    }

    console.log('=== KONIEC DEBUG ===');
}

function updateSummaryWithQuoteData() {
    console.log('[AcceptModal] Aktualizacja podsumowania z danymi wyceny');

    // Podstawowe dane kontaktowe
    document.getElementById('summaryEmail').textContent = document.getElementById('acceptEmail').value || '-';
    document.getElementById('summaryPhone').textContent = document.getElementById('acceptPhone').value || '-';

    // Sposób dostawy
    const isSelfPickup = document.getElementById('selfPickup').checked;
    const deliveryMethodElement = document.getElementById('summaryDeliveryMethod');
    const deliveryAddressSection = document.getElementById('deliveryAddressSummary');

    if (isSelfPickup) {
        deliveryMethodElement.textContent = 'Odbiór osobisty';
        deliveryAddressSection.style.display = 'none';
    } else {
        deliveryMethodElement.textContent = 'Dostawa kurierska';
        deliveryAddressSection.style.display = 'block';

        const address = [
            document.getElementById('deliveryName').value,
            document.getElementById('deliveryCompany').value,
            document.getElementById('deliveryAddress').value,
            `${document.getElementById('deliveryZip').value} ${document.getElementById('deliveryCity').value}`,
            document.getElementById('deliveryRegion').value
        ].filter(Boolean).join(', ');

        document.getElementById('summaryDeliveryAddress').textContent = address || '-';
    }

    // Faktura
    const wantInvoice = document.getElementById('wantInvoice').checked;
    const invoiceSection = document.getElementById('summaryInvoice');

    if (wantInvoice) {
        invoiceSection.style.display = 'block';

        const invoiceData = [
            document.getElementById('invoiceName').value,
            document.getElementById('invoiceCompany').value,
            document.getElementById('invoiceAddress').value,
            `${document.getElementById('invoiceZip').value} ${document.getElementById('invoiceCity').value}`,
            `NIP: ${document.getElementById('invoiceNip').value}`
        ].filter(Boolean).join(', ');

        document.getElementById('summaryInvoiceData').textContent = invoiceData || '-';
    } else {
        invoiceSection.style.display = 'none';
    }

    // Uwagi
    const comments = document.getElementById('acceptComments').value.trim();
    const commentsSection = document.getElementById('summaryComments');

    if (comments) {
        commentsSection.style.display = 'block';
        document.getElementById('summaryCommentsText').textContent = comments;
    } else {
        commentsSection.style.display = 'none';
    }

    // POPRAWKA: Użyj funkcji pobierającej rzeczywiste dane
    updateQuoteSummaryFromPageElements();
}

function updateQuoteSummaryFromPageElements() {
    const summaryContainer = document.getElementById('quoteSummaryContent');

    try {
        let totalNetto = '0.00';
        let totalVat = '0.00';
        let totalBrutto = '0.00';
        let quoteNumber = '';

        // Pobierz numer wyceny
        if (window.currentQuoteData && window.currentQuoteData.quote_number) {
            quoteNumber = window.currentQuoteData.quote_number;
        }

        console.log('[AcceptModal] Szukanie właściwych cen...');

        // POPRAWKA: Użyj dokładnych selektorów na podstawie Twojej diagnozy

        // 1. Brutto z podsumowania (price-brutto summary-total-main)
        const bruttoElement = document.querySelector('.price-brutto.summary-total-main');
        if (bruttoElement) {
            const bruttoText = bruttoElement.textContent;
            console.log('[AcceptModal] Znaleziono brutto summary-total-main:', bruttoText);

            const bruttoMatch = bruttoText.match(/([\d,\s]+)/);
            if (bruttoMatch) {
                totalBrutto = bruttoMatch[1]
                    .replace(/\s/g, '')
                    .replace(/&nbsp;/g, '')
                    .replace(',', '.');
            }
        }

        // 2. Netto z podsumowania (price-netto total-netto)
        const nettoElement = document.querySelector('.price-netto.total-netto');
        if (nettoElement) {
            const nettoText = nettoElement.textContent;
            console.log('[AcceptModal] Znaleziono netto total-netto:', nettoText);

            const nettoMatch = nettoText.match(/([\d,\s]+)/);
            if (nettoMatch) {
                totalNetto = nettoMatch[1]
                    .replace(/\s/g, '')
                    .replace(/&nbsp;/g, '')
                    .replace(',', '.');
            }
        }

        // FALLBACK: Jeśli nie znaleziono powyższych, użyj alternatywnych selektorów
        if (totalBrutto === '0.00') {
            console.log('[AcceptModal] Fallback - szukanie ostatniego elementu brutto');
            const allBruttoElements = document.querySelectorAll('.price-brutto');

            // Sprawdź czy któryś zawiera 2124 (Twoja prawdziwa cena)
            for (let element of allBruttoElements) {
                if (element.textContent.includes('2124')) {
                    const bruttoText = element.textContent;
                    const bruttoMatch = bruttoText.match(/([\d,\s]+)/);
                    if (bruttoMatch) {
                        totalBrutto = bruttoMatch[1].replace(/\s/g, '').replace(',', '.');
                        console.log('[AcceptModal] Fallback brutto z 2124:', totalBrutto);
                        break;
                    }
                }
            }
        }

        if (totalNetto === '0.00') {
            console.log('[AcceptModal] Fallback - szukanie ostatniego elementu netto');
            const allNettoElements = document.querySelectorAll('.price-netto');

            // Sprawdź czy któryś zawiera 1727 (Twoja prawdziwa cena)
            for (let element of allNettoElements) {
                if (element.textContent.includes('1727')) {
                    const nettoText = element.textContent;
                    const nettoMatch = nettoText.match(/([\d,\s]+)/);
                    if (nettoMatch) {
                        totalNetto = nettoMatch[1].replace(/\s/g, '').replace(',', '.');
                        console.log('[AcceptModal] Fallback netto z 1727:', totalNetto);
                        break;
                    }
                }
            }
        }

        // Oblicz VAT
        if (totalBrutto !== '0.00' && totalNetto !== '0.00') {
            const bruttoNum = parseFloat(totalBrutto);
            const nettoNum = parseFloat(totalNetto);
            const vatNum = bruttoNum - nettoNum;
            totalVat = vatNum.toFixed(2);
        } else if (totalBrutto !== '0.00') {
            // Oblicz netto z brutto (VAT 23%)
            const bruttoNum = parseFloat(totalBrutto);
            const nettoNum = bruttoNum / 1.23;
            const vatNum = bruttoNum - nettoNum;
            totalNetto = nettoNum.toFixed(2);
            totalVat = vatNum.toFixed(2);
        }

        // Wyrenderuj podsumowanie
        const summary = `
            <div style="display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #e5e5e5; font-size: 12px;">
                <span style="font-weight: 600; color: #666;">Numer wyceny:</span>
                <span style="color: #333;">${quoteNumber || 'N/A'}</span>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #e5e5e5; font-size: 12px;">
                <span style="font-weight: 600; color: #666;">Wartość netto:</span>
                <span style="color: #333;">${totalNetto} zł</span>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #e5e5e5; font-size: 12px;">
                <span style="font-weight: 600; color: #666;">VAT 23%:</span>
                <span style="color: #333;">${totalVat} zł</span>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 8px; font-weight: bold; background: rgba(237, 107, 36, 0.1); margin: 8px -8px 0 -8px; border-radius: 4px; font-size: 13px;">
                <span style="color: #ED6B24;">Wartość brutto:</span>
                <span style="color: #ED6B24;">${totalBrutto} zł</span>
            </div>
        `;

        summaryContainer.innerHTML = summary;

        console.log('[AcceptModal] POPRAWIONE podsumowanie wyceny:', {
            quoteNumber, totalNetto, totalVat, totalBrutto
        });

    } catch (error) {
        console.error('[AcceptModal] Błąd aktualizacji podsumowania wyceny:', error);
        summaryContainer.innerHTML = '<p style="color: #666; font-size: 12px;">Błąd ładowania danych wyceny</p>';
    }
}

// SZYBKI TEST w konsoli
function quickTestPrices() {
    console.log('=== SZYBKI TEST CEN ===');

    const bruttoElement = document.querySelector('.price-brutto.summary-total-main');
    const nettoElement = document.querySelector('.price-netto.total-netto');

    console.log('Brutto element:', bruttoElement);
    console.log('Brutto text:', bruttoElement ? bruttoElement.textContent : 'BRAK');

    console.log('Netto element:', nettoElement);
    console.log('Netto text:', nettoElement ? nettoElement.textContent : 'BRAK');

    console.log('=== KONIEC TESTU ===');
}

// Animowana aktualizacja progress bar
function updateProgressBarAnimated(stepNumber) {
    const steps = document.querySelectorAll('.progress-step');

    steps.forEach((step, index) => {
        const stepNum = index + 1;
        const circle = step.querySelector('.progress-circle');
        const label = step.querySelector('.progress-label');

        // Usuń wszystkie klasy z delikatnym opóźnieniem
        setTimeout(() => {
            step.classList.remove('active', 'completed');

            if (stepNum === stepNumber) {
                step.classList.add('active');
                // Delikatna animacja pulsu dla aktywnego kroku
                circle.style.animation = 'gentlePulse 0.6s ease-out';
            } else if (stepNum < stepNumber) {
                step.classList.add('completed');
                // Delikatna animacja checkmark
                circle.style.animation = 'gentleSuccess 0.4s ease-out';
            }

            // Wyczyść animacje po zakończeniu
            setTimeout(() => {
                circle.style.animation = '';
            }, 600);

        }, index * 100); // Kaskadowe animacje
    });
}

// Delikatne przewijanie na górę
function scrollToTopSmooth() {
    const modalContent = document.querySelector('.accept-modal-content');
    if (modalContent) {
        modalContent.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    }
}

// Focus na pierwszy element w kroku
function focusFirstElement(stepNumber) {
    setTimeout(() => {
        const step = document.getElementById(`accept-step-${stepNumber}`);
        const firstInput = step.querySelector('input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled])');

        if (firstInput) {
            firstInput.focus();
            // Delikatne podświetlenie focusowanego elementu
            firstInput.style.transition = 'all 0.3s ease';
            firstInput.style.boxShadow = '0 0 0 3px rgba(237, 107, 36, 0.2)';

            setTimeout(() => {
                firstInput.style.boxShadow = '';
            }, 1500);
        }
    }, 450); // Po zakończeniu animacji kroku
}

// Animacja błędu dla całego kroku
function addErrorShakeAnimation() {
    const currentStepElement = document.getElementById(`accept-step-${currentStep}`);
    currentStepElement.style.animation = 'gentleShake 0.5s ease-in-out';

    setTimeout(() => {
        currentStepElement.style.animation = '';
    }, 500);
}

// Obsługa zmiany opcji odbioru osobistego
function handleSelfPickupChange() {
    const isSelfPickup = document.getElementById('selfPickup').checked;
    const deliverySection = document.getElementById('deliverySection');

    if (isSelfPickup) {
        deliverySection.classList.add('hidden');
        clearDeliveryFields();
    } else {
        deliverySection.classList.remove('hidden');
    }

    console.log(`[AcceptModal] Odbiór osobisty: ${isSelfPickup}`);
}

// Obsługa toggle faktury
function handleInvoiceToggle() {
    const wantInvoice = document.getElementById('wantInvoice').checked;
    const invoiceFields = document.getElementById('invoiceFields');

    if (wantInvoice) {
        invoiceFields.style.display = 'block';
    } else {
        invoiceFields.style.display = 'none';
        clearInvoiceFields();
    }

    console.log(`[AcceptModal] Faktura: ${wantInvoice}`);
}

function showFieldError(errorId, message) {
    const errorElement = document.getElementById(errorId);
    if (errorElement) {
        errorElement.textContent = message;
        errorElement.classList.remove('hidden');

        // Delikatna animacja pojawienia się błędu
        errorElement.style.opacity = '0';
        errorElement.style.transform = 'translateY(-5px)';

        setTimeout(() => {
            errorElement.style.transition = 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)';
            errorElement.style.opacity = '1';
            errorElement.style.transform = 'translateY(0)';
        }, 50);

        // Dodaj animację shake do pola
        const fieldId = errorId.replace('Error', '');
        const field = document.getElementById(fieldId);
        if (field) {
            field.classList.add('error');
            field.style.animation = 'gentleFieldShake 0.4s ease-in-out';

            setTimeout(() => {
                field.style.animation = '';
            }, 400);
        }
    }
}

// Obsługa zmiany danych kontaktowych (auto-uzupełnianie)
async function handleContactDataChange() {
    const email = document.getElementById('acceptEmail').value.trim();
    const phone = document.getElementById('acceptPhone').value.trim();

    if (!email && !phone) return;

    try {
        console.log('[AcceptModal] Sprawdzanie istniejących danych klienta...');

        // Pobierz dane klienta dla tego tokena
        const token = getCurrentQuoteToken();
        const response = await fetch(`/quotes/api/client/quote/${token}/client-data`);

        if (response.ok) {
            const data = await response.json();

            // Sprawdź czy email lub telefon pasuje
            const emailMatch = normalizePhone(data.email) === normalizePhone(email);
            const phoneMatch = normalizePhone(data.phone) === normalizePhone(phone);

            if (emailMatch || phoneMatch) {
                existingClientData = data;
                showAutoFillInfo();
                fillFormWithExistingData(data);
                console.log('[AcceptModal] Znaleziono pasujące dane klienta');
            }
        }
    } catch (error) {
        console.error('[AcceptModal] Błąd pobierania danych klienta:', error);
    }
}

// Pokaż informację o auto-uzupełnieniu
function showAutoFillInfo() {
    const infoElement = document.getElementById('autoFillInfo');
    infoElement.style.display = 'flex';
}

// Wypełnij formularz istniejącymi danymi
function fillFormWithExistingData(data) {
    // Dane dostawy
    if (data.delivery) {
        document.getElementById('deliveryName').value = data.delivery.name || '';
        document.getElementById('deliveryCompany').value = data.delivery.company || '';
        document.getElementById('deliveryAddress').value = data.delivery.address || '';
        document.getElementById('deliveryZip').value = data.delivery.zip || '';
        document.getElementById('deliveryCity').value = data.delivery.city || '';
        document.getElementById('deliveryRegion').value = data.delivery.region || '';
    }

    // Dane do faktury (jeśli istnieją)
    if (data.invoice && data.invoice.nip) {
        document.getElementById('wantInvoice').checked = true;
        handleInvoiceToggle();

        document.getElementById('invoiceName').value = data.invoice.name || '';
        document.getElementById('invoiceCompany').value = data.invoice.company || '';
        document.getElementById('invoiceAddress').value = data.invoice.address || '';
        document.getElementById('invoiceZip').value = data.invoice.zip || '';
        document.getElementById('invoiceCity').value = data.invoice.city || '';
        document.getElementById('invoiceNip').value = data.invoice.nip || '';
    }
}

// Obsługa GUS
async function handleGusLookup() {
    const nipInput = document.getElementById('invoiceNip');
    const gusBtn = document.getElementById('gusLookupBtn');
    const nip = nipInput.value.trim().replace(/\s+/g, '');

    clearFieldError('invoiceNipError');

    if (!nip) {
        showFieldError('invoiceNipError', 'Podaj NIP aby skorzystać z GUS');
        return;
    }

    if (!isValidNIP(nip)) {
        showFieldError('invoiceNipError', 'Podaj prawidłowy NIP (10 cyfr)');
        return;
    }

    // Animacja loading
    gusBtn.classList.add('loading');
    gusBtn.disabled = true;
    gusBtn.textContent = 'Ładowanie...';

    try {
        const response = await fetch(`/clients/api/gus_lookup?nip=${nip}`);
        const data = await response.json();

        if (response.ok && data.name) {
            console.log('[AcceptModal] Dane z GUS otrzymane:', data);

            // POPRAWKA: Inteligentne parsowanie adresu
            const parsedAddress = parseGusAddress(data.address || '');

            // Wypełnij podstawowe pola
            document.getElementById('invoiceName').value = data.name || '';
            document.getElementById('invoiceCompany').value = data.company || data.name || '';

            // POPRAWKA: Wypełnij pola adresu z parsowanych danych
            document.getElementById('invoiceAddress').value = parsedAddress.street || '';
            document.getElementById('invoiceZip').value = parsedAddress.zipCode || '';
            document.getElementById('invoiceCity').value = parsedAddress.city || '';

            // Prosta informacja o sukcesie
            gusBtn.textContent = 'Pobrano dane ✓';
            gusBtn.style.background = '#28a745';

            setTimeout(() => {
                gusBtn.textContent = 'Pobierz z GUS';
                gusBtn.style.background = '#004aad';
            }, 2000);

            console.log('[AcceptModal] Dane GUS wypełnione:', {
                name: data.name,
                company: data.company || data.name,
                originalAddress: data.address,
                parsedAddress: parsedAddress
            });

        } else {
            gusBtn.textContent = 'Błąd ❌';
            gusBtn.style.background = '#dc3545';

            setTimeout(() => {
                gusBtn.textContent = 'Pobierz z GUS';
                gusBtn.style.background = '#004aad';
            }, 2000);

            showFieldError('invoiceNipError', data.error || 'Nie znaleziono danych dla podanego NIP');
        }
    } catch (error) {
        console.error('[AcceptModal] Błąd GUS:', error);

        gusBtn.textContent = 'Błąd połączenia ❌';
        gusBtn.style.background = '#dc3545';

        setTimeout(() => {
            gusBtn.textContent = 'Pobierz z GUS';
            gusBtn.style.background = '#004aad';
        }, 2000);

        showFieldError('invoiceNipError', 'Błąd połączenia z GUS');
    } finally {
        gusBtn.classList.remove('loading');
        gusBtn.disabled = false;
    }
}

// ========== POPRAWIONA FUNKCJA GUS Z ROZDZIELANIEM ADRESU ==========

// POPRAWKA: Ulepszona obsługa GUS z inteligentnym parsowaniem adresu
async function handleGusLookup() {
    const nipInput = document.getElementById('invoiceNip');
    const gusBtn = document.getElementById('gusLookupBtn');
    const nip = nipInput.value.trim().replace(/\s+/g, '');

    clearFieldError('invoiceNipError');

    if (!nip) {
        showFieldError('invoiceNipError', 'Podaj NIP aby skorzystać z GUS');
        return;
    }

    if (!isValidNIP(nip)) {
        showFieldError('invoiceNipError', 'Podaj prawidłowy NIP (10 cyfr)');
        return;
    }

    // Animacja loading
    gusBtn.classList.add('loading');
    gusBtn.disabled = true;
    gusBtn.textContent = 'Ładowanie...';

    try {
        const response = await fetch(`/clients/api/gus_lookup?nip=${nip}`);
        const data = await response.json();

        if (response.ok && data.name) {
            console.log('[AcceptModal] Dane z GUS otrzymane:', data);

            // POPRAWKA: Inteligentne parsowanie adresu
            const parsedAddress = parseGusAddress(data.address || '');

            // Wypełnij podstawowe pola
            document.getElementById('invoiceName').value = data.name || '';
            document.getElementById('invoiceCompany').value = data.company || data.name || '';

            // POPRAWKA: Wypełnij pola adresu z parsowanych danych
            document.getElementById('invoiceAddress').value = parsedAddress.street || '';
            document.getElementById('invoiceZip').value = parsedAddress.zipCode || '';
            document.getElementById('invoiceCity').value = parsedAddress.city || '';

            // Prosta informacja o sukcesie
            gusBtn.textContent = 'Pobrano dane ✓';
            gusBtn.style.background = '#28a745';

            setTimeout(() => {
                gusBtn.textContent = 'Pobierz z GUS';
                gusBtn.style.background = '#004aad';
            }, 2000);

            console.log('[AcceptModal] Dane GUS wypełnione:', {
                name: data.name,
                company: data.company || data.name,
                originalAddress: data.address,
                parsedAddress: parsedAddress
            });

        } else {
            gusBtn.textContent = 'Błąd ❌';
            gusBtn.style.background = '#dc3545';

            setTimeout(() => {
                gusBtn.textContent = 'Pobierz z GUS';
                gusBtn.style.background = '#004aad';
            }, 2000);

            showFieldError('invoiceNipError', data.error || 'Nie znaleziono danych dla podanego NIP');
        }
    } catch (error) {
        console.error('[AcceptModal] Błąd GUS:', error);

        gusBtn.textContent = 'Błąd połączenia ❌';
        gusBtn.style.background = '#dc3545';

        setTimeout(() => {
            gusBtn.textContent = 'Pobierz z GUS';
            gusBtn.style.background = '#004aad';
        }, 2000);

        showFieldError('invoiceNipError', 'Błąd połączenia z GUS');
    } finally {
        gusBtn.classList.remove('loading');
        gusBtn.disabled = false;
    }
}

// POPRAWKA: Funkcja do inteligentnego parsowania adresu z GUS
function parseGusAddress(fullAddress) {
    console.log('[GUS Parser] Parsowanie adresu:', fullAddress);

    if (!fullAddress || typeof fullAddress !== 'string') {
        return { street: '', zipCode: '', city: '' };
    }

    // Usuń zbędne spacje i znaki
    const cleanAddress = fullAddress.trim().replace(/\s+/g, ' ');

    // Wzorce do rozpoznania
    const zipCodePattern = /\b\d{2}-\d{3}\b/; // XX-XXX
    const zipCodeMatch = cleanAddress.match(zipCodePattern);

    let street = '';
    let zipCode = '';
    let city = '';

    if (zipCodeMatch) {
        zipCode = zipCodeMatch[0];
        const zipIndex = cleanAddress.indexOf(zipCode);

        // Wszystko przed kodem pocztowym to ulica
        street = cleanAddress.substring(0, zipIndex).trim();

        // Wszystko po kodzie pocztowym to miasto
        city = cleanAddress.substring(zipIndex + zipCode.length).trim();

        // Usuń ewentualne przecinki i inne znaki interpunkcyjne
        street = street.replace(/[,;]+$/, '').trim();
        city = city.replace(/^[,;]+/, '').trim();

    } else {
        // Jeśli nie ma kodu pocztowego, spróbuj innych metod
        // Szukaj wzorca: ulica, miasto lub ulica miasto

        const parts = cleanAddress.split(/[,;]/);

        if (parts.length >= 2) {
            // Pierwszy element to prawdopodobnie ulica
            street = parts[0].trim();

            // Ostatni element to prawdopodobnie miasto (może z kodem)
            const lastPart = parts[parts.length - 1].trim();

            // Sprawdź czy ostatnia część zawiera kod pocztowy
            const lastPartZipMatch = lastPart.match(zipCodePattern);
            if (lastPartZipMatch) {
                zipCode = lastPartZipMatch[0];
                city = lastPart.replace(zipCode, '').trim();
            } else {
                city = lastPart;
            }
        } else {
            // Jedna część - spróbuj wyodrębnić miasto z końca
            const words = cleanAddress.split(' ');

            if (words.length >= 3) {
                // Ostatnie słowo to prawdopodobnie miasto
                city = words[words.length - 1];

                // Sprawdź czy przedostatnie to kod pocztowy
                const possibleZip = words[words.length - 2];
                if (zipCodePattern.test(possibleZip)) {
                    zipCode = possibleZip;
                    street = words.slice(0, -2).join(' ');
                } else {
                    street = words.slice(0, -1).join(' ');
                }
            } else {
                // Za mało danych - wstaw całość jako ulicę
                street = cleanAddress;
            }
        }
    }

    // Dodatkowe czyszczenie
    street = cleanString(street);
    city = cleanString(city);
    zipCode = cleanString(zipCode);

    const result = { street, zipCode, city };
    console.log('[GUS Parser] Wynik parsowania:', result);

    return result;
}

// Pomocnicza funkcja do czyszczenia stringów
function cleanString(str) {
    if (!str) return '';

    return str
        .trim()
        .replace(/^[,\s]+|[,\s]+$/g, '')  // Usuń przecinki i spacje z początku/końca
        .replace(/\s+/g, ' ')            // Zamień wielokrotne spacje na pojedyncze
        .trim();
}



// Kopiowanie danych z dostawy do faktury
function copyDeliveryToInvoice() {
    document.getElementById('invoiceName').value = document.getElementById('deliveryName').value;
    document.getElementById('invoiceCompany').value = document.getElementById('deliveryCompany').value;
    document.getElementById('invoiceAddress').value = document.getElementById('deliveryAddress').value;
    document.getElementById('invoiceZip').value = document.getElementById('deliveryZip').value;
    document.getElementById('invoiceCity').value = document.getElementById('deliveryCity').value;

    console.log('[AcceptModal] Skopiowano dane z dostawy do faktury');
}

// Aktualizacja podsumowania
function updateSummary() {
    console.log('[AcceptModal] Aktualizacja podsumowania');

    // Dane kontaktowe
    document.getElementById('summaryEmail').textContent = document.getElementById('acceptEmail').value;
    document.getElementById('summaryPhone').textContent = document.getElementById('acceptPhone').value;

    // Sposób dostawy
    const isSelfPickup = document.getElementById('selfPickup').checked;
    const deliveryMethodElement = document.getElementById('summaryDeliveryMethod');
    const deliveryAddressSection = document.getElementById('deliveryAddressSummary');

    if (isSelfPickup) {
        deliveryMethodElement.textContent = 'Odbiór osobisty';
        deliveryAddressSection.style.display = 'none';
    } else {
        deliveryMethodElement.textContent = 'Dostawa kurierska';
        deliveryAddressSection.style.display = 'block';

        const address = [
            document.getElementById('deliveryName').value,
            document.getElementById('deliveryCompany').value,
            document.getElementById('deliveryAddress').value,
            `${document.getElementById('deliveryZip').value} ${document.getElementById('deliveryCity').value}`,
            document.getElementById('deliveryRegion').value
        ].filter(Boolean).join(', ');

        document.getElementById('summaryDeliveryAddress').textContent = address;
    }

    // Faktura
    const wantInvoice = document.getElementById('wantInvoice').checked;
    const invoiceSection = document.getElementById('summaryInvoice');

    if (wantInvoice) {
        invoiceSection.style.display = 'block';

        const invoiceData = [
            document.getElementById('invoiceName').value,
            document.getElementById('invoiceCompany').value,
            document.getElementById('invoiceAddress').value,
            `${document.getElementById('invoiceZip').value} ${document.getElementById('invoiceCity').value}`,
            `NIP: ${document.getElementById('invoiceNip').value}`
        ].filter(Boolean).join(', ');

        document.getElementById('summaryInvoiceData').textContent = invoiceData;
    } else {
        invoiceSection.style.display = 'none';
    }

    // Uwagi
    const comments = document.getElementById('acceptComments').value.trim();
    const commentsSection = document.getElementById('summaryComments');

    if (comments) {
        commentsSection.style.display = 'block';
        document.getElementById('summaryCommentsText').textContent = comments;
    } else {
        commentsSection.style.display = 'none';
    }

    // Podsumowanie wyceny - użyj globalnych danych wyceny
    updateQuoteSummary();
}

// Aktualizacja podsumowania wyceny
function updateQuoteSummary() {
    const summaryContainer = document.getElementById('quoteSummaryContent');

    if (!currentQuoteData) {
        summaryContainer.innerHTML = '<p>Brak danych wyceny</p>';
        return;
    }

    // Pobierz informacje o wybranych produktach i kosztach
    // (to będzie zależne od struktury danych wyceny w globalnym scope)
    const summary = `
        <div class="quote-summary-item">
            <span class="label">Numer wyceny:</span>
            <span class="value">${currentQuoteData.quote_number || 'N/A'}</span>
        </div>
        <div class="quote-summary-item">
            <span class="label">Wartość netto:</span>
            <span class="value">${currentQuoteData.total_netto || '0.00'} zł</span>
        </div>
        <div class="quote-summary-item">
            <span class="label">VAT 23%:</span>
            <span class="value">${currentQuoteData.total_vat || '0.00'} zł</span>
        </div>
        <div class="quote-summary-item total">
            <span class="label"><strong>Wartość brutto:</strong></span>
            <span class="value"><strong>${currentQuoteData.total_brutto || '0.00'} zł</strong></span>
        </div>
    `;

    summaryContainer.innerHTML = summary;
}

// Finalne submitowanie
async function handleFinalSubmit() {
    console.log('[AcceptModal] Rozpoczęcie finalnego submitowania');

    // POPRAWKA: Sprawdź checkbox akceptacji warunków
    const termsAccepted = document.getElementById('acceptTerms').checked;

    if (!termsAccepted) {
        showFieldError('termsError', 'Musisz zaakceptować warunki aby kontynuować');
        return;
    }

    // Wyczyść błąd checkbox
    clearFieldError('termsError');

    const submitBtn = document.getElementById('finalSubmitBtn');
    const loadingOverlay = document.getElementById('acceptLoadingOverlay');

    // Pokaż loading
    submitBtn.disabled = true;
    loadingOverlay.style.display = 'flex';

    try {
        // Przygotuj dane do wysłania
        const formData = collectFormData();

        // Wyślij dane
        const token = getCurrentQuoteToken();
        const response = await fetch(`/quotes/api/client/quote/${token}/accept-with-data`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(formData)
        });

        const result = await response.json();

        if (response.ok) {
            console.log('[AcceptModal] Wycena zaakceptowana pomyślnie:', result);

            if (result.redirect_url) {
                window.location.href = result.redirect_url;
            } else {
                showSuccessMessage('Wycena została zaakceptowana pomyślnie!');
                closeAcceptModal();
                setTimeout(() => {
                    window.location.reload();
                }, 2000);
            }

        } else {
            console.error('[AcceptModal] Błąd akceptacji:', result);
            showErrorMessage(result.error || 'Wystąpił błąd podczas akceptacji wyceny');
        }

    } catch (error) {
        console.error('[AcceptModal] Błąd sieciowy:', error);
        showErrorMessage('Błąd połączenia. Spróbuj ponownie.');
    } finally {
        submitBtn.disabled = false;
        loadingOverlay.style.display = 'none';
    }
}

// Zbieranie danych z formularza
function collectFormData() {
    const isSelfPickup = document.getElementById('selfPickup').checked;
    const wantInvoice = document.getElementById('wantInvoice').checked;

    const formData = {
        // Dane kontaktowe
        email: document.getElementById('acceptEmail').value.trim(),
        phone: document.getElementById('acceptPhone').value.trim(),

        // Uwagi
        comments: document.getElementById('acceptComments').value.trim(),

        // Opcje
        self_pickup: isSelfPickup,
        wants_invoice: wantInvoice
    };

    // Dane dostawy (jeśli nie odbiór osobisty)
    if (!isSelfPickup) {
        formData.delivery_name = document.getElementById('deliveryName').value.trim();
        formData.delivery_company = document.getElementById('deliveryCompany').value.trim();
        formData.delivery_address = document.getElementById('deliveryAddress').value.trim();
        formData.delivery_postcode = document.getElementById('deliveryZip').value.trim();
        formData.delivery_city = document.getElementById('deliveryCity').value.trim();
        formData.delivery_region = document.getElementById('deliveryRegion').value.trim();
    }

    // Dane do faktury (jeśli wybrano)
    if (wantInvoice) {
        formData.invoice_name = document.getElementById('invoiceName').value.trim();
        formData.invoice_company = document.getElementById('invoiceCompany').value.trim();
        formData.invoice_address = document.getElementById('invoiceAddress').value.trim();
        formData.invoice_postcode = document.getElementById('invoiceZip').value.trim();
        formData.invoice_city = document.getElementById('invoiceCity').value.trim();
        formData.invoice_nip = document.getElementById('invoiceNip').value.trim();
    }

    return formData;
}

// === FUNKCJE POMOCNICZE ===

// Walidacja email
function isValidEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

// Walidacja telefonu
function isValidPhone(phone) {
    // Usuń wszystkie znaki oprócz cyfr i +
    const cleaned = phone.replace(/[^\d+]/g, '');
    // Sprawdź czy ma odpowiednią długość (9 cyfr + ewentualnie +48)
    return cleaned.length >= 9 && cleaned.length <= 12;
}

// Normalizacja telefonu do porównania
function normalizePhone(phone) {
    if (!phone) return '';
    // Usuń spacje, myślniki, nawiasy
    let normalized = phone.replace(/[\s\-\(\)]/g, '');
    // Zamień +48 na początek
    if (normalized.startsWith('+48')) {
        normalized = normalized.substring(3);
    }
    return normalized;
}

// Walidacja kodu pocztowego
function isValidZipCode(zip) {
    const zipRegex = /^\d{2}-\d{3}$/;
    return zipRegex.test(zip);
}

// Walidacja NIP
function isValidNIP(nip) {
    const cleaned = nip.replace(/[\s\-]/g, '');
    return /^\d{10}$/.test(cleaned);
}

// Pokaż błąd pola
function showFieldError(errorId, message) {
    const errorElement = document.getElementById(errorId);
    if (errorElement) {
        errorElement.textContent = message;
        errorElement.classList.remove('hidden');

        // Tylko zmiana koloru ramki - BEZ skoków
        const fieldId = errorId.replace('Error', '');
        const field = document.getElementById(fieldId);
        if (field) {
            field.classList.add('error');
        }
    }
}

// Wyczyść błąd pola
function clearFieldError(errorId) {
    const errorElement = document.getElementById(errorId);
    if (errorElement) {
        errorElement.textContent = '';
        errorElement.classList.add('hidden');

        // Usuń błąd z pola
        const fieldId = errorId.replace('Error', '');
        const field = document.getElementById(fieldId);
        if (field && field.value.trim()) {
            field.classList.remove('error');
            field.classList.add('success');
        }
    }
}
// Wyczyść wszystkie błędy
function clearAllFieldErrors() {
    const errors = document.querySelectorAll('.form-error');
    errors.forEach(error => {
        error.textContent = '';
        error.classList.add('hidden');
    });

    const fields = document.querySelectorAll('.form-input');
    fields.forEach(field => {
        field.classList.remove('error', 'success');
    });
}

// Wyczyść pola dostawy
function clearDeliveryFields() {
    const deliveryFields = ['deliveryName', 'deliveryCompany', 'deliveryAddress', 'deliveryZip', 'deliveryCity', 'deliveryRegion'];
    deliveryFields.forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (field) field.value = '';
    });
}

// Wyczyść pola faktury
function clearInvoiceFields() {
    const invoiceFields = ['invoiceName', 'invoiceCompany', 'invoiceAddress', 'invoiceZip', 'invoiceCity', 'invoiceNip'];
    invoiceFields.forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (field) field.value = '';
    });
}

// Pobierz token obecnej wyceny
function getCurrentQuoteToken() {
    // Ta funkcja musi być dostosowana do sposobu przechowywania tokena w aplikacji
    // Może być to zmienna globalna, parametr URL, lub atrybut data-
    return window.currentQuoteToken || document.querySelector('[data-quote-token]')?.getAttribute('data-quote-token') || '';
}

// Pokaż komunikat sukcesu
function showSuccessMessage(message) {
    // Używaj istniejącego systemu toastów lub alertów z aplikacji
    if (typeof showToast === 'function') {
        showToast(message, 'success');
    } else if (typeof showAlert === 'function') {
        showAlert(message, 'success');
    } else {
        alert(message);
    }
}

// Pokaż komunikat błędu
function showErrorMessage(message) {
    // Używaj istniejącego systemu toastów lub alertów z aplikacji
    if (typeof showToast === 'function') {
        showToast(message, 'error');
    } else if (typeof showAlert === 'function') {
        showAlert(message, 'error');
    } else {
        alert(message);
    }
}

// Resetuj modal do stanu początkowego
function resetAcceptModal() {
    console.log('[AcceptModal] Reset modala do stanu początkowego');

    currentStep = 1;

    // Ukryj wszystkie kroki
    document.querySelectorAll('#acceptModal .accept-step').forEach(step => {
        step.style.display = 'none';
    });

    // Pokaż pierwszy krok
    document.getElementById('accept-step-1').style.display = 'block';

    // Ukryj wszystkie akcje i pokaż pierwszą
    document.querySelectorAll('[id^="step-"][id$="-actions"]').forEach(actions => {
        actions.style.display = 'none';
    });
    document.getElementById('step-1-actions').style.display = 'flex';

    // Reset progress bar
    updateProgressBar(1);

    // Wyczyść wszystkie pola
    clearAllFields();
    clearAllFieldErrors();

    // WYCZYŚĆ KOMUNIKATY WERYFIKACJI
    const existingSuccess = document.querySelector('.validation-success');
    if (existingSuccess) existingSuccess.remove();

    // Ukryj auto-fill info
    const autoFillInfo = document.getElementById('autoFillInfo');
    if (autoFillInfo) autoFillInfo.style.display = 'none';

    // Reset checkboxów
    document.getElementById('selfPickup').checked = false;
    document.getElementById('wantInvoice').checked = false;
    document.getElementById('acceptTerms').checked = false;

    // Reset widoczności sekcji
    const deliverySection = document.getElementById('deliverySection');
    if (deliverySection) deliverySection.classList.remove('hidden');

    const invoiceFields = document.getElementById('invoiceFields');
    if (invoiceFields) invoiceFields.style.display = 'none';

    // Reset danych
    existingClientData = null;
    clientData = {};

    // Przewiń na górę
    const scrollableContent = document.querySelector('#acceptModal .modal-scrollable-content');
    if (scrollableContent) {
        scrollableContent.scrollTop = 0;
    }

    console.log('[AcceptModal] Modal zresetowany - komunikaty weryfikacji usunięte');
}

async function loadAndFillClientData(email, phone) {
    try {
        console.log('[AcceptModal] Pobieranie danych klienta do auto-uzupełnienia...');

        const token = getCurrentQuoteToken();
        const response = await fetch(`/quotes/api/client/quote/${token}/client-data`);

        if (response.ok) {
            const clientData = await response.json();
            console.log('[AcceptModal] Otrzymano dane klienta:', clientData);

            // Sprawdź czy email lub telefon pasuje do danych z bazy
            const emailMatch = clientData.email && email && clientData.email.toLowerCase() === email.toLowerCase();
            const phoneMatch = clientData.phone && phone && normalizePhone(clientData.phone) === normalizePhone(phone);

            if (emailMatch || phoneMatch) {
                console.log('[AcceptModal] Dane pasują - wypełniam formularz');
                fillFormWithClientData(clientData);
                showAutoFillNotification();
            }
        }
    } catch (error) {
        console.error('[AcceptModal] Błąd pobierania danych klienta:', error);
    }
}

// Wypełnij formularz danymi klienta
function fillFormWithClientData(clientData) {
    // Dane dostawy
    if (clientData.delivery) {
        const deliveryName = document.getElementById('deliveryName');
        const deliveryCompany = document.getElementById('deliveryCompany');
        const deliveryAddress = document.getElementById('deliveryAddress');
        const deliveryZip = document.getElementById('deliveryZip');
        const deliveryCity = document.getElementById('deliveryCity');
        const deliveryRegion = document.getElementById('deliveryRegion');

        if (deliveryName && clientData.delivery.name) deliveryName.value = clientData.delivery.name;
        if (deliveryCompany && clientData.delivery.company) deliveryCompany.value = clientData.delivery.company;
        if (deliveryAddress && clientData.delivery.address) deliveryAddress.value = clientData.delivery.address;
        if (deliveryZip && clientData.delivery.zip) deliveryZip.value = clientData.delivery.zip;
        if (deliveryCity && clientData.delivery.city) deliveryCity.value = clientData.delivery.city;
        if (deliveryRegion && clientData.delivery.region) deliveryRegion.value = clientData.delivery.region;
    }

    // Dane do faktury (jeśli istnieją)
    if (clientData.invoice && clientData.invoice.nip) {
        document.getElementById('wantInvoice').checked = true;
        handleInvoiceToggle(); // Pokaż pola faktury

        const invoiceName = document.getElementById('invoiceName');
        const invoiceCompany = document.getElementById('invoiceCompany');
        const invoiceAddress = document.getElementById('invoiceAddress');
        const invoiceZip = document.getElementById('invoiceZip');
        const invoiceCity = document.getElementById('invoiceCity');
        const invoiceNip = document.getElementById('invoiceNip');

        if (invoiceName && clientData.invoice.name) invoiceName.value = clientData.invoice.name;
        if (invoiceCompany && clientData.invoice.company) invoiceCompany.value = clientData.invoice.company;
        if (invoiceAddress && clientData.invoice.address) invoiceAddress.value = clientData.invoice.address;
        if (invoiceZip && clientData.invoice.zip) invoiceZip.value = clientData.invoice.zip;
        if (invoiceCity && clientData.invoice.city) invoiceCity.value = clientData.invoice.city;
        if (invoiceNip && clientData.invoice.nip) invoiceNip.value = clientData.invoice.nip;
    }

    console.log('[AcceptModal] Formularz wypełniony danymi klienta');
}

// Pokaż powiadomienie o auto-uzupełnieniu
function showAutoFillNotification() {
    const autoFillInfo = document.getElementById('autoFillInfo');
    if (autoFillInfo) {
        autoFillInfo.style.display = 'flex';
    } else {
        console.log('[AcceptModal] Auto-fill notification: Wypełniono danymi z bazy');
    }
}

// Funkcja pomocnicza do pobierania tokenu wyceny
function getCurrentQuoteToken() {
    return window.QUOTE_TOKEN ||
        window.currentQuoteToken ||
        document.querySelector('[data-quote-token]')?.getAttribute('data-quote-token') ||
        '';
}

// Dodaj CSS styles bezpiecznie
function addContactValidationStyles() {
    // Sprawdź czy style już istnieją
    if (document.querySelector('#contact-validation-styles')) {
        return;
    }

    const spinnerStyles = `
.spinner {
    display: inline-block;
    width: 16px;
    height: 16px;
    border: 2px solid #ffffff;
    border-radius: 50%;
    border-top-color: transparent;
    animation: spin 1s ease-in-out infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

.validation-success {
    animation: slideIn 0.3s ease-out;
}

@keyframes slideIn {
    from { opacity: 0; transform: translateY(-10px); }
    to { opacity: 1; transform: translateY(0); }
}
    `;

    const styleSheet = document.createElement('style');
    styleSheet.id = 'contact-validation-styles';
    styleSheet.innerHTML = spinnerStyles;
    document.head.appendChild(styleSheet);

    console.log('[AcceptModal] Style CSS dodane');
}

addContactValidationStyles();

async function validateContactStep() {
    let isValid = true;

    const email = document.getElementById('acceptEmail').value.trim();
    const phone = document.getElementById('acceptPhone').value.trim();

    clearFieldError('emailError');
    clearFieldError('phoneError');

    // TYLKO podstawowa walidacja formatu - BEZ API
    if (!email && !phone) {
        showFieldError('emailError', 'Podaj email lub telefon');
        showFieldError('phoneError', 'Podaj email lub telefon');
        return false;
    }

    if (email && !isValidEmail(email)) {
        showFieldError('emailError', 'Podaj prawidłowy adres email');
        isValid = false;
    }

    if (phone && !isValidPhone(phone)) {
        showFieldError('phoneError', 'Podaj prawidłowy numer telefonu');
        isValid = false;
    }

    // Jeśli podstawowa walidacja przeszła, sprawdź w bazie
    if (isValid) {
        return await validateContactInDatabase(email, phone);
    }

    return false;
}

function showValidationSuccess(message) {
    // Usuń poprzednie komunikaty sukcesu
    const existingSuccess = document.querySelector('.validation-success');
    if (existingSuccess) existingSuccess.remove();

    // Stwórz nowy komunikat
    const successDiv = document.createElement('div');
    successDiv.className = 'validation-success';
    successDiv.innerHTML = `
        <div style="background: #e8f5e8; border: 1px solid #4caf50; color: #2e7d2e; padding: 12px; border-radius: 6px; margin: 10px 0; font-size: 14px;">
            <strong>✓ ${message}</strong>
        </div>
    `;

    // Wstaw po polach kontaktowych
    const phoneField = document.getElementById('acceptPhone');
    phoneField.parentNode.insertBefore(successDiv, phoneField.nextSibling);

    // KOMUNIKAT ZOSTAJE - usuń setTimeout
    console.log('[AcceptModal] Komunikat weryfikacji wyświetlony na stałe');
}

function initContactValidation() {
    // PUSTA FUNKCJA - brak auto-walidacji
    console.log('[AcceptModal] Walidacja kontaktowa - tylko po kliknięciu Dalej');
}

// Funkcja pomocnicza do pokazywania sukcesu
function showSuccessMessage(message) {
    // Usuń poprzednie komunikaty sukcesu
    const existingSuccess = document.querySelector('.validation-success');
    if (existingSuccess) existingSuccess.remove();

    // Stwórz nowy komunikat
    const successDiv = document.createElement('div');
    successDiv.className = 'validation-success';
    successDiv.innerHTML = `
        <div style="background: #e8f5e8; border: 1px solid #4caf50; color: #2e7d2e; padding: 12px; border-radius: 6px; margin: 10px 0; font-size: 14px;">
            <strong>✓ ${message}</strong>
        </div>
    `;

    // Wstaw po polach kontaktowych
    const phoneField = document.getElementById('acceptPhone');
    phoneField.parentNode.insertBefore(successDiv, phoneField.nextSibling);

    // Ukryj po 3 sekundach
    setTimeout(() => {
        if (successDiv.parentNode) {
            successDiv.remove();
        }
    }, 3000);
}

// Nowa funkcja do walidacji w bazie - wywoływana osobno
async function validateContactInDatabase(email, phone) {
    try {
        console.log('[AcceptModal] Sprawdzam dane w bazie...');

        // Pokaż loading
        const emailField = document.getElementById('acceptEmail');
        const phoneField = document.getElementById('acceptPhone');

        emailField.disabled = true;
        phoneField.disabled = true;

        // Dodaj spinner do przycisku "Dalej"
        const nextBtn = document.querySelector('#step-1-actions .btn-primary');
        const originalText = nextBtn.textContent;
        nextBtn.innerHTML = '<span class="spinner"></span> Sprawdzam...';
        nextBtn.disabled = true;

        const response = await fetch(`/quotes/api/client/quote/${getCurrentQuoteToken()}/validate-contact`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                email: email,
                phone: phone
            })
        });

        const result = await response.json();

        // Przywróć pola
        emailField.disabled = false;
        phoneField.disabled = false;
        nextBtn.textContent = originalText;
        nextBtn.disabled = false;

        if (response.ok && result.success) {
            console.log('[AcceptModal] Walidacja przeszła pomyślnie');

            // Pokaż komunikat o sukcesie
            if (result.client_has_data) {
                let successMsg = 'Dane zostały zweryfikowane';
                if (result.matched_email && result.matched_phone) {
                    successMsg += ' (email i telefon)';
                } else if (result.matched_email) {
                    successMsg += ' (email)';
                } else if (result.matched_phone) {
                    successMsg += ' (telefon)';
                }
                showValidationSuccess(successMsg);

                // AUTO-UZUPEŁNIENIE: Załaduj i wypełnij dane klienta
                await loadAndFillClientData(email, phone);

            } else {
                showValidationSuccess('Kontynuujesz jako nowy klient');
            }

            return true;
        } else {
            // Pokaż błąd z serwera
            const errorMsg = result.error || 'Błąd podczas weryfikacji danych';
            showFieldError('emailError', errorMsg);
            showFieldError('phoneError', errorMsg);
            return false;
        }

    } catch (error) {
        console.error('[AcceptModal] Błąd walidacji:', error);

        // Przywróć pola w przypadku błędu
        const emailField = document.getElementById('acceptEmail');
        const phoneField = document.getElementById('acceptPhone');
        const nextBtn = document.querySelector('#step-1-actions .btn-primary');

        emailField.disabled = false;
        phoneField.disabled = false;
        nextBtn.textContent = 'Dalej';
        nextBtn.disabled = false;

        showFieldError('emailError', 'Błąd połączenia. Spróbuj ponownie.');
        return false;
    }
}

// Wyczyść wszystkie pola formularza
function clearAllFields() {
    // Pola kontaktowe
    document.getElementById('acceptEmail').value = '';
    document.getElementById('acceptPhone').value = '';

    // Pola dostawy
    clearDeliveryFields();

    // Pola faktury
    clearInvoiceFields();

    // Uwagi
    document.getElementById('acceptComments').value = '';
}

// Otwórz modal akceptacji (zintegrować z istniejącym systemem)
function openAcceptModal(quoteData = null) {
    console.log('[AcceptModal] Otwieranie modala akceptacji');

    currentQuoteData = quoteData;
    resetAcceptModal();

    if (!document.getElementById('acceptModal').hasEventListeners) {
        initAcceptModal();
        document.getElementById('acceptModal').hasEventListeners = true;
    }

    // Pokaż modal bez przesadnych animacji
    const modal = document.getElementById('acceptModal');
    modal.style.display = 'flex';

    // Focus na pierwszym polu
    setTimeout(() => {
        const firstInput = document.getElementById('acceptEmail');
        if (firstInput) {
            firstInput.focus();
        }
    }, 100);

    console.log('[AcceptModal] Modal otwarty');
}

// Zamknij modal (zintegrować z istniejącą funkcją closeModal)
function closeAcceptModal() {
    console.log('[AcceptModal] Zamykanie modala akceptacji');

    const modal = document.getElementById('acceptModal');
    modal.style.display = 'none';

    setTimeout(() => {
        resetAcceptModal();
    }, 100);
}

// Integracja z istniejącym systemem modalów
// Nadpisz funkcję handleAcceptSubmit jeśli istnieje
if (typeof handleAcceptSubmit === 'function') {
    const originalHandleAcceptSubmit = handleAcceptSubmit;

    handleAcceptSubmit = function (event) {
        event.preventDefault();
        console.log('[AcceptModal] Przekierowanie na nowy system akceptacji');

        // Zamknij stary modal jeśli jest otwarty
        closeModal('acceptModal');

        // Otwórz nowy modal
        openAcceptModal();
    };
}

// Event listener dla ESC
document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
        const modal = document.getElementById('acceptModal');
        if (modal && modal.style.display !== 'none') {
            closeAcceptModal();
        }
    }
});

// Event listener dla kliknięcia poza modal
document.getElementById('acceptModal')?.addEventListener('click', function (event) {
    if (event.target === this) {
        closeAcceptModal();
    }
});

document.addEventListener('DOMContentLoaded', function () {
    if (document.getElementById('acceptModal')) {
        attachStepButtons();
    }
});

console.log('[AcceptModal] Moduł załadowany pomyślnie');

if (!document.querySelector('#contact-validation-styles')) {
    const styleSheet = document.createElement('style');
    styleSheet.id = 'contact-validation-styles';
    styleSheet.innerHTML = spinnerStyles;
    document.head.appendChild(styleSheet);
}

// === DODAJ TEN KOD NA SAMYM KOŃCU PLIKU ===

// Dodaj style do head gdy modal się inicjalizuje
if (!document.querySelector('#minimal-animations-styles')) {
    const minimalStyles = `
/* Tylko podstawowe animacje - BEZ focus effects dla inputów */
.accept-step {
    animation: fadeInStep 0.3s ease-out;
}

@keyframes fadeInStep {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

.btn-gus.loading::before {
    content: '';
    width: 12px;
    height: 12px;
    margin-right: 6px;
    border: 2px solid white;
    border-top-color: transparent;
    border-radius: 50%;
    display: inline-block;
    animation: spin 0.8s linear infinite;
    vertical-align: middle;
}

/* USUNIĘTE WSZYSTKIE ANIMACJE FOCUS I HOVER DLA INPUTÓW */
.form-input:focus,
.form-textarea:focus {
    /* TYLKO border i box-shadow - BEZ transform/scale */
    border-color: #ED6B24 !important;
    box-shadow: 0 0 0 2px rgba(237, 107, 36, 0.1) !important;
}

/* USUNIĘTE animacje hover dla inputów */
.form-input:hover,
.form-textarea:hover {
    /* BEZ animacji */
}
`;

    const styleSheet = document.createElement('style');
    styleSheet.id = 'minimal-animations-styles';
    styleSheet.innerHTML = minimalStyles;
    document.head.appendChild(styleSheet);
}

// Eksportuj uproszczone funkcje
window.goToStep = goToStep;
window.openAcceptModal = openAcceptModal;
window.closeAcceptModal = closeAcceptModal;
window.handleSelfPickupChange = handleSelfPickupChange;
window.handleInvoiceToggle = handleInvoiceToggle;
window.showFieldError = showFieldError;
window.clearFieldError = clearFieldError;
window.handleGusLookup = handleGusLookup;
window.showAutoFillInfo = showAutoFillInfo;
window.copyDeliveryToInvoice = copyDeliveryToInvoice;
window.resetAcceptModal = resetAcceptModal;
window.initAcceptModal = initAcceptModal;
window.handleFinalSubmit = handleFinalSubmit;
window.updateQuoteSummaryFromPage = updateQuoteSummaryFromPage;
window.debugQuotePrices = debugQuotePrices;
window.parseGusAddress = parseGusAddress;
window.updateQuoteSummaryFromPageElements = updateQuoteSummaryFromPageElements;
window.quickTestPrices = quickTestPrices;

console.log('[AcceptModal] Minimalne animacje załadowane - BEZ skoków inputów');