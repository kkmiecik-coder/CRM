// app/modules/calculator/static/js/save_quote.js

/**
 * ========================================
 * MODAL ZAPISU WYCENY - GŁÓWNA LOGIKA
 * ========================================
 */

document.addEventListener('DOMContentLoaded', function () {
    // ===== CACHE ELEMENTÓW DOM =====
    const modal = document.getElementById('saveQuoteModal');
    const openBtn = document.querySelector('.save-quote');
    const closeBtn = document.getElementById('closeSaveQuoteModal');
    const searchInput = document.getElementById('clientSearchInput');
    const resultsBox = document.getElementById('clientSearchResults');
    const feedbackBox = document.getElementById('quoteSaveFeedback');
    const saveQuoteBtn = document.getElementById('confirmSaveQuote');

    // Kroki modala - ZMIENIONE KLASY z sq-
    const stepSearch = document.querySelector('.sq-step-search');
    const stepForm = document.querySelector('.sq-step-form');
    const stepSuccess = document.querySelector('.sq-step-success');

    // ===== DEBOUNCE HELPER =====
    function debounce(func, delay) {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), delay);
        };
    }

    // ===== WYŚWIETLANIE KROKÓW =====
    function showStep(step) {
        [stepSearch, stepForm, stepSuccess].forEach(s => {
            s?.classList.remove('active');
            if (s) s.style.display = 'none';
        });

        step?.classList.add('active');
        if (step) step.style.display = 'block';
    }

    // ===== OTWIERANIE MODALA =====
    openBtn?.addEventListener('click', () => {
        modal.style.display = 'flex';
        showStep(stepSearch);
        searchInput.value = '';
        resultsBox.innerHTML = '';
        resultsBox.style.display = 'none';
        clearAllErrors();
        console.log("[save_quote.js] Otworzono modal zapisu wyceny");
    });

    // ===== ZAMYKANIE MODALA =====
    closeBtn?.addEventListener('click', () => {
        modal.style.display = 'none';
        console.log("[save_quote.js] Zamknięto modal zapisu wyceny");
    });

    // ===== KROK 1: WYSZUKIWANIE KLIENTA =====
    const handleSearch = debounce(async function (value) {
        const query = value.trim();
        console.log("[search_clients] Wpisany tekst:", query);

        if (query.length < 3) {
            resultsBox.style.display = 'none';
            resultsBox.innerHTML = '';
            return;
        }

        try {
            console.log("[search_clients] Wysyłam zapytanie do /calculator/search_clients");
            const res = await fetch(`/calculator/search_clients?q=${encodeURIComponent(query)}`);
            const clients = await res.json();

            let html = '';

            if (!clients || clients.length === 0) {
                html = '<div class="sq-no-results">Brak wyników wyszukiwania</div>';
            } else {
                html = clients.map(client => {
                    const hasEmail = client.email && client.email.trim() !== '';
                    const hasPhone = client.phone && client.phone.trim() !== '';

                    let contactInfo = '';
                    if (hasEmail && hasPhone) {
                        contactInfo = `${client.email} • ${client.phone}`;
                    } else if (hasEmail) {
                        contactInfo = client.email;
                    } else if (hasPhone) {
                        contactInfo = client.phone;
                    }

                    // ✅ NOWE: Badge dla klientów utworzonych przez innego handlowca
                    const otherClientBadge = !client.is_own_client 
                        ? '<span class="sq-other-client-badge">Klient utworzony przez innego handlowca</span>' 
                        : '';

                    return `
                        <div class="sq-search-result-item" 
                            data-id="${client.id}"
                            data-name="${client.name || ''}"
                            data-email="${client.email || ''}"
                            data-phone="${client.phone || ''}">
                            <div class="sq-search-result-row">
                                <div class="sq-search-result-info">
                                    <div class="sq-search-result-name">${client.name}</div>
                                    ${contactInfo ? `<div class="sq-search-result-contact">${contactInfo}</div>` : ''}
                                </div>
                                ${otherClientBadge}
                            </div>
                        </div>
                    `;
                }).join('');
            }

            // Zawsze dodaj przycisk "Utwórz nowego klienta" na dole
            html += `
                <button class="sq-create-client-btn" id="createNewClientBtn">
                    <span>+</span>
                    <span>Utwórz nowego klienta</span>
                </button>
            `;

            resultsBox.innerHTML = html;
            resultsBox.style.display = 'block';

            // Obsługa kliknięcia w wynik wyszukiwania
            attachSearchResultListeners();

        } catch (err) {
            console.error("[search_clients] Błąd fetch:", err);
            resultsBox.innerHTML = '<div class="sq-no-results">Błąd podczas wyszukiwania</div>';
            resultsBox.style.display = 'block';
        }
    }, 300);

    searchInput?.addEventListener('input', (e) => handleSearch(e.target.value));

    // ===== OBSŁUGA KLIKNIĘĆ W WYNIKI WYSZUKIWANIA =====
    function attachSearchResultListeners() {
        // Kliknięcie w istniejącego klienta
        document.querySelectorAll('.sq-search-result-item').forEach(el => {
            el.addEventListener('click', () => {
                const clientId = el.dataset.id;
                const clientName = el.dataset.name;
                const clientEmail = el.dataset.email;
                const clientPhone = el.dataset.phone;

                console.log("[search_clients] Wybrano klienta:", { clientId, clientName, clientEmail, clientPhone });

                // Przejdź do kroku 2 i wypełnij formularz
                goToFormStep(clientId, clientName, clientName, clientEmail, clientPhone);
            });
        });

        // Kliknięcie w "Utwórz nowego klienta"
        document.getElementById('createNewClientBtn')?.addEventListener('click', () => {
            const searchValue = searchInput.value.trim();
            console.log("[create_client] Tworzenie nowego klienta z wartością:", searchValue);

            // Przejdź do kroku 2 bez client_id (nowy klient)
            goToFormStep(null, searchValue, '', '', '');
        });
    }

    // ===== PRZEJŚCIE DO KROKU 2 (FORMULARZ) =====
    function goToFormStep(clientId, clientLogin, clientName, clientEmail, clientPhone) {
        showStep(stepForm);

        // Usuń poprzedni hidden input client_id jeśli istniał
        document.querySelector('[name="client_id"]')?.remove();

        // Jeśli mamy clientId (istniejący klient), dodaj hidden input
        if (clientId) {
            const hiddenInput = document.createElement('input');
            hiddenInput.type = 'hidden';
            hiddenInput.name = 'client_id';
            hiddenInput.value = clientId;
            document.querySelector('.sq-form-section')?.prepend(hiddenInput);
        }

        // Wypełnij pola formularza
        const loginField = document.querySelector('[name="client_login"]');
        const nameField = document.querySelector('[name="client_name"]');
        const emailField = document.querySelector('[name="client_email"]');
        const phoneField = document.querySelector('[name="client_phone"]');

        if (loginField) {
            loginField.value = clientLogin || '';
            loginField.removeAttribute('readonly'); // Pozwól edytować dla nowego klienta
        }
        if (nameField) nameField.value = clientName || '';
        if (emailField) emailField.value = clientEmail || '';
        if (phoneField) phoneField.value = clientPhone || '';

        // Renderuj podsumowanie produktów
        renderSummaryValues();
        renderProductsTable();

        // Wywołaj handleSourceChange jeśli źródło już wybrane
        setTimeout(handleSourceChange, 100);

        console.log("[goToFormStep] Przełączono do formularza");
    }

    // ===== RENDEROWANIE TABELI PRODUKTÓW =====
    function renderProductsTable() {
        const data = collectQuoteData();
        if (!data || !data.products) {
            console.error("[renderProductsTable] Brak danych produktów");
            return;
        }
        const tableBody = document.getElementById('productsTableBody');
        if (!tableBody) {
            console.warn("[renderProductsTable] Brak elementu #productsTableBody");
            return;
        }
        let html = '';
        data.products.forEach((product, idx) => {
            const selectedVariant = product.variants.find(v => v.is_selected);
            if (!selectedVariant) return; // Pomijamy produkty bez wybranego wariantu

            // ✅ DEBUG: Log szczegółowych danych produktu
            console.log(`[renderProductsTable] 🔍 DEBUG Produkt ${idx + 1}:`, {
                wymiary: `${product.length}x${product.width}x${product.thickness}`,
                quantity: product.quantity,
                'selectedVariant.final_price_brutto': selectedVariant.final_price_brutto,
                'selectedVariant.final_price_netto': selectedVariant.final_price_netto,
                'product.finishing_brutto': product.finishing_brutto,
                'selectedVariant.variant_code': selectedVariant.variant_code
            });

            // Parsuj variant_code aby wyciągnąć informacje o wariancie
            // Format: "dab-lity-ab" → Dąb Lity A/B
            const variantCode = selectedVariant.variant_code || '';
            let variantName = '';

            if (variantCode) {
                const parts = variantCode.split('-');

                // Gatunek drewna (pierwszy element)
                const species = {
                    'dab': 'Dąb',
                    'jes': 'Jesion',
                    'buk': 'Buk'
                }[parts[0]] || parts[0];

                // Technologia (drugi element)
                const technology = {
                    'lity': 'Lity',
                    'micro': 'Mikrowczep'
                }[parts[1]] || parts[1];

                // Klasa (trzeci element) - zamień "ab" na "A/B"
                const woodClass = parts[2] ? parts[2].toUpperCase().split('').join('/') : '';

                // Złóż nazwę wariantu
                variantName = `${species} ${technology}${woodClass ? ' ' + woodClass : ''}`;
            }

            const productName = `Klejonka ${variantName} ${product.length}x${product.width}x${product.thickness} cm (x${product.quantity} szt.)`;
            const rawPrice = selectedVariant.final_price_brutto.toFixed(2);
            const finishingPrice = product.finishing_brutto.toFixed(2);
            const totalPrice = (selectedVariant.final_price_brutto + product.finishing_brutto).toFixed(2);

            console.log(`[renderProductsTable] 🔍 DEBUG Produkt ${idx + 1} ceny:`, {
                rawPrice, finishingPrice, totalPrice
            });

            html += `
            <div class="sq-product-row">
                <div class="sq-product-name">${productName}</div>
                <div class="sq-product-value">${rawPrice} PLN</div>
                <div class="sq-product-value">${finishingPrice} PLN</div>
                <div class="sq-product-sum">${totalPrice} PLN</div>
            </div>
        `;
        });
        if (html === '') {
            html = '<div class="sq-product-row"><div class="sq-product-name" style="grid-column: 1/-1; text-align: center; color: #999;">Brak produktów z wybranym wariantem</div></div>';
        }
        tableBody.innerHTML = html;
        console.log("[renderProductsTable] Tabela produktów wyrenderowana");
    }

    // ===== RENDEROWANIE PODSUMOWANIA KWOT =====
    function renderSummaryValues() {
        const data = collectQuoteData();
        if (!data || !data.summary) {
            console.error("[renderSummaryValues] Brak danych summary");
            return;
        }

        const summary = data.summary;
        console.log("[renderSummaryValues] Podsumowanie:", summary);

        const setText = (id, value) => {
            const el = document.getElementById(id);
            if (el) {
                el.textContent = `${value.toFixed(2)} PLN`;
            }
        };

        setText("summary-products-brutto", summary.products_brutto);
        setText("summary-products-netto", summary.products_netto);
        setText("summary-finishing-brutto", summary.finishing_brutto);
        setText("summary-finishing-netto", summary.finishing_netto);
        setText("summary-shipping-brutto", summary.shipping_brutto);
        setText("summary-shipping-netto", summary.shipping_netto);
        setText("summary-total-brutto", summary.total_brutto);
        setText("summary-total-netto", summary.total_netto);
    }

    // ===== WALIDACJA FORMULARZA =====
    function validateForm() {
        console.log("[validateForm] Rozpoczynam walidację");
        clearAllErrors();
        let isValid = true;

        // 1. Źródło zapytania (required)
        const sourceField = document.querySelector('[name="quote_source"]');
        if (!sourceField || !sourceField.value.trim()) {
            showFieldError(sourceField, 'Wybierz źródło zapytania');
            isValid = false;
        }

        // 2. Nazwa klienta (required, min 3 znaki)
        const loginField = document.querySelector('[name="client_login"]');
        if (!loginField || loginField.value.trim().length < 3) {
            showFieldError(loginField, 'Minimalna długość: 3 znaki');
            isValid = false;
        }

        // 3. Imię i nazwisko - opcjonalne, bez walidacji
        // Pole zostało zmienione na opcjonalne

        // 4. Telefon (jeśli wypełniony, min 9 cyfr bez znaków specjalnych)
        const phoneField = document.querySelector('[name="client_phone"]');
        const phoneValue = phoneField?.value.trim();
        if (phoneValue) {
            // Usuń wszystkie znaki oprócz cyfr do walidacji
            const phoneDigits = phoneValue.replace(/\D/g, '');
            if (phoneDigits.length < 9) {
                showFieldError(phoneField, 'Minimum 9 cyfr');
                isValid = false;
            }
        }

        // 5. Email (jeśli wypełniony, prawidłowy format)
        const emailField = document.querySelector('[name="client_email"]');
        const emailValue = emailField?.value.trim();
        if (emailValue && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailValue)) {
            showFieldError(emailField, 'Nieprawidłowy format email');
            isValid = false;
        }

        // ✅ ZMIENIONE: 6. Jedno z pól: telefon LUB email (wyjątki: OLX i Czernecki)
        const sourceValue = sourceField?.value.toLowerCase() || '';
        const isOlxSource = sourceValue.includes('olx');
        const isCzerneckiSource = sourceValue.includes('czernecki');

        // Dla OLX i Czernecki - telefon i email są opcjonalne
        // Dla pozostałych źródeł - wymagany jest telefon LUB email
        if (!isOlxSource && !isCzerneckiSource) {
            const phoneDigits = phoneValue ? phoneValue.replace(/\D/g, '') : '';
            if (!phoneDigits && !emailValue) {
                showFieldError(phoneField, 'Wymagany telefon lub email');
                showFieldError(emailField, 'Wymagany telefon lub email');
                isValid = false;
            }
        }

        // 7. Sprawdź czy wszystkie produkty mają wybrane warianty
        const forms = document.querySelectorAll('.quote-form');
        let missingVariants = [];

        forms.forEach((form, index) => {
            const selectedRadio = form.querySelector('.variants input[type="radio"]:checked');
            if (!selectedRadio) {
                missingVariants.push(index + 1);
            }
        });

        if (missingVariants.length > 0) {
            showGlobalError(`Wybierz wariant dla produktu: ${missingVariants.join(', ')}`);
            isValid = false;
        }

        // 8. Walidacja dostępności wariantów
        if (window.variantAvailability && !window.variantAvailability.validate()) {
            console.error("[validateForm] Walidacja dostępności wariantów nie powiodła się");
            showGlobalError('Niektóre wybrane warianty są niedostępne');
            isValid = false;
        }

        console.log(`[validateForm] Wynik: ${isValid ? 'PRZESZŁA' : 'NIE PRZESZŁA'}`);
        return isValid;
    }

    // ===== WYŚWIETLANIE BŁĘDÓW =====
    function showFieldError(field, message) {
        if (!field) return;
        field.classList.add('error');
        const errorSpan = field.parentElement.querySelector('.sq-error-message');
        if (errorSpan) {
            errorSpan.textContent = message;
        }
    }

    function clearFieldError(field) {
        if (!field) return;
        field.classList.remove('error');
        const errorSpan = field.parentElement.querySelector('.sq-error-message');
        if (errorSpan) {
            errorSpan.textContent = '';
        }
    }

    function clearAllErrors() {
        document.querySelectorAll('.sq-form-input').forEach(field => {
            clearFieldError(field);
        });
        feedbackBox.innerHTML = '';
        feedbackBox.className = 'sq-feedback';
    }

    // ===== OBSŁUGA ZMIANY ŹRÓDŁA ZAPYTANIA =====
    function handleSourceChange() {
        const sourceField = document.querySelector('[name="quote_source"]');
        const phoneLabel = document.querySelector('[name="client_phone"]')?.parentElement.querySelector('.sq-form-label');
        const emailLabel = document.querySelector('[name="client_email"]')?.parentElement.querySelector('.sq-form-label');
        const noteElement = document.querySelector('.sq-input-note');

        if (!sourceField) return;

        const sourceValue = sourceField.value.toLowerCase();
        const isOlxSource = sourceValue.includes('olx');
        const isCzerneckiSource = sourceValue.includes('czernecki');

        if (isOlxSource || isCzerneckiSource) {
            // OLX lub Czernecki - usuń gwiazdki i zmień notatkę
            const sourceName = isOlxSource ? 'OLX' : 'Czernecki';

            if (phoneLabel) {
                phoneLabel.innerHTML = 'Telefon <span class="sq-optional" style="color: #999;">(opcjonalne)</span>';
            }
            if (emailLabel) {
                emailLabel.innerHTML = 'E-mail <span class="sq-optional" style="color: #999;">(opcjonalne)</span>';
            }
            if (noteElement) {
                noteElement.innerHTML = `
                <span class="sq-required">*</span> - wymagane pola<br>
                <span style="color: #999;">Dla ${sourceName} telefon i e-mail są opcjonalne</span>
            `;
            }
            console.log(`[handleSourceChange] ${sourceName}: telefon i email opcjonalne`);
        } else {
            // Inne źródła - przywróć gwiazdki
            if (phoneLabel) {
                phoneLabel.innerHTML = 'Telefon <span class="sq-optional">*</span>';
            }
            if (emailLabel) {
                emailLabel.innerHTML = 'E-mail <span class="sq-optional">*</span>';
            }
            if (noteElement) {
                noteElement.innerHTML = `
                <span class="sq-required">*</span> - wymagane pola<br>
                <span class="sq-optional">*</span> - jedno z pól jest wymagane
            `;
            }
            console.log('[handleSourceChange] Standardowe źródło: telefon LUB email wymagany');
        }
    }

    function showGlobalError(message) {
        feedbackBox.className = 'sq-feedback error';
        feedbackBox.textContent = message;
    }

    function showGlobalSuccess(message) {
        feedbackBox.className = 'sq-feedback success';
        feedbackBox.textContent = message;
    }

    // ===== ZAPISYWANIE WYCENY =====
    saveQuoteBtn?.addEventListener('click', async () => {
        console.log("[save_quote.js] Kliknięto Zapisz wycenę");

        // Walidacja
        if (!validateForm()) {
            console.log('[save_quote.js] Walidacja nie przeszła');
            return;
        }

        // Pokaż loading
        feedbackBox.className = 'sq-feedback';
        feedbackBox.textContent = 'Zapisywanie wyceny...';

        // Zbierz dane z formularza
        const clientIdInput = document.querySelector('[name="client_id"]');
        const client_id = clientIdInput?.value?.trim() || null;
        const clientLogin = document.querySelector('[name="client_login"]')?.value?.trim();
        const clientName = document.querySelector('[name="client_name"]')?.value?.trim() || null;
        const clientPhone = document.querySelector('[name="client_phone"]')?.value?.trim() || null;
        const clientEmail = document.querySelector('[name="client_email"]')?.value?.trim() || null;
        const quoteSource = document.querySelector('[name="quote_source"]')?.value?.trim();
        const quoteNote = document.getElementById('quote_note')?.value?.trim() || '';

        // Zbierz dane produktów
        const quoteData = collectQuoteData();
        if (!quoteData) {
            showGlobalError('Błąd zbierania danych produktów');
            return;
        }

        const {
            products,
            summary,
            courier_name,
            shipping_cost_brutto,
            shipping_cost_netto,
            quote_client_type,
            quote_multiplier
        } = quoteData;

        if (products.length === 0) {
            showGlobalError('Wycena nie może być pusta. Dodaj produkty.');
            return;
        }

        console.log("[save_quote.js] ⚠️ DEBUG quote_type:");
        console.log("  - quoteData.quote_type:", quoteData.quote_type);
        console.log("  - getCurrentPriceMode():", window.getCurrentPriceMode?.());
        console.log("  - Radio netto checked:", document.getElementById('priceModeNetto')?.checked);
        console.log("  - Radio brutto checked:", document.getElementById('priceModeBrutto')?.checked);

        // Przygotuj payload
        const payload = {
            client_id,
            client_login: clientLogin,
            client_name: clientName,
            client_phone: clientPhone,
            client_email: clientEmail,
            quote_source: quoteSource,
            products,
            total_price: summary.total_brutto,
            courier_name,
            shipping_cost_netto,
            shipping_cost_brutto,
            quote_client_type,
            quote_multiplier,
            quote_note: quoteNote,
            quote_type: quoteData.quote_type || 'brutto'
        };

        console.log("[save_quote.js] Payload:", payload);

        // Wyślij do backendu
        try {
            const response = await fetch('/calculator/save_quote', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const text = await response.text();
            const data = JSON.parse(text);

            if (data.error) {
                showGlobalError('Błąd: ' + data.error);
                console.error("[save_quote.js] Błąd z backendu:", data.error);
            } else {
                // Sukces - przejdź do kroku 3
                showStep(stepSuccess);

                // Wyświetl numer wyceny
                const quoteNumberDisplay = document.getElementById('quoteNumberDisplay');
                if (quoteNumberDisplay && data.quote_number) {
                    quoteNumberDisplay.textContent = data.quote_number;
                }

                // Obsługa przycisków
                setupSuccessButtons(data.quote_id);

                console.log("[save_quote.js] Wycena zapisana pomyślnie");

                // Oznacz draft jako zapisany
                if (window.quoteDraftBackup && window.quoteDraftBackup.markQuoteAsSaved) {
                    window.quoteDraftBackup.markQuoteAsSaved();
                }
            }

        } catch (err) {
            showGlobalError('Wystąpił błąd sieci lub serwera');
            console.error("[save_quote.js] Błąd fetch:", err);
        }
    });

    // ===== OBSŁUGA PRZYCISKÓW W KROKU SUKCESU =====
    function setupSuccessButtons(quoteId) {
        // Przycisk "Przejdź do wyceny"
        const goToQuoteBtn = document.getElementById('goToQuoteBtn');
        if (goToQuoteBtn && quoteId) {
            goToQuoteBtn.onclick = () => {
                console.log(`[success] Przekierowanie do wyceny ID: ${quoteId}`);
                window.location.href = `/quotes?open_quote=${quoteId}`;
            };
        }

        // Przycisk "Nowa wycena"
        const newQuoteBtn = document.getElementById('newQuoteBtn');
        if (newQuoteBtn) {
            newQuoteBtn.onclick = () => {
                console.log('[success] Nowa wycena - przeładowanie strony');
                if (window.quoteDraftBackup && window.quoteDraftBackup.resetForNewQuote) {
                    window.quoteDraftBackup.resetForNewQuote();
                }
                window.location.reload();
            };
        }

        // Przycisk "Zamknij"
        const closeModalBtn = document.getElementById('closeModalBtn');
        if (closeModalBtn) {
            closeModalBtn.onclick = () => {
                console.log('[success] Zamknij modal');
                if (window.quoteDraftBackup && window.quoteDraftBackup.resetForNewQuote) {
                    window.quoteDraftBackup.resetForNewQuote();
                }
                modal.style.display = 'none';
            };
        }
    }

    // ===== AKTUALIZACJA TABELI PRZY ZMIANACH W KALKULATORZE =====
    // Nasłuchuj na custom event z calculator.js
    document.addEventListener('calculatorDataChanged', () => {
        if (stepForm && stepForm.classList.contains('active')) {
            renderProductsTable();
            renderSummaryValues();
        }
    });

    // ===== OBSŁUGA ZMIANY ŹRÓDŁA ZAPYTANIA =====
    document.addEventListener('change', function (e) {
        if (e.target.matches('[name="quote_source"]')) {
            handleSourceChange();
        }
    });

}); // END DOMContentLoaded


/**
 * ========================================
 * FUNKCJA ZBIERANIA DANYCH WYCENY
 * (Bez zmian - działa z głównym kalkulatorem)
 * ========================================
 */
function collectQuoteData() {
    console.log("[collectQuoteData] Start zbierania danych z formularzy");

    if (window.variantAvailability && !window.variantAvailability.validate()) {
        console.error("[collectQuoteData] Walidacja dostępności wariantów nie powiodła się");
        return null;
    }

    const forms = document.querySelectorAll('.quote-form');
    const products = [];

    let sumProductBrutto = 0;
    let sumProductNetto = 0;
    let sumFinishingBrutto = 0;
    let sumFinishingNetto = 0;

    forms.forEach((form, index) => {
        const length = parseFloat(form.querySelector('[data-field="length"]')?.value || 0);
        const width = parseFloat(form.querySelector('[data-field="width"]')?.value || 0);
        const thickness = parseFloat(form.querySelector('[data-field="thickness"]')?.value || 0);
        const quantity = parseInt(form.querySelector('[data-field="quantity"]')?.value || 1);

        console.log(`[collectQuoteData] 🔍 DEBUG Produkt ${index + 1} - wymiary:`, {
            length, width, thickness, quantity
        });

        const finishingType = form.querySelector('[data-finishing-type].active')?.dataset.finishingType || null;
        const finishingVariant = form.querySelector('[data-finishing-variant].active')?.dataset.finishingVariant || null;
        const finishingColor = form.querySelector('[data-finishing-color].active')?.dataset.finishingColor || null;
        const finishingGloss = form.querySelector('[data-finishing-gloss].active')?.dataset.finishingGloss || null;

        const finishingBrutto = parseFloat(form.dataset.finishingBrutto || 0);
        const finishingNetto = parseFloat(form.dataset.finishingNetto || 0);

        console.log(`[collectQuoteData] Produkt ${index + 1} - wykończenie:`, {
            finishingType, finishingVariant, finishingColor, finishingGloss,
            finishingBrutto, finishingNetto, quantity
        });

        let hasSelectedVariant = false;

        const allVariants = Array.from(form.querySelectorAll('.variants input[type="radio"]')).map(radio => {
            const brutto = parseFloat(radio.dataset.totalBrutto || 0);
            const netto = parseFloat(radio.dataset.totalNetto || 0);
            const volume = (length / 100) * (width / 100) * (thickness / 100);

            // ✅ DEBUG: Log szczegółowych danych dla zaznaczonego wariantu
            if (radio.checked) {
                console.log(`[collectQuoteData] 🔍 DEBUG Produkt ${index + 1} - zaznaczony wariant ${radio.value}:`, {
                    brutto, netto, volume,
                    'radio.dataset.totalBrutto': radio.dataset.totalBrutto,
                    'radio.dataset.totalNetto': radio.dataset.totalNetto,
                    'radio.dataset.pricePerM3': radio.dataset.pricePerM3,
                    'radio.dataset.multiplier': radio.dataset.multiplier
                });
            }

            const checkbox = form.querySelector(`[data-variant="${radio.value}"]`);
            const isAvailable = checkbox && checkbox.checked;

            if (radio.checked) {
                sumProductBrutto += brutto;
                sumProductNetto += netto;
                hasSelectedVariant = true;
            }

            return {
                variant_code: radio.value,
                is_selected: radio.checked,
                is_available: isAvailable,
                price_per_m3: parseFloat(radio.dataset.pricePerM3 || 0),
                volume_m3: volume,
                multiplier: parseFloat(radio.dataset.multiplier || 1),
                final_price: parseFloat(radio.dataset.finalPrice || 0),
                final_price_netto: netto,
                final_price_brutto: brutto,
                finishing_type: finishingType,
                finishing_variant: finishingVariant,
                finishing_color: finishingColor,
                finishing_gloss_level: finishingGloss,
                finishing_netto: finishingNetto,
                finishing_brutto: finishingBrutto
            };
        });

        console.log(`[collectQuoteData] Produkt ${index + 1}: ${allVariants.length} wariantów (${allVariants.filter(v => v.is_available).length} dostępnych, ${allVariants.filter(v => v.is_selected).length} zaznaczonych)`);

        if (hasSelectedVariant && finishingBrutto > 0) {
            sumFinishingBrutto += finishingBrutto;
            sumFinishingNetto += finishingNetto;
            console.log(`[collectQuoteData] Dodano wykończenie dla produktu ${index + 1}: ${finishingBrutto} PLN brutto (już uwzględnia ${quantity} szt)`);
        }

        products.push({
            index,
            length,
            width,
            thickness,
            quantity,
            finishing_type: finishingType,
            finishing_variant: finishingVariant,
            finishing_color: finishingColor,
            finishing_gloss_level: finishingGloss,
            finishing_netto: finishingNetto,
            finishing_brutto: finishingBrutto,
            variants: allVariants
        });
    });

    console.log(`[collectQuoteData] Zebrano ${products.length} produktów:`);
    products.forEach((product, index) => {
        const totalCount = product.variants.length;
        const availableCount = product.variants.filter(v => v.is_available).length;
        const selectedCount = product.variants.filter(v => v.is_selected).length;
        console.log(`  Produkt ${index + 1}: ${totalCount} wariantów (${availableCount} dostępnych, ${selectedCount} zaznaczonych)`);
    });

    const shippingBrutto = parseFloat(document.getElementById('delivery-brutto')?.textContent.replace(" PLN", "")) || 0;
    const shippingNetto = parseFloat(document.getElementById('delivery-netto')?.textContent.replace(" PLN", "")) || 0;
    const courierName = document.getElementById('courier-name')?.textContent.trim() || null;

    // ✅ POPRAWIONA LOGIKA: Rozróżnienie per rola (flexible vs standardowy partner)
    const firstForm = forms[0];
    const clientTypeSelect = firstForm?.querySelector('select[data-field="clientType"]');
    let selectedClientType = null;
    let selectedMultiplier = 1.0;

    // Sprawdź czy to flexible partner
    const isFlexiblePartner = document.body.dataset.flexiblePartner === 'true';

    if (window.isPartner && !isFlexiblePartner) {
        // Standardowy partner: użyj danych z body (fixed multiplier)
        selectedMultiplier = window.userMultiplier;
        selectedClientType = document.body.dataset.clientType || null;
        console.log(`[collectQuoteData] Standardowy Partner: grupa="${selectedClientType}", mnożnik=${selectedMultiplier}`);

    } else {
        // Admin/User/Flexible Partner: użyj danych z selecta (user choice)
        selectedClientType = clientTypeSelect?.value || null;

        if (selectedClientType && window.multiplierMapping && window.multiplierMapping[selectedClientType]) {
            selectedMultiplier = window.multiplierMapping[selectedClientType];
            console.log(`[collectQuoteData] User/Flexible Partner: grupa="${selectedClientType}", mnożnik=${selectedMultiplier}`);
        } else {
            console.warn(`[collectQuoteData] ⚠️ Brak wybranej grupy cenowej - używam domyślnego mnożnika 1.0`);
        }
    }

    // Pobierz notatkę z textarea
    const quoteNote = document.getElementById('quote_note')?.value.trim() || '';


    // ========================================
    // POBIERZ TRYB CEN (BRUTTO/NETTO)
    // ========================================

    let quoteType = 'brutto'; // Domyślnie brutto

    // Pobierz z funkcji window.getCurrentPriceMode jeśli dostępna
    if (typeof window.getCurrentPriceMode === 'function') {
        quoteType = window.getCurrentPriceMode();
        console.log(`[collectQuoteData] Tryb cen z getCurrentPriceMode(): ${quoteType}`);
    } else {
        // Fallback - sprawdź bezpośrednio radio buttony
        const nettoRadio = document.getElementById('priceModeNetto');
        if (nettoRadio && nettoRadio.checked) {
            quoteType = 'netto';
        }
        console.log(`[collectQuoteData] Tryb cen z radio buttonów (fallback): ${quoteType}`);
    }

    console.log(`[collectQuoteData] SUMA produktów brutto=${sumProductBrutto}, netto=${sumProductNetto}`);
    console.log(`[collectQuoteData] SUMA wykończenia brutto=${sumFinishingBrutto}, netto=${sumFinishingNetto}`);
    console.log(`[collectQuoteData] SUMA wysyłki brutto=${shippingBrutto}, netto=${shippingNetto}`);
    console.log(`[collectQuoteData] Kurier: ${courierName}`);
    console.log(`[collectQuoteData] Grupa cenowa: ${selectedClientType} (mnożnik: ${selectedMultiplier})`);
    console.log(`[collectQuoteData] Notatka: "${quoteNote}" (${quoteNote.length} znaków)`);

    const result = {
        products,
        courier_name: courierName,
        shipping_cost_brutto: shippingBrutto,
        shipping_cost_netto: shippingNetto,
        quote_client_type: selectedClientType,
        quote_multiplier: selectedMultiplier,
        quote_note: quoteNote,
        quote_type: quoteType,  // ✅ TYLKO TUTAJ
        summary: {
            products_brutto: sumProductBrutto,
            products_netto: sumProductNetto,
            finishing_brutto: sumFinishingBrutto,
            finishing_netto: sumFinishingNetto,
            shipping_brutto: shippingBrutto,
            shipping_netto: shippingNetto,
            total_brutto: sumProductBrutto + sumFinishingBrutto + shippingBrutto,
            total_netto: sumProductNetto + sumFinishingNetto + shippingNetto
        }
    };

    console.log("[collectQuoteData] Zwracam podsumowanie:", result);
    return result;
}

// Licznik znaków dla notatki
function initNoteCounter() {
    const noteTextarea = document.getElementById('quote_note');
    const noteCounter = document.getElementById('note_counter');

    if (!noteTextarea || !noteCounter) return;

    const maxLength = 180;

    function updateCounter() {
        const currentLength = noteTextarea.value.length;
        const remaining = maxLength - currentLength;

        noteCounter.textContent = remaining;

        // Dodaj klasę ostrzegawczą gdy zostało mało znaków
        const counterElement = noteCounter.parentElement;
        if (remaining <= 20) {
            counterElement.classList.add('warning');
        } else {
            counterElement.classList.remove('warning');
        }
    }

    // Event listener dla zmian w textarea
    noteTextarea.addEventListener('input', updateCounter);

    // Inicjalna aktualizacja
    updateCounter();

    console.log('[save_quote.js] Licznik znaków dla notatki zainicjalizowany');
}

/**
 * ========================================
 * FUNKCJE DEBUGOWANIA
 * ========================================
 */
function logVariantAvailability() {
    console.log("[logVariantAvailability] Stan dostępności wariantów:");

    const forms = Array.from(document.querySelectorAll('.quote-form'));
    forms.forEach((form, index) => {
        console.log(`  Produkt ${index + 1}:`);

        const checkboxes = form.querySelectorAll('.variant-availability-checkbox');
        checkboxes.forEach(checkbox => {
            const variantCode = checkbox.dataset.variant;
            const isAvailable = checkbox.checked;
            const radio = form.querySelector(`input[type="radio"][value="${variantCode}"]`);
            const isSelected = radio && radio.checked;

            console.log(`    ${variantCode}: ${isAvailable ? 'dostępny' : 'niedostępny'}${isSelected ? ' (zaznaczony)' : ''}`);
        });
    });
}

window.logVariantAvailability = logVariantAvailability;


/**
 * ========================================
 * ROZSZERZENIE QUOTE DRAFT BACKUP
 * ========================================
 */
function enhanceQuoteDraftBackupWithSaveDetection() {
    if (window.quoteDraftBackup) {
        const backup = window.quoteDraftBackup;
        let isQuoteSaved = false;

        const originalSaveCurrentState = backup.saveCurrentState.bind(backup);

        backup.saveCurrentState = function () {
            if (isQuoteSaved) {
                console.log('[QuoteDraftBackup] Pomijam zapis - wycena już zapisana');
                backup.stopAutoSave();
                return;
            }
            originalSaveCurrentState();
        };

        backup.markQuoteAsSaved = function () {
            console.log('[QuoteDraftBackup] Oznaczam wycenę jako zapisaną');
            isQuoteSaved = true;
            backup.stopAutoSave();

            setTimeout(() => {
                backup.clearDraft();
                console.log('[QuoteDraftBackup] Draft cookies usunięte');
            }, 1000);
        };

        backup.resetForNewQuote = function () {
            console.log('[QuoteDraftBackup] Reset dla nowej wyceny');
            isQuoteSaved = false;
            backup.clearDraft();

            setTimeout(() => {
                if (!isQuoteSaved) {
                    backup.startAutoSave();
                    console.log('[QuoteDraftBackup] System zrestartowany');
                }
            }, 2000);
        };

        return backup;
    }
    return null;
}

document.addEventListener('DOMContentLoaded', function () {

    // Inicjalizacja licznika znaków dla notatki
    initNoteCounter();

    setTimeout(() => {
        const enhanced = enhanceQuoteDraftBackupWithSaveDetection();
        if (enhanced) {
            console.log('[save_quote.js] System QuoteDraftBackup rozszerzony o mechanizm zatrzymania');
        } else {
            console.warn('[save_quote.js] Nie udało się rozszerzyć QuoteDraftBackup - może nie został jeszcze zainicjalizowany');
        }
    }, 1500);
});