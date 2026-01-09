// app/modules/baselinker/static/js/baselinker.js

console.log('[Baselinker] Module loaded');

class BaselinkerModal {
    constructor() {
        this.currentStep = 1;
        this.totalSteps = 3;
        this.quoteData = null;
        this.modalData = null;
        this.isSubmitting = false;
        this.originalClientData = null; // NOWE: przechowuje oryginalne dane klienta

        this.init();
    }

    init() {
        console.log('[Baselinker] Initializing modal handlers');
        this.attachEventListeners();
    }

    attachEventListeners() {
        // Event listener dla przycisku "Zamów" w modalu szczegółów wyceny
        document.addEventListener('click', (e) => {
            const orderBtn = e.target.closest('#quote-order-btn');
            if (orderBtn) {
                e.preventDefault();
                const quoteId = this.extractQuoteIdFromModal();
                if (quoteId) {
                    this.openModal(quoteId);
                } else {
                    this.showAlert('Nie udało się określić ID wyceny', 'error');
                }
            }
        });

        // Event listeners dla modala
        this.setupModalEventListeners();
    }

    /**
     * Sprawdza czy wycena jest w trybie NETTO
     * @returns {boolean}
     */
    isNettoMode() {
        return this.modalData?.quote?.quote_type === 'netto';
    }

    setupModalEventListeners() {
        // ZOPTYMALIZOWANE: Jeden event listener dla wszystkich kliknięć
        document.addEventListener('click', (e) => {
            const target = e.target;

            // Zamykanie modala
            if (target.closest('#baselinker-close-modal') ||
                target.closest('#baselinker-close-modal-footer')) {
                this.closeModal();
                return;
            }

            // Zamykanie przez kliknięcie tła
            if (target.classList.contains('bl-style-modal-overlay')) {
                this.closeModal();
                return;
            }

            // Nawigacja między krokami
            if (target.closest('#baselinker-prev-step')) {
                this.prevStep();
                return;
            }

            if (target.closest('#baselinker-next-step')) {
                this.nextStep();
                return;
            }

            if (target.closest('#baselinker-submit-order')) {
                this.submitOrder();
                return;
            }

            // Sync config
            if (target.closest('#baselinker-sync-config')) {
                this.syncConfig();
                return;
            }

            // Kopiuj z faktury do dostawy
            if (target.closest('#bl-copy-invoice-to-delivery')) {
                e.preventDefault();
                this.copyInvoiceToDelivery();
                return;
            }

            // Kopiuj z dostawy do faktury
            if (target.closest('#bl-copy-delivery-to-invoice')) {
                e.preventDefault();
                this.copyDeliveryToInvoice();
                return;
            }

            // Pobierz z GUS
            if (target.closest('#bl-gus-lookup-btn')) {
                e.preventDefault();
                this.handleGusLookup();
                return;
            }
        });

        // Klawisz ESC - musi być osobny listener dla keydown
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isModalOpen()) {
                this.closeModal();
            }
        });
    }

    extractQuoteIdFromModal() {
        console.log('[Baselinker] Próba wyodrębnienia ID wyceny z modala...');
        
        // METODA 1: Spróbuj pobrać z currentQuoteData (globalny stan z quotes.js)
        if (typeof currentQuoteData !== 'undefined' && currentQuoteData && currentQuoteData.id) {
            console.log(`[Baselinker] ✅ ID wyceny z currentQuoteData: ${currentQuoteData.id}`);
            return currentQuoteData.id;
        }
        
        // METODA 2: Spróbuj pobrać z URL modalbox (jeśli endpoint używa ID)
        const modal = document.getElementById('quote-details-modal');
        if (modal && modal.dataset && modal.dataset.quoteId) {
            const quoteId = parseInt(modal.dataset.quoteId);
            console.log(`[Baselinker] ✅ ID wyceny z modala: ${quoteId}`);
            return quoteId;
        }
        
        // METODA 3: Spróbuj wyciągnąć z elementu z numerem wyceny
        const quoteNumberElement = document.getElementById('quotes-details-modal-quote-number');
        if (quoteNumberElement && quoteNumberElement.textContent) {
            const quoteNumber = quoteNumberElement.textContent.trim();
            console.log(`[Baselinker] Znaleziono numer wyceny: ${quoteNumber}`);
            
            // Wyszukaj wycenę w allQuotes po numerze
            if (typeof allQuotes !== 'undefined' && Array.isArray(allQuotes)) {
                const quote = allQuotes.find(q => q.quote_number === quoteNumber);
                if (quote) {
                    console.log(`[Baselinker] ✅ ID wyceny z allQuotes: ${quote.id}`);
                    return quote.id;
                }
            }
        }
        
        console.error('[Baselinker] ❌ Nie udało się znaleźć ID wyceny żadną metodą');
        console.log('[Baselinker] Debug info:', {
            currentQuoteData: typeof currentQuoteData !== 'undefined' ? currentQuoteData : 'undefined',
            modal: modal ? 'exists' : 'not found',
            quoteNumberElement: quoteNumberElement ? quoteNumberElement.textContent : 'not found',
            allQuotes: typeof allQuotes !== 'undefined' ? `array with ${allQuotes.length} items` : 'undefined'
        });
        
        return null;
    }

    async updateClientDataInDatabase(clientData) {
        try {
            console.log('[Baselinker] Zapisywanie danych klienta do bazy:', clientData);

            // POPRAWKA: Użyj client_id z quote zamiast client.id
            const clientId = this.modalData.quote?.client_id || this.modalData.client?.id;

            if (!clientId) {
                console.error('[Baselinker] ❌ Brak ID klienta w modalData');
                this.showAlert('Błąd: Nie można określić ID klienta', 'error');
                return false;
            }

            console.log(`[Baselinker] Używam client_id: ${clientId}`);

            const requestBody = {
                client_name: clientData.client_number || clientData.delivery_name,
                client_delivery_name: clientData.delivery_name,
                email: clientData.email,
                phone: clientData.phone,
                delivery: {
                    name: clientData.delivery_name,
                    company: clientData.delivery_company,
                    address: clientData.delivery_address,
                    zip: clientData.delivery_postcode,
                    city: clientData.delivery_city,
                    region: clientData.delivery_region,
                    country: 'Polska'
                },
                invoice: {
                    name: clientData.invoice_name,
                    company: clientData.invoice_company,
                    address: clientData.invoice_address,
                    zip: clientData.invoice_postcode,
                    city: clientData.invoice_city,
                    nip: clientData.invoice_nip
                }
            };

            const response = await fetch(`/clients/${clientId}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestBody)
            });

            // Obsługa konfliktu emaila (409)
            if (response.status === 409) {
                const errorData = await response.json();
                if (errorData.error_code === 'EMAIL_EXISTS' && errorData.existing_client) {
                    console.log('[Baselinker] Konflikt emaila - pokazuję dialog wyboru');
                    const userChoice = await this.showEmailConflictDialog(errorData.existing_client, clientData.email);

                    if (userChoice === 'change_email') {
                        // Użytkownik chce zmienić email - wróć do formularza
                        return 'CHANGE_EMAIL';
                    } else if (userChoice === 'reassign') {
                        // Przepnij wycenę pod istniejącego klienta
                        return await this.reassignQuoteToClient(errorData.existing_client.id, requestBody);
                    }
                    return false;
                }
            }

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                console.error('[Baselinker] ❌ Odpowiedź serwera:', errorData);
                throw new Error(errorData.error || `HTTP ${response.status}`);
            }

            const result = await response.json();
            console.log('[Baselinker] ✅ Dane klienta zaktualizowane pomyślnie:', result);
            return true;

        } catch (error) {
            console.error('[Baselinker] ❌ Błąd podczas aktualizacji danych klienta:', error);
            this.showAlert(`Błąd podczas zapisywania danych klienta: ${error.message}`, 'error');
            return false;
        }
    }

    // Dialog wyboru przy konflikcie emaila
    async showEmailConflictDialog(existingClient, email) {
        return new Promise((resolve) => {
            const dialogHtml = `
                <div class="bl-email-conflict-overlay" id="emailConflictDialog">
                    <div class="bl-email-conflict-modal">
                        <div class="bl-email-conflict-header">
                            <span class="bl-email-conflict-icon">⚠️</span>
                            <h3>Email już istnieje w systemie</h3>
                        </div>
                        <div class="bl-email-conflict-body">
                            <p>Email <strong>${email}</strong> jest już przypisany do klienta:</p>
                            <div class="bl-existing-client-info">
                                <strong>${existingClient.name}</strong>
                            </div>
                            <p>Co chcesz zrobić?</p>
                        </div>
                        <div class="bl-email-conflict-actions">
                            <button type="button" class="bl-btn bl-btn-secondary" id="btnChangeEmail">
                                ✏️ Użyj innego emaila
                            </button>
                            <button type="button" class="bl-btn bl-btn-primary" id="btnReassignClient">
                                🔄 Przepnij do istniejącego klienta
                            </button>
                        </div>
                    </div>
                </div>
            `;

            // Dodaj style jeśli nie istnieją
            if (!document.getElementById('emailConflictStyles')) {
                const styles = document.createElement('style');
                styles.id = 'emailConflictStyles';
                styles.textContent = `
                    .bl-email-conflict-overlay {
                        position: fixed;
                        top: 0;
                        left: 0;
                        right: 0;
                        bottom: 0;
                        background: rgba(0, 0, 0, 0.6);
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        z-index: 10001;
                    }
                    .bl-email-conflict-modal {
                        background: white;
                        border-radius: 12px;
                        padding: 24px;
                        max-width: 450px;
                        width: 90%;
                        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
                    }
                    .bl-email-conflict-header {
                        display: flex;
                        align-items: center;
                        gap: 12px;
                        margin-bottom: 16px;
                    }
                    .bl-email-conflict-icon {
                        font-size: 28px;
                    }
                    .bl-email-conflict-header h3 {
                        margin: 0;
                        font-size: 18px;
                        color: #333;
                    }
                    .bl-email-conflict-body {
                        margin-bottom: 20px;
                        color: #555;
                    }
                    .bl-email-conflict-body p {
                        margin: 8px 0;
                    }
                    .bl-existing-client-info {
                        background: #f5f5f5;
                        padding: 12px 16px;
                        border-radius: 8px;
                        margin: 12px 0;
                        border-left: 4px solid #2196F3;
                    }
                    .bl-email-conflict-actions {
                        display: flex;
                        gap: 12px;
                        flex-wrap: wrap;
                    }
                    .bl-email-conflict-actions .bl-btn {
                        flex: 1;
                        min-width: 150px;
                        padding: 12px 16px;
                        border: none;
                        border-radius: 8px;
                        cursor: pointer;
                        font-size: 14px;
                        font-weight: 500;
                        transition: all 0.2s;
                    }
                    .bl-email-conflict-actions .bl-btn-secondary {
                        background: #e0e0e0;
                        color: #333;
                    }
                    .bl-email-conflict-actions .bl-btn-secondary:hover {
                        background: #d0d0d0;
                    }
                    .bl-email-conflict-actions .bl-btn-primary {
                        background: #2196F3;
                        color: white;
                    }
                    .bl-email-conflict-actions .bl-btn-primary:hover {
                        background: #1976D2;
                    }
                `;
                document.head.appendChild(styles);
            }

            // Wstaw dialog do DOM
            const container = document.createElement('div');
            container.innerHTML = dialogHtml;
            document.body.appendChild(container.firstElementChild);

            const dialog = document.getElementById('emailConflictDialog');
            const btnChangeEmail = document.getElementById('btnChangeEmail');
            const btnReassignClient = document.getElementById('btnReassignClient');

            const cleanup = () => {
                dialog.remove();
            };

            btnChangeEmail.addEventListener('click', () => {
                cleanup();
                resolve('change_email');
            });

            btnReassignClient.addEventListener('click', () => {
                cleanup();
                resolve('reassign');
            });
        });
    }

    // Przepięcie wyceny do innego klienta
    async reassignQuoteToClient(newClientId, clientData) {
        try {
            const quoteId = this.modalData.quote?.id;
            if (!quoteId) {
                throw new Error('Brak ID wyceny');
            }

            console.log(`[Baselinker] Przepinanie wyceny ${quoteId} do klienta ${newClientId}`);

            const response = await fetch(`/quotes/api/quotes/${quoteId}/reassign-client`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    new_client_id: newClientId,
                    client_data: clientData
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.error || `HTTP ${response.status}`);
            }

            const result = await response.json();
            console.log('[Baselinker] ✅ Wycena przepięta pomyślnie:', result);

            // Zaktualizuj modalData z nowym client_id
            this.modalData.quote.client_id = newClientId;
            this.modalData.client = { ...this.modalData.client, id: newClientId };

            this.showAlert(result.message || 'Wycena została przepięta do istniejącego klienta', 'success');
            return true;

        } catch (error) {
            console.error('[Baselinker] ❌ Błąd podczas przepinania wyceny:', error);
            this.showAlert(`Błąd: ${error.message}`, 'error');
            return false;
        }
    }

    async openModal(quoteId) {
        console.log(`[Baselinker] Opening modal for quote ID: ${quoteId}`);

        try {
            this.showLoadingOverlay();

            // WAŻNE: RESET STANU MODALA
            this.currentStep = 1;
            this.isSubmitting = false;
            this.originalShippingCost = null; // Reset poprzednich wartości

            const response = await fetch(`/baselinker/api/quote/${quoteId}/order-modal-data`);

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `HTTP ${response.status}`);
            }

            this.modalData = await response.json();
            console.log('[Baselinker] Modal data loaded:', this.modalData);
            console.log('[Baselinker] 🔍 DEBUG - Struktura klienta:', {
                client: this.modalData.client,
                client_id: this.modalData.client?.id,
                client_keys: Object.keys(this.modalData.client || {}),
                quote: this.modalData.quote,
                quote_client_id: this.modalData.quote?.client_id
            });
            
            // KRYTYCZNA POPRAWKA: Zapisz oryginalne koszty wysyłki z danych modalData
            this.originalShippingCost = parseFloat(this.modalData.costs.shipping_brutto) || 0;
            console.log(`[Baselinker] ✅ Zapisano oryginalne koszty wysyłki: ${this.originalShippingCost} PLN`);

            this.originalClientData = this.cloneClientData(this.modalData.client);
            this.populateModalData();
            this.showModal();

            // WAŻNE: Ustaw krok na 1 i zaktualizuj
            this.currentStep = 1;
            this.updateStep();

        } catch (error) {
            console.error('[Baselinker] Error opening modal:', error);
            this.showAlert(`Błąd ładowania danych: ${error.message}`, 'error');
        } finally {
            this.hideLoadingOverlay();
        }
    }

    // NOWA FUNKCJA: Klonuje dane klienta
    cloneClientData(clientData) {
        return {
            client_number: clientData.client_number || '',  // Nazwa klienta/firmy
            delivery_name: clientData.delivery_name || clientData.number || '',
            delivery_company: clientData.delivery_company || clientData.company || '',
            delivery_address: clientData.delivery_address || '',
            delivery_postcode: clientData.delivery_postcode || '',
            delivery_city: clientData.delivery_city || '',
            delivery_region: clientData.delivery_region || '',
            email: clientData.email || '',
            phone: clientData.phone || '',
            invoice_name: clientData.invoice_name || clientData.name || '',
            invoice_company: clientData.invoice_company || clientData.company || '',
            invoice_nip: clientData.invoice_nip || '',
            invoice_address: clientData.invoice_address || clientData.delivery_address || '',
            invoice_postcode: clientData.invoice_postcode || clientData.delivery_postcode || '',
            invoice_city: clientData.invoice_city || clientData.delivery_city || '',
            invoice_region: clientData.invoice_region || clientData.delivery_region || '',
            want_invoice: !!(clientData.invoice_nip && clientData.invoice_nip.trim() !== '')
        };
    }

    // NOWA FUNKCJA: Pobiera aktualne dane z formularza
    getCurrentClientData() {
        return {
            client_number: this.originalClientData?.client_number || '',  // Zachowaj z oryginalnych danych
            delivery_name: this.getInputValue('delivery-fullname'),
            delivery_company: this.getInputValue('delivery-company'),
            delivery_address: this.getInputValue('delivery-address'),
            delivery_postcode: this.getInputValue('delivery-postcode'),
            delivery_city: this.getInputValue('delivery-city'),
            delivery_region: this.getInputValue('delivery-region'),
            email: this.getInputValue('client-email'),
            phone: this.getInputValue('client-phone'),
            invoice_name: this.getInputValue('invoice-fullname'),
            invoice_company: this.getInputValue('invoice-company'),
            invoice_nip: this.getInputValue('invoice-nip'),
            invoice_address: this.getInputValue('invoice-address'),
            invoice_postcode: this.getInputValue('invoice-postcode'),
            invoice_city: this.getInputValue('invoice-city'),
            invoice_region: this.getInputValue('invoice-region'),
            want_invoice: document.getElementById('want-invoice-checkbox')?.checked || false
        };
    }

    setSelectValue(selectId, value) {
        const select = document.getElementById(selectId);
        if (!select || !value) {
            console.log(`[Baselinker] ⚠️ setSelectValue: brak elementu lub wartości (${selectId})`);
            return;
        }

        console.log(`[Baselinker] setSelectValue dla ${selectId} z wartością: "${value}"`);

        // Konwertuj wartość na lowercase dla porównania
        const valueLower = String(value).toLowerCase().trim();

        // Znajdź opcję o odpowiedniej wartości (dokładne dopasowanie)
        let option = Array.from(select.options).find(opt =>
            opt.value.toLowerCase().trim() === valueLower
        );

        if (option) {
            select.value = option.value;
            console.log(`[Baselinker] ✅ Dokładne dopasowanie ${selectId}: "${option.value}"`);
            return;
        }

        // Jeśli nie ma dokładnego dopasowania, spróbuj częściowego
        console.log(`[Baselinker] ⚠️ Nie znaleziono dokładnej opcji "${value}" w ${selectId}, próbuję częściowego dopasowania`);

        const partialMatch = Array.from(select.options).find(opt =>
            opt.value.toLowerCase().includes(valueLower) ||
            valueLower.includes(opt.value.toLowerCase())
        );

        if (partialMatch) {
            select.value = partialMatch.value;
            console.log(`[Baselinker] ✅ Częściowe dopasowanie ${selectId}: "${partialMatch.value}"`);
            return;
        }

        // Jeśli nie znaleziono żadnego dopasowania
        console.warn(`[Baselinker] ❌ Nie znaleziono opcji dla "${value}" w ${selectId}`);
        console.log(`[Baselinker] Dostępne opcje w ${selectId}:`,
            Array.from(select.options).map(opt => opt.value)
        );
    }

    // NOWA FUNKCJA: Porównuje dane klienta
    hasClientDataChanged() {
        if (!this.originalClientData) return false;

        const currentData = this.getCurrentClientData();

        // Funkcja normalizująca wartości (trimuje i zamienia puste stringi na '')
        const normalize = (value) => {
            if (value === null || value === undefined) return '';
            return String(value).trim();
        };

        // Porównaj wszystkie pola
        for (const key in this.originalClientData) {
            const originalValue = normalize(this.originalClientData[key]);
            const currentValue = normalize(currentData[key]);

            if (originalValue !== currentValue) {
                console.log(`[Baselinker] Zmiana w polu ${key}: "${originalValue}" -> "${currentValue}"`);
                return true;
            }
        }

        return false;
    }

    // NOWA FUNKCJA: Pokazuje dialog aktualizacji danych klienta
    async showClientDataUpdateDialog() {
        const message = `Dane klienta zostały zmienione w formularzu.\n\nCzy chcesz zaktualizować dane klienta w bazie danych?\n\n• Tak - zaktualizuj dane w bazie\n• Nie - kontynuuj z nowymi danymi tylko dla tego zamówienia`;
        
        return new Promise((resolve) => {
            // Użyj natywnego confirm jako fallback
            const result = confirm(message);
            resolve(result);
        });
    }

    populateModalData() {
        if (!this.modalData) return;

        console.log('[Baselinker] Populating modal with data');

        // Krok 1: Przegląd zamówienia
        this.populateOrderSummary();
        this.populateProductsList();
        this.populateFinancialSummary();

        // Krok 2: Konfiguracja
        this.populateConfigurationForm();
        this.populateClientPreview();

        // Krok 3: Potwierdzenie
        this.populateFinalSummary();
    }

    /**
     * Renderuje podsumowanie zamówienia (KROK 1) z obsługą trybu netto/brutto
     */
    populateOrderSummary() {
        const container = document.getElementById('baselinker-order-summary');
        if (!container) return;

        const quote = this.modalData.quote;
        const client = this.modalData.client;

        let summaryHTML = `
        <div class="bl-style-summary-row">
            <span>Numer wyceny:</span>
            <strong>${quote.quote_number}</strong>
        </div>
        <div class="bl-style-summary-row">
            <span>Klient:</span>
            <strong>${client.name}${client.company ? ` - ${client.company}` : ''}</strong>
        </div>
        <div class="bl-style-summary-row">
            <span>Data wyceny:</span>
            <strong>${new Date(quote.created_at).toLocaleDateString('pl-PL')}</strong>
        </div>
        <div class="bl-style-summary-row">
            <span>Status wyceny:</span>
            <div class="bl-style-status-badge bl-style-status-ready">✓ ${quote.status_name}</div>
        </div>
        <div class="bl-style-summary-row">
            <span>Źródło wyceny:</span>
            <strong>${quote.source || 'Nie podano'}</strong>
        </div>
    `;

        // ✅ Dodaj notatkę jeśli istnieje
        if (quote.notes && quote.notes.trim()) {
            summaryHTML += `
            <div class="bl-style-summary-row bl-style-summary-note">
                <span>Notatka:</span>
                <div class="bl-style-note-text">${this.escapeHtml(quote.notes)}</div>
            </div>
        `;
        }

        // ✅ DOPIERO TERAZ wstaw do kontenera
        container.innerHTML = summaryHTML;
    }

    /**
     * Renderuje listę produktów (KROK 1) z obsługą trybu netto/brutto
     */
    populateProductsList() {
        const container = document.getElementById('baselinker-products-list');
        if (!container) return;

        const products = this.modalData.products;
        const isNetto = this.isNettoMode();

        if (!products || products.length === 0) {
            container.innerHTML = '<p>Brak produktów do wyświetlenia</p>';
            return;
        }

        console.log('[Baselinker] Renderowanie listy produktów, tryb:', isNetto ? 'NETTO' : 'BRUTTO');

        container.innerHTML = products.map(product => {
            // POPRAWKA: Pobierz quantity z finishing details
            let quantity = 1;

            if (product.finishing && product.finishing.quantity) {
                quantity = parseInt(product.finishing.quantity);
            } else if (product.quantity) {
                quantity = parseInt(product.quantity);
            }

            if (isNaN(quantity) || quantity <= 0) {
                quantity = 1;
            }

            // 🆕 NOWE: Wybierz odpowiednie ceny w zależności od trybu
            const unitPrice = isNetto ? product.unit_price_netto : product.unit_price_brutto;
            const priceLabel = isNetto ? 'netto' : 'brutto';

            return `
            <div class="bl-style-product-item">
                <div class="bl-style-product-name">
                    ${this.buildProductName(product)}
                    <div class="bl-style-product-details">
                        Waga: <span style="font-weight: 400;">${this.calculateProductWeight(product)} kg</span>
                        ${product.finishing ?
                    `<br>Wykończenie: <span class="bl-style-product-finishing">${this.getFinishingDescription(product.finishing)}</span>` : ''}
                    </div>
                </div>
                <div>${product.dimensions}</div>
                <div class="bl-style-product-quantity">${quantity} szt.</div>
                <div class="bl-style-product-price">
                    <div class="bl-style-amount">
                        <div class="bl-style-amount-main">${this.formatCurrency(unitPrice)}</div>
                        <div class="bl-style-amount-label">${priceLabel}</div>
                    </div>
                </div>
            </div>
        `;
        }).join('');
    }

    getFinishingDescription(finishing) {
        if (!finishing) return 'Brak wykończenia';
        
        const parts = [
            finishing.variant,
            finishing.type,
            finishing.color,
            finishing.gloss
        ].filter(Boolean);
        
        return parts.length > 0 ? parts.join(' - ') : 'Brak wykończenia';
    }

    /**
     * Renderuje podsumowanie finansowe (KROK 1) z obsługą trybu netto/brutto
     */
    populateFinancialSummary() {
        const container = document.getElementById('baselinker-financial-summary');
        if (!container) return;

        const costs = this.modalData.costs;
        const isNetto = this.isNettoMode();

        console.log('[Baselinker] Renderowanie podsumowania finansowego, tryb:', isNetto ? 'NETTO' : 'BRUTTO');

        // 🆕 NOWE: Wybierz odpowiednie kwoty w zależności od trybu
        const productsCost = isNetto ? costs.products_netto : costs.products_brutto;
        const finishingCost = isNetto ? costs.finishing_netto : costs.finishing_brutto;
        const shippingCost = isNetto ? costs.shipping_netto : costs.shipping_brutto;
        const totalCost = isNetto ? costs.total_netto : costs.total_brutto;
        const priceLabel = isNetto ? 'netto' : 'brutto';

        container.innerHTML = `
        <div class="bl-style-summary-row">
            <span>Koszt produktów:</span>
            <div class="bl-style-amount">
                <div class="bl-style-amount-main">${this.formatCurrency(productsCost)}</div>
                <div class="bl-style-amount-label">${priceLabel}</div>
            </div>
        </div>
        <div class="bl-style-summary-row">
            <span>Koszt wykończenia:</span>
            <div class="bl-style-amount">
                <div class="bl-style-amount-main">${this.formatCurrency(finishingCost)}</div>
                <div class="bl-style-amount-label">${priceLabel}</div>
            </div>
        </div>
        <div class="bl-style-summary-row">
            <span>Koszt wysyłki:</span>
            <div class="bl-style-amount">
                <div class="bl-style-amount-main">${this.formatCurrency(shippingCost)}</div>
                <div class="bl-style-amount-label">${priceLabel}</div>
            </div>
        </div>
        <div class="bl-style-summary-row">
            <span>Wartość całkowita:</span>
            <div class="bl-style-amount">
                <div class="bl-style-amount-main">${this.formatCurrency(totalCost)}</div>
                <div class="bl-style-amount-label">${priceLabel}</div>
            </div>
        </div>
    `;
    }

    populateConfigurationForm() {
        const config = this.modalData.config;

        console.log('[Baselinker] Konfiguracja otrzymana:', config);

        // 1. ŹRÓDŁA ZAMÓWIEŃ
        const orderSourceSelect = document.getElementById('order-source-select');
        if (orderSourceSelect) {
            orderSourceSelect.innerHTML = '<option value="">Wybierz źródło...</option>';

            // Usuń tylko undefined/null, ale zostaw 0 (to jest prawidłowe ID)
            const validSources = config.order_sources.filter(source =>
                source.id !== null && source.id !== undefined && source.id !== ''
            );
            console.log(`[Baselinker] Prawidłowe źródła (włącznie z ID=0): ${validSources.length}`, validSources);

            let sourceSelected = false;

            validSources.forEach(source => {
                const option = document.createElement('option');
                option.value = source.id;
                option.textContent = source.name;

                orderSourceSelect.appendChild(option);
            });

            // TYLKO dopasowanie na podstawie źródła wyceny - BEZ FALLBACK
            const quoteSource = this.modalData.quote.source;
            console.log(`[Baselinker] Źródło wyceny: "${quoteSource}"`);

            if (quoteSource) {
                // Szukaj dopasowania po nazwie źródła
                const matchingSource = validSources.find(source => {
                    const sourceName = source.name.toLowerCase();
                    const quoteSourceLower = quoteSource.toLowerCase();

                    // Dopasowania:
                    return sourceName.includes(quoteSourceLower) ||
                        quoteSourceLower.includes(sourceName.split(' ')[0]) ||
                        // Dodatkowe dopasowanie dla "Osobiście"
                        (quoteSourceLower === 'osobiście' && sourceName.includes('osobiście')) ||
                        (quoteSourceLower === 'osobiscie' && sourceName.includes('osobiście'));
                });

                if (matchingSource) {
                    orderSourceSelect.value = matchingSource.id;
                    sourceSelected = true;
                    console.log(`[Baselinker] ✅ Automatycznie dopasowano źródło: ${matchingSource.name} (ID: ${matchingSource.id}) na podstawie źródła wyceny "${quoteSource}"`);
                } else {
                    console.log(`[Baselinker] ⚠️ Nie znaleziono dopasowania dla źródła wyceny "${quoteSource}"`);
                    console.log(`[Baselinker] Dostępne źródła:`, validSources.map(s => ({ id: s.id, name: s.name })));
                }
            }

            // Komunikat o rezultacie
            if (!sourceSelected) {
                if (quoteSource) {
                    console.log(`[Baselinker] ⚪ Nie znaleziono dopasowania dla źródła "${quoteSource}" - użytkownik musi wybrać ręcznie`);
                } else {
                    console.log(`[Baselinker] ⚪ Brak źródła w wycenie - użytkownik musi wybrać ręcznie`);
                }
            }

            // Informacja o braku źródeł
            if (validSources.length === 0) {
                const option = document.createElement('option');
                option.value = '';
                option.textContent = 'Brak dostępnych źródeł - uruchom synchronizację';
                option.disabled = true;
                orderSourceSelect.appendChild(option);
            }
        }

        // 2. STATUSY ZAMÓWIEŃ - POPRAWIONA LOGIKA
        const orderStatusSelect = document.getElementById('order-status-select');
        if (orderStatusSelect) {
            orderStatusSelect.innerHTML = '<option value="">Wybierz status...</option>';

            let defaultStatusSet = false;

            config.order_statuses.forEach(status => {
                const option = document.createElement('option');
                option.value = status.id;
                option.textContent = status.name;

                // POPRAWKA: Priorytet dla statusu "Nowe - nieopłacone" (ID: 105112)
                if (status.id === 105112) {
                    option.selected = true;
                    defaultStatusSet = true;
                    console.log(`[Baselinker] ✅ Ustawiono PRIORYTETOWY status: ${status.name} (ID: ${status.id})`);
                }

                orderStatusSelect.appendChild(option);
            });

            // KRYTYCZNE: Ustaw wartość select programowo
            if (defaultStatusSet) {
                orderStatusSelect.value = '105112';
                console.log(`[Baselinker] ✅ Programowo ustawiono wartość select na: ${orderStatusSelect.value}`);
            }

            // Fallback - jeśli nie ma statusu 105112, spróbuj znaleźć podobny
            if (!defaultStatusSet) {
                const fallbackStatus = config.order_statuses.find(status =>
                    status.name.toLowerCase().includes('nowe') &&
                    status.name.toLowerCase().includes('nieopłacone')
                );

                if (fallbackStatus) {
                    orderStatusSelect.value = fallbackStatus.id;
                    console.log(`[Baselinker] ✅ Fallback: ustawiono status ${fallbackStatus.name} (ID: ${fallbackStatus.id})`);
                }
            }
        }

        // 3. METODY PŁATNOŚCI - POPRAWIONA LOGIKA
        const paymentMethodSelect = document.getElementById('payment-method-select');
        if (paymentMethodSelect) {
            paymentMethodSelect.innerHTML = '<option value="">Wybierz metodę...</option>';

            let defaultPaymentSet = false;

            config.payment_methods.forEach(method => {
                const option = document.createElement('option');
                option.value = method;
                option.textContent = method;

                // POPRAWKA: Priorytet dla "Przelew bankowy"
                if (method === 'Przelew bankowy') {
                    option.selected = true;
                    defaultPaymentSet = true;
                    console.log(`[Baselinker] ✅ Ustawiono PRIORYTETOWĄ metodę płatności: ${method}`);
                }

                paymentMethodSelect.appendChild(option);
            });

            // KRYTYCZNE: Ustaw wartość select programowo
            if (defaultPaymentSet) {
                paymentMethodSelect.value = 'Przelew bankowy';
                console.log(`[Baselinker] ✅ Programowo ustawiono metodę płatności: ${paymentMethodSelect.value}`);
            }

            // Fallback - jeśli nie ma "Przelew bankowy", weź pierwszy z listy
            if (!defaultPaymentSet && config.payment_methods.length > 0) {
                paymentMethodSelect.value = config.payment_methods[0];
                console.log(`[Baselinker] ✅ Fallback: ustawiono pierwszą metodę płatności: ${config.payment_methods[0]}`);
            }
        }

        // 4. METODA DOSTAWY - NOWA LOGIKA DLA INPUT (zamiast select)
        const deliveryMethodInput = document.getElementById('delivery-method-input');
        if (deliveryMethodInput) {
            // Pobierz courier_name z wyceny
            const courierFromQuote = this.modalData.quote?.courier_name;
            console.log(`[Baselinker] Kurier z wyceny: "${courierFromQuote}"`);

            // Jeśli jest courier_name i nie jest pusty ani "-", użyj go; w przeciwnym razie ustaw "Odbiór osobisty"
            if (courierFromQuote && courierFromQuote.trim() !== '' && courierFromQuote.trim() !== '-') {
                deliveryMethodInput.value = courierFromQuote.trim();
                console.log(`[Baselinker] ✅ Ustawiono metodę dostawy z wyceny: "${courierFromQuote}"`);
            } else {
                deliveryMethodInput.value = 'Odbiór osobisty';
                console.log(`[Baselinker] ✅ Ustawiono domyślną metodę dostawy: "Odbiór osobisty"`);
            }
        }

        // 5. SETUP EVENT LISTENERS - POPRAWIONY
        this.setupConfigurationEventListeners();

        // 6. OPÓŹNIONA WALIDACJA I SETUP
        setTimeout(() => {
            // Debug wartości
            console.log('[Baselinker] 🔍 DEBUG po ustawieniu domyślnych wartości:');
            this.debugSelectValues();

            this.debugShippingCosts();
        }, 100);
    }

    populateClientPreview() {
        // Nowa funkcja obsługująca formularze klienta
        this.populateClientData();
    }

    // 5. NOWA METODA - POPRAWIONA OBSŁUGA EVENT LISTENERÓW KONFIGURACJI
    setupConfigurationEventListeners() {
        const selectIds = ['order-source-select', 'order-status-select', 'payment-method-select'];

        selectIds.forEach(selectId => {
            const select = document.getElementById(selectId);
            if (select) {
                // 🔧 POPRAWKA: Zachowaj aktualną wartość przed klonowaniem
                const currentValue = select.value;
                console.log(`[Baselinker] 💾 Zachowuję wartość ${selectId}: "${currentValue}"`);

                // Usuń poprzednie event listenery przez klonowanie
                const newSelect = select.cloneNode(true);
                select.parentNode.replaceChild(newSelect, select);

                // 🔧 POPRAWKA: Przywróć wartość po klonowaniu
                const freshSelect = document.getElementById(selectId);
                if (freshSelect && currentValue) {
                    freshSelect.value = currentValue;
                    console.log(`[Baselinker] ✅ Przywrócono wartość ${selectId}: "${freshSelect.value}"`);
                }

                // Dodaj nowy event listener do świeżego elementu
                if (freshSelect) {
                    freshSelect.addEventListener('change', (e) => {
                        console.log(`[Baselinker] 🔄 Zmiana w ${selectId}: "${e.target.value}"`);

                        // Usuń błąd z tego pola
                        freshSelect.classList.remove('bl-style-error');
                        const errorMsg = freshSelect.parentNode?.querySelector('.bl-style-error-message');
                        if (errorMsg) {
                            errorMsg.remove();
                        }

                        // Sprawdź walidację
                        this.validateConfiguration();
                    });
                }
            }
        });

        // Dodaj event listener dla klikalnych opcji dostawy
        this.setupDeliveryOptionsListeners();

        console.log('[Baselinker] ✅ Event listenery skonfigurowane z zachowaniem wartości');
    }

    // NOWA FUNKCJA: Obsługa klikalnych opcji dostawy
    setupDeliveryOptionsListeners() {
        const deliveryOptions = document.querySelectorAll('.bl-delivery-option');

        deliveryOptions.forEach(option => {
            option.addEventListener('click', (e) => {
                const value = e.target.getAttribute('data-value');
                const deliveryInput = document.getElementById('delivery-method-input');

                if (deliveryInput && value) {
                    deliveryInput.value = value;
                    console.log(`[Baselinker] ✅ Ustawiono metodę dostawy: "${value}"`);
                }
            });
        });
    }

    populateClientData() {
        const client = this.modalData.client;

        // Wypełnij dane dostawy
        this.setInputValue('delivery-fullname', client.delivery_name || client.number || '');
        this.setInputValue('delivery-company', client.delivery_company || client.company || '');
        this.setInputValue('delivery-address', client.delivery_address || '');
        this.setInputValue('delivery-postcode', client.delivery_postcode || '');
        this.setInputValue('delivery-city', client.delivery_city || '');
        this.setInputValue('delivery-region', client.delivery_region || '');
        this.setInputValue('client-email', client.email || '');
        this.setInputValue('client-phone', client.phone || '');

        // Wypełnij dane faktury
        this.setInputValue('invoice-fullname', client.invoice_name || client.name || '');
        this.setInputValue('invoice-company', client.invoice_company || client.company || '');
        this.setInputValue('invoice-nip', client.invoice_nip || '');
        this.setInputValue('invoice-address', client.invoice_address || client.delivery_address || '');
        this.setInputValue('invoice-postcode', client.invoice_postcode || client.delivery_postcode || '');
        this.setInputValue('invoice-city', client.invoice_city || client.delivery_city || '');
        this.setInputValue('invoice-region', client.invoice_region || client.delivery_region || '');

        // Checkbox faktury i event listener
        const wantInvoiceCheckbox = document.getElementById('want-invoice-checkbox');
        const invoiceSection = document.getElementById('invoice-data-section');

        if (wantInvoiceCheckbox && invoiceSection) {
            const hasNip = client.invoice_nip && client.invoice_nip.trim() !== '';
            wantInvoiceCheckbox.checked = hasNip;
            invoiceSection.style.display = hasNip ? 'block' : 'none';

            // 🆕 NOWY EVENT LISTENER: Auto-kopiowanie danych z dostawy do faktury
            wantInvoiceCheckbox.addEventListener('change', (e) => {
                invoiceSection.style.display = e.target.checked ? 'block' : 'none';

                // Jeśli włączono fakturę i pola faktury są puste, skopiuj z dostawy
                if (e.target.checked && this.shouldAutoCopyToInvoice()) {
                    this.autoCopyDeliveryToInvoice();
                }
            });
        }
    }

    shouldAutoCopyToInvoice() {
        const invoiceFields = [
            'invoice-fullname', 'invoice-company', 'invoice-address',
            'invoice-postcode', 'invoice-city', 'invoice-region'
        ];

        // Sprawdź czy wszystkie pola faktury są puste
        return invoiceFields.every(fieldId => {
            const value = this.getInputValue(fieldId);
            return !value || value.trim() === '';
        });
    }

    autoCopyDeliveryToInvoice() {
        const copyMapping = {
            'delivery-fullname': 'invoice-fullname',
            'delivery-company': 'invoice-company',
            'delivery-address': 'invoice-address',
            'delivery-postcode': 'invoice-postcode',
            'delivery-city': 'invoice-city',
            'delivery-region': 'invoice-region' // 🆕 KOPIOWANIE WOJEWÓDZTWA
        };

        for (const [sourceId, targetId] of Object.entries(copyMapping)) {
            const sourceValue = this.getInputValue(sourceId);
            if (sourceValue) {
                this.setInputValue(targetId, sourceValue);
            }
        }

        console.log('[Baselinker] ✅ Auto-skopiowano dane z dostawy do faktury (włącznie z województwem)');
    }

    // POPRAWIONA FUNKCJA: Bardziej dokładna walidacja
    validateConfigurationForm() {
        const orderSource = document.getElementById('order-source-select');
        const orderStatus = document.getElementById('order-status-select');
        const paymentMethod = document.getElementById('payment-method-select');

        let isValid = true;
        let errorMessages = [];

        // Reset poprzednich błędów
        this.clearValidationErrors();

        console.log('[Baselinker] Walidacja formularza konfiguracji:');
        console.log(`- Źródło: "${orderSource?.value}" (type: ${typeof orderSource?.value})`);
        console.log(`- Status: "${orderStatus?.value}" (type: ${typeof orderStatus?.value})`);
        console.log(`- Płatność: "${paymentMethod?.value}" (type: ${typeof paymentMethod?.value})`);

        // 🔧 POPRAWIONA WALIDACJA ŹRÓDŁA - akceptuj ID = 0 oraz inne prawidłowe wartości
        if (!orderSource?.value && orderSource?.value !== '0') {
            this.markFieldAsError(orderSource, 'Wybierz źródło zamówienia z listy');
            errorMessages.push('Źródło zamówienia jest wymagane - wybierz z listy');
            isValid = false;
            console.log('[Baselinker] BŁĄD: Nie wybrano źródła zamówienia');
        } else if (orderSource?.value === '') {
            this.markFieldAsError(orderSource, 'Wybierz źródło zamówienia z listy');
            errorMessages.push('Źródło zamówienia jest wymagane - wybierz z listy');
            isValid = false;
            console.log('[Baselinker] BŁĄD: Puste źródło zamówienia');
        } else {
            console.log(`[Baselinker] ✅ Prawidłowe źródło zamówienia: ${orderSource.value}`);
        }

        if (!orderStatus?.value || orderStatus.value.trim() === '') {
            this.markFieldAsError(orderStatus, 'Wybierz status zamówienia');
            errorMessages.push('Status zamówienia jest wymagany');
            isValid = false;
            console.log('[Baselinker] BŁĄD: Brak statusu zamówienia');
        } else {
            console.log(`[Baselinker] ✅ Prawidłowy status zamówienia: ${orderStatus.value}`);
        }

        if (!paymentMethod?.value || paymentMethod.value.trim() === '') {
            this.markFieldAsError(paymentMethod, 'Wybierz metodę płatności');
            errorMessages.push('Metoda płatności jest wymagana');
            isValid = false;
            console.log('[Baselinker] BŁĄD: Brak metody płatności');
        } else {
            console.log(`[Baselinker] ✅ Prawidłowa metoda płatności: ${paymentMethod.value}`);
        }

        console.log(`[Baselinker] Walidacja zakończona: ${isValid ? 'SUKCES' : 'BŁĄD'}`);

        // Pokaż komunikat błędu jeśli potrzeba
        if (!isValid) {
            this.showValidationAlert(errorMessages);
        }

        return isValid;
    }

    async nextStep() {
        console.log(`[Baselinker] Próba przejścia z kroku ${this.currentStep} na ${this.currentStep + 1}`);

        if (this.currentStep < this.totalSteps) {
            // POPRAWKA: Walidacja TYLKO kroku 2
            if (this.currentStep === 2) {
                console.log('[Baselinker] Walidacja kroku 2...');

                if (!this.validateConfigurationForm()) {
                    console.log('[Baselinker] Walidacja nie przeszła - blokowanie przejścia');
                    return;
                }

                console.log('[Baselinker] 🔍 DEBUG przed sprawdzaniem zmian danych klienta:');
                console.log('- originalClientData:', this.originalClientData);
                console.log('- currentClientData:', this.getCurrentClientData());

                // Sprawdź czy dane klienta się zmieniły
                if (this.hasClientDataChanged()) {
                    const shouldUpdate = await this.showClientDataUpdateDialog();
                    if (shouldUpdate) {
                        // NOWE: Faktycznie zapisz dane klienta
                        const currentData = this.getCurrentClientData();
                        const updateResult = await this.updateClientDataInDatabase(currentData);

                        if (updateResult === 'CHANGE_EMAIL') {
                            // Użytkownik wybrał zmianę emaila - zostań na tym kroku
                            this.showAlert('Zmień adres email i spróbuj ponownie', 'info');
                            // Ustaw focus na polu email
                            const emailInput = document.getElementById('client-email');
                            if (emailInput) {
                                emailInput.focus();
                                emailInput.select();
                            }
                            return;
                        } else if (updateResult === true) {
                            this.showAlert('Dane klienta zostały zaktualizowane w bazie danych', 'success');
                            // Zaktualizuj oryginalne dane aby uniknąć ponownej walidacji
                            this.originalClientData = this.cloneClientData(currentData);
                        } else {
                            // Jeśli nie udało się zapisać, zatrzymaj proces
                            this.showAlert('Nie udało się zapisać danych klienta. Spróbuj ponownie.', 'error');
                            return;
                        }
                    } else {
                        this.showAlert('Kontynuujesz z nowymi danymi tylko dla tego zamówienia', 'info');
                    }
                }
            }

            console.log('[Baselinker] Przechodzę do następnego kroku');
            this.currentStep++;
            this.updateStep();
        }
    }

    updateStep() {
        console.log(`[Baselinker] Updating to step ${this.currentStep}`);

        // Aktualizuj progress bar
        document.querySelectorAll('.bl-style-progress-step').forEach((step, index) => {
            step.classList.remove('active', 'completed');
            if (index + 1 < this.currentStep) {
                step.classList.add('completed');
            } else if (index + 1 === this.currentStep) {
                step.classList.add('active');
            }
        });

        // Aktualizuj zawartość kroków
        document.querySelectorAll('.bl-style-step-content').forEach((content, index) => {
            content.classList.remove('active');
            if (index + 1 === this.currentStep) {
                content.classList.add('active');
            }
        });

        // Obsługa przycisków
        const prevBtn = document.getElementById('baselinker-prev-step');
        const nextBtn = document.getElementById('baselinker-next-step');
        const submitBtn = document.getElementById('baselinker-submit-order');

        // PRZYCISK WSTECZ
        if (prevBtn) {
            if (this.currentStep > 1) {
                prevBtn.style.display = 'flex';
                prevBtn.disabled = false;
                prevBtn.style.opacity = '1';
                prevBtn.style.cursor = 'pointer';
                prevBtn.classList.remove('bl-style-btn-disabled');
            } else {
                prevBtn.style.display = 'none';
            }
        }

        // PRZYCISK NASTĘPNY
        if (nextBtn) {
            if (this.currentStep < this.totalSteps) {
                nextBtn.style.display = 'flex';

                if (this.currentStep === 1) {
                    nextBtn.disabled = false;
                    nextBtn.style.opacity = '1';
                    nextBtn.style.cursor = 'pointer';
                    nextBtn.classList.remove('bl-style-btn-disabled');
                }
            } else {
                nextBtn.style.display = 'none';
            }
        }

        // PRZYCISK ZŁÓŻ ZAMÓWIENIE
        if (submitBtn) {
            if (this.currentStep === this.totalSteps) {
                submitBtn.style.display = 'flex';
                submitBtn.disabled = false;
                submitBtn.style.opacity = '1';
                submitBtn.style.cursor = 'pointer';
                submitBtn.classList.remove('bl-style-btn-disabled');
            } else {
                submitBtn.style.display = 'none';
            }
        }

        // 🔧 POPRAWKA: OBSŁUGA SPECJALNA DLA KAŻDEGO KROKU - bez resetowania event listenerów
        if (this.currentStep === 2) {
            // Krok 2: Konfiguracja - TYLKO wyczyść błędy i uruchom walidację
            this.clearValidationErrors();

            // 🔧 POPRAWKA: NIE wywołuj ponownie handleDeliveryMethodChange() - to resetuje wartości
            // this.handleDeliveryMethodChange(); // ❌ USUŃ TO

            setTimeout(() => {
                this.validateConfiguration();
            }, 100);
        }

        if (this.currentStep === 3) {
            // Krok 3: Potwierdzenie
            this.prepareValidation();
        }
    }

    validateConfiguration() {
        // Walidacja TYLKO w kroku 2
        if (this.currentStep !== 2) {
            console.log(`[Baselinker] validateConfiguration: Pomijam walidację - obecnie krok ${this.currentStep}`);
            return true;
        }

        // 🔧 DODAJ DEBUG przed walidacją
        this.debugSelectValues();

        const isValid = this.validateConfigurationForm();
        console.log(`[Baselinker] validateConfiguration wynik dla kroku 2: ${isValid}`);

        // Aktualizuj stan przycisku Next
        const nextBtn = document.getElementById('baselinker-next-step');
        if (nextBtn && this.currentStep === 2) {
            nextBtn.disabled = !isValid;
            if (isValid) {
                nextBtn.classList.remove('bl-style-btn-disabled');
                nextBtn.style.opacity = '1';
                nextBtn.style.cursor = 'pointer';
            } else {
                nextBtn.classList.add('bl-style-btn-disabled');
                nextBtn.style.opacity = '0.6';
                nextBtn.style.cursor = 'not-allowed';
            }
        }

        return isValid;
    }

    async submitOrder() {
        if (this.isSubmitting) return;

        console.log('[Baselinker] Submitting order...');

        // Debug przed wysłaniem
        this.debugShippingCosts();
        this.debugSelectValues(); // Dodaj to

        // Walidacja końcowa
        if (!this.validateConfigurationForm()) {
            console.log('[Baselinker] ❌ Walidacja nie przeszła - przerywam składanie zamówienia');
            return;
        }

        // Pobierz wartości z formularza
        const orderSourceId = document.getElementById('order-source-select').value;
        const orderStatusId = document.getElementById('order-status-select').value;
        const paymentMethod = document.getElementById('payment-method-select').value;
        const deliveryMethod = document.getElementById('delivery-method-input').value;

        // DODATKOWA WALIDACJA PRZED WYSŁANIEM
        console.log('[Baselinker] 🔍 FINALNA WALIDACJA PRZED WYSŁANIEM:');
        console.log(`- order_source_id: "${orderSourceId}" (type: ${typeof orderSourceId})`);
        console.log(`- order_status_id: "${orderStatusId}" (type: ${typeof orderStatusId})`);
        console.log(`- payment_method: "${paymentMethod}" (type: ${typeof paymentMethod})`);
        console.log(`- delivery_method: "${deliveryMethod}" (type: ${typeof deliveryMethod})`);

        // Sprawdź czy wartości nie są puste
        if (!orderSourceId && orderSourceId !== '0') {
            console.log('[Baselinker] ❌ KRYTYCZNY BŁĄD: orderSourceId jest puste!');
            this.showAlert('Błąd: Nie wybrano źródła zamówienia', 'error');
            return;
        }

        if (!orderStatusId) {
            console.log('[Baselinker] ❌ KRYTYCZNY BŁĄD: orderStatusId jest puste!');
            this.showAlert('Błąd: Nie wybrano statusu zamówienia', 'error');
            return;
        }

        if (!paymentMethod) {
            console.log('[Baselinker] ❌ KRYTYCZNY BŁĄD: paymentMethod jest puste!');
            this.showAlert('Błąd: Nie wybrano metody płatności', 'error');
            return;
        }

        // Sprawdź aktualną metodę dostawy
        const isPersonalPickup = deliveryMethod && (
            deliveryMethod.toLowerCase().includes('odbiór') ||
            deliveryMethod.toLowerCase().includes('odbior')
        );

        const currentShippingCost = this.modalData.costs.shipping_brutto;

        console.log(`[Baselinker] 📦 SZCZEGÓŁY ZAMÓWIENIA:`);
        console.log(`- Metoda dostawy: "${deliveryMethod}"`);
        console.log(`- Odbiór osobisty: ${isPersonalPickup}`);
        console.log(`- Oryginalne koszty wysyłki: ${this.originalShippingCost} PLN`);
        console.log(`- Aktualne koszty wysyłki: ${currentShippingCost} PLN`);

        // Potwierdzenie użytkownika z dokładnymi informacjami
        let confirmMessage = `Czy na pewno chcesz złożyć zamówienie w Baselinker dla wyceny ${this.modalData.quote.quote_number}?\n\n`;
        confirmMessage += `📦 Metoda dostawy: ${deliveryMethod}\n`;

        if (isPersonalPickup) {
            confirmMessage += `💰 Koszt wysyłki: 0.00 PLN (odbiór osobisty)\n`;
            if (this.originalShippingCost > 0) {
                confirmMessage += `   (oryginale: ${this.formatCurrency(this.originalShippingCost)} - wyzerowane)\n`;
            }
        } else {
            confirmMessage += `💰 Koszt wysyłki: ${this.formatCurrency(currentShippingCost)}\n`;
        }

        confirmMessage += `\n⚠️ Tej operacji nie można cofnąć.`;

        if (!confirm(confirmMessage)) {
            return;
        }

        this.isSubmitting = true;
        const submitBtn = document.getElementById('baselinker-submit-order');

        if (submitBtn) {
            const btnText = submitBtn.querySelector('.bl-style-btn-text');
            const btnLoading = submitBtn.querySelector('.bl-style-btn-loading');

            submitBtn.disabled = true;
            if (btnText) btnText.style.display = 'none';
            if (btnLoading) btnLoading.style.display = 'flex';
        }

        try {
            // NOWE: Pobierz aktualne dane klienta z formularza
            const currentClientData = this.getCurrentClientData();

            const orderData = {
                order_source_id: parseInt(orderSourceId), // Konwertuj na int
                order_status_id: parseInt(orderStatusId), // Konwertuj na int
                payment_method: paymentMethod,
                delivery_method: deliveryMethod,
                shipping_cost_override: currentShippingCost,
                // NOWE: Dodaj dane klienta do zamówienia
                client_data: currentClientData
            };

            console.log('[Baselinker] 📤 FINALNE dane zamówienia z danymi klienta:', orderData);

            const response = await fetch(`/baselinker/api/quote/${this.modalData.quote.id}/create-order`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(orderData)
            });

            const result = await response.json();
            console.log('[Baselinker] 📥 Odpowiedź serwera:', result);

            if (response.ok && result.success) {
                console.log('[Baselinker] ✅ Zamówienie utworzone pomyślnie:', result);
                this.showSuccessModal(result.order_id, result.quote_number);
                this.closeModal();
            } else {
                console.error('[Baselinker] ❌ Błąd tworzenia zamówienia:', result);
                this.showAlert(`Błąd podczas tworzenia zamówienia: ${result.error}`, 'error');
            }

        } catch (error) {
            console.error('[Baselinker] 💥 Błąd sieci:', error);
            this.showAlert(`Błąd sieci: ${error.message}`, 'error');
        } finally {
            // Przywróć przycisk
            this.isSubmitting = false;
            if (submitBtn) {
                const btnText = submitBtn.querySelector('.bl-style-btn-text');
                const btnLoading = submitBtn.querySelector('.bl-style-btn-loading');

                submitBtn.disabled = false;
                if (btnText) btnText.style.display = 'flex';
                if (btnLoading) btnLoading.style.display = 'none';
            }
        }
    }

    /**
     * Renderuje finalne podsumowanie (KROK 3) z obsługą trybu netto/brutto
     */
    populateFinalSummary() {
        const container = document.getElementById('baselinker-final-summary');
        if (!container) return;

        const quote = this.modalData.quote;
        const client = this.modalData.client;
        const costs = this.modalData.costs;
        const isNetto = this.isNettoMode();

        console.log('[Baselinker] Renderowanie finalnego podsumowania, tryb:', isNetto ? 'NETTO' : 'BRUTTO');

        // DEBUG: Wyświetl szczegóły produktów
        console.log('[Baselinker] Debug modalData.products:', this.modalData.products);
        this.modalData.products.forEach((product, index) => {
            console.log(`[Baselinker] Produkt ${index}:`, {
                name: product.name,
                quantity: product.quantity,
                finishing: product.finishing,
                finishing_quantity: product.finishing ? product.finishing.quantity : null
            });
        });

        // 🆕 NOWE: Oblicz całkowitą ilość produktów
        let totalQuantity = 0;
        this.modalData.products.forEach(product => {
            let quantity = 1;

            if (product.finishing && product.finishing.quantity) {
                quantity = parseInt(product.finishing.quantity);
            } else if (product.quantity) {
                quantity = parseInt(product.quantity);
            }

            if (!isNaN(quantity) && quantity > 0) {
                totalQuantity += quantity;
            }
        });

        console.log('[Baselinker] Obliczona całkowita ilość produktów:', totalQuantity);

        // 🆕 NOWE: Wybierz odpowiednie kwoty w zależności od trybu
        const productsCost = isNetto ? costs.products_netto : costs.products_brutto;
        const finishingCost = isNetto ? costs.finishing_netto : costs.finishing_brutto;
        const shippingCost = isNetto ? costs.shipping_netto : costs.shipping_brutto;
        const totalCost = isNetto ? costs.total_netto : costs.total_brutto;
        const priceLabel = isNetto ? 'netto' : 'brutto';

        container.innerHTML = `
        <h4 class="bl-style-section-subtitle">Podsumowanie zamówienia</h4>
            
        <div class="bl-style-summary-grid">
            <div class="bl-style-summary-item">
                <span class="bl-style-summary-label">Wycena:</span>
                <span class="bl-style-summary-value">${quote.quote_number}</span>
            </div>
                
            <div class="bl-style-summary-item">
                <span class="bl-style-summary-label">Klient:</span>
                <span class="bl-style-summary-value">${client.name}</span>
            </div>
                
            <div class="bl-style-summary-item">
                <span class="bl-style-summary-label">Liczba produktów:</span>
                <span class="bl-style-summary-value">${this.modalData.products.length} poz. (${totalQuantity} szt.)</span>
            </div>
        </div>

        <div class="bl-style-financial-breakdown">
            <div class="bl-style-summary-row">
                <span>Koszt produktów:</span>
                <div class="bl-style-amount">
                    <div class="bl-style-amount-main">${this.formatCurrency(productsCost)}</div>
                    <div class="bl-style-amount-label">${priceLabel}</div>
                </div>
            </div>
                
            <div class="bl-style-summary-row">
                <span>Koszt wykończenia:</span>
                <div class="bl-style-amount">
                    <div class="bl-style-amount-main">${this.formatCurrency(finishingCost)}</div>
                    <div class="bl-style-amount-label">${priceLabel}</div>
                </div>
            </div>
                
            <div class="bl-style-summary-row">
                <span>Koszt wysyłki:</span>
                <div class="bl-style-amount">
                    <div class="bl-style-amount-main">${this.formatCurrency(shippingCost)}</div>
                    <div class="bl-style-amount-label">${priceLabel}</div>
                </div>
            </div>
                
            <div class="bl-style-summary-row bl-style-summary-total">
                <span>Wartość całkowita:</span>
                <div class="bl-style-amount">
                    <div class="bl-style-amount-main">${this.formatCurrency(totalCost)}</div>
                    <div class="bl-style-amount-label">${priceLabel}</div>
                </div>
            </div>
        </div>
    `;
    }

    prepareValidation() {
        const container = document.getElementById('baselinker-config-display');
        if (!container) return;

        // Sprawdź konfigurację
        const orderSource = document.getElementById('order-source-select')?.value;
        const orderStatus = document.getElementById('order-status-select')?.value;
        const paymentMethod = document.getElementById('payment-method-select')?.value;
        const deliveryMethod = document.getElementById('delivery-method-input')?.value;

        // Pobierz aktualne dane klienta z formularza (krok 2)
        const currentClientData = this.getCurrentClientData();

        // Sprawdź czy klient chce fakturę
        const wantInvoice = document.getElementById('want-invoice-checkbox')?.checked || false;

        // Sekcja konfiguracji zamówienia
        let configSection = `
        <div class="bl-style-validation-section">
            <h4>Konfiguracja zamówienia</h4>
            <div class="bl-style-config-row">
                <span class="bl-style-config-label">Źródło:</span>
                <span class="bl-style-config-value">${this.getSelectedOptionText('order-source-select')}</span>
            </div>
            <div class="bl-style-config-row">
                <span class="bl-style-config-label">Status:</span>
                <span class="bl-style-config-value">${this.getSelectedOptionText('order-status-select')}</span>
            </div>
            <div class="bl-style-config-row">
                <span class="bl-style-config-label">Płatność:</span>
                <span class="bl-style-config-value">${this.getSelectedOptionText('payment-method-select')}</span>
            </div>
            <div class="bl-style-config-row">
                <span class="bl-style-config-label">Dostawa:</span>
                <span class="bl-style-config-value">${deliveryMethod || 'Nie wybrano'}</span>
            </div>
        </div>
        `;

        // Sekcja adresu dostawy
        let deliverySection = `
        <div class="bl-style-validation-section">
            <h4>Adres dostawy</h4>
            <div class="bl-style-config-row">
                <span class="bl-style-config-label">Imię:</span>
                <span class="bl-style-config-value">${currentClientData.delivery_name || '-'}</span>
            </div>
            ${currentClientData.delivery_company ? `
            <div class="bl-style-config-row">
                <span class="bl-style-config-label">Firma:</span>
                <span class="bl-style-config-value">${currentClientData.delivery_company}</span>
            </div>
            ` : ''}
            <div class="bl-style-config-row">
                <span class="bl-style-config-label">Adres:</span>
                <span class="bl-style-config-value">${currentClientData.delivery_address || '-'}</span>
            </div>
            <div class="bl-style-config-row">
                <span class="bl-style-config-label">Miasto:</span>
                <span class="bl-style-config-value">${currentClientData.delivery_postcode || ''} ${currentClientData.delivery_city || '-'}</span>
            </div>
            ${currentClientData.delivery_region ? `
            <div class="bl-style-config-row">
                <span class="bl-style-config-label">Województwo:</span>
                <span class="bl-style-config-value">${currentClientData.delivery_region}</span>
            </div>
            ` : ''}
            <div class="bl-style-config-row">
                <span class="bl-style-config-label">Email:</span>
                <span class="bl-style-config-value">${currentClientData.email || '-'}</span>
            </div>
            <div class="bl-style-config-row">
                <span class="bl-style-config-label">Telefon:</span>
                <span class="bl-style-config-value">${currentClientData.phone || '-'}</span>
            </div>
        </div>
        `;

        // Sekcja danych faktury (jeśli zaznaczono)
        let invoiceSection = '';
        if (wantInvoice) {
            invoiceSection = `
            <div class="bl-style-validation-section" style="grid-column: 1 / -1;">
                <h4>Dane do faktury</h4>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                    <div>
                        <div class="bl-style-config-row">
                            <span class="bl-style-config-label">Imię:</span>
                            <span class="bl-style-config-value">${currentClientData.invoice_name || '-'}</span>
                        </div>
                        ${currentClientData.invoice_company ? `
                        <div class="bl-style-config-row">
                            <span class="bl-style-config-label">Firma:</span>
                            <span class="bl-style-config-value">${currentClientData.invoice_company}</span>
                        </div>
                        ` : ''}
                        ${currentClientData.invoice_nip ? `
                        <div class="bl-style-config-row">
                            <span class="bl-style-config-label">NIP:</span>
                            <span class="bl-style-config-value">${currentClientData.invoice_nip}</span>
                        </div>
                        ` : ''}
                    </div>
                    <div>
                        <div class="bl-style-config-row">
                            <span class="bl-style-config-label">Adres:</span>
                            <span class="bl-style-config-value">${currentClientData.invoice_address || '-'}</span>
                        </div>
                        <div class="bl-style-config-row">
                            <span class="bl-style-config-label">Miasto:</span>
                            <span class="bl-style-config-value">${currentClientData.invoice_postcode || ''} ${currentClientData.invoice_city || '-'}</span>
                        </div>
                        ${currentClientData.invoice_region ? `
                        <div class="bl-style-config-row">
                            <span class="bl-style-config-label">Województwo:</span>
                            <span class="bl-style-config-value">${currentClientData.invoice_region}</span>
                        </div>
                        ` : ''}
                    </div>
                </div>
            </div>
            `;
        }

        // Złóż wszystko razem w grid z nagłówkiem
        container.innerHTML = `
        <h3 class="bl-style-section-title" style="margin-bottom: 16px;">
            <span class="bl-style-icon">⚙️</span>
            Wybrana konfiguracja
        </h3>
        <div class="bl-style-validation-grid">
            ${configSection}
            ${deliverySection}
        </div>
        ${invoiceSection}
        `;

        // POPRAWKA: Aktualizuj finalne podsumowanie z aktualnymi kosztami
        this.populateFinalSummary();

        // Sprawdź czy wszystko jest gotowe
        const finalStatus = document.getElementById('final-order-status');
        if (finalStatus) {
            if (orderSource && orderStatus && paymentMethod) {
                finalStatus.className = 'bl-style-status-ready';
                finalStatus.innerHTML = '✓ Gotowe do wysłania';
            } else {
                finalStatus.className = 'bl-style-status-warning';
                finalStatus.innerHTML = '⚠ Wymagana konfiguracja';
            }
        }
    }

    prevStep() {
        console.log(`[Baselinker] Próba powrotu z kroku ${this.currentStep} na ${this.currentStep - 1}`);

        if (this.currentStep > 1) {
            this.currentStep--;
            console.log(`[Baselinker] Powrót do kroku ${this.currentStep}`);
            this.updateStep();
        } else {
            console.log(`[Baselinker] Już jesteśmy w pierwszym kroku`);
        }
    }

    async syncConfig() {
        console.log('[Baselinker] Syncing configuration...');

        try {
            const response = await fetch('/baselinker/api/sync-config');
            const result = await response.json();

            if (result.success) {
                this.showAlert('Konfiguracja zsynchronizowana pomyślnie', 'success');
                // Odśwież dane modala jeśli jest otwarty
                if (this.modalData) {
                    this.openModal(this.modalData.quote.id);
                }
            } else {
                this.showAlert('Błąd synchronizacji konfiguracji', 'error');
            }
        } catch (error) {
            console.error('[Baselinker] Sync error:', error);
            this.showAlert('Błąd połączenia podczas synchronizacji', 'error');
        }
    }

    showModal() {
        const modal = document.getElementById('baselinker-modal');
        if (modal) {
            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';

            // Animacja z nowym systemem klas
            setTimeout(() => {
                modal.classList.add('active');
            }, 10);
        }
    }

    closeModal() {
        const modal = document.getElementById('baselinker-modal');
        if (modal) {
            modal.classList.remove('active');
            document.body.style.overflow = '';

            setTimeout(() => {
                modal.style.display = 'none';
            }, 300);
        }

        // Reset stanu
        this.currentStep = 1;
        this.modalData = null;
        this.originalClientData = null; // NOWE: Reset danych klienta
        this.isSubmitting = false;
    }

    isModalOpen() {
        const modal = document.getElementById('baselinker-modal');
        return modal && modal.style.display !== 'none';
    }

    showLoadingOverlay() {
        let overlay = document.getElementById('baselinker-loading-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'baselinker-loading-overlay';
            overlay.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100vw;
                height: 100vh;
                background: rgba(0, 0, 0, 0.5);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10001;
                color: white;
                font-size: 18px;
            `;
            overlay.innerHTML = '<div>Ładowanie danych...</div>';
            document.body.appendChild(overlay);
        }
        overlay.style.display = 'flex';
    }

    hideLoadingOverlay() {
        const overlay = document.getElementById('baselinker-loading-overlay');
        if (overlay) {
            overlay.style.display = 'none';
        }
    }

    showAlert(message, type = 'info') {
        // Usuń istniejące alerty
        const existingAlerts = document.querySelectorAll('.bl-style-alert');
        existingAlerts.forEach(alert => alert.remove());

        // Utwórz nowy alert
        const alert = document.createElement('div');
        alert.className = `bl-style-alert bl-style-alert-${type}`;

        alert.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                <span>${message.replace(/\n/g, '<br>')}</span>
                <button onclick="this.parentElement.parentElement.remove()" 
                        style="background: none; border: none; color: inherit; cursor: pointer; font-size: 18px; margin-left: 12px;">×</button>
            </div>
        `;

        document.body.appendChild(alert);

        // Auto-remove po 5 sekundach (oprócz błędów)
        if (type !== 'error') {
            setTimeout(() => {
                if (alert.parentElement) {
                    alert.remove();
                }
            }, 5000);
        }
    }

    // NOWA FUNKCJA: Oblicza wagę produktu
    calculateProductWeight(product) {
        // 1) jeśli backend dostarczył weight → użyj go
        if (product.weight != null) {
            return product.weight.toFixed(2);
        }
        // 2) w przeciwnym razie oblicz z volume_m3
        if (product.volume_m3) {
            return (product.volume_m3 * 1000 * 0.7).toFixed(2);
        }
        return '0.00';
    }

    // Utility methods
    translateVariantCode(code) {
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
        return translations[code] || code || 'Nieznany wariant';
    }

    formatCurrency(amount) {
        if (amount == null || isNaN(amount)) return '0.00 PLN';
        return `${parseFloat(amount).toFixed(2)} PLN`;
    }

    getSelectedOptionText(selectId) {
        const select = document.getElementById(selectId);
        if (!select || !select.value) return '';
        const selectedOption = select.options[select.selectedIndex];
        return selectedOption ? selectedOption.textContent : '';
    }

    clearValidationErrors() {
        // Usuń klasy błędów z wszystkich pól
        document.querySelectorAll('.bl-style-form-select.bl-style-error').forEach(field => {
            field.classList.remove('bl-style-error');
        });

        // Usuń komunikaty błędów
        document.querySelectorAll('.bl-style-error-message').forEach(msg => {
            msg.remove();
        });
    }

    markFieldAsError(field, message) {
        if (!field) return;

        field.classList.add('bl-style-error');

        // Dodaj komunikat błędu pod polem
        const errorMsg = document.createElement('div');
        errorMsg.className = 'bl-style-error-message';
        errorMsg.innerHTML = `⚠️ ${message}`;

        // Wstaw po polu
        if (field.parentNode) {
            field.parentNode.appendChild(errorMsg);
        }
    }

    showValidationAlert(messages) {
        const message = `Aby przejść dalej, wypełnij wymagane pola:\n\n• ${messages.join('\n• ')}`;
        this.showAlert(message, 'warning');
    }

    // NOWE UTILITY FUNCTIONS
    getInputValue(inputId) {
        const element = document.getElementById(inputId);
        if (element) {
            return (element.value || '').trim();
        }
        return '';
    }

    // Utility methods
    buildProductName(product) {
        console.log('[Baselinker] buildProductName - dane produktu:', product);

        // ZAWSZE używaj tłumaczenia na podstawie variant_code, niezależnie od tego co przysłał backend
        if (!product.variant_code) {
            console.warn('[Baselinker] Brak variant_code w produkcie:', product);
            return product.name || 'Nieznany produkt';
        }

        // Tłumacz kod wariantu na pełną nazwę
        const baseName = this.translateVariantCode(product.variant_code);

        // Formatuj wymiary - upewnij się że mają odstęp przed "cm"
        let dimensions = product.dimensions || '';
        if (dimensions && !dimensions.includes(' cm')) {
            dimensions = `${dimensions} cm`;
        }

        // Formatuj wykończenie na podstawie obiektu finishing
        let finishingText = ' surowa'; // Domyślnie surowa

        if (product.finishing && product.finishing.type && product.finishing.type !== '' && product.finishing.type !== 'Surowe') {
            let finishingParts = [product.finishing.type.toLowerCase()];

            // Dodaj kolor jeśli istnieje i nie jest "Brak"
            if (product.finishing.color && product.finishing.color !== '' && product.finishing.color !== null) {
                finishingParts.push(product.finishing.color);
            }

            finishingText = ` ${finishingParts.join(' ')}`;
        }

        // Składamy całość: "Klejonka [gatunek] [technologia] [klasa] [wymiary] cm [wykończenie]"
        const result = `${baseName} ${dimensions}${finishingText}`.trim();
        console.log('[Baselinker] buildProductName - wynik:', result);

        return result;
    }

    parseVariantCode(code) {
        const translations = {
            'dab': 'dęb',
            'jes': 'jesion',
            'buk': 'buk'
        };

        const techTranslations = {
            'lity': 'lita',        // POPRAWKA: lity -> lita (rodzaj żeński dla klejonki)
            'micro': 'mikrowczep'
        };

        const classTranslations = {
            'ab': 'A/B',
            'bb': 'B/B'
        };

        if (!code) return { species: 'nieznany', technology: '', woodClass: '' };

        const parts = code.toLowerCase().split('-');
        const species = translations[parts[0]] || parts[0];
        const technology = techTranslations[parts[1]] || parts[1];
        const woodClass = classTranslations[parts[2]] || parts[2];

        console.log(`[Baselinker] parseVariantCode("${code}"):`, { species, technology, woodClass });

        return { species, technology, woodClass };
    }

    getFinishingDisplay(finishing) {
        console.log('[Baselinker] getFinishingDisplay - dane wykończenia:', finishing);

        // Sprawdź typ danych i konwertuj na string
        if (!finishing || finishing === null || finishing === undefined) {
            return 'surowa';
        }

        // Konwertuj na string i sprawdź czy pusty
        const finishingStr = String(finishing).trim();

        if (finishingStr === 'Brak' || finishingStr === '' || finishingStr === 'brak') {
            return 'surowa';
        }

        // Sprawdź czy to liczba (może być ID wykończenia)
        if (!isNaN(finishing) && finishing !== '') {
            // Jeśli to liczba, prawdopodobnie to ID wykończenia - zwróć surowa jako fallback
            console.warn('[Baselinker] getFinishingDisplay: otrzymano ID wykończenia zamiast nazwy:', finishing);
            return 'surowa';
        }

        // Mapowanie nazw wykończeń na standardowe formy (żeński rodzaj)
        const finishingMapping = {
            'Lakier': 'lakierowana',
            'lakier': 'lakierowana',
            'Lakierowane': 'lakierowana',
            'lakierowane': 'lakierowana',
            'Olejowane': 'olejowana',
            'olejowane': 'olejowana',
            'Olej': 'olejowana',
            'olej': 'olejowana',
            'Surowe': 'surowa',
            'surowe': 'surowa',
            'Surowa': 'surowa',
            'surowa': 'surowa'
        };

        const result = finishingMapping[finishingStr] || finishingStr.toLowerCase();
        console.log('[Baselinker] getFinishingDisplay - wynik:', result);

        return result;
    }

    setInputValue(inputId, value) {
        const element = document.getElementById(inputId);
        if (!element) {
            console.log(`[Baselinker] ⚠️ setInputValue: element ${inputId} nie znaleziony`);
            return;
        }

        // Sprawdź czy to select
        if (element.tagName.toLowerCase() === 'select') {
            console.log(`[Baselinker] setInputValue: ${inputId} jest SELECT-em, używam setSelectValue`);
            this.setSelectValue(inputId, value || '');
        } else {
            // Dla input-ów normalne ustawienie
            element.value = value || '';
            console.log(`[Baselinker] setInputValue: ustawiono ${inputId} = "${element.value}"`);
        }
    }

    showSuccessModal(orderId, quoteNumber) {
        // Usuń istniejący modal sukcesu jeśli jest
        const existingModal = document.getElementById('baselinker-success-modal');
        if (existingModal) {
            existingModal.remove();
        }

        // Utwórz nowy modal sukcesu
        const modal = document.createElement('div');
        modal.id = 'baselinker-success-modal';
        modal.className = 'bl-style-modal-overlay';
        modal.innerHTML = `
            <div class="bl-style-modal-box" style="max-width: 600px;">
                <div class="bl-style-modal-header" style="background: linear-gradient(135deg, #4284F3 0%, #1651B4 100%);">
                    <h2 class="bl-style-modal-title">
                        <span class="bl-style-icon">✅</span>
                        Zamówienie zostało złożone pomyślnie!
                    </h2>
                    <button class="bl-style-modal-close" id="success-modal-close">&times;</button>
                </div>

                <div class="bl-style-modal-content" style="text-align: center; padding: 40px 24px;">
                    <div class="success-icon" style="margin-bottom: 24px;">
                        <div style="width: 80px; height: 80px; background: linear-gradient(135deg, #4284F3 0%, #1651B4 100%); border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto; box-shadow: 0 8px 32px rgba(66, 132, 243, 0.3);">
                            <span style="color: white; font-size: 36px; font-weight: bold;">✓</span>
                        </div>
                    </div>

                    <div class="order-info" style="margin-bottom: 32px;">
                        <h3 style="color: #1F2020; margin-bottom: 8px; font-size: 18px;">Numer zamówienia w Baselinker:</h3>
                        <div class="order-number" style="font-size: 32px; font-weight: bold; color: #4284F3; margin-bottom: 16px;">
                            #${orderId}
                        </div>
                        <p style="color: #666; font-size: 14px; line-height: 1.5;">
                            Zamówienie dla wyceny <strong>${quoteNumber}</strong> zostało pomyślnie utworzone w systemie Baselinker.
                        </p>
                    </div>

                    <div class="success-actions" style="display: flex; gap: 16px; justify-content: center; flex-wrap: wrap;">
                        <button id="view-order-baselinker" class="bl-style-btn bl-style-btn-primary" style="min-width: 200px;">
                            <span class="bl-style-icon">🔗</span>
                            Przejdź do Baselinker
                        </button>
                        <button id="success-modal-close-btn" class="bl-style-btn bl-style-btn-secondary" style="min-width: 120px;">
                            Zamknij
                        </button>
                    </div>

                    <div class="success-notes" style="margin-top: 32px; padding: 16px; background: #E3F2FD; border-radius: 8px; border-left: 4px solid #2196F3;">
                        <p style="color: #1565c0; font-size: 13px; margin: 0; line-height: 1.4;">
                            <strong>ℹ️ Informacja:</strong> Status wyceny został automatycznie zmieniony na "Złożone". 
                            Możesz teraz zarządzać zamówieniem w panelu Baselinker.
                        </p>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        // Event listeners
        const closeButtons = modal.querySelectorAll('#success-modal-close, #success-modal-close-btn');
        closeButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                modal.style.display = 'none';
                modal.remove();
            });
        });

        const baselinkerBtn = modal.querySelector('#view-order-baselinker');
        if (baselinkerBtn) {
            baselinkerBtn.addEventListener('click', () => {
                const baselinkerUrl = `https://panel-f.baselinker.com/orders.php#order:${orderId}`;
                window.open(baselinkerUrl, '_blank');
                modal.style.display = 'none';
                modal.remove();
            });
        }

        // Zamykanie przez ESC
        const handleEsc = (e) => {
            if (e.key === 'Escape') {
                modal.style.display = 'none';
                modal.remove();
                document.removeEventListener('keydown', handleEsc);
            }
        };
        document.addEventListener('keydown', handleEsc);

        // Pokaż modal
        modal.style.display = 'flex';
        setTimeout(() => modal.classList.add('active'), 10);

        // 🆕 NOWE: Automatycznie odśwież modal szczegółów wyceny po 1 sekundzie
        console.log('[Baselinker] Planowanie automatycznego odświeżenia modalu wyceny...');
        setTimeout(() => {
            console.log('[Baselinker] Odświeżam modal szczegółów wyceny');
            if (typeof window.refreshQuoteDetailsModal === 'function') {
                console.log('[Baselinker] ✅ Wywołuję refreshQuoteDetailsModal()');
                window.refreshQuoteDetailsModal();
            } else {
                console.warn('[Baselinker] ⚠️ Funkcja refreshQuoteDetailsModal() niedostępna');
            }
        }, 1000);
    }

    updateAllSummariesWithNewShipping() {
        console.log('[Baselinker] Aktualizuję wszystkie podsumowania z nowymi kosztami wysyłki');

        // Aktualizuj krok 1 - podsumowanie finansowe
        this.populateFinancialSummary();

        // Aktualizuj krok 3 - finalne podsumowanie (jeśli jesteśmy na tym kroku)
        if (this.currentStep === 3) {
            this.populateFinalSummary();
            this.prepareValidation();
        }

        console.log('[Baselinker] Aktualne koszty po zmianie:', this.modalData.costs);
    }

    // USUNIĘTA FUNKCJA - nie jest już potrzebna, bo pole metody dostawy to teraz input tekstowy, a nie select
    // handleDeliveryMethodChange() { ... }

    updateShippingCosts(newShippingCost) {
        if (!this.modalData) {
            console.warn('[Baselinker] Brak modalData - nie można aktualizować kosztów wysyłki');
            return;
        }

        // Zabezpieczenie przed NaN
        newShippingCost = parseFloat(newShippingCost) || 0;

        console.log(`[Baselinker] 📊 Aktualizacja kosztów wysyłki: ${this.modalData.costs.shipping_brutto} → ${newShippingCost}`);

        // Zaktualizuj dane w modalData
        const VAT_RATE = 0.23;
        const oldShippingBrutto = this.modalData.costs.shipping_brutto;
        const oldTotalBrutto = this.modalData.costs.total_brutto;

        this.modalData.costs.shipping_brutto = newShippingCost;
        this.modalData.costs.shipping_netto = newShippingCost / (1 + VAT_RATE);

        // Przelicz total - odejmij stare koszty wysyłki i dodaj nowe
        this.modalData.costs.total_brutto = oldTotalBrutto - oldShippingBrutto + newShippingCost;
        this.modalData.costs.total_netto =
            this.modalData.costs.products_netto +
            this.modalData.costs.finishing_netto +
            this.modalData.costs.shipping_netto;

        console.log(`[Baselinker] ✅ Zaktualizowane koszty:`, {
            shipping_brutto: this.modalData.costs.shipping_brutto,
            shipping_netto: this.modalData.costs.shipping_netto.toFixed(2),
            total_brutto: this.modalData.costs.total_brutto,
            total_netto: this.modalData.costs.total_netto.toFixed(2)
        });
    }

    updateFinancialSummaryWithNewShipping() {
        // Aktualizuj krok 1 - podsumowanie finansowe
        this.populateFinancialSummary();

        // Aktualizuj krok 3 - finalne podsumowanie
        if (this.currentStep === 3) {
            this.populateFinalSummary();
        }
    }

    debugFormState() {
        const orderSource = document.getElementById('order-source-select');
        const orderStatus = document.getElementById('order-status-select');
        const paymentMethod = document.getElementById('payment-method-select');
        const deliveryMethod = document.getElementById('delivery-method-input');

        console.log('[Baselinker] DEBUG - Stan formularza:');
        console.log(`- Źródło: value="${orderSource?.value}", selectedIndex=${orderSource?.selectedIndex}`);
        console.log(`- Status: value="${orderStatus?.value}", selectedIndex=${orderStatus?.selectedIndex}`);
        console.log(`- Płatność: value="${paymentMethod?.value}", selectedIndex=${paymentMethod?.selectedIndex}`);
        console.log(`- Dostawa: value="${deliveryMethod?.value}"`);
    }

    debugShippingCosts() {
        console.log('[Baselinker] 🔍 DEBUG - Koszty wysyłki:');
        console.log(`- Oryginalne koszty: ${this.originalShippingCost}`);
        console.log(`- Aktualne koszty w modalData: ${this.modalData?.costs?.shipping_brutto}`);

        const deliveryMethod = document.getElementById('delivery-method-input')?.value;
        console.log(`- Wybrana metoda dostawy: "${deliveryMethod}"`);

        const isPersonalPickup = deliveryMethod && (
            deliveryMethod.toLowerCase().includes('odbiór') ||
            deliveryMethod.toLowerCase().includes('odbior')
        );
        console.log(`- Czy odbiór osobisty: ${isPersonalPickup}`);
    }

    debugClientData() {
        console.log('[Baselinker] 🔍 DEBUG - Dane klienta:');

        const originalData = this.originalClientData;
        const currentData = this.getCurrentClientData();

        console.log('Oryginalne dane:', originalData);
        console.log('Aktualne dane:', currentData);

        // Sprawdź które pola się zmieniły
        const changedFields = [];
        for (const key in originalData) {
            if (originalData[key] !== currentData[key]) {
                changedFields.push({
                    field: key,
                    old: originalData[key],
                    new: currentData[key]
                });
            }
        }

        if (changedFields.length > 0) {
            console.log('Zmienione pola:', changedFields);
        } else {
            console.log('Brak zmian w danych klienta');
        }

        return changedFields;
    }

    debugSelectValues() {
        const selectIds = ['order-source-select', 'order-status-select', 'payment-method-select'];

        console.log('[Baselinker] 🔍 DEBUG - Aktualne wartości select-ów:');
        selectIds.forEach(selectId => {
            const select = document.getElementById(selectId);
            if (select) {
                console.log(`- ${selectId}: value="${select.value}", selectedIndex=${select.selectedIndex}, options=${select.options.length}`);

                // Sprawdź czy wartość istnieje w opcjach
                const option = Array.from(select.options).find(opt => opt.value === select.value);
                if (!option && select.value) {
                    console.warn(`⚠️ Wartość "${select.value}" nie istnieje w opcjach ${selectId}!`);
                }
            } else {
                console.log(`- ${selectId}: ELEMENT NIE ZNALEZIONY`);
            }
        });

        // Dodaj debug dla delivery method input
        const deliveryInput = document.getElementById('delivery-method-input');
        if (deliveryInput) {
            console.log(`- delivery-method-input: value="${deliveryInput.value}"`);
        } else {
            console.log(`- delivery-method-input: ELEMENT NIE ZNALEZIONY`);
        }
    }
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ========== FUNKCJE KOPIOWANIA I GUS ========== //

    /**
     * Kopiuje dane z faktury do adresu dostawy
     */
    copyInvoiceToDelivery() {
        console.log('[Baselinker] Kopiowanie danych z faktury do dostawy');

        const copyMapping = {
            'invoice-fullname': 'delivery-fullname',
            'invoice-company': 'delivery-company',
            'invoice-address': 'delivery-address',
            'invoice-postcode': 'delivery-postcode',
            'invoice-city': 'delivery-city',
            'invoice-region': 'delivery-region'
        };

        let copiedCount = 0;
        const copiedFields = [];

        for (const [sourceId, targetId] of Object.entries(copyMapping)) {
            const sourceValue = this.getInputValue(sourceId);
            if (sourceValue) {
                this.setInputValue(targetId, sourceValue);
                copiedFields.push(targetId);
                copiedCount++;
            }
        }

        // Wizualny feedback na przycisku
        const btn = document.getElementById('bl-copy-invoice-to-delivery');
        if (btn) {
            const originalHTML = btn.innerHTML;
            const originalClass = btn.className;

            btn.className = 'bl-copy-invoice-btn success';
            btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
            </svg>
            Skopiowano!
        `;

            setTimeout(() => {
                btn.className = originalClass;
                btn.innerHTML = originalHTML;
            }, 2000);
        }

        // Animacja skopiowanych pól
        copiedFields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field && field.value) {
                field.classList.add('bl-copied-field');
                setTimeout(() => {
                    field.classList.remove('bl-copied-field');
                }, 1500);
            }
        });

        if (copiedCount > 0) {
            this.showAlert(`Skopiowano ${copiedCount} pól z faktury do adresu dostawy`, 'success');
        } else {
            this.showAlert('Brak danych do skopiowania - wypełnij dane faktury', 'warning');
        }

        console.log(`[Baselinker] Skopiowano ${copiedCount} pól`);
    }

    /**
     * Kopiuje dane z adresu dostawy do faktury
     */
    copyDeliveryToInvoice() {
        console.log('[Baselinker] Kopiowanie danych z dostawy do faktury');

        const copyMapping = {
            'delivery-fullname': 'invoice-fullname',
            'delivery-company': 'invoice-company',
            'delivery-address': 'invoice-address',
            'delivery-postcode': 'invoice-postcode',
            'delivery-city': 'invoice-city',
            'delivery-region': 'invoice-region'
        };

        let copiedCount = 0;
        const copiedFields = [];

        for (const [sourceId, targetId] of Object.entries(copyMapping)) {
            const sourceValue = this.getInputValue(sourceId);
            if (sourceValue) {
                this.setInputValue(targetId, sourceValue);
                copiedFields.push(targetId);
                copiedCount++;
            }
        }

        // Wizualny feedback na przycisku
        const btn = document.getElementById('bl-copy-delivery-to-invoice');
        if (btn) {
            const originalHTML = btn.innerHTML;
            const originalClass = btn.className;

            btn.className = 'bl-copy-delivery-btn success';
            btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
            </svg>
            Skopiowano!
        `;

            setTimeout(() => {
                btn.className = originalClass;
                btn.innerHTML = originalHTML;
            }, 2000);
        }

        // Animacja skopiowanych pól
        copiedFields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field && field.value) {
                field.classList.add('bl-copied-field');
                setTimeout(() => {
                    field.classList.remove('bl-copied-field');
                }, 1500);
            }
        });

        if (copiedCount > 0) {
            this.showAlert(`Skopiowano ${copiedCount} pól z dostawy do faktury`, 'success');
        } else {
            this.showAlert('Brak danych do skopiowania - wypełnij adres dostawy', 'warning');
        }

        console.log(`[Baselinker] Skopiowano ${copiedCount} pól`);
    }

    /**
     * Obsługa pobierania danych z GUS
     */
    async handleGusLookup() {
        console.log('[Baselinker] Pobieranie danych z GUS');

        const nipInput = document.getElementById('invoice-nip');
        const gusBtn = document.getElementById('bl-gus-lookup-btn');
        const errorElement = document.getElementById('error-invoice-nip');

        if (!nipInput || !gusBtn) {
            console.error('[Baselinker] Nie znaleziono elementów NIP lub przycisku GUS');
            return;
        }

        const nip = nipInput.value.trim().replace(/\s+/g, '');

        // Wyczyść poprzednie błędy
        if (errorElement) {
            errorElement.style.display = 'none';
            errorElement.textContent = '';
        }
        nipInput.classList.remove('bl-style-error');

        // Walidacja NIP
        if (!nip) {
            this.showGusError(nipInput, errorElement, 'Podaj NIP aby skorzystać z GUS');
            return;
        }

        if (!this.isValidNIP(nip)) {
            this.showGusError(nipInput, errorElement, 'Podaj prawidłowy NIP (10 cyfr)');
            return;
        }

        // Animacja loading
        gusBtn.classList.add('loading');
        gusBtn.disabled = true;
        const originalText = gusBtn.textContent;
        gusBtn.textContent = 'Ładowanie...';

        try {
            const response = await fetch(`/clients/api/gus_lookup?nip=${nip}`);
            const data = await response.json();

            if (response.ok && data.name) {
                console.log('[Baselinker] Dane z GUS otrzymane:', data);

                // Parsuj adres z GUS
                const parsedAddress = this.parseGusAddress(data.address || '');

                // Wypełnij pola faktury
                this.setInputValue('invoice-fullname', data.name || '');
                this.setInputValue('invoice-company', data.company || data.name || '');
                this.setInputValue('invoice-address', parsedAddress.street || '');
                this.setInputValue('invoice-postcode', parsedAddress.zipCode || data.zip || '');
                this.setInputValue('invoice-city', parsedAddress.city || data.city || '');

                // POPRAWKA: Województwo - używaj setInputValue która wykrywa że to select
                if (data.voivodeship) {
                    console.log(`[Baselinker] 🔍 Ustawiam województwo: "${data.voivodeship}"`);
                    this.setInputValue('invoice-region', data.voivodeship);

                    // DODATKOWA WERYFIKACJA
                    setTimeout(() => {
                        const regionSelect = document.getElementById('invoice-region');
                        if (regionSelect) {
                            console.log(`[Baselinker] ✅ Weryfikacja województwa: wartość = "${regionSelect.value}"`);
                            if (!regionSelect.value || regionSelect.value === '') {
                                console.error(`[Baselinker] ❌ Województwo nie zostało ustawione! Próba ponowna...`);
                                // Próba bezpośredniego ustawienia
                                const options = Array.from(regionSelect.options);
                                const matchingOption = options.find(opt =>
                                    opt.value.toLowerCase() === data.voivodeship.toLowerCase()
                                );
                                if (matchingOption) {
                                    regionSelect.value = matchingOption.value;
                                    console.log(`[Baselinker] ✅ Województwo ustawione bezpośrednio: ${regionSelect.value}`);
                                }
                            }
                        }
                    }, 100);
                } else {
                    console.log('[Baselinker] ⚠️ Brak województwa w odpowiedzi GUS');
                }

                // Feedback sukcesu
                gusBtn.textContent = 'Pobrano dane ✓';
                gusBtn.style.background = '#28a745';

                setTimeout(() => {
                    gusBtn.textContent = originalText;
                    gusBtn.style.background = '';
                }, 2000);

                // Informacja o źródle danych (GUS lub CEIDG)
                if (data._source === 'CEIDG') {
                    this.showAlert('✓ Dane pobrane z rejestru CEIDG (jednoosobowa działalność)', 'success');
                } else {
                    this.showAlert('Dane z GUS zostały pobrane pomyślnie', 'success');
                }

                // Animacja wypełnionych pól (włącznie z województwem)
                const filledFields = ['invoice-fullname', 'invoice-company', 'invoice-address', 'invoice-postcode', 'invoice-city', 'invoice-region'];
                filledFields.forEach(fieldId => {
                    const field = document.getElementById(fieldId);
                    if (field && field.value) {
                        field.classList.add('bl-copied-field');
                        setTimeout(() => {
                            field.classList.remove('bl-copied-field');
                        }, 1500);
                    }
                });

            } else {
                this.showGusError(nipInput, errorElement, data.error || 'Nie znaleziono danych dla podanego NIP');
                gusBtn.textContent = 'Błąd ❌';
                gusBtn.style.background = '#dc3545';

                setTimeout(() => {
                    gusBtn.textContent = originalText;
                    gusBtn.style.background = '';
                }, 2000);
            }

        } catch (error) {
            console.error('[Baselinker] Błąd GUS:', error);
            this.showGusError(nipInput, errorElement, 'Błąd połączenia z GUS');

            gusBtn.textContent = 'Błąd połączenia ❌';
            gusBtn.style.background = '#dc3545';

            setTimeout(() => {
                gusBtn.textContent = originalText;
                gusBtn.style.background = '';
            }, 2000);

        } finally {
            gusBtn.classList.remove('loading');
            gusBtn.disabled = false;
        }
    }

    /**
     * Pokazuje błąd walidacji GUS
     */
    showGusError(nipInput, errorElement, message) {
        if (nipInput) {
            nipInput.classList.add('bl-style-error');
        }

        if (errorElement) {
            errorElement.textContent = message;
            errorElement.style.display = 'block';
        }

        this.showAlert(message, 'error');
    }

    /**
     * Walidacja numeru NIP
     */
    isValidNIP(nip) {
        // NIP musi mieć dokładnie 10 cyfr
        return /^\d{10}$/.test(nip);
    }

    /**
     * Parsuje adres z GUS na komponenty
     */
    parseGusAddress(fullAddress) {
        console.log('[Baselinker] Parsowanie adresu GUS:', fullAddress);

        if (!fullAddress || typeof fullAddress !== 'string') {
            return { street: '', zipCode: '', city: '' };
        }

        const cleanAddress = fullAddress.trim().replace(/\s+/g, ' ');
        const zipCodePattern = /\b\d{2}-\d{3}\b/;
        const zipCodeMatch = cleanAddress.match(zipCodePattern);

        let street = '';
        let zipCode = '';
        let city = '';

        if (zipCodeMatch) {
            zipCode = zipCodeMatch[0];
            const zipIndex = cleanAddress.indexOf(zipCode);

            // Wszystko przed kodem pocztowym to ulica
            street = cleanAddress.substring(0, zipIndex).trim();
            street = street.replace(/[,;]+$/, '').trim();

            // Wszystko po kodzie pocztowym to miasto
            city = cleanAddress.substring(zipIndex + zipCode.length).trim();
            city = city.replace(/^[,;]+/, '').trim();

        } else {
            // Jeśli nie ma kodu pocztowego, spróbuj innych metod
            const parts = cleanAddress.split(/[,;]/);

            if (parts.length >= 2) {
                street = parts[0].trim();
                const lastPart = parts[parts.length - 1].trim();

                const lastPartZipMatch = lastPart.match(zipCodePattern);
                if (lastPartZipMatch) {
                    zipCode = lastPartZipMatch[0];
                    city = lastPart.replace(zipCodePattern, '').trim();
                } else {
                    city = lastPart;
                }
            } else {
                street = cleanAddress;
            }
        }

        console.log('[Baselinker] Sparsowany adres:', { street, zipCode, city });

        return { street, zipCode, city };
    }
}

// Inicjalizacja po załadowaniu DOM
document.addEventListener('DOMContentLoaded', () => {
    console.log('[Baselinker] DOM loaded, initializing...');
    window.baselinkerModal = new BaselinkerModal();
});

// Export dla użycia w innych modułach
if (typeof module !== 'undefined' && module.exports) {
    module.exports = BaselinkerModal;
}