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

    setupModalEventListeners() {
        // Zamykanie modala
        document.addEventListener('click', (e) => {
            if (e.target.closest('#baselinker-close-modal') ||
                e.target.closest('#baselinker-close-modal-footer')) {
                this.closeModal();
            }

            // Zamykanie przez kliknięcie tła
            if (e.target.classList.contains('bl-style-modal-overlay')) {
                this.closeModal();
            }
        });

        // Nawigacja między krokami
        document.addEventListener('click', (e) => {
            if (e.target.closest('#baselinker-prev-step')) {
                this.prevStep();
            }

            if (e.target.closest('#baselinker-next-step')) {
                this.nextStep();
            }

            if (e.target.closest('#baselinker-submit-order')) {
                this.submitOrder();
            }

            // Sync config button
            if (e.target.closest('#baselinker-sync-config')) {
                this.syncConfig();
            }
        });

        // Klawisz ESC
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
            
            const response = await fetch(`/clients/${clientId}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    client_name: clientData.delivery_name,
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
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
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
        if (select && value) {
            // Znajdź opcję o odpowiedniej wartości
            const option = Array.from(select.options).find(opt =>
                opt.value.toLowerCase() === value.toLowerCase()
            );

            if (option) {
                select.value = option.value;
                console.log(`[Baselinker] ✅ Ustawiono ${selectId}: ${option.value}`);
            } else {
                console.log(`[Baselinker] ⚠️ Nie znaleziono opcji "${value}" w ${selectId}`);
                // Jeśli nie ma dokładnego dopasowania, spróbuj częściowego
                const partialMatch = Array.from(select.options).find(opt =>
                    opt.value.toLowerCase().includes(value.toLowerCase()) ||
                    value.toLowerCase().includes(opt.value.toLowerCase())
                );

                if (partialMatch) {
                    select.value = partialMatch.value;
                    console.log(`[Baselinker] ✅ Częściowe dopasowanie ${selectId}: ${partialMatch.value}`);
                }
            }
        }
    }

    // NOWA FUNKCJA: Porównuje dane klienta
    hasClientDataChanged() {
        if (!this.originalClientData) return false;

        const currentData = this.getCurrentClientData();
        
        // Porównaj wszystkie pola
        for (const key in this.originalClientData) {
            if (this.originalClientData[key] !== currentData[key]) {
                console.log(`[Baselinker] Zmiana w polu ${key}: "${this.originalClientData[key]}" -> "${currentData[key]}"`);
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

        // Dodaj notatkę jeśli istnieje
        if (quote.notes && quote.notes.trim()) {
            summaryHTML += `
                <div class="bl-style-summary-row bl-style-summary-note">
                    <span>Notatka:</span>
                    <div class="bl-style-note-text">${this.escapeHtml(quote.notes)}</div>
                </div>
            `;
        }

        container.innerHTML = summaryHTML;
    }

    populateProductsList() {
        const container = document.getElementById('baselinker-products-list');
        if (!container) return;

        const products = this.modalData.products;

        if (!products || products.length === 0) {
            container.innerHTML = '<p>Brak produktów do wyświetlenia</p>';
            return;
        }

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
                            <div class="bl-style-amount-brutto">${this.formatCurrency(product.unit_price_brutto)}</div>
                            <div class="bl-style-amount-netto">${this.formatCurrency(product.unit_price_netto)} netto</div>
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

    populateFinancialSummary() {
        const container = document.getElementById('baselinker-financial-summary');
        if (!container) return;

        const costs = this.modalData.costs;

        container.innerHTML = `
            <div class="bl-style-summary-row">
                <span>Koszt produktów:</span>
                <div class="bl-style-amount">
                    <div class="bl-style-amount-brutto">${this.formatCurrency(costs.products_brutto)}</div>
                    <div class="bl-style-amount-netto">${this.formatCurrency(costs.products_netto)} netto</div>
                </div>
            </div>
            <div class="bl-style-summary-row">
                <span>Koszt wykończenia:</span>
                <div class="bl-style-amount">
                    <div class="bl-style-amount-brutto">${this.formatCurrency(costs.finishing_brutto)}</div>
                    <div class="bl-style-amount-netto">${this.formatCurrency(costs.finishing_netto)} netto</div>
                </div>
            </div>
            <div class="bl-style-summary-row">
                <span>Koszt wysyłki:</span>
                <div class="bl-style-amount">
                    <div class="bl-style-amount-brutto">${this.formatCurrency(costs.shipping_brutto)}</div>
                    <div class="bl-style-amount-netto">${this.formatCurrency(costs.shipping_netto)} netto</div>
                </div>
            </div>
            <div class="bl-style-summary-row">
                <span>Wartość całkowita:</span>
                <div class="bl-style-amount">
                    <div class="bl-style-amount-brutto">${this.formatCurrency(costs.total_brutto)}</div>
                    <div class="bl-style-amount-netto">${this.formatCurrency(costs.total_netto)} netto</div>
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

        // 4. METODY DOSTAWY - POPRAWIONA LOGIKA Z ZABEZPIECZENIAMI
        const deliveryMethodSelect = document.getElementById('delivery-method-select');
        if (deliveryMethodSelect) {
            deliveryMethodSelect.innerHTML = '<option value="">Wybierz metodę...</option>';

            // 🔧 POPRAWKA 1: Zabezpieczenie przed undefined delivery_methods
            const deliveryMethods = config.delivery_methods || [];
            console.log('[Baselinker] Dostępne metody dostawy:', deliveryMethods);

            if (deliveryMethods.length === 0) {
                console.warn('[Baselinker] ⚠️ Brak metod dostawy w konfiguracji - używam domyślnych');
                // Fallback na wypadek problemów z backendem
                deliveryMethods.push('Kurier', 'Odbiór osobisty');
            }

            let courierMethodSet = false;

            // 🔧 POPRAWKA 2: Użycie prawidłowej ścieżki do nazwy kuriera
            const courierFromQuote = this.modalData.quote?.courier_name; // BYŁO: this.modalData.courier
            console.log(`[Baselinker] Kurier z wyceny: "${courierFromQuote}"`);

            deliveryMethods.forEach(method => {
                const option = document.createElement('option');
                option.value = method;
                option.textContent = method;

                // Wybierz metodę kuriera z wyceny jako domyślną (dopasowanie częściowe)
                if (courierFromQuote && method.toLowerCase().includes(courierFromQuote.toLowerCase())) {
                    option.selected = true;
                    courierMethodSet = true;
                    console.log(`[Baselinker] ✅ Ustawiono metodę dostawy z wyceny: ${method} (dopasowana do: ${courierFromQuote})`);
                }

                deliveryMethodSelect.appendChild(option);
            });

            // Ustaw wartość select programowo
            if (courierMethodSet && courierFromQuote) {
                // Znajdź metodę która najlepiej pasuje do kuriera z wyceny
                const matchingMethod = deliveryMethods.find(method =>
                    method.toLowerCase().includes(courierFromQuote.toLowerCase())
                );
                if (matchingMethod) {
                    deliveryMethodSelect.value = matchingMethod;
                    console.log(`[Baselinker] ✅ Programowo ustawiono metodę dostawy: ${matchingMethod}`);
                }
            } else if (deliveryMethods.length > 0) {
                deliveryMethodSelect.value = deliveryMethods[0];
                console.log(`[Baselinker] ✅ Auto-wybrano pierwszą metodę dostawy: ${deliveryMethods[0]}`);
            }
        }

        // 5. SETUP EVENT LISTENERS - POPRAWIONY
        this.setupConfigurationEventListeners();

        // 6. OPÓŹNIONA WALIDACJA I SETUP
        setTimeout(() => {
            // Debug wartości
            console.log('[Baselinker] 🔍 DEBUG po ustawieniu domyślnych wartości:');
            this.debugSelectValues();

            // 🔧 POPRAWKA: Wywołaj handleDeliveryMethodChange() TYLKO RAZ na początku
            if (!this.deliveryMethodListenerAttached) {
                this.handleDeliveryMethodChange();
                this.deliveryMethodListenerAttached = true;
            }

            this.debugShippingCosts();
        }, 100);
    }

    populateClientPreview() {
        // Nowa funkcja obsługująca formularze klienta
        this.populateClientData();
    }

    // 5. NOWA METODA - POPRAWIONA OBSŁUGA EVENT LISTENERÓW KONFIGURACJI
    setupConfigurationEventListeners() {
        const selectIds = ['order-source-select', 'order-status-select', 'payment-method-select', 'delivery-method-select'];

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

                        // Specjalna obsługa dla metody dostawy
                        if (selectId === 'delivery-method-select') {
                            this.handleDeliveryMethodChangeEvent(e);
                        }

                        // Sprawdź walidację
                        this.validateConfiguration();
                    });
                }
            }
        });

        console.log('[Baselinker] ✅ Event listenery skonfigurowane z zachowaniem wartości');
    }

    // NOWA FUNKCJA dla obsługi zmiany metody dostawy z event listenera
    handleDeliveryMethodChangeEvent(event) {
        const selectedMethod = event.target.value;
        console.log(`[Baselinker] 🚚 Zmiana metody dostawy na: "${selectedMethod}"`);

        // Sprawdź czy wybrano odbiór osobisty
        const isPersonalPickup = selectedMethod && (
            selectedMethod.toLowerCase().includes('odbiór') ||
            selectedMethod.toLowerCase().includes('odbior') ||
            selectedMethod.toLowerCase().includes('personal') ||
            selectedMethod.toLowerCase().includes('pickup')
        );

        if (isPersonalPickup) {
            console.log('[Baselinker] 🏪 Wykryto odbiór osobisty - zerowanie kosztów wysyłki');
            this.updateShippingCosts(0);
        } else {
            console.log(`[Baselinker] 🚛 Przywracanie oryginalnych kosztów wysyłki: ${this.originalShippingCost}`);
            this.updateShippingCosts(this.originalShippingCost);
        }

        // Zaktualizuj wszystkie podsumowania
        this.updateAllSummariesWithNewShipping();
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
                        const updateSuccess = await this.updateClientDataInDatabase(currentData);
                        
                        if (updateSuccess) {
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
        const deliveryMethod = document.getElementById('delivery-method-select').value;

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

    populateFinalSummary() {
        const container = document.getElementById('baselinker-final-summary');
        if (!container) return;

        const quote = this.modalData.quote;
        const client = this.modalData.client;

        // DEBUG: Wyświetl szczegóły produktów
        console.log('[Baselinker] Debug modalData.products:', this.modalData.products);
        this.modalData.products.forEach((product, index) => {
            console.log(`[Baselinker] Produkt ${index}:`, {
                name: product.name,
                quantity: product.quantity,
                finishing: product.finishing,
                finishing_quantity: product.finishing ? product.finishing.quantity : 'brak'
            });
        });

        // POPRAWKA: Używaj quantity z finishing details (tak jak w modalu szczegółów)
        const totalQuantity = this.modalData.products.reduce((sum, product) => {
            // Sprawdź czy product ma finishing z quantity
            let quantity = 1; // domyślna wartość
            
            if (product.finishing && product.finishing.quantity) {
                quantity = parseInt(product.finishing.quantity);
            } else if (product.quantity) {
                quantity = parseInt(product.quantity);
            }
            
            // Upewnij się, że quantity jest liczbą większą od 0
            if (isNaN(quantity) || quantity <= 0) {
                quantity = 1;
            }
            
            console.log(`[Baselinker] Produkt "${product.name}": quantity=${quantity}`);
            return sum + quantity;
        }, 0);

        console.log(`[Baselinker] Obliczona łączna ilość: ${totalQuantity}`);

        // POPRAWKA: Użyj aktualnych kosztów (po ewentualnym zerowaniu wysyłki)
        const costs = this.modalData.costs;

        container.innerHTML = `
            <div class="bl-style-summary-row">
                <span>Wycena:</span>
                <strong>${quote.quote_number}</strong>
            </div>
            <div class="bl-style-summary-row">
                <span>Klient:</span>
                <strong>${client.name}${client.company ? ` - ${client.company}` : ''}</strong>
            </div>
            <div class="bl-style-summary-row">
                <span>Produktów:</span>
                <strong>${this.modalData.products.length} ${this.modalData.products.length === 1 ? 'pozycja' : 'pozycje'} (${totalQuantity} szt.)</strong>
            </div>
            <div class="bl-style-summary-row">
                <span>Koszt wysyłki:</span>
                <strong>${this.formatCurrency(costs.shipping_brutto)}</strong>
            </div>
            <div class="bl-style-summary-row">
                <span>Wartość zamówienia:</span>
                <strong>${this.formatCurrency(costs.total_brutto)} brutto</strong>
            </div>
            <div class="bl-style-summary-row">
                <span>Status zamówienia:</span>
                <div class="bl-style-status-ready" id="final-order-status">✓ Gotowe do wysłania</div>
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
        const deliveryMethod = document.getElementById('delivery-method-select')?.value;

        container.innerHTML = `
        <div class="bl-style-config-row">
            <span class="bl-style-config-label">Źródło zamówienia:</span>
            <span class="bl-style-config-value">${this.getSelectedOptionText('order-source-select')}</span>
        </div>
        <div class="bl-style-config-row">
            <span class="bl-style-config-label">Status zamówienia:</span>
            <span class="bl-style-config-value">${this.getSelectedOptionText('order-status-select')}</span>
        </div>
        <div class="bl-style-config-row">
            <span class="bl-style-config-label">Metoda płatności:</span>
            <span class="bl-style-config-value">${this.getSelectedOptionText('payment-method-select')}</span>
        </div>
        <div class="bl-style-config-row">
            <span class="bl-style-config-label">Metoda dostawy:</span>
            <span class="bl-style-config-value">${this.getSelectedOptionText('delivery-method-select') || 'Nie wybrano'}</span>
        </div>
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
        if (element) {
            if (element.tagName.toLowerCase() === 'select') {
                // Dla select-ów użyj specjalnej funkcji
                this.setSelectValue(inputId, value || '');
            } else {
                // Dla input-ów normalne ustawienie
                element.value = value || '';
            }
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

    handleDeliveryMethodChange() {
        const deliveryMethodSelect = document.getElementById('delivery-method-select');

        if (!deliveryMethodSelect) return;

        // Usuń poprzedni event listener jeśli istnieje
        if (this.deliveryMethodChangeHandler) {
            deliveryMethodSelect.removeEventListener('change', this.deliveryMethodChangeHandler);
        }

        // Stwórz nowy handler
        this.deliveryMethodChangeHandler = (e) => {
            const selectedMethod = e.target.value;
            console.log(`[Baselinker] Zmiana metody dostawy na: "${selectedMethod}"`);

            // POPRAWIONA LOGIKA: Sprawdź czy wybrano odbiór osobisty
            const isPersonalPickup = selectedMethod && (
                selectedMethod.toLowerCase().includes('odbiór') ||
                selectedMethod.toLowerCase().includes('odbior') ||
                selectedMethod.toLowerCase().includes('personal') ||
                selectedMethod.toLowerCase().includes('pickup')
            );

            if (isPersonalPickup) {
                console.log('[Baselinker] Wykryto odbiór osobisty - zerowanie kosztów wysyłki');
                this.updateShippingCosts(0);
            } else {
                // KRYTYCZNA POPRAWKA: Przywróć ORYGINALNE koszty wysyłki
                console.log(`[Baselinker] Przywracanie oryginalnych kosztów wysyłki: ${this.originalShippingCost}`);
                this.updateShippingCosts(this.originalShippingCost);
            }

            // Zaktualizuj wszystkie podsumowania
            this.updateAllSummariesWithNewShipping();
        };

        // Dodaj nowy event listener
        deliveryMethodSelect.addEventListener('change', this.deliveryMethodChangeHandler);

        console.log(`[Baselinker] Event listener dla metody dostawy dodany. Oryginalne koszty: ${this.originalShippingCost}`);
    }

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
        const deliveryMethod = document.getElementById('delivery-method-select');

        console.log('[Baselinker] DEBUG - Stan formularza:');
        console.log(`- Źródło: value="${orderSource?.value}", selectedIndex=${orderSource?.selectedIndex}`);
        console.log(`- Status: value="${orderStatus?.value}", selectedIndex=${orderStatus?.selectedIndex}`);
        console.log(`- Płatność: value="${paymentMethod?.value}", selectedIndex=${paymentMethod?.selectedIndex}`);
        console.log(`- Dostawa: value="${deliveryMethod?.value}", selectedIndex=${deliveryMethod?.selectedIndex}`);
    }

    debugShippingCosts() {
        console.log('[Baselinker] 🔍 DEBUG - Koszty wysyłki:');
        console.log(`- Oryginalne koszty: ${this.originalShippingCost}`);
        console.log(`- Aktualne koszty w modalData: ${this.modalData?.costs?.shipping_brutto}`);

        const deliveryMethod = document.getElementById('delivery-method-select')?.value;
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
        const selectIds = ['order-source-select', 'order-status-select', 'payment-method-select', 'delivery-method-select'];

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
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
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