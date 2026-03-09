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
    const quoteSourceSelect = document.getElementById('quoteSourceSelect');

    // Kroki modala - ZMIENIONE KLASY z sq-
    const stepSearch = document.querySelector('.sq-step-search');
    const stepForm = document.querySelector('.sq-step-form');
    const stepSuccess = document.querySelector('.sq-step-success');

    // Cache źródeł wycen (ładowane raz przy pierwszym otwarciu modala)
    let quoteSources = null;
    let quoteSourcesLoaded = false;

    // ===== DEBOUNCE HELPER =====
    function debounce(func, delay) {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), delay);
        };
    }

    // ===== ŁADOWANIE ŹRÓDEŁ WYCEN Z API =====
    async function loadQuoteSources() {
        if (quoteSourcesLoaded) {
            return quoteSources;
        }

        try {
            const response = await fetch('/calculator/api/quote-sources');

            if (!response.ok) {
                throw new Error(`HTTP error: ${response.status}`);
            }

            const data = await response.json();
            quoteSources = data;
            quoteSourcesLoaded = true;

            // Wypełnij select źródłami
            renderQuoteSourcesSelect(data);

            return data;

        } catch (error) {
            console.error("[loadQuoteSources] Błąd ładowania źródeł:", error);

            // Fallback - pokaż podstawowe opcje (źródło jest opcjonalne)
            if (quoteSourceSelect) {
                quoteSourceSelect.innerHTML = `
                    <option value="">-- Wybierz źródło --</option>
                    <option value="Osobiście">Osobiście</option>
                    <option value="Telefon">Telefon</option>
                    <option value="E-mail">E-mail</option>
                `;
            }
            return null;
        }
    }

    // ===== RENDEROWANIE SELECTA ŹRÓDEŁ =====
    function renderQuoteSourcesSelect(data) {
        if (!quoteSourceSelect || !data) return;

        // Początkowa opcja - puste źródło jest dozwolone
        let html = '<option value="">-- Wybierz źródło --</option>';

        // Format API: { success: true, sources: [{id, name, skip_contact_validation}, ...] }
        const sources = data.sources || [];

        for (const source of sources) {
            html += `<option value="${source.name}" data-skip-validation="${source.skip_contact_validation}">${source.name}</option>`;
        }

        quoteSourceSelect.innerHTML = html;
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

    // ===== TRYB EDYCJI - DETEKCJA =====
    // UWAGA: nie cachujemy jako const - quoteEditMode jest ustawiane pozniej przez QuoteEditLoader
    function getIsEditMode() { return window.quoteEditMode?.isActive === true; }
    function getEditModeData() { return window.quoteEditMode || {}; }

    // ===== OTWIERANIE MODALA =====
    openBtn?.addEventListener('click', async () => {
        modal.style.display = 'flex';
        clearAllErrors();

        // Załaduj źródła wycen (tylko przy pierwszym otwarciu)
        await loadQuoteSources();

        if (getIsEditMode()) {
            // TRYB EDYCJI: pomiń krok 1, przejdź do formularza z kartą klienta

            // Zmień tytuł modala
            const modalTitle = modal.querySelector('.sq-modal-title');
            if (modalTitle) modalTitle.textContent = 'Aktualizuj wycenę';

            // Zmień tekst przycisku zapisu
            if (saveQuoteBtn) saveQuoteBtn.textContent = 'Aktualizuj wycenę';

            // Przejdź do kroku 2 (formularz)
            showStep(stepForm);

            // Wstaw kartę klienta zamiast edytowalnych pól
            renderEditModeClientCard();

            // Ustaw źródło wyceny jeśli było zapisane
            if (getEditModeData().source && quoteSourceSelect) {
                setTimeout(() => {
                    quoteSourceSelect.value = getEditModeData().source;
                }, 100);
            }

            // Ustaw notatkę jeśli była zapisana
            const noteTextarea = document.getElementById('quote_note');
            if (noteTextarea && getEditModeData().notes) {
                noteTextarea.value = getEditModeData().notes;
                // Odśwież licznik znaków
                noteTextarea.dispatchEvent(new Event('input'));
            }

            // Renderuj podsumowanie
            renderSummaryValues();
            renderProductsTable();

        } else {
            // TRYB NORMALNY: pokaż krok 1 (wyszukiwanie klienta)
            showStep(stepSearch);
            searchInput.value = '';
            resultsBox.innerHTML = '';
            resultsBox.style.display = 'none';
        }

    });

    // ===== KARTA KLIENTA W TRYBIE EDYCJI =====
    function renderEditModeClientCard() {
        const formSection = modal.querySelector('.sq-form-section');
        if (!formSection) return;

        const client = getEditModeData().client || {};
        const quoteNumber = getEditModeData().quoteNumber || '';

        // Usuń poprzednią kartę klienta jeśli istnieje (zapobiega duplikacji)
        const existingCard = formSection.querySelector('.edit-mode-client-card');
        if (existingCard) existingCard.remove();

        // Ukryj standardowe pola klienta, zachowaj źródło i notatkę
        const fieldsToHide = formSection.querySelectorAll('.sq-form-group');
        fieldsToHide.forEach(group => {
            const input = group.querySelector('input[name]');
            if (input && ['client_login', 'client_name', 'client_phone', 'client_email'].includes(input.name)) {
                group.style.display = 'none';
            }
        });

        // Ukryj notatkę o wymaganych polach
        const inputNote = formSection.querySelector('.sq-input-note');
        if (inputNote) inputNote.style.display = 'none';

        // Wstaw kartę klienta na górze sekcji formularza
        const clientCard = document.createElement('div');
        clientCard.className = 'edit-mode-client-card';
        clientCard.innerHTML = `
            <div class="client-card-header">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                    <circle cx="12" cy="7" r="4"/>
                </svg>
                Klient przypisany do wyceny
            </div>
            <div class="client-card-body">
                <div class="client-info-row">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                        <circle cx="12" cy="7" r="4"/>
                    </svg>
                    <span class="client-name">${client.client_name || client.client_number || 'Brak nazwy'}</span>
                </div>
                ${client.email ? `
                <div class="client-info-row">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="2" y="4" width="20" height="16" rx="2"/>
                        <path d="M22 7l-10 7L2 7"/>
                    </svg>
                    <span>${client.email}</span>
                </div>` : ''}
                ${client.phone ? `
                <div class="client-info-row">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/>
                    </svg>
                    <span>${client.phone}</span>
                </div>` : ''}
            </div>
            ${quoteNumber ? `
            <div class="client-card-footer">
                <small>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                        <polyline points="14 2 14 8 20 8"/>
                    </svg>
                    Edycja wyceny: ${quoteNumber}
                </small>
            </div>` : ''}
        `;

        // Wstaw kartę jako pierwszy element sekcji (przed źródłem)
        formSection.insertBefore(clientCard, formSection.firstChild);

        // Zmień tytuł sekcji
        const sectionTitle = formSection.querySelector('.sq-section-title');
        if (sectionTitle) sectionTitle.textContent = 'Dane wyceny';
    }

    // ===== ZAMYKANIE MODALA =====
    closeBtn?.addEventListener('click', () => {
        modal.style.display = 'none';
    });

    // ===== PRZYCISK "UTWÓRZ NOWEGO" (statyczny w headerze) =====
    const createNewBtn = document.getElementById('createNewClientBtnTop');
    if (createNewBtn) {
        createNewBtn.disabled = true;
        createNewBtn.addEventListener('click', () => {
            const searchValue = searchInput.value.trim();
            if (searchValue.length >= 3) {
                goToFormStep(null, searchValue, '', '', '');
            }
        });
    }

    // Aktywuj/deaktywuj przycisk w zależności od długości inputu
    searchInput?.addEventListener('input', () => {
        if (createNewBtn) {
            createNewBtn.disabled = searchInput.value.trim().length < 3;
        }
    });

    // ===== KROK 1: WYSZUKIWANIE KLIENTA =====
    const handleSearch = debounce(async function (value) {
        const query = value.trim();

        if (query.length < 3) {
            resultsBox.style.display = 'none';
            resultsBox.innerHTML = '';
            return;
        }

        try {
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


                // Przejdź do kroku 2 i wypełnij formularz
                goToFormStep(clientId, clientName, clientName, clientEmail, clientPhone);
            });
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

    }

    // ===== SPRAWDZANIE CZY WYCENA MA WYKOŃCZENIE =====
    function quoteHasFinishing(data) {
        if (!data || !data.products) return false;
        return data.products.some(p => {
            const finishing = (p.finishing_brutto || 0) + (p.edges_brutto || 0);
            return finishing > 0;
        });
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
            return;
        }

        const hasFinishing = quoteHasFinishing(data);
        const tableHeader = tableBody.closest('.sq-products-table')?.querySelector('.sq-table-header');

        // Ukryj/pokaż kolumny Wykończenie i Suma w nagłówku
        if (tableHeader) {
            const headers = tableHeader.querySelectorAll(':scope > div');
            if (headers.length >= 4) {
                headers[2].style.display = hasFinishing ? '' : 'none'; // Wykończenie
                headers[3].style.display = hasFinishing ? '' : 'none'; // Suma
            }
            // Zmień grid w zależności od obecności wykończenia
            tableHeader.style.gridTemplateColumns = hasFinishing ? '2fr 1fr 1fr 1fr' : '2fr 1fr';
        }

        let html = '';
        data.products.forEach((product, idx) => {
            const selectedVariant = product.variants.find(v => v.is_selected);
            if (!selectedVariant) return; // Pomijamy produkty bez wybranego wariantu

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

            // Buduj nazwę produktu z wykończeniem i obróbką krawędzi
            let productNameParts = [];

            // Część 1: Gatunek + wymiary
            productNameParts.push(`${variantName} ${product.length}×${product.width}×${product.thickness} cm`);

            // Część 2: Wykończenie
            let finishingText = '';
            if (product.finishing_type) {
                // Parsuj finishingType, np. "Lakierowanie|Bezbarwne|Półmat" lub "Olejowanie|Bejca dąb|Satyna"
                const finishingParts = product.finishing_type.split('|');

                if (finishingParts.length >= 2) {
                    const mainType = finishingParts[0]; // np. "Lakierowanie"
                    const variant = finishingParts[1]; // np. "Bezbarwne" lub "Orzech 22-74"

                    finishingText = `${mainType} ${variant}`;
                } else {
                    finishingText = product.finishing_type;
                }
            } else {
                finishingText = 'Surowy';
            }
            productNameParts.push(finishingText);

            // Część 3: Obróbka krawędzi
            if (product.edges_type && product.edges_type !== 'none') {
                let edgesText = '';

                if (product.edges_type === 'rounded') {
                    edgesText = `Zaokrąglenie R${product.edges_r_value}`;
                } else if (product.edges_type === 'chamfer') {
                    edgesText = `Fazowanie R${product.edges_r_value} ${product.edges_angle_value}°`;
                }

                if (edgesText) {
                    productNameParts.push(edgesText);
                }
            }

            // Część 4: Ilość
            const productName = `${productNameParts.join(' | ')} | ${product.quantity} szt.`;
            const rawPrice = selectedVariant.final_price_brutto.toFixed(2);
            // Wykończenie = finishing + krawędzie (wliczone razem)
            const finishingWithEdges = product.finishing_brutto + (product.edges_brutto || 0);
            const finishingPrice = finishingWithEdges.toFixed(2);
            const totalPrice = (selectedVariant.final_price_brutto + finishingWithEdges).toFixed(2);

            html += `
            <div class="sq-product-row" style="grid-template-columns: ${hasFinishing ? '2fr 1fr 1fr 1fr' : '2fr 1fr'};">
                <div class="sq-product-name">${productName}</div>
                <div class="sq-product-value">${rawPrice} PLN</div>
                ${hasFinishing ? `<div class="sq-product-value">${finishingPrice} PLN</div>` : ''}
                ${hasFinishing ? `<div class="sq-product-sum">${totalPrice} PLN</div>` : ''}
            </div>
        `;
        });
        if (html === '') {
            html = '<div class="sq-product-row"><div class="sq-product-name" style="grid-column: 1/-1; text-align: center; color: #999;">Brak produktów z wybranym wariantem</div></div>';
        }
        tableBody.innerHTML = html;
    }

    // ===== RENDEROWANIE PODSUMOWANIA KWOT =====
    function renderSummaryValues() {
        const data = collectQuoteData();
        if (!data || !data.summary) {
            console.error("[renderSummaryValues] Brak danych summary");
            return;
        }

        const summary = data.summary;

        const setText = (id, value) => {
            const el = document.getElementById(id);
            if (el) {
                el.textContent = `${value.toFixed(2)} PLN`;
            }
        };

        setText("summary-products-brutto", summary.products_brutto);
        setText("summary-products-netto", summary.products_netto);
        // Wykończenie = finishing + krawędzie (wliczone razem)
        const totalFinishing = summary.finishing_brutto + summary.edges_brutto;
        setText("summary-finishing-brutto", totalFinishing);
        setText("summary-finishing-netto", summary.finishing_netto + summary.edges_netto);

        // Ukryj wiersz wykończenia jeśli = 0
        const finishingRow = document.getElementById('summary-finishing-brutto')?.closest('.sq-summary-row');
        if (finishingRow) {
            finishingRow.style.display = totalFinishing > 0 ? '' : 'none';
        }
        setText("summary-shipping-brutto", summary.shipping_brutto);
        setText("summary-shipping-netto", summary.shipping_netto);
        setText("summary-total-brutto", summary.total_brutto);
        setText("summary-total-netto", summary.total_netto);
    }

    // ===== WALIDACJA FORMULARZA =====
    function validateForm() {
        clearAllErrors();
        let isValid = true;

        // W trybie edycji pomijamy walidację danych klienta (klient jest przypisany)
        if (!getIsEditMode()) {
            // 2. Nazwa klienta (required, min 3 znaki)
            const loginField = document.querySelector('[name="client_login"]');
            if (!loginField || loginField.value.trim().length < 3) {
                showFieldError(loginField, 'Minimalna długość: 3 znaki');
                isValid = false;
            }

            // 4. Telefon (jeśli wypełniony, min 9 cyfr bez znaków specjalnych)
            const phoneField = document.querySelector('[name="client_phone"]');
            const phoneValue = phoneField?.value.trim();
            if (phoneValue) {
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

            // 6. Jedno z pól: telefon LUB email (wyjątek: źródła z skip_contact_validation=true)
            const sourceField = document.querySelector('[name="quote_source"]');
            const selectedOption = sourceField?.options[sourceField.selectedIndex];
            const skipValidation = selectedOption?.dataset?.skipValidation === 'true';

            if (!skipValidation) {
                const phoneDigits = phoneValue ? phoneValue.replace(/\D/g, '') : '';
                if (!phoneDigits && !emailValue) {
                    showFieldError(phoneField, 'Wymagany telefon lub email');
                    showFieldError(emailField, 'Wymagany telefon lub email');
                    isValid = false;
                }
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

    // ===== INLINE WALIDACJA NA BLUR =====
    function attachInlineValidation() {
        const loginField = document.querySelector('[name="client_login"]');
        const phoneField = document.querySelector('[name="client_phone"]');
        const emailField = document.querySelector('[name="client_email"]');

        if (phoneField) {
            phoneField.addEventListener('blur', function () {
                const val = this.value.trim();
                if (val) {
                    const digits = val.replace(/\D/g, '');
                    if (digits.length < 9) {
                        showFieldError(this, 'Minimum 9 cyfr');
                    } else {
                        clearFieldError(this);
                    }
                } else {
                    clearFieldError(this);
                }
            });
            phoneField.addEventListener('input', function () {
                if (this.classList.contains('error')) {
                    const digits = this.value.trim().replace(/\D/g, '');
                    if (digits.length >= 9) {
                        clearFieldError(this);
                    }
                }
            });
        }

        if (emailField) {
            emailField.addEventListener('blur', function () {
                const val = this.value.trim();
                if (val && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val)) {
                    showFieldError(this, 'Nieprawidlowy format email');
                } else {
                    clearFieldError(this);
                }
            });
            emailField.addEventListener('input', function () {
                if (this.classList.contains('error')) {
                    const val = this.value.trim();
                    if (!val || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val)) {
                        clearFieldError(this);
                    }
                }
            });
        }
    }

    // Uruchom inline walidację
    attachInlineValidation();

    // ===== OBSŁUGA ZMIANY ŹRÓDŁA ZAPYTANIA =====
    function handleSourceChange() {
        const sourceField = document.querySelector('[name="quote_source"]');
        const phoneLabel = document.querySelector('[name="client_phone"]')?.parentElement.querySelector('.sq-form-label');
        const emailLabel = document.querySelector('[name="client_email"]')?.parentElement.querySelector('.sq-form-label');
        const noteElement = document.querySelector('.sq-input-note');

        if (!sourceField) return;

        // Pobierz atrybut skip_contact_validation z wybranej opcji
        const selectedOption = sourceField.options[sourceField.selectedIndex];
        const skipValidation = selectedOption?.dataset?.skipValidation === 'true';
        const sourceName = sourceField.value;

        if (skipValidation) {
            // Źródło z pomijaniem walidacji - usuń gwiazdki i zmień notatkę
            if (phoneLabel) {
                phoneLabel.innerHTML = 'Telefon <span class="sq-optional" style="color: #999;">(opcjonalne)</span>';
            }
            if (emailLabel) {
                emailLabel.innerHTML = 'E-mail <span class="sq-optional" style="color: #999;">(opcjonalne)</span>';
            }
            if (noteElement) {
                noteElement.innerHTML = `
                <span class="sq-required">*</span> - wymagane pola<br>
                <span style="color: #999;">Dla "${sourceName}" telefon i e-mail są opcjonalne</span>
            `;
            }
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

        // Walidacja
        if (!validateForm()) {
            return;
        }

        // Pokaż loading
        feedbackBox.className = 'sq-feedback';
        feedbackBox.textContent = getIsEditMode() ? 'Aktualizowanie wyceny...' : 'Zapisywanie wyceny...';

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

        const quoteSource = document.querySelector('[name="quote_source"]')?.value?.trim();
        const quoteNote = document.getElementById('quote_note')?.value?.trim() || '';

        if (getIsEditMode()) {
            // ===== TRYB EDYCJI: PUT update =====
            const editUuid = getEditModeData().editUuid;
            if (!editUuid) {
                showGlobalError('Błąd: brak identyfikatora wyceny do aktualizacji');
                return;
            }

            const payload = {
                products,
                total_price: summary.total_brutto,
                settings: {
                    courierName: courier_name,
                    shippingNetto: shipping_cost_netto,
                    shippingBrutto: shipping_cost_brutto,
                    clientType: quote_client_type,
                    multiplier: quote_multiplier,
                    source: quoteSource,
                    notes: quoteNote,
                    quoteType: quoteData.quote_type || 'brutto'
                }
            };


            try {
                const response = await fetch(`/calculator/api/update_quote/${editUuid}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const data = await response.json();

                if (!data.success) {
                    showGlobalError('Błąd: ' + (data.error || 'Nieznany błąd'));
                    console.error("[save_quote.js] Błąd aktualizacji:", data.error);
                } else {
                    // Sukces - przejdź do kroku 3
                    showStep(stepSuccess);
                    showEditSuccessStep(data);
                }

            } catch (err) {
                showGlobalError('Wystąpił błąd sieci lub serwera');
                console.error("[save_quote.js] Błąd fetch (PUT):", err);
            }

        } else {
            // ===== TRYB NORMALNY: POST nowa wycena =====
            const clientIdInput = document.querySelector('[name="client_id"]');
            const client_id = clientIdInput?.value?.trim() || null;
            const clientLogin = document.querySelector('[name="client_login"]')?.value?.trim();
            const clientName = document.querySelector('[name="client_name"]')?.value?.trim() || null;
            const clientPhone = document.querySelector('[name="client_phone"]')?.value?.trim() || null;
            const clientEmail = document.querySelector('[name="client_email"]')?.value?.trim() || null;

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


                    // Oznacz draft jako zapisany
                    if (window.quoteDraftBackup && window.quoteDraftBackup.markQuoteAsSaved) {
                        window.quoteDraftBackup.markQuoteAsSaved();
                    }
                }

            } catch (err) {
                showGlobalError('Wystąpił błąd sieci lub serwera');
                console.error("[save_quote.js] Błąd fetch (POST):", err);
            }
        }
    });

    // ===== OBSŁUGA PRZYCISKÓW W KROKU SUKCESU =====
    function setupSuccessButtons(quoteId) {
        // Przycisk "Przejdź do wyceny"
        const goToQuoteBtn = document.getElementById('goToQuoteBtn');
        if (goToQuoteBtn && quoteId) {
            goToQuoteBtn.onclick = () => {
                window.location.href = `/quotes?open_quote=${quoteId}`;
            };
        }

        // Przycisk "Nowa wycena"
        const newQuoteBtn = document.getElementById('newQuoteBtn');
        if (newQuoteBtn) {
            newQuoteBtn.onclick = () => {
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
                if (window.quoteDraftBackup && window.quoteDraftBackup.resetForNewQuote) {
                    window.quoteDraftBackup.resetForNewQuote();
                }
                modal.style.display = 'none';
            };
        }
    }

    // ===== KROK SUKCESU DLA TRYBU EDYCJI =====
    function showEditSuccessStep(data) {
        const successContent = modal.querySelector('.sq-success-content');
        if (!successContent) return;

        const quoteNumber = data.quote_number || getEditModeData().quoteNumber || '';
        const quoteId = data.quote_id || getEditModeData().quoteId;

        successContent.innerHTML = `
            <div class="sq-success-icon" style="color: #16a34a;">&#10003;</div>
            <h3 class="sq-success-title">Wycena została zaktualizowana</h3>
            <div class="sq-success-number">${quoteNumber}</div>
            <p class="sq-success-text">
                Zmiany w wycenie zostały pomyślnie zapisane.
            </p>
            <div class="sq-success-actions">
                <button id="goToQuoteBtn" class="sq-success-btn sq-btn-primary">
                    Przejdź do wyceny
                </button>
                <button id="backToQuotesBtn" class="sq-success-btn sq-btn-secondary">
                    Wróć do listy wycen
                </button>
            </div>
        `;

        // Obsługa przycisków
        document.getElementById('goToQuoteBtn')?.addEventListener('click', () => {
            window.location.href = `/quotes?open_quote=${quoteId}`;
        });

        document.getElementById('backToQuotesBtn')?.addEventListener('click', () => {
            window.location.href = '/quotes';
        });
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
    let sumEdgesBrutto = 0;
    let sumEdgesNetto = 0;

    forms.forEach((form, index) => {
        const length = parseFloat(form.querySelector('[data-field="length"]')?.value || 0);
        const width = parseFloat(form.querySelector('[data-field="width"]')?.value || 0);
        const thickness = parseFloat(form.querySelector('[data-field="thickness"]')?.value || 0);
        const quantity = parseInt(form.querySelector('[data-field="quantity"]')?.value || 1);

        // ✅ POPRAWKA: Pobierz dane wykończenia z form.dataset (nowy system hierarchiczny)
        // Dane są zapisywane przez updateSelectedFinishing() w calculator.js
        const finishingType = form.dataset.finishingType || null;
        const finishingVariant = form.dataset.finishingVariant || null;
        const finishingColor = form.dataset.finishingColor || null;
        const finishingFullPath = form.dataset.finishingFullPath || null;
        const finishingOptionId = form.dataset.finishingOptionId || null;

        // Fallback dla starszego systemu - jeśli dane nie są w dataset, spróbuj z DOM
        const finishingGloss = form.dataset.finishingGloss ||
            form.querySelector('[data-finishing-gloss].active')?.dataset.finishingGloss || null;

        const finishingBrutto = parseFloat(form.dataset.finishingBrutto || 0);
        const finishingNetto = parseFloat(form.dataset.finishingNetto || 0);

        // Pobierz dane obróbki krawędzi
        const edgesBrutto = parseFloat(form.dataset.edgesBrutto || 0);
        const edgesNetto = parseFloat(form.dataset.edgesNetto || 0);
        const edgesType = form.dataset.edgesType || null;
        const edgesRValue = parseInt(form.dataset.edgesRValue) || null;
        const edgesAngleValue = form.dataset.edgesAngleValue ? parseInt(form.dataset.edgesAngleValue) : null;
        const edgesSvg = form.dataset.edgesSvg || '';
        let edgesData = [];
        try {
            edgesData = form.dataset.edgesData ? JSON.parse(form.dataset.edgesData) : [];
        } catch (e) {
            // Ignore JSON parse errors, use default empty array
        }

        let hasSelectedVariant = false;

        const allVariants = Array.from(form.querySelectorAll('.variants input[type="radio"]')).map(radio => {
            const brutto = parseFloat(radio.dataset.totalBrutto || 0);
            const netto = parseFloat(radio.dataset.totalNetto || 0);
            const volume = (length / 100) * (width / 100) * (thickness / 100);
            const productShape = form.dataset.productShape || 'rectangular';
            let realVolume;
            if (productShape === 'round') {
                const a = (length / 100) / 2;
                const b = (width / 100) / 2;
                realVolume = Math.PI * a * b * (thickness / 100);
            } else {
                realVolume = volume;
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
                real_volume_m3: realVolume,
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


        if (hasSelectedVariant && finishingBrutto > 0) {
            sumFinishingBrutto += finishingBrutto;
            sumFinishingNetto += finishingNetto;
        }

        // Dodaj koszty obróbki krawędzi do sumy (tylko jeśli wariant jest wybrany)
        // Cena już uwzględnia ilość sztuk (mnożenie odbywa się w EdgesModule)
        if (hasSelectedVariant && edgesBrutto > 0) {
            sumEdgesBrutto += edgesBrutto;
            sumEdgesNetto += edgesNetto;
        }

        products.push({
            index: index + 1,
            length,
            width,
            thickness,
            quantity,
            shape: form.dataset.productShape || 'rectangular',
            finishing_type: finishingType,
            finishing_variant: finishingVariant,
            finishing_color: finishingColor,
            finishing_gloss_level: finishingGloss,
            finishing_netto: finishingNetto,
            finishing_brutto: finishingBrutto,
            // Obróbka krawędzi
            edges: edgesData,
            edges_type: edgesType,
            edges_r_value: edgesRValue,
            edges_angle_value: edgesAngleValue,
            edges_netto: edgesNetto,
            edges_brutto: edgesBrutto,
            edges_svg: edgesSvg,
            variants: allVariants
        });
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

    } else {
        // Admin/User/Flexible Partner: użyj danych z selecta (user choice)
        selectedClientType = clientTypeSelect?.value || null;

        if (selectedClientType && window.multiplierMapping && window.multiplierMapping[selectedClientType]) {
            selectedMultiplier = window.multiplierMapping[selectedClientType];
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
    } else {
        // Fallback - sprawdź bezpośrednio radio buttony
        const nettoRadio = document.getElementById('priceModeNetto');
        if (nettoRadio && nettoRadio.checked) {
            quoteType = 'netto';
        }
    }


    const result = {
        products,
        courier_name: courierName,
        shipping_cost_brutto: shippingBrutto,
        shipping_cost_netto: shippingNetto,
        quote_client_type: selectedClientType,
        quote_multiplier: selectedMultiplier,
        quote_note: quoteNote,
        quote_type: quoteType,
        summary: {
            products_brutto: sumProductBrutto,
            products_netto: sumProductNetto,
            finishing_brutto: sumFinishingBrutto,
            finishing_netto: sumFinishingNetto,
            edges_brutto: sumEdgesBrutto,
            edges_netto: sumEdgesNetto,
            shipping_brutto: shippingBrutto,
            shipping_netto: shippingNetto,
            total_brutto: sumProductBrutto + sumFinishingBrutto + sumEdgesBrutto + shippingBrutto,
            total_netto: sumProductNetto + sumFinishingNetto + sumEdgesNetto + shippingNetto
        }
    };

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

}

/**
 * ========================================
 * FUNKCJE DEBUGOWANIA
 * ========================================
 */
document.addEventListener('DOMContentLoaded', function () {

    // Inicjalizacja licznika znaków dla notatki
    initNoteCounter();
});